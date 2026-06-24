from dataclasses import dataclass
from typing import Dict, List, Optional
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
from pynetcom.utils import huawei_router_tools


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
    """Huawei VRP transceiver. Field sources:

    * ``devm/ports/port/optical-module`` (huawei-pic NS) — primary source
      of Huawei-specific fields: ``trans-bw``, ``trans-mode``,
      ``wavelength``, ``transmission-distance``, ``vendor-pn`` and the
      measured tx/rx-power.
    * ``components/component/transceiver/state`` (OpenConfig) — fallback
      via :meth:`merge_missing_fields_from`. The useful field here is
      ``ethernet-pmd``: Huawei publishes the decoded identity directly,
      so we never see raw EEPROM bytes.

    ``ethernet_pmd`` is resolved by the following priority chain:

    1. If ``trans-mode == "copper-mode"`` the module is a copper SFP. We
       call :func:`huawei_router_tools.copper_pmd_from_bw` (a direct
       ``trans-bw → EXT_ETH_*BASE_T*`` mapping). This is NOT a heuristic
       — ``trans-mode`` is an explicit Huawei YANG leaf.
    2. Otherwise, if the OC namespace gave us a valid ``ETH_*`` identity
       (not ``ETH_UNDEFINED``), we keep it normalised by
       ``_normalise_ethernet_pmd`` on the base class.
    3. Otherwise ``ethernet_pmd`` stays ``None``. We deliberately do not
       guess by distance or wavelength — the AI consumer receives the raw
       fields and assesses the type cautiously.
    """

    prefix = ['devm', 'ports', 'port', 'optical-module']
    field_mapping = OpenconfigTranseiver.field_mapping.copy()
    field_mapping.update({
        'vendor_name': ['vendor-name'],
        'form_factor': ['type'],
        'connector_type': ['fiber-type'],
        'vendor_pn': ['vendor-pn'],
        'bandwidth': ['trans-bw'],
        'wavelength': ['wavelength'],
        'transmission_distance': ['transmission-distance'],
        'trans_mode': ['trans-mode'],
        'input_power': ['rx-power'],
        'output_power': ['tx-power'],
    })
    vendor_name = None
    vendor_pn = None
    bandwidth = None
    wavelength = None
    transmission_distance = None
    trans_mode = None
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
        # Resolve ethernet_pmd per the priority chain (see class docstring).
        self._resolve_ethernet_pmd()
        self.ddm = HuaweiDDM(data)
        self.physical_channels = HuaweiPhysicalChannels(data)
        self.thresholds = HuaweiTransceiverThresholdsList(data)

    def _resolve_ethernet_pmd(self) -> None:
        """Populate ``ethernet_pmd`` per the Huawei rules (see class docstring)."""
        # 1) An explicit copper-mode marker from the device wins over OC.
        mode = (self.trans_mode or '').strip().lower() if isinstance(self.trans_mode, str) else ''
        if mode == 'copper-mode':
            self.ethernet_pmd = huawei_router_tools.copper_pmd_from_bw(self.bandwidth)
            return
        # 2) The base ``OpenconfigTranseiver.__init__`` has already
        #    normalised OC ``ethernet-pmd`` (namespace prefix stripped,
        #    ``ETH_UNDEFINED`` → None). Nothing else to do — optical
        #    modules end up with the precise OC identity or with ``None``
        #    (the AI consumer then assesses the type from the raw fields).
        return

    def __str__(self):
        # Copper is identified by the ``BASE_T`` / ``BASE_TX`` substring in
        # ``ethernet_pmd``; ``form_factor`` now only carries OC-valid
        # identities (sfp / sfp-plus / qsfp28 / ...).
        is_copper = isinstance(self.ethernet_pmd, str) and (
            'BASE_T' in self.ethernet_pmd or 'BASE_TX' in self.ethernet_pmd
        )
        return (super().__str__() + f"""
                DDM: {None if is_copper else self.ddm}
                Additional info:
                VendorPN: {self.vendor_pn},
                Bandwidth: {self.bandwidth},
                Wavelength: {self.wavelength},
                TransmissionDistance: {self.transmission_distance},
                TransMode: {self.trans_mode},
                """
                )

@dataclass
class HuaweiInterface(OpenconfigInterface):
    """Huawei VRP port interface (state-tree subset).

    The ``encap_type`` attribute (vendor-agnostic indicator of
    tagged/untagged port encapsulation — see
    :class:`OpenconfigInterface.encap_type` docstring) has no single
    source leaf on Huawei: probed live on an ATN-910C, neither
    ``/ifm/interfaces/interface`` nor
    ``/devm/ports/port/ethernet`` (the huawei-pic Ethernet container)
    expose a port-level encap-type field. Instead the value is derived
    client-side from the presence of sub-interfaces:

      * one or more sibling ``/ifm/interfaces/interface`` entries with
        ``class=sub-interface`` and ``parent-name`` equal to this port
        name  → ``encap_type="dot1q"``
      * zero such siblings → ``encap_type="null"``

    The single-port :class:`HuaweiInterfaceRPCRequest` filter does not
    return sibling sub-interfaces (the YANG list key is ``name``, which
    is exact-match, and ``parent-name`` is not a valid filter key
    either — probed live). The recommended orchestration is therefore
    to issue ONE cheap bulk
    :class:`~pynetcom.utils.helpers.netconf.rpc_requests.HuaweiSubInterfaceListRPCRequest`
    fetching ``{name, class, parent-name}`` for every interface, build a
    parent-index with :func:`parse_sub_interface_parents`, and stamp
    ``encap_type`` on each interface via :func:`apply_sub_interface_index`.

    For single-interface callers, :meth:`derive_encap_type` is a one-shot
    helper.
    """
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

    @staticmethod
    def derive_encap_type(
        port_name: str,
        sub_if_index: Dict[str, List[str]],
    ) -> str:
        """Compute ``encap_type`` for one Huawei port from a sub-IF index.

        :param port_name: parent port name (``"GigabitEthernet0/2/28"``,
            ``"Eth-Trunk2"``, …).
        :type port_name: str
        :param sub_if_index: ``{parent_name: [child_name, ...]}`` from
            :func:`parse_sub_interface_parents`. Missing parent → port has
            zero children → ``"null"``.
        :type sub_if_index: Dict[str, List[str]]
        :return: ``"dot1q"`` if the port has >=1 sub-interface, otherwise
            ``"null"``. Never returns ``None`` for a known port — the
            absence of children is itself the answer.
        :rtype: str
        """
        if not port_name:
            return "null"
        children = sub_if_index.get(port_name) or []
        return "dot1q" if children else "null"


def parse_sub_interface_parents(response: dict) -> Dict[str, List[str]]:
    """Parse a HuaweiSubInterfaceListRPCRequest reply into a parent index.

    Returns ``{parent_name: [child_names]}`` where ``parent_name`` is the
    physical / aggregated parent (e.g. ``"GigabitEthernet0/2/28"``,
    ``"Eth-Trunk2"``) and ``child_names`` are the
    ``class=sub-interface`` siblings whose ``parent-name`` matches.

    Notes
    -----
    * Main interfaces (``class=main-interface``) and other non-
      ``sub-interface`` rows are skipped — they're not children.
    * Rows with empty / missing ``parent-name`` are also skipped — defensive
      against malformed responses (a valid sub-interface always carries
      ``parent-name``).
    * The order of children inside each list mirrors the response order,
      which on Huawei is typically the operator's creation order; no
      sorting is applied here.
    """
    if not isinstance(response, dict):
        return {}
    container = OpenconfigInterface({})
    cleaned = container.remove_namespaces(container._unwrap_data_node(response))
    ifm = cleaned.get("ifm") or {}
    interfaces_node = ifm.get("interfaces") or {}
    rows = interfaces_node.get("interface")
    if rows is None:
        return {}
    if isinstance(rows, dict):
        rows = [rows]

    index: Dict[str, List[str]] = {}
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        if entry.get("class") != "sub-interface":
            continue
        parent = entry.get("parent-name")
        if not parent:
            continue
        name = entry.get("name")
        if not name:
            continue
        index.setdefault(parent, []).append(name)
    return index


def apply_sub_interface_index(
    interfaces: List["HuaweiInterface"],
    sub_if_index: Dict[str, List[str]],
) -> None:
    """Stamp ``encap_type`` on each HuaweiInterface from a sub-IF index.

    In-place mutation: iterates over ``interfaces`` and sets
    ``iface.encap_type`` to either ``"dot1q"`` (sub-IF children present)
    or ``"null"`` (no children) using
    :meth:`HuaweiInterface.derive_encap_type`. Interfaces that ARE
    themselves sub-interfaces (name containing ``"."``) are NOT updated —
    the concept "this sub-IF is tagged" is redundant (sub-IFs carry their
    own VLAN encoding in the name and don't have child sub-IFs).
    """
    if sub_if_index is None:
        sub_if_index = {}
    for iface in interfaces:
        if iface is None:
            continue
        port_name = getattr(iface, "name", None)
        if not port_name:
            continue
        # Sub-interfaces themselves don't have a port-level encap-type
        # (they ARE the encapsulated logical interfaces). Leave their
        # encap_type as None — callers that want to display sub-IF VLAN
        # info should use the SAP / sub-interface dataclasses.
        if "." in port_name:
            continue
        iface.encap_type = HuaweiInterface.derive_encap_type(
            port_name, sub_if_index
        )

