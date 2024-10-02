"""

"""
import requests
import json
import base64
import logging
import os
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# https://network.developer.nokia.com/api-documentation/
# https://network.developer.nokia.com/learn/23_11/api-technologies-frameworks-and-design-guides/getting-started-nsp-apis_apistyle/

# Настраиваем логгер
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')



class RestNSP(object):
    """
    This is low level class used to get data from NSP by sending requests
    and retriev data in JSON format

    Attributes:
        data (list): List with results of all requests.
        limit (int): limit of results per request.
        __pagination_is_trunked (bool): Flag, indicating that there are data for pagination request.
        __pagination_end_row (str): End row of pagination request.
        token (str): Token for authorization.
        AUTH_REST_URL (str): URL for authorization request.
        token_filename (str): Path to token file.
    """
    data = list() # List with results of all requests
    limit = 1000
    __pagination_is_trunked = False
    __pagination_end_row = 0
    token = None
    AUTH_REST_URL = "/rest-gateway/rest/api/v1/auth/token"
    token_filename = 'nsp_token.txt'

    def __init__(self, nsp_host, nsp_username, nsp_password):
        """
        Initialize RestNSP object.

        :param nsp_host: https://X.X.X.X
        :param nsp_username: nsp_api_user
        :param nsp_password: nsp_api_user_password
        """
        self.logger = logging.getLogger('pynetcom')
        self.API_NSP_HOST = nsp_host
        self.API_NSP_USER = nsp_username
        self.API_NSP_PASS = nsp_password
        # Пробуем использовать токен из файла
        if os.path.exists(self.token_filename):
            self.__read_token()
            logging.debug('read token: %s', self.token)
        else:
            self.__auth()
        self.__update_request_header()

    def __read_token(self):
        """Load token from file."""
        with open(self.token_filename, 'r') as file:
            self.token = file.read().replace('\n', '')

    def __write_token(self):
        """Write token to file."""
        with open(self.token_filename, 'w') as file:
            file.write(self.token)

    def __reset_pagination(self):
        """Reset pagination parameters."""
        self.__pagination_is_trunked = False
        self.__pagination_end_row = 0  

    def __update_request_header(self):
        """Update header request with auth token."""
        self.header = { "Authorization": "Bearer " + self.token, "content-type":"application/json" }

    def clear_data(self):
        self.data = list()



    def __auth(self):
        """
        Request token for authorization

        """

        # Decode login and password in base64 with following format username:password
        credentials = f"{self.API_NSP_USER}:{self.API_NSP_PASS}"
        encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
        payload = { "grant_type": "client_credentials" }

        url = self.API_NSP_HOST + self.AUTH_REST_URL
        logging.debug('AUTHENTICATE through url: %s', url)

        headers = { 
            "content-type":"application/json", 
            "Authorization":"Basic "+encoded_credentials,
        }
        response = requests.post(url, json=payload, headers=headers, verify=False)
        logging.debug('POSTING response.status_code: %d', response.status_code)
        logging.debug('POSTING response.json: %s', response.json())
        response_json = response.json()
        if response.status_code == 200:
            logging.info("SUCCESSFUL AUTHORIZATION")
        else:
            logging.error("POST: ERROR. Token not received: %d", response.status_code)
            return False
        # Вытащить токен из полученных данных
        self.token = response_json ["access_token"]
        self.__write_token()
        self.__update_request_header()
        logging.debug('token: %s', self.token)
        return self.token 

    def send_request(self, rest_url):
        """
        Send GET-request to NSP API.

        :param rest_url: URL Endpoint (for example /NetworkSupervision/rest/api/v1/networkElements)
        :return: data in JSON format
        """
        # NSP use 8544 port for nsp data and another for authorization
        self.url = self.API_NSP_HOST + ':8544' + rest_url

        if self.__pagination_is_trunked:
           self.url += "?pageStart=" + str(self.__pagination_end_row) + "&pageEnd=" + str(self.__pagination_end_row + self.limit)
        else:
            self.clear_data()
 
        logging.debug("SENDING REQUEST to url: %s", self.url)

        response = requests.get (self.url, headers=self.header, data=None, verify=False)
        if response.status_code == 401:
            logging.warning('Unauthorized')
            self.__auth()
            # По хорошему тут нужна рекурсия, но пока и так сойдет
            response = requests.get (self.url, headers=self.header, data=None, verify=False)
        else:
            logging.debug('SUCCESS AUTHENTICATE USING EXISTING TOKEN')

        logging.debug('RECEIVE response.status_code: %d', response.status_code)
        if response.status_code == 200:
            logging.info("GET REQUEST IS OK")
        else:
            logging.error("GET REQUEST RETURN ERROR: %d", response.status_code)
            return False

        response_header = response.headers
        response_json = response.json() # Convert json to python objects

        logging.debug('GETTING response_header: %s', response_header)
        total_rows = response_json['response']['totalRows']
        end_row = response_json['response']['endRow']

        self.data.extend( response_json['response']['data'] )

        if total_rows > end_row:
            self.__pagination_is_trunked = True
            self.__pagination_end_row = end_row
            logging.debug('PAGE')
            self.send_request(rest_url)
        else:
            self.__reset_pagination()
            return self.data

        # {'response': {'status': 0, 'startRow': 0, 'endRow': 1000, 'totalRows': 32687, 'data': 


    def get_data(self):
        """
        Return data

        :return: data in JSON format
        """
        return self.data 
