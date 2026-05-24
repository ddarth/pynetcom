from dataclasses import dataclass
from .openconfig import OpenconfigLLDPNeighborState, OpenconfigInterfaceLLDP, OpenconfigInterface, OpenconfigTranseiver
from typing import Dict, List, Optional
from .openconfig import OpenconfigTransceiverThresholdsList, OpenconfigTransceiverThreshold, PhysicalChannel, PhysicalChannels, Severity
from .openconfig import RPCDataContainer


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
        # Example of a full format:
        # "1/1/24, 100Mb/1-Gig/10-Gig Ethernet, \"Oc.RRS26.AC_01 MMM 1/1/22 (RTN980 1/17/3)\""
        # In practice, the string may be shorter and without commas.
        if not isinstance(self.port_description, str):
            return

        parts = [p.strip().replace('"', '') for p in self.port_description.split(',')]
        if not parts:
            return

        # Always use the first part as port_id
        self.port_id = parts[0]

        # If there is a textual description (third part) — take it,
        # otherwise keep the last available part (or the original string).
        if len(parts) >= 3:
            self.port_description = parts[2]
        else:
            self.port_description = parts[-1]

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

def _deep_merge_dicts(primary: dict, secondary: dict) -> dict:
    """
    Merge two dictionaries shallowly with nested dict support.
    Values from 'secondary' are added only if missing in 'primary'.
    For nested dicts, merge recursively.
    """
    result = dict(primary) if isinstance(primary, dict) else {}
    if not isinstance(secondary, dict):
        return result
    for k, v in secondary.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge_dicts(result[k], v)
        elif k not in result:
            result[k] = v
    return result

def _build_merged_nokia_port_view(raw_data: dict) -> dict:
    """
    Nokia SROS specific:
    - Responses contain multiple 'state.port' entries: connector (physical, transceiver)
      and breakout (logical, ethernet/lldp).
    - We construct a synthetic view where 'state.port' is a single dict that merges:
        - 'transceiver' from connector entry
        - 'ethernet' (incl. lldp, shaping) from breakout entry
    This allows downstream field mappings to work as if everything lived under one port.
    """
    cleaner = RPCDataContainer()
    data = cleaner.remove_namespaces(raw_data)
    state = data.get('state') or {}
    ports = state.get('port')
    if not isinstance(ports, list):
        # Already a single port or unexpected shape; return as-is
        return data

    connector_port = None
    breakout_port = None
    for p in ports:
        if isinstance(p, dict):
            if 'transceiver' in p:
                connector_port = p
            if 'ethernet' in p:
                breakout_port = p

    # Base: prefer breakout (to keep correct port-id for logical side), then connector
    merged_port = {}
    if breakout_port:
        merged_port = dict(breakout_port)
    if connector_port:
        # Add physical/transceiver info from connector
        merged_port = _deep_merge_dicts(merged_port, {'transceiver': connector_port.get('transceiver')})
        # Preserve connector-specific attributes if missing (like if-index)
        merged_port = _deep_merge_dicts(merged_port, {k: v for k, v in connector_port.items() if k not in ('ethernet', 'transceiver')})

    # If neither identified, return original data
    if not merged_port:
        return data

    # Assemble merged data tree
    merged_data = dict(data)
    merged_state = dict(state)
    merged_state['port'] = merged_port
    merged_data['state'] = merged_state
    return merged_data

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
    """Nokia SR OS port interface (state-tree subset).

    The ``encap_type`` attribute (vendor-agnostic indicator of
    tagged/untagged port encapsulation — see
    :class:`OpenconfigInterface.encap_type` docstring) is NOT populated by
    this parser. The source leaf
    (``configure/port/<port-id>/ethernet/encap-type``) lives in the
    configure datastore (``urn:nokia.com:sros:ns:yang:sr:conf``) and only
    surfaces when fetched via ``<get-config source="running"
    with-defaults="report-all">`` — the per-port subtree filter
    :class:`NokiaInterfaceRPCRequest` uses operates on the state-tree
    (``<get>``).

    The recommended orchestration is to perform ONE bulk
    :class:`~pynetcom.utils.helpers.netconf.rpc_requests.NokiaPortConfigRPCRequest`
    round-trip and merge the resulting ``{port-id: encap-type}`` map into
    the per-port :class:`NokiaInterface` objects with
    :func:`apply_port_encap_type_map`. See that function's docstring for
    the rationale (one cheap RPC vs N-per-port).
    """
    prefix = []
    field_mapping = OpenconfigInterface.field_mapping.copy()
    field_mapping.update({
        'last_state_change': ['state', 'port', 'oper-state-last-changed'],
        'shaping': ['state', 'port', 'ethernet', 'oper-egress-rate'],
    })
    lldp : NokiaLLDP = None
    shaping: int = None
    transeiver : NokiaTransceiver = None
    def __init__(self, data: dict):
        super().__init__(data)
        # Nokia-specific: merge connector+breakout into a unified 'state.port' view
        merged = _build_merged_nokia_port_view(data)
        # Populate Nokia-specific fields (e.g. shaping) from merged view
        self.populate_from_data(merged)
        # Fallback: merge missing from OpenConfig
        oc = OpenconfigInterface(data)
        self.merge_missing_fields_from(oc)
        # Build sub-containers from merged view to ensure LLDP and thresholds are present
        self.lldp = NokiaLLDP(merged)
        self.transeiver = NokiaTransceiver(merged)


def parse_port_encap_type_map(response: dict) -> Dict[str, str]:
    """Parse a NokiaPortConfigRPCRequest reply into a ``{port_id: encap_type}`` map.

    The response shape (configure namespace,
    ``urn:nokia.com:sros:ns:yang:sr:conf``)::

        configure/port[port-id]/ethernet/encap-type

    Returns a flat dict, e.g. ``{"1/1/11": "null", "1/1/15": "dot1q"}``.

    Notes
    -----
    * The default-valued ``encap-type=null`` only appears in the response
      when the caller passed ``with_defaults="report-all"`` to
      :meth:`NetconfClient.get_config`. Without it, untagged ports drop
      out of the map silently, and the caller cannot distinguish
      "explicitly default" from "leaf absent because misconfigured" —
      ALWAYS pair this parser with ``with_defaults="report-all"``.
    * Ports lacking an ``ethernet`` container entirely (e.g. management
      ``A/1`` on certain MDA combinations) are skipped — there is no
      Ethernet encapsulation to report.
    """
    if not isinstance(response, dict):
        return {}
    container = OpenconfigInterface({})
    cleaned = container.remove_namespaces(container._unwrap_data_node(response))
    configure_root = cleaned.get("configure") or cleaned
    ports = configure_root.get("port")
    if ports is None:
        return {}
    if isinstance(ports, dict):
        ports = [ports]

    out: Dict[str, str] = {}
    for entry in ports:
        if not isinstance(entry, dict):
            continue
        port_id = entry.get("port-id")
        if not port_id:
            continue
        eth = entry.get("ethernet")
        if not isinstance(eth, dict):
            # No <ethernet> container — no encap-type leaf to report.
            continue
        encap = eth.get("encap-type")
        if encap is None:
            continue
        out[port_id] = str(encap).strip().lower()
    return out


def apply_port_encap_type_map(
    interfaces: List["NokiaInterface"],
    encap_map: Dict[str, str],
) -> None:
    """Stamp ``encap_type`` on each NokiaInterface from a port-config map.

    In-place mutation: iterates over ``interfaces`` and sets
    ``iface.encap_type`` to ``encap_map[iface.name]`` when present.
    Interfaces not present in the map (e.g. LAGs like ``lag-1`` —
    LAG-level encap is on the underlying physical ports, not the LAG
    itself) are left untouched.

    Use after a bulk
    :class:`~pynetcom.utils.helpers.netconf.rpc_requests.NokiaPortConfigRPCRequest`
    round-trip so the operator avoids N+1 get-config calls.
    """
    if not encap_map:
        return
    for iface in interfaces:
        if iface is None:
            continue
        port_id = getattr(iface, "name", None)
        if not port_id:
            continue
        value = encap_map.get(port_id)
        if value is not None:
            iface.encap_type = value