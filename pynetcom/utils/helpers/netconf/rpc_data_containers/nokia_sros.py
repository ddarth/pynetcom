from dataclasses import dataclass
from .openconfig import OpenconfigLLDPNeighborState, OpenconfigInterfaceLLDP, OpenconfigInterface, OpenconfigTranseiver
from typing import Dict, List, Optional
from .openconfig import OpenconfigTransceiverThresholdsList, OpenconfigTransceiverThreshold, PhysicalChannel, PhysicalChannels, Severity
from .openconfig import RPCDataContainer
from pynetcom.utils import nokia_router_tools


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


# Per-lane container: one ``lane`` entry from
# ``digital-diagnostic-monitoring/lane[N]``. ``lane-id`` is the 1-based
# lane index; per-lane Tx/Rx/bias live under the ``current`` leaf of each
# power block. Used by :class:`NokiaTransceiver` to populate
# ``physical_channels`` for multi-lane 100G modules.
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

# Per-lane list under ``state/port/transceiver/digital-diagnostic-monitoring``.
# NATIVE Nokia path (the OpenConfig ``physical-channels`` subtree is not
# populated by SR OS). Wired into :class:`NokiaTransceiver.physical_channels`.
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
    """Nokia SR OS transceiver (state-tree subset).

    Fields come from ``/state/port/transceiver`` (NS
    ``urn:nokia.com:sros:ns:yang:sr:state``). Nokia does not publish a
    decoded ``ethernet-pmd`` leaf — it only exposes the raw EEPROM bytes
    (SFF-8472 / 8636 / 8024). The decoding is delegated to
    :func:`nokia_router_tools.derive_ethernet_pmd_from_sff`.

    Vendor-agnostic normalisation applied here:

    * ``equipped="true"`` → ``present="PRESENT"``,
      ``equipped="false"`` → ``present="NOT_PRESENT"``. The state-tree has
      no ``present`` leaf of its own — we derive it from ``equipped``.
    * ``laser-wavelength=0`` → ``trans_mode="copper-mode"``; otherwise
      ``trans_mode="single-mode"`` (our fleet has no multi-mode SFPs on
      network ports, so we do not publish a more specific value).
    * ``transmission_distance`` is derived from ``link-length-information``
      via :func:`nokia_router_tools.transmission_distance_from_sff`.
    """

    prefix = ['state', 'port', 'transceiver']
    field_mapping = OpenconfigTranseiver.field_mapping.copy()
    field_mapping.update({
        'form_factor': ['connector-type'],
        'connector_type': ['connector-code'],
        'vendor_name': ['model-number'],
        # Additional fields
        'vendor_pn': ['vendor-part-number'],
        'bandwidth': ['trans-bw'],
        'wavelength': ['laser-wavelength'],
        'input_power': ['rx-power'],
        'output_power': ['tx-power'],
        # Raw SFF dumps plus the module-present flag.
        'optical_compliance': ['optical-compliance'],
        'optical_compliance_extension': ['optical-compliance-extension'],
        'link_length_information': ['link-length-information'],
        'equipped': ['equipped'],
    })
    # The raw SFF fields are an implementation detail and are not exposed.
    serialization_exclude = OpenconfigTranseiver.serialization_exclude | {
        'optical_compliance',
        'optical_compliance_extension',
        'link_length_information',
        'equipped',
    }
    optical_compliance = None
    optical_compliance_extension = None
    link_length_information = None
    equipped = None
    physical_channels : "NokiaPhysicalChannels" = None
    thresholds : NokiaTransceiverThresholdsList = None
    def __init__(self, data: dict):
        self.populate_from_data(data)
        # Per-lane optics for multi-lane modules (100G cfp2 / qsfp28-LR4).
        # Nokia keeps per-lane Tx/Rx under
        # ``state/port/transceiver/digital-diagnostic-monitoring/lane[1..4]``
        # — a NATIVE subtree, NOT the OpenConfig ``physical-channels`` path
        # (Nokia does not populate that). Set this BEFORE the OpenConfig
        # merge so the (empty) OC ``physical_channels`` does not overwrite
        # the native lanes. For 10G single-lane modules the ``lane`` list is
        # absent and this yields an empty list — the aggregate
        # ``input_power`` / ``output_power`` cover those. Verified live
        # 24 Jul 2026 on ``Oc.MSC_3.CR_01`` port 3/1/1 (cfp2, 4 lanes).
        self.physical_channels = NokiaPhysicalChannels(data)
        self.merge_missing_fields_from(OpenconfigTranseiver(data))
        self.thresholds = NokiaTransceiverThresholdsList(data)
        # Vendor-agnostic field normalisation.
        self._normalise_present()
        self._derive_trans_mode()
        self._derive_transmission_distance()
        self._derive_ethernet_pmd_from_sff(data)
        # Nokia 7250 IXR returns ``form_factor`` as a namespaced identity
        # (e.g. ``openconfig-transport-types:QSFP28``). Strip + lowercase
        # so the vendor-agnostic dataclass yields the OpenAPI enum form.
        self._normalise_form_factor()

    def _normalise_present(self) -> None:
        """``equipped="true"`` → ``present="PRESENT"``; ``"false"`` → ``"NOT_PRESENT"``."""
        eq = self.equipped
        if isinstance(eq, str):
            val = eq.strip().lower()
            if val == 'true':
                if not self.present:
                    self.present = 'PRESENT'
            elif val == 'false':
                self.present = 'NOT_PRESENT'

    def _derive_trans_mode(self) -> None:
        """``laser-wavelength=0`` → copper-mode; otherwise single-mode."""
        if self.trans_mode:
            return
        wl = self.wavelength
        try:
            wl_int = int(float(str(wl).strip())) if wl is not None else None
        except (TypeError, ValueError):
            wl_int = None
        if wl_int == 0:
            self.trans_mode = 'copper-mode'
        elif wl_int is not None and wl_int > 0:
            self.trans_mode = 'single-mode'

    def _derive_transmission_distance(self) -> None:
        """Derive the distance in metres from ``link-length-information``."""
        if self.transmission_distance is not None:
            return
        self.transmission_distance = nokia_router_tools.transmission_distance_from_sff(
            self.link_length_information,
        )

    def _derive_ethernet_pmd_from_sff(self, raw_data: dict) -> None:
        """Decode the precise PMD identity from the raw SFF dump.

        Uses ``optical-compliance``, ``optical-compliance-extension``,
        ``laser-wavelength`` and the port-level ``type`` leaf (the latter
        disambiguates 1G versus 10G BiDi modules that share identical SFF
        bytes). For an empty / NOT_PRESENT module the helper receives an
        empty string and returns None.
        """
        if self.present == 'NOT_PRESENT':
            self.ethernet_pmd = None
            return
        # Port-level <type> leaf is needed for BiDi disambiguation.
        port_type = self._extract_port_type(raw_data)
        derived = nokia_router_tools.derive_ethernet_pmd_from_sff(
            self.optical_compliance,
            self.optical_compliance_extension,
            wavelength=self.wavelength,
            port_type=port_type,
        )
        if derived:
            self.ethernet_pmd = derived
        # If the helper returns None we keep whatever was there (either
        # None from OC or a valid OC value if one happens to arrive).

    def _extract_port_type(self, raw_data) -> Optional[str]:
        """Extract ``/state/port/type`` (or ``state.port.type``) from the raw dict.

        The shape may be a single ``port`` dict or a list (Nokia merged
        view). The lookup is defensive: any unexpected shape yields None.
        """
        if not isinstance(raw_data, dict):
            return None
        node = self._unwrap_data_node(raw_data)
        node = self.remove_namespaces(node)
        state = node.get('state') if isinstance(node, dict) else None
        if not isinstance(state, dict):
            return None
        port = state.get('port')
        if isinstance(port, list):
            for p in port:
                if isinstance(p, dict) and 'transceiver' in p and isinstance(p.get('type'), str):
                    return p['type']
            # Fallback: any entry that carries a ``type`` leaf.
            for p in port:
                if isinstance(p, dict) and isinstance(p.get('type'), str):
                    return p['type']
            return None
        if isinstance(port, dict):
            t = port.get('type')
            return t if isinstance(t, str) else None
        return None



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


def parse_multi_port_interface_response(
    response: dict, ports: List[str]
) -> List["NokiaInterface"]:
    """Split a :class:`NokiaMultiPortInterfaceRPCRequest` reply into per-port objects.

    The batch ``<get>`` returns an interleaved ``/state/port`` list (a
    connector entry with ``transceiver`` and a breakout entry with
    ``ethernet`` per requested port) plus one OpenConfig
    ``/interfaces/interface`` per port. Because
    :func:`_build_merged_nokia_port_view` merges *whatever* connector +
    breakout it finds in a port list, feeding the whole batch to
    :class:`NokiaInterface` at once would cross-contaminate ports — so this
    function slices a single-port view per requested port-id first
    (connector + breakout grouped by the same
    :func:`~pynetcom.utils.helpers.netconf.rpc_requests.nokia_connector_breakout`
    split the builder used) and materialises one :class:`NokiaInterface`
    each (transceiver with per-lane optics + oper/admin status).

    :param response: raw NETCONF reply dict (xmltodict shape).
    :param ports: the SAME port-id list passed to the builder — needed to
        regroup connector/breakout entries deterministically.
    :rtype: List[NokiaInterface]
    """
    if not isinstance(response, dict) or not ports:
        return []
    from pynetcom.utils.helpers.netconf.rpc_requests import nokia_connector_breakout

    cleaner = RPCDataContainer()
    cleaned = cleaner.remove_namespaces(cleaner._unwrap_data_node(response))
    if not isinstance(cleaned, dict):
        return []

    state = cleaned.get('state') or {}
    port_entries = state.get('port')
    if isinstance(port_entries, dict):
        port_entries = [port_entries]
    if not isinstance(port_entries, list):
        port_entries = []
    by_id: Dict[str, list] = {}
    for p in port_entries:
        if isinstance(p, dict) and p.get('port-id') is not None:
            by_id.setdefault(p['port-id'], []).append(p)

    oc_ifaces = (cleaned.get('interfaces') or {}).get('interface')
    if isinstance(oc_ifaces, dict):
        oc_ifaces = [oc_ifaces]
    if not isinstance(oc_ifaces, list):
        oc_ifaces = []
    oc_by_name: Dict[str, dict] = {}
    for oc in oc_ifaces:
        if isinstance(oc, dict):
            nm = oc.get('name') or (oc.get('state') or {}).get('name')
            if nm:
                oc_by_name[nm] = oc

    out: List["NokiaInterface"] = []
    for port in ports:
        connector, breakout = nokia_connector_breakout(port)
        matched: list = []
        for pid in dict.fromkeys([connector, breakout]):  # preserve order, dedupe
            matched.extend(by_id.get(pid, []))
        if not matched:
            continue
        sub: dict = {'state': {'port': matched}}
        oc = oc_by_name.get(breakout) or oc_by_name.get(port)
        if oc is not None:
            sub['interfaces'] = {'interface': oc}
        out.append(NokiaInterface(sub))
    return out


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