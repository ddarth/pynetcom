from pynetcom import NetconfClient
from config import NETCONF_HOST, NETCONF_PORT, NETCONF_USER, NETCONF_PASSWORD
import logging
import json

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Set needed logging level
logging.getLogger().setLevel(logging.WARNING)
logging.getLogger('pynetcom').setLevel(logging.INFO)


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
"""
Minimal configuration for Nokia SR OS (7750, 7250) SW 23.10
/configure 
    system 
        netconf 
            no auto-config-save
            no shutdown
        exit
        security 
            user-template tacplus_default access netconf
            profile "default" 
                netconf 
                    base-op-authorization 
                        get
                        get-config
                        get-data
                    exit
                exit
            exit
        exit
    exit
exit

Minimal configuration for Nokia TimOS (7210) SW 23.09
Because 7210 not support tacacs, we need to create new user.

/configure 
    system 
        netconf 
            no shutdown
        exit
        security 
            # Create new user because 7210 not support tacacs
            user "netconf_user"
                password "netconf_password"
                access console netconf 
            exit
        exit
    exit
exit
"""

netconf_client = NetconfClient(host=NETCONF_HOST, port=NETCONF_PORT, 
                               user=NETCONF_USER, password=NETCONF_PASSWORD, 
                               device_params={'name':'alu'})

print('#########################################################################')
print('# Nokia: Get port status by GET request.')
print('#########################################################################')
# For Nokia SR OS (7750, 7250)
request_filter = """
    <state xmlns="urn:nokia.com:sros:ns:yang:sr:state">
        <port>
            <port-id>1/1/31</port-id>
        </port>
    </state>
"""
# For TimOS (7210)
request_filter = """
    <oper-data-format-cli-block>
        <cli-show>port 1/1/28</cli-show>
    </oper-data-format-cli-block>
"""
# For debug you can use get_raw method, is some XML parse error
# status = netconf_client.get_raw(request_filter)

status = netconf_client.get(request_filter)

# Print result in pretty format
print(json.dumps(status, indent=4))


