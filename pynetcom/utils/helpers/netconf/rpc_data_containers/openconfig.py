from typing import Dict, List
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import json


class RPCDataContainer():
    # Mapping: attribute name -> path to value
    field_mapping: Dict[str, List[str]] = {}
    prefix: List[str] = []
    # Fields excluded from serialization
    serialization_exclude = { 'field_mapping', 'prefix' }

    def extract_value(self, data: dict, path: List[str], default=None):
        """Extracts value by path"""
        result = data
        path = self.prefix + path
        for key in path:
            if isinstance(result, dict):
                result = result.get(key)
                if result is None:
                    return default
            else:
                return default
        return result if result is not None else default
        
    def remove_namespaces(self, data):
        """
        Recursively removes all keys starting with '@xmlns'
        из словаря или списка любой вложенности.
        """
        if isinstance(data, dict):
            # Create new dictionary without @xmlns keys and with cleaned tag names
            cleaned_dict = {}
            for key, value in data.items():
                # Skip namespace declarations
                if isinstance(key, str) and key.startswith('@xmlns'):
                    continue

                # Recursively clean value
                cleaned_value = self.remove_namespaces(value)

                # If after cleaning the value becomes a dictionary of {'#text': '...'} — expand to primitive
                if isinstance(cleaned_value, dict):
                    # Keep only non-attribute keys (excluding those that start with '@')
                    non_attr_keys = [k for k in cleaned_value.keys() if not (isinstance(k, str) and k.startswith('@'))]
                    if len(non_attr_keys) == 1 and non_attr_keys[0] == '#text':
                        cleaned_value = cleaned_value['#text']

                # Remove namespace prefix from tag name (e.g. 'ns:tag' -> 'tag')
                cleaned_key = key
                if isinstance(cleaned_key, str) and not cleaned_key.startswith('@') and ':' in cleaned_key:
                    cleaned_key = cleaned_key.split(':', 1)[1]

                # Write cleaned key-value pair
                cleaned_dict[cleaned_key] = cleaned_value

            return cleaned_dict

        if isinstance(data, list):
            # Apply cleaning to each list item
            return [self.remove_namespaces(item) for item in data]

        # Primitive types return as is
        return data

    
    def populate_from_data(self, data: dict):
        """Automatically populates fields based on field_mapping"""
        data = self.remove_namespaces(data)
        for attr_name, path in self.field_mapping.items():
            setattr(self, attr_name, self.extract_value(data, path))

    def merge_missing_fields_from(self, other: "RPCDataContainer", keys: List[str] = None):
        """Populates missing (None) fields with values from another container.
        If keys are not provided, takes the union of field_mapping keys and other attributes.
        """
        if keys is None:
            keys = list(set(getattr(other, 'field_mapping', {}).keys()) | set(other.__dict__.keys()))
        for key in keys:
            if getattr(self, key, None) is None:
                value = getattr(other, key, None)
                if value is not None:
                    setattr(self, key, value)

    def _to_plain_value(self, value):
        """Converts value to serializable form for JSON/dictionary."""
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, RPCDataContainer):
            return value.to_dict()
        if isinstance(value, list):
            return [self._to_plain_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._to_plain_value(val) for key, val in value.items()}
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, timedelta):
            return value.total_seconds()
        return value

    def to_dict(self) -> dict:
        """Recursively converts container and its fields into a dictionary.

        - Takes annotated fields from the entire class hierarchy (to include
          values set at the class level, e.g. severity for subclasses)
        - Adds non-annotated fields from __dict__ instance
        - Converts Enum -> .value and nested containers/lists
        """
        result = {}
        # Collect set of excluded fields from entire MRO
        exclude = set()
        for cls in type(self).mro():
            exclude.update(getattr(cls, 'serialization_exclude', set()))

        # Annotated fields from entire MRO (including base classes)
        for cls in type(self).mro():
            annotations = getattr(cls, '__annotations__', {}) or {}
            for name in annotations.keys():
                if name in exclude:
                    continue
                if name in result:
                    continue
                try:
                    value = getattr(self, name)
                except AttributeError:
                    continue
                result[name] = self._to_plain_value(value)

        # Additional fields created on instance
        for name, value in self.__dict__.items():
            if name in exclude:
                continue
            if name not in result:
                result[name] = self._to_plain_value(value)

        return result

    def get_json(self) -> str:
        """Serializes container to JSON with support for Enum and nested containers."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=4)

@dataclass
class DDM(RPCDataContainer):
    temperature = float
    voltage = float
    def __str__(self):
        return (f'Temperature: {self.temperature} C, Voltage: {self.voltage} V')



class PhysicalChannel(RPCDataContainer):
    prefix = ['state']
    field_mapping = {
        'index': ['index'],
        'output_power': ['output-power', 'instant'],
        'input_power': ['input-power', 'instant'],
        'laser_bias_current': ['laser-bias-current', 'instant'],
    }
    index = None
    output_power = None
    input_power = None
    laser_bias_current = None
    def __init__(self, data: dict):
        self.populate_from_data(data)
    def __str__(self):
        return (f"""Index: {self.index}, InputPower: {self.input_power}, OutputPower: {self.output_power}, LaserBiasCurrent: {self.laser_bias_current}""")


class PhysicalChannels(RPCDataContainer):
    prefix = ['components', 'component', 'transceiver', 'physical-channels']
    field_mapping = {
        'physical_channels': ['channel'],
    }
    physical_channels : List[PhysicalChannel] = []
    def __init__(self, data: dict):
        self.populate_from_data(data)
        self.physical_channels = [PhysicalChannel(channel) for channel in self.physical_channels] if self.physical_channels else []
    def __str__(self):
        if self.physical_channels is None or len(self.physical_channels) == 0:
            return str(None)
        return (f"""PhysicalChannels: {"\n\t- ".join(str(channel).strip() for channel in self.physical_channels)}""")

@dataclass
class Severity(Enum):
    CRITICAL = 'CRITICAL'
    MAJOR = 'MAJOR'
    MINOR = 'MINOR'
    WARNING = 'WARNING'
    INDETERMINATE = 'INDETERMINATE'

class OpenconfigTransceiverThreshold(RPCDataContainer):
    prefix = ['state', 'thresholds']
    field_mapping = {
    }
    severity : Severity = None
    input_power_upper = None
    input_power_lower = None
    output_power_upper = None
    output_power_lower = None
    def __init__(self, data: dict):
        self.populate_from_data(data)

    def __str__(self):
        return (f"""Severity: {self.severity}, \n\tInputPowerUpper: {self.input_power_upper}, InputPowerLower: {self.input_power_lower}, OutputPowerUpper: {self.output_power_upper}, OutputPowerLower: {self.output_power_lower}""")

class OpenconfigTransceiverThresholdsList(RPCDataContainer):
    prefix = ['components', 'component', 'transceiver', 'state', 'thresholds']
    field_mapping = {
        'thresholds': ['threshold'],
    }
    thresholds : List[OpenconfigTransceiverThreshold] = []
    def __init__(self, data: dict):
        self.populate_from_data(data)
        self.thresholds = [OpenconfigTransceiverThreshold(threshold) for threshold in self.thresholds] if self.thresholds else []
        self.filter_empty_thresholds()
    def __str__(self):
        return (f"""Thresholds: {"\n\t- ".join(str(threshold).strip() for threshold in self.thresholds)}""")

    def _has_any_value(self, t: OpenconfigTransceiverThreshold) -> bool:
        return any([
            getattr(t, 'input_power_upper', None) is not None,
            getattr(t, 'input_power_lower', None) is not None,
            getattr(t, 'output_power_upper', None) is not None,
            getattr(t, 'output_power_lower', None) is not None,
        ])

    def filter_empty_thresholds(self):
        if not self.thresholds:
            return
        self.thresholds = [t for t in self.thresholds if self._has_any_value(t)]

class OpenconfigTranseiver(RPCDataContainer):
    prefix = ['components', 'component', 'transceiver', 'state']
    field_mapping = {
        'enabled': ['enabled'],
        'present': ['present'],
        'form_factor': ['form-factor'],
        'connector_type': ['connector-type'],
        'vendor': ['vendor'],
        'ethernet_pmd': ['ethernet-pmd'],
        'output_power': ['output-power', 'instant'],
        'input_power': ['input-power', 'instant'],
    }
    enabled = None
    present = None
    form_factor = None
    connector_type = None
    vendor = None
    ethernet_pmd = None
    output_power = None
    input_power = None
    physical_channels : PhysicalChannels = None
    thresholds : OpenconfigTransceiverThresholdsList = None
    def __init__(self, data: dict):
        self.populate_from_data(data)
        self.physical_channels = PhysicalChannels(data)
        self.thresholds = OpenconfigTransceiverThresholdsList(data)
    def __str__(self):
        return (f"""Enabled: {self.enabled}, 
                Present: {self.present}, 
                FormFactor: {self.form_factor},
                ConnectorType: {self.connector_type},
                Vendor: {self.vendor},
                EthernetPMD: {self.ethernet_pmd},
                OutputPower: {self.output_power},
                InputPower: {self.input_power},
                PhysicalChannels: {self.physical_channels},
                Thresholds: {self.thresholds}
                """)

@dataclass
class OpenconfigInterfaceCounters(RPCDataContainer):
    prefix = ['interfaces', 'interface']
    field_mapping = {
        'in_octets': ['state', 'counters', 'in-octets'],
        'out_octets': ['state', 'counters', 'out-octets'],
        'in_pkts': ['state', 'counters', 'in-unicast-pkts'],
        'out_pkts': ['state', 'counters', 'out-unicast-pkts'],
        'in_discards': ['state', 'counters', 'in-discards'],
        'out_discards': ['state', 'counters', 'out-discards'],
        'in_errors': ['state', 'counters', 'in-errors'],
        'out_errors': ['state', 'counters', 'out-errors'],
        'in_crc_errors': ['ethernet', 'state', 'counters', 'in-crc-errors'],
    }
    in_octets = None
    out_octets = None
    in_pkts = None
    out_pkts = None
    in_discards = None
    out_discards = None
    in_errors = None
    out_errors = None
    in_crc_errors = None
    def __init__(self, data: dict):
        self.populate_from_data(data)

    def __str__(self):
        return (
            f"""InOctets: {self.in_octets}, 
            OutOctets: {self.out_octets}, 
            InPkts: {self.in_pkts}, 
            OutPkts: {self.out_pkts}, 
            InDiscards: {self.in_discards}, 
            OutDiscards: {self.out_discards}, 
            InErrors: {self.in_errors}, 
            OutErrors: {self.out_errors}, 
            InCRCErrors: {self.in_crc_errors}'"""
        )
                
    



@dataclass
class OpenconfigInterfaceEthernet(RPCDataContainer):
    prefix = ['interfaces', 'interface', 'ethernet']
    field_mapping = {
        'auto_negotate': ['state', 'auto-negotiate'],
        'port_speed': ['state', 'port-speed'],
        'duplex_mode': ['state', 'duplex-mode'],
    }
    auto_negotate = None # True/False
    port_speed = None # SPEED_1GB, SPEED_10GB
    duplex_mode = None # FULL
    def __init__(self, data: dict):
        self.populate_from_data(data)
    
    def __str__(self):
        return (
            f"""AutoNegotiate: {self.auto_negotate},
            PortSpeed: {self.port_speed},
            DuplexMode: {self.duplex_mode}'
            """
        )
    
class OpenconfigLLDPNeighborState(RPCDataContainer):
    prefix = ['state']
    field_mapping = {
        'system_name': ['system-name'],
        'system_description': ['system-description'],
        'age': ['age'],
        'port_id': ['port-id'],
        'port_description': ['port-description'],
        'management_address': ['management-address'],
        'management_address_type': ['management-address-type'],
    }
    system_name = None
    system_description = None
    age = None
    port_id = None
    port_description = None
    management_address = None
    management_address_type = None
    def __init__(self, data: dict):
        self.populate_from_data(data)
    
    def get_age(self) -> timedelta:
        if self.age is None:
            return None
        if isinstance(self.age, str):
            return timedelta(seconds=int(self.age.strip()))
        return self.age
    def __str__(self):
        return (f"""SystemName: {self.system_name},
                SystemDescription: {self.system_description},
                Age: {self.get_age()},
                PortId: {self.port_id},
                PortDescription: {self.port_description},
                ManagementAddress: {self.management_address},
                ManagementAddressType: {self.management_address_type}
                """
                )
    
class OpenconfigInterfaceLLDP(RPCDataContainer):
    prefix = ['lldp', 'interfaces', 'interface']
    field_mapping = {
        'enabled': ['state', 'enabled'],
        'neighbors': ['neighbors', 'neighbor'],
    }
    enabled = None
    neighbors: List[OpenconfigLLDPNeighborState] = []

    def __init__(self, data: dict):
        self.populate_from_data(data)
        neighbors_raw = self.neighbors or []
        if isinstance(neighbors_raw, dict):
            neighbors_raw = [neighbors_raw]
        self.neighbors = [OpenconfigLLDPNeighborState(neighbor) for neighbor in neighbors_raw]
        
    def __str__(self):
        joined = "\n\t- " + "\n\t- ".join(str(n).strip() for n in self.neighbors) if self.neighbors else "[]"
        return (f"""Enabled: {self.enabled},
                Neighbors: {joined}
                """
                )

@dataclass
class OpenconfigInterface(RPCDataContainer):
    prefix = ['interfaces', 'interface']
    field_mapping = {
        'name': ['state', 'name'],
        'description': ['state', 'description'],
        'admin_status': ['state', 'admin-status'],
        'oper_status': ['state', 'oper-status'],
        'last_state_change': ['state', 'last-change'],
    }
    name = None
    description = None
    admin_status = None
    oper_status = None
    last_state_change = None
    counters : OpenconfigInterfaceCounters = None
    ethernet : OpenconfigInterfaceEthernet = None
    transeiver : OpenconfigTranseiver = None
    lldp : OpenconfigInterfaceLLDP = None
    def __init__(self, data: dict):
        self.populate_from_data(data)
        self.counters = OpenconfigInterfaceCounters(data)
        self.ethernet = OpenconfigInterfaceEthernet(data)
        self.transeiver = OpenconfigTranseiver(data)
        self.lldp = OpenconfigInterfaceLLDP(data)

    def get_last_change(self) -> datetime:
        """Преобразует значение last-change из микросекунд в datetime"""
        # print(self.last_state_change, type(self.last_state_change))
        if self.last_state_change is None:
            return None
        if isinstance(self.last_state_change, str):
            timestamp = int(self.last_state_change.strip())
        timestamp = timestamp / 1_000_000_000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)

    def __str__(self):
        return (f"""Name: {self.name}, 
                Admin: {self.admin_status}, 
                Oper: {self.oper_status},
                Description: {self.description},
                Last Change: {self.get_last_change()},
                \nCounters: \t{self.counters}\n
                \nEthernet: \t{self.ethernet}\n
                \nTranseiver: \t{self.transeiver}
                \nLLDP: \t{self.lldp}
                """
                )

    def get_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=4)
    


