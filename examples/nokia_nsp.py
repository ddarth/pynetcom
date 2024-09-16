import logging
from pynetcom import RestNSP
from config import API_NSP_HOST, API_NSP_USER, API_NSP_PASS

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Set needed logging level
logging.getLogger().setLevel(logging.INFO)

# 
API_NSP_USER =  API_NSP_USER
API_NSP_PASS = API_NSP_PASS
API_NSP_HOST = API_NSP_HOST

"""
Various Huawei NCE API urls

/rest-gateway/rest/api/v1/location/services
/FaultManagement/rest/api/v2/alarms/details
/NetworkSupervision/rest/api/v1/networkElements
"""

def get_nsp_all_alarms():
    """Get all alarms from NSP"""
    nsp = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    nsp.send_request("/FaultManagement/rest/api/v2/alarms/details")

    alarms = nsp.get_data()
    nes = list()
    for alarm in alarms:
        print(alarm['neName'], alarm['alarmName'])

def get_nsp_all_ne():
    """Get all network elements from NSP"""
    nsp = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    nsp.send_request("/NetworkSupervision/rest/api/v1/networkElements")

    elements = nsp.get_data()
    print(nsp.token)
    for ne in elements:
        # print(ne)
        print(ne['name'], ne['ipAddress'], ne['type'], ne['managedState'])
    return elements



def main():

    nes = get_nsp_all_alarms()
    nes = get_nsp_all_ne()

main() 
