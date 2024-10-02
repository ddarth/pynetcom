import requests
import json
import os
import logging
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

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
        if os.path.exists(self.token_filename):
            self.__read_token()
            logging.debug('read token: %s', self.token)
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
        Request token for authorization
        """
        payload = { "grantType": "password", "userName": self.API_NCE_USER, "value": self.API_NCE_PASS }

        url = self.API_NCE_HOST + self.AUTH_REST_URL
        logging.debug(['url: ', url])
        # verify=False - disable ssl certificate verification check
        response = requests.put(url, data=json.dumps(payload), 
            headers = {"content-type":"application/json", "Accept":"application/json"}, 
            verify=False
        )
        logging.debug('POSTING response.status_code: %d', response.status_code)
        logging.debug('POSTING response.json: %s', response.json())
        response_json = response.json()
        if response.status_code == 200:
            logging.info("SUCCESSFUL AUTHORIZATION")
        else:
            logging.error("POST: ERROR. Token not received: %d", response.status_code)
            if response_json['exceptionId'] == 'user.user.policy_violation_stop':
                logging.error('Check used status on NCE. May be it disabled')
            if response_json['exceptionId'] == 'user.pwd.expired':
                logging.error('Check used status on NCE. User password is expiried')
            return False
        # Get token from received data
        self.token = response_json ["accessSession"]
        self.__write_token()
        self.__update_request_header()
        logging.debug('token: %s', self.token)
        return self.token        

    def send_request(self, rest_url: str, get_params: str = '', data: dict = None) -> dict:
        """
        Send GET-request to NCE API.

        :param rest_url: URL Endpoint (for example /restconf/v1/data/ietf-alarms:alarms/alarm-list)
        :param get_params: Additional get parameters (after ? for example filter=10)
        :param data: Body of request
        :return: data in JSON format
        """
        logging.info('send_request')
        self.url = self.API_NCE_HOST + rest_url
        if not self.is_trunked:
            self.url += "?limit=" + self.limit

        if get_params != '':
            self.url += "&" + get_params
        logging.debug(f"url: {self.url}")
        response = requests.get (self.url, headers=self.header, data=data, verify=False)

        if response.status_code == 401:
            logging.warning('Unauthorized')
            self.__auth()
            # По хорошему тут нужна рекурсия, но пока и так сойдет
            response = requests.get (self.url, headers=self.header, data=data, verify=False)
        else:
            logging.debug('SUCCESS AUTHENTICATE USING EXISTING TOKEN')

        if response.status_code == 200:
            logging.info("GET REQUEST IS OK")
        else:
            logging.error("GET REQUEST RETURN ERROR: %d", response.status_code)
            logging.debug(response.json())
            return False
        # Look the header. It contain pagination flag which indicate that
        # the data is croped and also contain link to "next request".

        response_header = response.headers
        # print(response.json())
        # print(response_header)
        self.data.append( response.json() )
        
        if response_header["is-truncated"] == "true":
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