import logging
from pynetcom import RestNSP
from config import API_NSP_HOST, API_NSP_USER, API_NSP_PASS, API_NSP_NE_NAME
import json
# Configure logging (change to logging.DEBUG or logging.INFO for verbose output)
LOG_LEVEL = logging.WARNING
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('pynetcom').setLevel(LOG_LEVEL)
logging.getLogger('urllib3').setLevel(logging.WARNING)

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

NE example:
{
    "fdn": "fdn:model:equipment:NetworkElement:1452373",
    "sourceType": "nfmp",
    "sourceSystem": "fdn:realm:sam",
    "sources": [
        "fdn:realm:sam:network:172.28.2.84"
    ],
    "name": "Router1",
    "neName": "Router1",
    "neId": "172.28.2.84",
    "description": null,
    "ipAddress": "172.28.2.84",
    "type": "7250 IXR-e",
    "product": "7250 IXR",
    "version": "TiMOS-C-23.10.R6",
    "resyncState": "failed",
    "managedState": "managed",
    "longitude": 0.0,
    "latitude": 0.0,
    "location": "Router1",
    "topologyGroup": "fdn:realm:sam:topologyGroup:Network-MyNetwork",
    "adminState": "unlocked",
    "operState": "enabled",
    "standbyState": "providingService",
    "availabilityStates": [],
    "objectDetails": null,
    "networkType": "ip",
    "communicationState": "up",
    "communicationStateDetails": null,
    "macAddress": "A0-67-D6-12-34-56",
    "clliCode": "N/A",
    "links": [
        {
            "rel": "self",
            "href": "https://172.28.192.11:8544/NetworkSupervision/rest/api/v1/networkElements/fdn:model:equipment:NetworkElement:1452373"
        },
        {
            "rel": "shelves",
            "href": "https://172.28.192.11:8544/NetworkSupervision/rest/api/v1/networkElements/fdn:model:equipment:NetworkElement:1452373/shelves{?filter}"
        },
        {
            "rel": "radioEquipment",
            "href": "https://172.28.192.11:8544/NetworkSupervision/rest/api/v1/networkElements/fdn:model:equipment:NetworkElement:1452373/radioEquipment{?filter}"
        }
    ]
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
    
    nsp.close()

def get_nsp_ne_name_alarms(ne_name: str):
    """Get all alarms from NSP by neName"""
    nsp = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    nsp.send_request(f"/FaultManagement/rest/api/v2/alarms/details?alarmFilter=neName='{ne_name}'")

    alarms = nsp.get_data()
    nes = list()
    for alarm in alarms:
        print(alarm['neName'], alarm['alarmName'], alarm['severity'], ' | \t', alarm['affectedObjectName'], ' | \t', alarm['affectedObjectType'], ' | \t', alarm['affectedObject'])
    
    nsp.close()

def get_nsp_all_ne():
    """Get all network elements from NSP"""
    nsp = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    nsp.send_request("/NetworkSupervision/rest/api/v1/networkElements")

    elements = nsp.get_data()
    print(nsp.token)
    for ne in elements[:3]:
        print(json.dumps(ne, indent=4))
        # print(ne['name'], ne['ipAddress'], ne['type'], ne['managedState'])
    
    nsp.close()
    return elements



def main():

    # nes = get_nsp_all_alarms()
    # nes = get_nsp_ne_name_alarms(API_NSP_NE_NAME)
    nes = get_nsp_all_ne()

main() 
