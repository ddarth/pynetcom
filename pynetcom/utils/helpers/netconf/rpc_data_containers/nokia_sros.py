from dataclasses import dataclass
from .openconfig import OpenconfigLLDPNeighborState, OpenconfigInterfaceLLDP, OpenconfigInterface, OpenconfigTranseiver
from typing import List
from .openconfig import OpenconfigTransceiverThresholdsList, OpenconfigTransceiverThreshold, PhysicalChannel, PhysicalChannels, Severity


@dataclass
class NokiaLLDPNeighborState(OpenconfigLLDPNeighborState):
    prefix = []
    field_mapping = {
        'system_name': ['system-name'],
        'system_description': ['system-description'],
        'age': ['age'],
        'port_description': ['port-description'],
        'management_address': ['mgmt-address', 'mgmt-address'],
        'management_address_type': ['mgmt-address', 'mgmt-address-subtype']
    }
    system_name = None
    system_description = None
    age = None
    port_description = None
    management_address = None
    management_address_type = None
    def __init__(self, data: dict):
        self.populate_from_data(data)
        self._parse_port_description()
    def _parse_port_description(self) -> None:
        # "port-description": "1/1/24, 100Mb/1-Gig/10-Gig Ethernet, \"Oc.RRS26.AC_01 MMM 1/1/22 (RTN980 1/17/3)\"",
        if isinstance(self.port_description, str):
            self.port_id = self.port_description.split(', ')[0].strip()
            self.port_description = self.port_description.split(', ')[2].strip().replace('\"', '')

class NokiaLLDP(OpenconfigInterfaceLLDP):
    prefix = ['state', 'port', 'ethernet', 'lldp']
    field_mapping = {
        'neighbors': ['dest-mac', 'remote-system'],
    }
    neighbors: List[NokiaLLDPNeighborState] = []
    def __init__(self, data: dict):
        self.populate_from_data(data)
        neighbors_raw = self.neighbors or []
        if isinstance(neighbors_raw, dict):
            neighbors_raw = [neighbors_raw]
        self.neighbors = [NokiaLLDPNeighborState(neighbor) for neighbor in neighbors_raw]

class NokiaPhysicalChannel(PhysicalChannel):
    prefix = ['state', 'port', 'transceiver', 'digital-diagnostic-monitoring', 'physical-channels', 'physical-channel']
    field_mapping = PhysicalChannel.field_mapping.copy()
    field_mapping.update({
        'index': ['index'],
        'output_power': ['output-power', 'instant'],
        'input_power': ['input-power', 'instant'],
    })
    index = None
    output_power = None
    input_power = None

@dataclass
class NokiaTransceiverThresholdCritical(OpenconfigTransceiverThreshold):
    prefix = []
    field_mapping = OpenconfigTransceiverThreshold.field_mapping.copy()
    field_mapping.update({
        'input_power_upper': ['received-optical-power', 'high-alarm'],
        'input_power_lower': ['received-optical-power', 'low-alarm'],
        'output_power_upper': ['transmit-output-power', 'high-alarm'],
        'output_power_lower': ['transmit-output-power', 'low-alarm'],
    })
    severity = Severity.CRITICAL
    def __init__(self, data: dict):
        self.populate_from_data(data)

@dataclass
class NokiaTransceiverThresholdWarning(OpenconfigTransceiverThreshold):
    prefix = []
    field_mapping = OpenconfigTransceiverThreshold.field_mapping.copy()
    field_mapping.update({
        'input_power_upper': ['received-optical-power', 'high-warning'],
        'input_power_lower': ['received-optical-power', 'low-warning'],
        'output_power_upper': ['transmit-output-power', 'high-warning'],
        'output_power_lower': ['transmit-output-power', 'low-warning'],
    })
    severity = Severity.WARNING
    def __init__(self, data: dict):
        self.populate_from_data(data)


class NokiaTransceiverThresholdsList(OpenconfigTransceiverThresholdsList):
    prefix = ['state', 'port', 'transceiver']
    # field_mapping = OpenconfigTransceiverThresholdsList.field_mapping.copy()
    field_mapping = {
        'physical_channels': ['digital-diagnostic-monitoring', 'lane'],
        'ddm': ['digital-diagnostic-monitoring'],
    }
    # Exclude physical_channels and ddm from output JSON
    serialization_exclude = OpenconfigTransceiverThresholdsList.serialization_exclude.union({'physical_channels', 'ddm'})

    physical_channels : List[OpenconfigTransceiverThreshold] = []
    ddm = None
    def __init__(self, data: dict):
        self.populate_from_data(data)
        if self.physical_channels and len(self.physical_channels) > 0:
            threshold_critical = NokiaTransceiverThresholdCritical(self.physical_channels[0])
            threshold_warning = NokiaTransceiverThresholdWarning(self.physical_channels[0])
            self.thresholds = [threshold_critical, threshold_warning]
        else:
            threshold_critical = NokiaTransceiverThresholdCritical(self.ddm)
            threshold_warning = NokiaTransceiverThresholdWarning(self.ddm)
            self.thresholds = [threshold_critical, threshold_warning]

        self.filter_empty_thresholds()


# Not used, because OpenconfigPhysicalChannel is used instead
class NokiaPhysicalChannel(NokiaPhysicalChannel):
    prefix = []
    field_mapping = NokiaPhysicalChannel.field_mapping.copy()
    field_mapping.update({
        'index': ['lane-id'],
        'output_power': ['transmit-output-power', 'current'],
        'input_power': ['received-optical-power', 'current'],
        'laser_bias_current': ['transmit-bias-current', 'current'],
    })
    def __init__(self, data: dict):
        self.populate_from_data(data)

# Not used, because OpenconfigPhysicalChannels is used instead
class NokiaPhysicalChannels(PhysicalChannels):
    prefix = ['state', 'port', 'transceiver', 'digital-diagnostic-monitoring']
    field_mapping = PhysicalChannels.field_mapping.copy()
    field_mapping.update({
        'physical_channels': ['lane'],
    })
    physical_channels: List[NokiaPhysicalChannel] = []
    def __init__(self, data: dict):
        self.populate_from_data(data)
        self.physical_channels = [NokiaPhysicalChannel(physical_channel) for physical_channel in self.physical_channels] if self.physical_channels else []

@dataclass
class NokiaTransceiver(OpenconfigTranseiver):
    prefix = ['state', 'port', 'transceiver']
    field_mapping = OpenconfigTranseiver.field_mapping.copy()
    field_mapping.update({
        'form_factor': ['connector-type'],
        'connector_type': ['connector-code'],
        'vendor_name': ['model-number'],
        # Additional fields
        'vendor_pn': ['vendor-part-number'],
        'bandwidth': ['trans-bw'],
        'wavelength': ['wavelength'],
        'input_power': ['rx-power'],
        'output_power': ['tx-power'],
    })
    # physical_channels : NokiaPhysicalChannels = None
    thresholds : NokiaTransceiverThresholdsList = None
    def __init__(self, data: dict):
        self.populate_from_data(data)
        self.merge_missing_fields_from(OpenconfigTranseiver(data))
        # self.physical_channels = NokiaPhysicalChannels(data)
        self.thresholds = NokiaTransceiverThresholdsList(data)



class NokiaInterface(OpenconfigInterface):
    prefix = []
    field_mapping = OpenconfigInterface.field_mapping.copy()
    field_mapping.update({
        'shaping': ['state', 'port', 'ethernet', 'oper-egress-rate'],
    })
    lldp : NokiaLLDP = None
    shaping: int = None
    transeiver : NokiaTransceiver = None
    def __init__(self, data: dict):
        super().__init__(data)
        self.populate_from_data(data)
        # Fallback: merge missing from OpenConfig
        oc = OpenconfigInterface(data)
        self.merge_missing_fields_from(oc)
        self.lldp = NokiaLLDP(data)
        self.transeiver = NokiaTransceiver(data)