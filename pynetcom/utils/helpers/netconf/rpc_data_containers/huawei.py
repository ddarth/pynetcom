from dataclasses import dataclass
from .openconfig import RPCDataContainer
from .openconfig import OpenconfigTranseiver, OpenconfigInterface
from .openconfig import DDM
from .openconfig import PhysicalChannel, PhysicalChannels
from .openconfig import OpenconfigTransceiverThreshold, OpenconfigTransceiverThresholdsList
from .openconfig import Severity
from typing import List


@dataclass
class HuaweiDDM(DDM, RPCDataContainer):
    prefix = ['devm', 'ports', 'port', 'optical-module']
    field_mapping = {
        'temperature': ['temperature'],
        'voltage': ['voltage'],
    }
    def __init__(self, data: dict):
        self.populate_from_data(data)

@dataclass
class HuaweiPhysicalChannel(PhysicalChannel):
    prefix = []
    field_mapping = PhysicalChannel.field_mapping.copy()
    field_mapping.update({
        'index': ['number'],
        'output_power': ['tx-power'],
        'input_power': ['rx-power'],
        'laser_bias_current': ['bias'],
        # Additional fields
        'wavelength': ['wavelength'],
    })
    wavelength = None
    def __init__(self, data: dict):
        self.populate_from_data(data)

@dataclass
class HuaweiPhysicalChannels(PhysicalChannels):
    prefix = ['devm', 'ports', 'port', 'optical-module']
    field_mapping = PhysicalChannels.field_mapping.copy()
    field_mapping.update({
        'physical_channels': ['channels', 'channel'],
    })
    def __init__(self, data: dict):
        self.populate_from_data(data)
        self.physical_channels = [HuaweiPhysicalChannel(channel) for channel in self.physical_channels] if self.physical_channels else []

@dataclass
class HuaweiTransceiverThresholdCritical(OpenconfigTransceiverThreshold):
    prefix = ['devm', 'ports', 'port', 'optical-module']
    field_mapping = OpenconfigTransceiverThreshold.field_mapping.copy()
    field_mapping.update({
        'input_power_upper': ['rx-high-alarm-power'],
        'input_power_lower': ['rx-low-alarm-power'],
        'output_power_upper': ['tx-high-alarm-power'],
        'output_power_lower': ['tx-low-alarm-power'],
    })
    severity = Severity.CRITICAL
    def __init__(self, data: dict):
        self.populate_from_data(data)

@dataclass
class HuaweiTransceiverThresholdWarning(OpenconfigTransceiverThreshold):
    prefix = ['devm', 'ports', 'port', 'optical-module']
    field_mapping = OpenconfigTransceiverThreshold.field_mapping.copy()
    field_mapping.update({
        'input_power_upper': ['rx-high-warn-power'],
        'input_power_lower': ['rx-low-warn-power'],
        'output_power_upper': ['tx-high-warn-power'],
        'output_power_lower': ['tx-low-warn-power'],
    })
    severity = Severity.WARNING
    def __init__(self, data: dict):
        self.populate_from_data(data)


class HuaweiTransceiverThresholdsList(OpenconfigTransceiverThresholdsList):
    thresholds : List[OpenconfigTransceiverThreshold] = []
    def __init__(self, data: dict):
        threshold_critical = HuaweiTransceiverThresholdCritical(data)
        threshold_warning = HuaweiTransceiverThresholdWarning(data)
        self.thresholds = [threshold_critical, threshold_warning]
        self.filter_empty_thresholds()


@dataclass
class HuaweiTransceiver(OpenconfigTranseiver):
    prefix = ['devm', 'ports', 'port', 'optical-module']
    field_mapping = OpenconfigTranseiver.field_mapping.copy()
    field_mapping.update({
        'vendor_name': ['vendor-name'],
        'form_factor': ['type'],
        'connector_type': ['fiber-type'],
        'vendor_pn': ['vendor-pn'],
        'bandwidth': ['trans-bw'],
        'wavelength': ['wavelength'],
        'input_power': ['rx-power'],
        'output_power': ['tx-power'],
    })
    vendor_name = None
    vendor_pn = None
    bandwidth = None
    wavelength = None
    input_power = None
    output_power = None
    ddm = None
    physical_channels = None
    thresholds = None
    def __init__(self, data: dict):
        # Populate Huawei-specific subtree first
        self.populate_from_data(data)
        # Fallback: merge missing from OpenConfig
        oc = OpenconfigTranseiver(data)
        self.merge_missing_fields_from(oc)
        self.ddm = HuaweiDDM(data)
        self.physical_channels = HuaweiPhysicalChannels(data)
        self.thresholds = HuaweiTransceiverThresholdsList(data)
    def __str__(self):
        return (super().__str__() + f"""
                DDM: {None if self.form_factor == 'copper' else self.ddm}
                Additional info:
                VendorPN: {self.vendor_pn},
                Bandwidth: {self.bandwidth},
                Wavelength: {self.wavelength},
                """
                )

@dataclass
class HuaweiInterface(OpenconfigInterface):
    prefix = []
    field_mapping = OpenconfigInterface.field_mapping.copy()
    field_mapping.update({
        'shaping': ['ifm', 'interfaces', 'interface', 'qos', 'port-shapings', 'port-shaping', 'shaping-value'],
    })
    transeiver: HuaweiTransceiver = None
    shaping: int = None
    def __init__(self, data: dict):
        super().__init__(data)
        self.populate_from_data(data)
        # Fallback: merge missing from OpenConfig
        oc = OpenconfigInterface(data)
        self.merge_missing_fields_from(oc)

        self.transeiver = HuaweiTransceiver(data)

    def __str__(self):
        return (super().__str__() + f"""
                Shaping: {self.shaping}
                """
                )

