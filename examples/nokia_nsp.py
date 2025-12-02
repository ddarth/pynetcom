import logging
from pynetcom import RestNSP
from config import API_NSP_HOST, API_NSP_USER, API_NSP_PASS, API_NSP_NE_NAME

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Set needed logging level
logging.getLogger().setLevel(logging.INFO)

# 
API_NSP_USER =  API_NSP_USER
API_NSP_PASS = API_NSP_PASS
API_NSP_HOST = API_NSP_HOST

"""
Various Nokia NSP API urls

/rest-gateway/rest/api/v1/location/services
/FaultManagement/rest/api/v2/alarms/details
/NetworkSupervision/rest/api/v1/networkElements

Alarm example:
{
    "fdn": "fdn:model:fm:Alarm:957642",
    "objectFullName": "faultManager:network@172.28.0.60@shelf-1@cardSlot-1@card@daughterCardSlot-1@daughterCard@port-19|alarm-12-4-10",
    "sourceType": "nfmp",
    "sourceSystem": "fdn:realm:sam",
    "severity": "cleared",
    "previousSeverity": "major",
    "originalSeverity": "major",
    "highestSeverity": "major",
    "probableCause": "portLinkProblem",
    "alarmName": "LinkDown",
    "specificProblem": "Not Applicable",
    "alarmType": "communicationsAlarm",
    "affectedObject": "network:172.28.0.60:shelf-1:cardSlot-1:card:daughterCardSlot-1:daughterCard:port-19",
    "affectedObjectType": "equipment.PhysicalPort",
    "affectedObjectName": "Port 1/1/19",
    "acknowledged": false,
    "wasAcknowledged": false,
    "acknowledgedBy": "N/A",
    "clearedBy": "N/A",
    "deletedBy": "N/A",
    "firstTimeDetected": 1748288798390,
    "lastTimeDetected": 1764524483884,
    "lastTimeSeverityChanged": 1764524491734,
    "lastTimeEscalated": null,
    "lastTimeDeEscalated": null,
    "lastTimeCleared": 1764524491734,
    "lastTimeAcknowledged": 0,
    "nodeTimeOffset": -1,
    "frequency": null,
    "numberOfOccurrences": 82,
    "numberOfOccurrencesSinceClear": 0,
    "numberOfOccurrencesSinceAck": 0,
    "serviceAffecting": false,
    "implicitlyCleared": true,
    "additionalText": "N/A",
    "neId": "172.28.0.60",
    "neName": "Router1",
    "userText": "N/A",
    "adminState": "unlocked",
    "impact": 0,
    "rootCause": false
}
"""

def get_nsp_all_alarms():
    """Get all alarms from NSP"""
    nsp = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    nsp.send_request("/FaultManagement/rest/api/v2/alarms/details")

    alarms = nsp.get_data()
    nes = list()
    for alarm in alarms:
        print(alarm['neName'], alarm['alarmName'])

def get_nsp_ne_name_alarms(ne_name: str):
    """Get all alarms from NSP by neName"""
    nsp = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    nsp.send_request(f"/FaultManagement/rest/api/v2/alarms/details?alarmFilter=neName='{ne_name}'")

    alarms = nsp.get_data()
    nes = list()
    for alarm in alarms:
        print(alarm['neName'], alarm['alarmName'], alarm['severity'], ' | \t', alarm['affectedObjectName'], ' | \t', alarm['affectedObjectType'], ' | \t', alarm['affectedObject'])

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

    # nes = get_nsp_all_alarms()
    nes = get_nsp_ne_name_alarms(API_NSP_NE_NAME)
    # nes = get_nsp_all_ne()

main() 
