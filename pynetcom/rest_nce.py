import json
import logging
import os
import random
import re
import threading
import time
from typing import Dict, Optional, Tuple

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger('pynetcom.rest_nce')


# --------------------------------------------------------------------------- #
#  Per-endpoint concurrency limits                                            #
# --------------------------------------------------------------------------- #
#
# NCE rejects requests with HTTP 429 when client exceeds a per-endpoint limit.
# Documented limits in the NCE-T NBI Guide are nominal and often stricter in
# practice — e.g. /ltps is documented as "~10 concurrent" but empirically
# starts rejecting at 2 parallel GETs (it is actually rate-limited at ~5 req/s).
#
# The map below is consulted by ``send_request`` and ``send_post_request`` —
# every outgoing request for a matching URL path is gated by a shared
# Semaphore. Unknown endpoints are not throttled (backward compatible).
#
# Values are based on empirical measurements on the production NCE. For
# endpoints not covered here, callers are responsible for sensible concurrency;
# if measurements reveal a limit, add it here instead of in consumer code.
#
# Format: {regex pattern to match url path: max_concurrent_requests}
#
ENDPOINT_LIMITS: Dict[str, int] = {
    # /ltps is rate-limited (~5 req/s). Any parallelism triggers 429 rapidly;
    # the safe setting is max_concurrent=1. See
    # network_entries/examples/measure_endpoint_limits.py for the measurement.
    r'/restconf/v\d+/data/huawei-nce-resource-inventory:ltps': 1,
    # query-optical-power: empirically handles 6 concurrent without 429,
    # saturates at 4x speedup (see examples/experiment_thresholds.py).
    r'/restconf/v\d+/operations/ietf-trans-oam:query-optical-power': 6,
}

# Response codes that warrant a retry. 429 is rate limiting; 502/503/504 are
# transient gateway/backend issues. Others (400, 401, 403, 404, 409) indicate
# a real client or server problem that retrying cannot fix.
_RETRYABLE_STATUS = {429, 502, 503, 504}


class NCEAuthenticationError(Exception):
    """Exception raised when NCE authentication fails."""
    
    # Known error codes and their descriptions
    ERROR_MESSAGES = {
        'user.user.policy_violation_lock': 'User account is LOCKED due to too many failed login attempts. Wait {0} minutes or contact NCE administrator.',
        'user.user.policy_violation_stop': 'User account is DISABLED on NCE. Contact NCE administrator to enable the account.',
        'user.pwd.expired': 'User password has EXPIRED. Change password on NCE before using API.',
        'user.pwd.wrong': 'Invalid username or password.',
        'user.user.not_exist': 'User does not exist on NCE.',
    }
    
    def __init__(self, exception_id: str, response_json: dict = None):
        self.exception_id = exception_id
        self.response_json = response_json or {}
        self.detail_args = self.response_json.get('descArgs', [])
        
        # Get human-readable message
        if exception_id in self.ERROR_MESSAGES:
            message = self.ERROR_MESSAGES[exception_id]
            if self.detail_args:
                message = message.format(*self.detail_args)
        else:
            message = f"Authentication failed: {exception_id}"
            if self.detail_args:
                message += f" (details: {self.detail_args})"
        
        super().__init__(message)


class RestNCE(object):
    """
    This is low level class used to get data from NCE by sending requests
    and retriev data in JSON format
    """
    data = list() # List with results of all requests
    limit = "1000"
    is_trunked = False
    token = None
    AUTH_REST_URL = "/rest/plat/smapp/v1/sessions"
    token_filename = 'nce_token.txt'

    def __init__(self, nce_host, nce_username, nce_password,
                 endpoint_limits: Optional[Dict[str, int]] = None,
                 max_retries: int = 6):
        """
        :param nce_host: https://X.X.X.X:26335
        :param nce_username: nce_api_user
        :param nce_password: nce_api_user_password
        :param endpoint_limits: Optional override of per-endpoint concurrency
            limits. Merged over the module-level :data:`ENDPOINT_LIMITS` dict.
            Use this when connecting to a NCE with different sizing (e.g.
            6K env, where documented /links limit is 20 vs 10 on 3K).
        :param max_retries: How many times to retry a single request that
            fails with 429/5xx. Exponential backoff 0.2s..8s. Default 6
            gives worst-case ~20s per request before giving up.
        """

        self.logger = logging.getLogger('pynetcom')
        self.API_NCE_HOST = nce_host
        self.API_NCE_USER = nce_username
        self.API_NCE_PASS = nce_password
        self.max_retries = max_retries

        # Build per-endpoint semaphores from module defaults + caller overrides.
        # URL pattern -> Semaphore. Matched by ``_get_semaphore`` at each call.
        limits = dict(ENDPOINT_LIMITS)
        if endpoint_limits:
            limits.update(endpoint_limits)
        self._semaphores: Dict[re.Pattern, threading.Semaphore] = {
            re.compile(pattern): threading.Semaphore(n)
            for pattern, n in limits.items()
        }

        # Retry telemetry. Consumers can inspect this to tune concurrency —
        # if a counter grows during normal operation, something's wrong
        # (limit changed, other client is using NCE, network issue).
        self.retry_stats: Dict[str, int] = {
            '429': 0, '502': 0, '503': 0, '504': 0, 'exhausted': 0,
        }

        # Create session for connection pooling (reuses TCP/SSL connections)
        self.session = requests.Session()
        self.session.verify = False

        if os.path.exists(self.token_filename):
            self.__read_token()
            logger.debug('read token: %s', self.token)
        else:
            self.__auth()
        self.header = { "X-Auth-Token": self.token, "content-type":"application/json" }

    def _get_semaphore(self, url: str) -> Optional[threading.Semaphore]:
        """
        Return the semaphore for the given URL, or None if no limit configured.

        Matches the URL path (query string stripped) against compiled patterns
        in ``self._semaphores``. The first pattern that matches wins — patterns
        should be disjoint in practice.
        """
        path = url.split('?', 1)[0]
        for pattern, sem in self._semaphores.items():
            if pattern.search(path):
                return sem
        return None

    def _request_with_retry(self, method: str, url: str,
                            **request_kwargs) -> requests.Response:
        """
        Perform an HTTP request with retry on 429/5xx and exponential backoff.

        Bumps the per-status counter in ``self.retry_stats`` on every retry,
        and the ``'exhausted'`` counter when ``max_retries`` is exceeded.
        The caller is responsible for handling the final response — including
        any residual non-200 status after retries.

        :param method: ``'get'`` or ``'post'`` — attribute of ``self.session``.
        :param url: Full absolute URL to request.
        :param request_kwargs: Passed directly to ``self.session.<method>``.
        :return: Final ``requests.Response`` (may still be non-200 if retries
                 were exhausted — caller logs and returns).
        """
        session_method = getattr(self.session, method)
        backoff = 0.2
        response: Optional[requests.Response] = None
        for attempt in range(self.max_retries + 1):
            response = session_method(url, **request_kwargs)
            if response.status_code not in _RETRYABLE_STATUS:
                return response
            if attempt >= self.max_retries:
                self.retry_stats['exhausted'] += 1
                return response
            self.retry_stats[str(response.status_code)] += 1
            logger.debug(
                'retry #%d (%s %s): status=%d, backoff=%.2fs',
                attempt + 1, method.upper(), url, response.status_code, backoff)
            time.sleep(backoff + random.random() * 0.1)
            backoff = min(backoff * 2, 8.0)
        return response  # unreachable in theory; satisfies type checker

    def __read_token(self):
        """Load token from file."""
        with open(self.token_filename, 'r') as file:
            self.token = file.read().replace('\n', '')

    def __write_token(self):
        """Write token to file."""
        with open(self.token_filename, 'w') as file:
            file.write(self.token)

    def __update_request_header(self):
        """Update header request with auth token."""
        self.header = { "X-Auth-Token": self.token, "content-type":"application/json" }



    def __auth(self):
        """
        Request token for authorization.
        
        Raises:
            NCEAuthenticationError: If authentication fails due to policy or credentials issues.
        """
        payload = { "grantType": "password", "userName": self.API_NCE_USER, "value": self.API_NCE_PASS }

        url = self.API_NCE_HOST + self.AUTH_REST_URL
        logger.debug(['url: ', url])
        # verify=False - disable ssl certificate verification check
        response = self.session.put(url, data=json.dumps(payload), 
            headers = {"content-type":"application/json", "Accept":"application/json"}
        )
        logger.debug('POSTING response.status_code: %d', response.status_code)
        
        try:
            response_json = response.json()
            logger.debug('POSTING response.json: %s', response_json)
        except json.JSONDecodeError:
            response_json = {}
        
        if response.status_code == 200:
            logger.info("SUCCESSFUL AUTHORIZATION")
        else:
            exception_id = response_json.get('exceptionId', 'unknown_error')
            logger.error("NCE Authentication failed: %s", exception_id)
            
            # Remove invalid token file if exists
            if os.path.exists(self.token_filename):
                try:
                    os.remove(self.token_filename)
                    logger.debug("Removed invalid token file: %s", self.token_filename)
                except OSError:
                    pass
            
            # Raise descriptive exception
            raise NCEAuthenticationError(exception_id, response_json)
        
        # Get token from received data
        self.token = response_json["accessSession"]
        self.__write_token()
        self.__update_request_header()
        logger.debug('token: %s', self.token)
        return self.token        

    def send_request(self, rest_url: str, get_params: str = '', data: dict = None) -> dict:
        """
        Send GET-request to NCE API.

        Gated by a per-endpoint semaphore (see :data:`ENDPOINT_LIMITS`) and
        retried on HTTP 429/5xx with exponential backoff. 401 triggers
        token re-auth and one immediate retry as before.

        :param rest_url: URL Endpoint (for example /restconf/v1/data/ietf-alarms:alarms/alarm-list)
        :param get_params: Additional get parameters (after ? for example filter=10)
        :param data: Body of request
        :return: data in JSON format

        Raises:
            NCEAuthenticationError: If re-authentication fails.
        """
        logger.info('send_request')
        self.url = self.API_NCE_HOST + rest_url
        if not self.is_trunked:
            self.url += "?limit=" + self.limit

        if get_params != '':
            self.url += "&" + get_params
        logger.debug(f"url: {self.url}")

        sem = self._get_semaphore(self.url)
        if sem is not None:
            with sem:
                response = self._request_with_retry(
                    'get', self.url, headers=self.header, data=data)
        else:
            response = self._request_with_retry(
                'get', self.url, headers=self.header, data=data)

        if response.status_code == 401:
            logger.warning('Unauthorized - token expired or invalid, re-authenticating...')
            # Remove old token file
            if os.path.exists(self.token_filename):
                try:
                    os.remove(self.token_filename)
                except OSError:
                    pass
            # Re-authenticate (may raise NCEAuthenticationError)
            self.__auth()
            # Retry request with new token (still gated by same semaphore).
            if sem is not None:
                with sem:
                    response = self._request_with_retry(
                        'get', self.url, headers=self.header, data=data)
            else:
                response = self._request_with_retry(
                    'get', self.url, headers=self.header, data=data)
        else:
            logger.debug('SUCCESS AUTHENTICATE USING EXISTING TOKEN')

        if response.status_code == 200:
            logger.info("GET REQUEST IS OK")
        else:
            logger.error("GET REQUEST RETURN ERROR: %d", response.status_code)
            try:
                logger.debug(response.json())
            except json.JSONDecodeError:
                logger.debug(response.text)
            return False
        # Look the header. It contain pagination flag which indicate that
        # the data is croped and also contain link to "next request".

        response_header = response.headers
        # print(response.json())
        # print(response_header)
        self.data.append(response.json())

        if response_header.get("is-truncated") == "true":
            self.is_trunked = True
            self.send_request(response_header["next-page"])
        else:
            self.is_trunked = False
            return self.data
    
    def send_post_request(self, rest_url: str, data: dict = None) -> dict:
        """
        Send POST request to NCE API with JSON body.

        Used by Performance Monitoring and other POST-based endpoints.
        Gated by a per-endpoint semaphore (see :data:`ENDPOINT_LIMITS`) and
        retried on HTTP 429/5xx with exponential backoff. 401 triggers
        token re-auth and one immediate retry.
        No pagination — returns single response.

        :param rest_url: Full URL path (e.g. /restconf/v1/operations/...)
        :param data: JSON body dict
        :return: Response JSON dict, or False on error
        """
        url = self.API_NCE_HOST + rest_url
        logger.debug(f"POST url: {url}")

        sem = self._get_semaphore(url)
        if sem is not None:
            with sem:
                response = self._request_with_retry(
                    'post', url, headers=self.header, json=data)
        else:
            response = self._request_with_retry(
                'post', url, headers=self.header, json=data)

        if response.status_code == 401:
            logger.warning('Unauthorized on POST - re-authenticating...')
            if os.path.exists(self.token_filename):
                try:
                    os.remove(self.token_filename)
                except OSError:
                    pass
            self.__auth()
            if sem is not None:
                with sem:
                    response = self._request_with_retry(
                        'post', url, headers=self.header, json=data)
            else:
                response = self._request_with_retry(
                    'post', url, headers=self.header, json=data)

        try:
            return response.json()
        except json.JSONDecodeError:
            logger.error(f"POST returned non-JSON: {response.status_code} {response.text[:200]}")
            return False

    def clear_data(self):
        """
        Used between requests
        """
        self.data = list()

    def get_pages_data(self):
        """
        Return data. Depricated.

        :return: data in JSON format
        """
        return self.data 
    
    def get_data(self):
        """
        Return data

        :return: data in JSON format
        """
        return self.data
    
    def close(self):
        """Close the session and release connections."""
        if self.session:
            self.session.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close session."""
        self.close()
        return False