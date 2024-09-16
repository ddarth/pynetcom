from pynetcom import RestNCE
import json
from config import API_NCE_HOST, API_NCE_USER, API_NCE_PASS
import logging

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Setting authentication parameters
API_NCE_USER =  API_NCE_USER
API_NCE_PASS = API_NCE_PASS
API_NCE_HOST = API_NCE_HOST

# Set needed logging level
logging.getLogger().setLevel(logging.INFO)

"""
Various Huawei NCE API urls

/restconf/v2/data/huawei-nce-resource-inventory:transceivers
/restconf/v2/data/huawei-nce-resource-inventory:subnets/subnet/8be47e18-4604-11e9-99a4-5b70d0bfdc96
/restconf/v3/data/huawei-nce-resource-inventory:igp-links/igp-link/cd331141-712a-407c-a09f-4cf093e197f5
/restconf/v2/data/huawei-nce-resource-inventory:links/link/e38d6f1b-4755-11e9-a952-286ed488d730
/restconf/v2/data/huawei-nce-resource-inventory:slots/slot/f35a74b1-4955-11e9-a4a2-340a9837e9be
/restconf/v2/data/huawei-nce-resource-inventory:cards/card/{res-id}
/restconf/v2/data/huawei-nce-resource-inventory:frames/frame/{res-id}
/restconf/v2/data/huawei-nce-resource-inventory:racks/rack/{res-id}
/restconf/v2/data/huawei-nce-resource-inventory:network-elements/network-element/{res-id}
/restconf/v2/data/huawei-nce-resource-inventory:network-elements
[name ip-address ref-parent-subnet]
/restconf/v3/data/huawei-nce-resource-inventory:ltps/ltp/{res-id} # ports

"""

# Initialize RestNCE object
nce = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
#########################################################################

# Get subnets from NCE
nce.send_request("/restconf/v2/data/huawei-nce-resource-inventory:subnets")

items = nce.get_data()
# or use items = nce.send_request("some_url")

result = list()
print('#########################################################################')
print('# Found the following subnets.')
print('#########################################################################')
for item in items:
    # print (item)
    for subnet in item["subnets"]["subnet"]:
        if subnet['node-class'] == 'subnet':
            res_subnet = {'name': subnet['name'], 'res-id': subnet['res-id']}
            print(res_subnet)
            result.append(res_subnet)
print('#########################################################################') 
nce.clear_data()

#########################################################################
# Get hosts by hostname
nce.send_request("/restconf/v2/data/huawei-nce-resource-inventory:network-elements", 'name=Bc.MSC4_.N8k02')
"""
Return the following object
{
    'network-elements': {
        'network-element': [
            {
                'platform-version': 'V800R022C01SPC500', 
                'is-virtual': False, 
                'lsr-id': 192.168.10.20', 
                'res-id': '79132ad3-a0e5-42b6-a814-d46b379a2459', 
                'ip-address': 192.168.100.20', 
                'is-gateway': -1, 
                'dev-sys-name': 'bc-msc-01', 
                'physical-id': 2683836, 
                'container': False, 
                'as-number': 65999, 
                'patch-version': 'SPH1b2', 
                'location': 'Beijing China', 
                'pre-config': 0, 
                'product-name': 'ATN910C-G', 
                'ref-parent-subnet': '2e7d104c-2528-466c-913c-5571ae8e0480', 
                'software-version': 'ATN 910C-GV800R022C00SPC600(VRPV800R022C01SPC500)', 
                'manufacturer': 'Huawei', 
                'remark': 'NE Auto Discovery', 
                'name': 'bc-msc-01', 
                'hardware-version': 'ATN910C-G', 
                'detail-dev-type-name': 'ATN910C-G', 
                'communication-state': '0', 
                'sn': '2102352YXXXXXXXXXXXX', 
                'admin-status': 'active', 
                'mac': 'AA:BB:CC:DD:EE:FF', 
                'create-time': 1674031210784, 
                'last-modified': 1725836653621
            }
        ]
    }
}
"""
items = nce.get_data()
result = list()
print('#########################################################################')
print('# Found the following hosts.')
print('#########################################################################')
for item in items:
    # print (item)
    for host in item["network-elements"]["network-element"]:
        res_host = {
            'name': host['name'], 
            'om_ip': host['ip-address'], 
            'product-name': host['product-name'],
            'res-id': host['res-id']
        }
        print(res_host)
        result.append(res_host)

nce.clear_data()
print('#########################################################################')
print('# Found the following alarms.')
print('#########################################################################')

#########################################################################
# Get alarms by host resource id
nce.send_request("/restconf/v1/data/ietf-alarms:alarms/alarm-list", 'resource=008ca2e2-3d92-45f8-b2c0-ebb425932a36', { 'is-cleared': False } )


"""
Return the following object
{
    'alarm': [
        {
            'time-created': '2024-09-04T11:48:12.000Z', 
            'is-acked': False, 
            'resource-alarm-parameters': {
                'perceived-severity': 'major', 
                'is-cleared': False, 
                'status-change': [], 
                'last-changed': '2024-09-04T11:48:12.000Z'
            }, 
            'x733-alarm-parameters': {
                'event-type': 'communications-alarm'
            }, 
            'operator-state-change': [], 
            'alarm-parameters': {
                'repair-action': '', 
                'ne-name': 'TestNE', 
                'location-info': 'PLA:(ID,1)', 
                'native-probable-cause': 'MAC_EXT_EXC', 
                'probable-cause': '1.ETHDROP:To detect dropped packets over the high number of incidents threshold.\n2.ETHEXCCOL:The failure of successive post-conflict frame sent over the high threshold.\n3.RXBBAD:Bytes of bad packets received over the high threshold.', 
                'root-cause-identifier': False, 
                'ems-time': '2024-09-04T11:48:17.021Z', 
                'alarm-serial-number': '341262459', 
                'reason-id': 13444, 
                'tenant-id': 'default-organization-id', 
                'tenant': '', 
                'alarm-text': 'Bit error threshold-crossing detected at MAC layer', 
                'other-info': '\nAlarm Parameter II(hex) 0x03', 
                'ip-address': '8-3183'
            }, 
            'common-alarm-parameters': {
                'alt-resource': [], 
                'resource': '56a5f7ef-bfb3-11ea-92c8-b008759ca873', 
                'resource-url': '/restconf/v2/data/huawei-nce-resource-inventory:ltps/ltp/56a5f7ef-bfb3-11ea-92c8-b008759ca873', 
                'related-alarm': [], 
                'alarm-type-qualifier': '268374017-13444', 
                'impacted-resource': [], 
                'root-cause-resource': [], 
                'alarm-type-id': 'communications-alarm', 
                'layer': 'LR_LAG_Fragment', 
                'md-name': 'Huawei/NCE', 
                'product-type': 'OptiX RTN 905'
            }
        }
    ]
}
"""
items = nce.get_data()
result = list()
for item in items:
    # print (item)
    for alarm in item["alarm"]:
        # print( json.dumps(alarm, indent=4) )
        res_alarm = {
            'last-changed': alarm['resource-alarm-parameters']['last-changed'], 
            'perceived-severity': alarm['resource-alarm-parameters']['perceived-severity'], 
            'alarm-text': alarm['alarm-parameters']['alarm-text'], 
            'native-probable-cause': alarm['alarm-parameters']['native-probable-cause'], 
            'probable-cause': alarm['alarm-parameters']['probable-cause'], 
            'location-info': alarm['alarm-parameters']['location-info'], 
            'other-info': alarm['alarm-parameters']['other-info'], 
            'ne-name': alarm['alarm-parameters']['ne-name']
        }
        print(json.dumps(res_alarm, indent=4))
        result.append(res_alarm)


