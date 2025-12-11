import requests
import json
import os
import logging
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger('pynetcom.rest_nce')


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

    def __init__(self, nce_host, nce_username, nce_password):
        """
        :param nce_host: https://X.X.X.X:26335
        :param nce_username: nce_api_user
        :param nce_password: nce_api_user_password
        """
        
        self.logger = logging.getLogger('pynetcom')
        self.API_NCE_HOST = nce_host
        self.API_NCE_USER = nce_username
        self.API_NCE_PASS = nce_password
        
        # Create session for connection pooling (reuses TCP/SSL connections)
        self.session = requests.Session()
        self.session.verify = False
        
        if os.path.exists(self.token_filename):
            self.__read_token()
            logger.debug('read token: %s', self.token)
        else:
            self.__auth()
        self.header = { "X-Auth-Token": self.token, "content-type":"application/json" }

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
        response = self.session.get(self.url, headers=self.header, data=data)

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
            # Retry request with new token
            response = self.session.get(self.url, headers=self.header, data=data)
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