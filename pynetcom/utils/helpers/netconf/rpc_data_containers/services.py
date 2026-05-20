"""
Vendor-agnostic data containers for L2VPN services, FDB and neighbor (ARP) tables.

The class hierarchy in this module mirrors the OpenConfig YANG model
``openconfig-network-instance`` (and the ``openconfig-if-ip`` neighbor list)
so that callers can rely on a stable, standards-aligned shape regardless of
which vendor's device produced the data underneath.

Mapping summary (OpenConfig path → Python class):

    /network-instances/network-instance                       → NetworkInstance
    /.../connection-points/connection-point                   → ConnectionPoint
    /.../connection-points/connection-point/endpoints/endpoint → Endpoint
        ... /local                                            → LocalEndpoint  (= SAP / AC)
        ... /remote                                           → RemoteEndpoint (= PW / SDP-binding)
    /.../fdb                                                  → Fdb
    /.../fdb/mac-table                                        → MacTable
    /.../fdb/mac-table/entries/entry                          → MacEntry
    openconfig-if-ip ipv4/neighbors/neighbor (projected)      → Neighbor

The ``Neighbor`` projection deserves a comment: in pure OpenConfig, ARP/ND
entries live under each subinterface and you would walk every interface bound
to a network-instance to gather them. For practical operator queries (e.g.
"give me every ARP entry on VRF X") that nesting is awkward, so we flatten
neighbors into a list on NetworkInstance and carry the originating ``vrf`` /
``interface`` as plain fields on every Neighbor. The field names still follow
OpenConfig (``ip``, ``link_layer_address``, ``origin``).

These classes are intentionally usable in three ways:

    1. As parsers — pass a dict produced by xmltodict to ``__init__`` (after
       a vendor adapter has mapped vendor-native fields to OpenConfig names),
       and ``populate_from_data`` will pull values out of ``field_mapping``.
    2. As manually-built data containers — instantiate with ``data=None`` and
       set fields directly (used by vendor adapters that need to do their
       own per-vendor extraction before producing OpenConfig objects).
    3. As serialisers — call ``to_dict()`` / ``get_json()`` to obtain the
       canonical OpenConfig-shaped JSON.

Vendor-specific subclasses (NokiaVplsService, HuaweiVsi, etc.) live in
``nokia_services.py`` and ``huawei_services.py`` and override ``prefix`` and
``field_mapping`` while inheriting all serialisation behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from pynetcom.utils.helpers.netconf.rpc_data_containers.openconfig import RPCDataContainer


# ---- Enums --------------------------------------------------------------- #
class NetworkInstanceType(Enum):
    """OpenConfig identityref ``network-instance-types:*``."""
    DEFAULT_INSTANCE = "DEFAULT_INSTANCE"
    L2VPN = "L2VPN"        # VPLS, VSI — multipoint L2
    L2P2P = "L2P2P"        # VPWS, EPIPE, VLL — point-to-point L2
    L3VPN = "L3VPN"        # VPRN, VRF
    L2L3 = "L2L3"          # IRB / integrated routing & bridging


class EndpointType(Enum):
    """OpenConfig identityref ``endpoint-types:*``."""
    LOCAL = "LOCAL"        # = SAP / AC
    REMOTE = "REMOTE"      # = PW / SDP-binding


class MacEntryType(Enum):
    """OpenConfig identityref ``mac-entry-types:*``."""
    STATIC = "STATIC"
    DYNAMIC = "DYNAMIC"


class MacSourceType(Enum):
    """Origin of a MAC entry — where the device learned it.

    Not part of stock OpenConfig (which exposes only static/dynamic). We add
    this as a pragmatic field because operators routinely need to ask
    "show me MACs learned locally vs. learned over PWs". On Nokia this maps
    directly to the YANG ``locale`` leaf on each FDB entry (``sap`` /
    ``sdp-bind``). On Huawei it's derived from the entry's ``pw-role`` /
    ``out-interface-name`` shape — see HuaweiMacEntry.
    """
    SAP = "SAP"   # learned on a local Service Access Point  (LOCAL endpoint)
    PW = "PW"     # learned over a Pseudo-Wire                (REMOTE endpoint)


class NeighborOrigin(Enum):
    """OpenConfig identityref ``ip-neighbor-origin:*``."""
    STATIC = "STATIC"
    DYNAMIC = "DYNAMIC"
    OTHER = "OTHER"


# ---- LocalEndpoint / RemoteEndpoint ------------------------------------- #
@dataclass
class LocalEndpoint(RPCDataContainer):
    """OpenConfig: /endpoints/endpoint/local/{config,state}.

    Represents the local side of a connection point in an L2VPN service, i.e.
    the binding of the service to a physical/logical interface on the local
    device — the SAP (Nokia) / AC (Huawei). The ``subinterface`` field names
    the underlying port and encapsulation, formatted vendor-specifically
    (e.g. Nokia "1/1/1:100", Huawei "GE0/2/0.100"). ``vlan`` exposes the
    outer VLAN tag separately when the device reports it as a distinct field.
    """
    prefix: list = None
    field_mapping: dict = None
    serialization_exclude = RPCDataContainer.serialization_exclude

    subinterface: Optional[str] = None
    vlan: Optional[int] = None
    oper_status: Optional[str] = None
    admin_status: Optional[str] = None
    encapsulation: Optional[str] = None   # dot1q | qinq | null | ...

    def __init__(self, data: Optional[dict] = None):
        if data is not None and self.field_mapping:
            self.populate_from_data(data)


@dataclass
class RemoteEndpoint(RPCDataContainer):
    """OpenConfig: /endpoints/endpoint/remote/{config,state}.

    Represents the remote side of a connection point in an L2VPN service —
    the pseudo-wire (PW) terminating on a remote PE. In Nokia terms this is
    a spoke-sdp or mesh-sdp binding (identified by sdp-id : vc-id); in
    Huawei terms it is a PW under the VSI (identified by remote peer + pw-id).

    Fields follow the OpenConfig naming convention so that operators can write
    code that does not care which vendor produced the entry.
    """
    prefix: list = None
    field_mapping: dict = None
    serialization_exclude = RPCDataContainer.serialization_exclude

    virtual_circuit_identifier: Optional[int] = None   # pw-id / vc-id
    remote_system: Optional[str] = None                # IP / loopback of the remote PE
    sdp_id: Optional[int] = None                       # Nokia SDP identifier (None for Huawei)
    pw_type: Optional[str] = None                      # ethernet | vlan | ...
    oper_status: Optional[str] = None
    # H-VPLS PW-redundancy role. Set from the vendor's native leaf:
    #   * Huawei — ``role`` ("primary" / "secondary") on each <pw> entry,
    #     plus ``pw-role`` ("master" / "slave") on FDB records.
    #   * Nokia — there is no per-spoke-sdp role surfaced at this layer
    #     (failover is handled by SDP-side mechanisms); stays ``None``.
    # Normalised to lower-case strings: ``"primary"`` / ``"secondary"`` /
    # ``"master"`` / ``"slave"`` / ``None``.
    role: Optional[str] = None

    def __init__(self, data: Optional[dict] = None):
        if data is not None and self.field_mapping:
            self.populate_from_data(data)


# ---- Endpoint ------------------------------------------------------------ #
@dataclass
class Endpoint(RPCDataContainer):
    """OpenConfig: /connection-points/connection-point/endpoints/endpoint.

    A single endpoint of a connection point. Exactly one of ``local`` / ``remote``
    is populated, governed by the ``type`` field. The base ``serialization_exclude``
    is reused — ``to_dict`` will recursively flatten ``local`` / ``remote`` via
    ``RPCDataContainer._to_plain_value``.
    """
    prefix: list = None
    field_mapping: dict = None
    serialization_exclude = RPCDataContainer.serialization_exclude

    endpoint_id: Optional[str] = None
    type: Optional[EndpointType] = None
    local: Optional[LocalEndpoint] = None
    remote: Optional[RemoteEndpoint] = None

    def __init__(self, data: Optional[dict] = None):
        if data is not None and self.field_mapping:
            self.populate_from_data(data)


# ---- ConnectionPoint ----------------------------------------------------- #
@dataclass
class ConnectionPoint(RPCDataContainer):
    """OpenConfig: /connection-points/connection-point.

    Groups one or more Endpoints. In a classic VPLS, a ConnectionPoint maps
    to a single AC / SAP / PW; in a redundancy scheme it may carry multiple
    endpoints sharing the same connection-point-id.
    """
    prefix: list = None
    field_mapping: dict = None
    serialization_exclude = RPCDataContainer.serialization_exclude

    connection_point_id: Optional[str] = None
    endpoints: List[Endpoint] = None

    def __init__(self, data: Optional[dict] = None):
        self.endpoints = []
        if data is not None and self.field_mapping:
            self.populate_from_data(data)


# ---- MAC table (FDB) ----------------------------------------------------- #
@dataclass
class MacEntry(RPCDataContainer):
    """OpenConfig: /fdb/mac-table/entries/entry.

    A single MAC forwarding entry. ``interface`` is a reference to the
    connection-point that learned the MAC (in vendor-agnostic notation —
    typically the port / SAP / PW identifier the operator would recognise).

    For PW-learned entries (``source_type == PW``) we additionally surface
    two vendor-extension fields that let callers identify the remote PE
    without a follow-up RPC:

      * ``remote_system`` — IP/loopback of the remote PE that originated
        the MAC (Huawei: native ``peer-ip`` leaf on every FDB record;
        Nokia: not surfaced in v1, see :class:`Endpoint` / sdp-bind join).
      * ``pw_id`` — pseudo-wire identifier in vendor notation (Huawei:
        ``pw-id`` leaf; Nokia: the vc-id half of ``sdp-bind``, i.e. the
        right side of ``"<sdp_id>:<vc_id>"``).
    """
    prefix: list = None
    field_mapping: dict = None
    serialization_exclude = RPCDataContainer.serialization_exclude

    mac_address: Optional[str] = None
    vlan: Optional[int] = None
    interface: Optional[str] = None
    entry_type: Optional[MacEntryType] = None
    source_type: Optional[MacSourceType] = None    # SAP | PW (where learned)
    # Seconds since the entry's age timer started (or seconds-to-expiry on
    # vendors that surface a TTL — see vendor adapter docstrings). Strictly
    # Optional[int] — vendors that publish only a timestamp put it in
    # :attr:`last_update` instead so this field stays type-clean.
    age: Optional[int] = None
    # ISO-8601 timestamp of the last learn / refresh event, on vendors that
    # publish it (Nokia ``last-update`` / ``last-update-time``). Free-form
    # string, vendor-native — no parsing into datetime to keep the contract
    # transport-agnostic. ``None`` when the vendor does not surface it
    # (Huawei does not on the standard MAC subtree).
    last_update: Optional[str] = None
    # Convenience back-link to the parent service (set by ServicesClient).
    network_instance: Optional[str] = None
    # PW-learned enrichment (populated only when source_type == PW):
    remote_system: Optional[str] = None    # peer-IP of the originating PE
    pw_id: Optional[str] = None            # vendor PW identifier (string)

    def __init__(self, data: Optional[dict] = None):
        if data is not None and self.field_mapping:
            self.populate_from_data(data)


@dataclass
class MacTable(RPCDataContainer):
    """OpenConfig: /fdb/mac-table — wrapper around the entries list."""
    prefix: list = None
    field_mapping: dict = None
    serialization_exclude = RPCDataContainer.serialization_exclude

    entries: List[MacEntry] = None

    def __init__(self, data: Optional[dict] = None):
        self.entries = []
        if data is not None and self.field_mapping:
            self.populate_from_data(data)


@dataclass
class Fdb(RPCDataContainer):
    """OpenConfig: /fdb — container holding the MAC table."""
    prefix: list = None
    field_mapping: dict = None
    serialization_exclude = RPCDataContainer.serialization_exclude

    mac_table: Optional[MacTable] = None

    def __init__(self, data: Optional[dict] = None):
        self.mac_table = MacTable()


# ---- Neighbor (ARP / ND) ------------------------------------------------- #
@dataclass
class Neighbor(RPCDataContainer):
    """Projection of OpenConfig ipv4/neighbors/neighbor onto a flat list.

    See module docstring for the rationale: ARP entries are exposed flat with
    explicit ``vrf`` and ``interface`` fields so that filtering by VRF or by
    MAC is a simple list comprehension, not an interface walk.
    """
    prefix: list = None
    field_mapping: dict = None
    serialization_exclude = RPCDataContainer.serialization_exclude

    ip: Optional[str] = None
    link_layer_address: Optional[str] = None
    interface: Optional[str] = None
    origin: Optional[NeighborOrigin] = None
    vrf: Optional[str] = None
    age: Optional[int] = None

    def __init__(self, data: Optional[dict] = None):
        if data is not None and self.field_mapping:
            self.populate_from_data(data)


# ---- L3Interface --------------------------------------------------------- #
@dataclass
class L3Interface(RPCDataContainer):
    """An L3 (IP-bearing) interface, flattened with an explicit ``vrf`` field.

    OpenConfig models this as ``/interfaces/interface`` plus the
    ``subinterfaces/.../ipv4/addresses/address`` subtree, cross-referenced
    from ``/network-instances/network-instance/interfaces``. As with
    :class:`Neighbor`, we project it flat: one object per IP interface with
    ``vrf`` carried directly, so "list the L3 interfaces of VRF X" is a plain
    query rather than a multi-subtree walk.

    Vendor notes:
      - ``vrf`` is the routing-instance name. For the global instance it is
        ``"Base"`` on Nokia and ``"_public_"`` on Huawei.
      - ``ipv4_prefix_length`` is populated on Huawei (derived from the
        netmask the device returns) but stays ``None`` on Nokia — the SR OS
        state model exposes the operational address without a mask.
      - ``l2_service`` is populated only when ``enrich_l2_service=True`` is
        passed to ``get_l3_interfaces``. It names the L2 service (VPLS / VSI)
        that this L3 interface routes into. Stays ``None`` for "pure L3"
        interfaces that don't terminate any L2 service. See
        :meth:`ServicesClient.get_l3_interfaces` and
        :meth:`ServicesClient.find_l2_service_by_ip`.
    """
    prefix: list = None
    field_mapping: dict = None
    serialization_exclude = RPCDataContainer.serialization_exclude

    name: Optional[str] = None
    vrf: Optional[str] = None
    ipv4_address: Optional[str] = None
    ipv4_prefix_length: Optional[int] = None
    oper_status: Optional[str] = None
    admin_status: Optional[str] = None
    mtu: Optional[int] = None
    # Populated by L2-L3 binding enrichment (opt-in). On Huawei: resolved
    # via the huawei-fim-ifm ve-group → VSI SAP join. On Nokia: read from
    # /configure/service/vprn[...]/interface[...]/vpls/vpls-name. Stays
    # None for "pure L3" interfaces with no L2 binding.
    l2_service: Optional[str] = None

    def __init__(self, data: Optional[dict] = None):
        if data is not None and self.field_mapping:
            self.populate_from_data(data)


# ---- NetworkInstance ----------------------------------------------------- #
@dataclass
class NetworkInstance(RPCDataContainer):
    """OpenConfig: /network-instances/network-instance.

    The top-level container for an L2VPN service (VPLS / VSI), an L3VPN
    instance (VPRN / VRF), or the default routing instance. Vendor adapters
    construct one of these per discovered service/VRF and either fill the
    nested ``connection_points`` / ``fdb`` / ``neighbors`` themselves or
    leave them ``None`` for lazy retrieval by the high-level client.
    """
    prefix: list = None
    field_mapping: dict = None
    serialization_exclude = RPCDataContainer.serialization_exclude

    name: Optional[str] = None
    type: Optional[NetworkInstanceType] = None
    enabled: Optional[bool] = None
    oper_status: Optional[str] = None
    route_distinguisher: Optional[str] = None
    route_targets: Optional[List[str]] = None
    description: Optional[str] = None

    connection_points: Optional[List[ConnectionPoint]] = None
    fdb: Optional[Fdb] = None
    neighbors: Optional[List[Neighbor]] = None

    def __init__(self, data: Optional[dict] = None):
        self.route_targets = []
        self.connection_points = []
        self.neighbors = []
        if data is not None and self.field_mapping:
            self.populate_from_data(data)

    # Convenience accessors used by the high-level client and examples ----- #
    def saps(self) -> List[Endpoint]:
        """Return only LOCAL endpoints (SAPs / ACs) across all connection points."""
        result: List[Endpoint] = []
        for cp in self.connection_points or []:
            for ep in cp.endpoints or []:
                if ep.type == EndpointType.LOCAL:
                    result.append(ep)
        return result

    def pseudowires(self) -> List[Endpoint]:
        """Return only REMOTE endpoints (PWs / SDP-bindings) across all connection points."""
        result: List[Endpoint] = []
        for cp in self.connection_points or []:
            for ep in cp.endpoints or []:
                if ep.type == EndpointType.REMOTE:
                    result.append(ep)
        return result

    def mac_entries(self) -> List[MacEntry]:
        """Return the flat list of MAC entries (empty if FDB not populated)."""
        if self.fdb is None or self.fdb.mac_table is None:
            return []
        return self.fdb.mac_table.entries or []
