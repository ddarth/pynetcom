from dataclasses import dataclass
from typing import List
from .openconfig import (
    RPCDataContainer,
    OpenconfigTranseiver,
    OpenconfigInterface,
    DDM,
    PhysicalChannel,
    PhysicalChannels,
    OpenconfigTransceiverThreshold,
    OpenconfigTransceiverThresholdsList,
    Severity,
    parse_utc_datetime,
)


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
class HuaweiInterfaceEthernet(RPCDataContainer):
    """
    Huawei-specific Ethernet state mapper.
    Fills OpenConfig-like fields from Huawei PIC model:
    devm -> ports -> port -> ethernet (huawei-pic)
    """
    prefix = ['devm', 'ports', 'port']
    field_mapping = {
        'auto_negotate': ['ethernet', 'negotiation'],   # 'enabled'/'disabled'
        'port_speed': ['physical-bandwidth'],            # e.g. '1000M'
        'duplex_mode': ['ethernet', 'duplex-status'],          # 'full'/'half'
    }
    auto_negotate = None
    port_speed = None
    duplex_mode = None
    def __init__(self, data: dict):
        self.populate_from_data(data)
        # Normalize negotiation to boolean if possible, otherwise keep raw value
        if isinstance(self.auto_negotate, str):
            val = self.auto_negotate.strip().lower()
            if val in ('enabled', 'enable', 'true', 'yes'):
                self.auto_negotate = True
            elif val in ('disabled', 'disable', 'false', 'no'):
                self.auto_negotate = False

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
        'last_up_time': ['devm', 'ports', 'port', 'last-up-time'],
        'last_down_time': ['devm', 'ports', 'port', 'last-down-time'],
    })
    transeiver: HuaweiTransceiver = None
    shaping: int = None
    last_up_time = None
    last_down_time = None
    def __init__(self, data: dict):
        super().__init__(data)
        self.populate_from_data(data)
        # Fallback: merge missing from OpenConfig
        oc = OpenconfigInterface(data)
        self.merge_missing_fields_from(oc)

        # Merge Huawei-specific Ethernet values into OpenConfig Ethernet if missing
        if getattr(self, 'ethernet', None) is not None:
            h_eth = HuaweiInterfaceEthernet(data)
            self.ethernet.merge_missing_fields_from(h_eth, keys=['auto_negotate', 'port_speed', 'duplex_mode'])

        self.transeiver = HuaweiTransceiver(data)

        # Compute last_state_change based on Huawei-specific devm times, if available
        candidates = [
            parse_utc_datetime(self.last_up_time),
            parse_utc_datetime(self.last_down_time),
        ]
        candidates = [dt for dt in candidates if dt is not None]
        if candidates:
            self.last_state_change = max(candidates)

    def __str__(self):
        return (super().__str__() + f"""
                Shaping: {self.shaping}
                """
                )

