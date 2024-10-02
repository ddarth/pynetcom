from pynetcom import NetconfClient
from config import NETCONF_HOST, NETCONF_PORT, NETCONF_USER, NETCONF_PASSWORD
import logging
import json

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Set needed logging level
logging.getLogger().setLevel(logging.INFO)

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

netconf_client = NetconfClient(host="10.255.77.6", port=22, 
                               user="M2M_user", password="M2M_user_123", 
                               device_params={'name':'huaweiyang'})
# netconf_client.get_config()
# config = netconf_client.get_config()
# print(json.dumps(config, indent=4))

print('#########################################################################')
print('# Get port status.')
print('#########################################################################')

request_filter = """
            <ifm xmlns="urn:huawei:yang:huawei-ifm">
                <interfaces>
                    <interface>
                        <name>GigabitEthernet0/1/2</name>
                    </interface>
                </interfaces>
            </ifm>
"""
status = netconf_client.get(request_filter)
print(json.dumps(status['data']['ifm'], indent=4))