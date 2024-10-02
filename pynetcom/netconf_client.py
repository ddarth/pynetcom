from ncclient import manager
# from ncclient.xml_ import to_ele
from ncclient.xml_ import *
import xmltodict
import xml.dom.minidom
import logging
from  typing import Type, Optional

class NetconfClient:
    def __init__(self, host, port, user, password, device_params=None, hostkey_verify=False):
        """
        When instantiating a connection to a known type of NETCONF server:

            Alcatel Lucent: device_params={'name':'alu'}
            Ciena: device_params={'name':'ciena'}
            Cisco:
                CSR: device_params={'name':'csr'}
                Nexus: device_params={'name':'nexus'}
                IOS XR: device_params={'name':'iosxr'}
                IOS XE: device_params={'name':'iosxe'}
            H3C: device_params={'name':'h3c'}
            HP Comware: device_params={'name':'hpcomware'}
            Huawei:
                device_params={'name':'huawei'}
                device_params={'name':'huaweiyang'}
            Juniper: device_params={'name':'junos'}
            Server or anything not in above: device_params={'name':'default'}
        """
        self.logger = logging.getLogger('pynetcom')
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.device_params = device_params
        self.hostkey_verify = hostkey_verify
        self.session : Optional[manager.Manager] = None
        self.__connect()

    def __connect(self):
        self.logger.debug(f'Connecting to {self.host}, {self.port}')
        self.session = manager.connect(
            host=self.host,
            port=self.port,
            username=self.user,
            password=self.password,
            device_params=self.device_params,
            hostkey_verify=self.hostkey_verify,
            timeout=120
        )
        

    def get_config(self):
        self.logger.debug(f'Get config')
        config = self.session.get_config(source="running")
        # config = self.session.get_configuration()
        # print('########################################')
        # print(config)
        return xmltodict.parse(config.xml)
    
    def get(self, request_filter):
        self.logger.debug(f'Get request with filter: {request_filter}')
        response = self.session.get(("subtree", request_filter))
        # print(response)
        return xmltodict.parse(response.data_xml)

    def close(self):
        self.session.close()