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
neighbors into a list on NetworkInstance and carry the originating
``vprn_name`` / ``interface`` as plain fields on every Neighbor. The field
names still follow OpenConfig (``ip``, ``link_layer_address``, ``origin``).
The routing-instance name lives on ``vprn_name`` (canonical value ``"Base"``
for the global routing table, vendor-symmetric across Nokia/Huawei).

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
    outer VLAN tag separately, and ``port`` exposes the physical port name
    without the VLAN suffix — both derived client-side from ``subinterface``
    because neither vendor exposes them as distinct YANG leaves on the SAP /
    AC subtree (verified by live YANG probe — see Phase 0 of the SAP-fields
    refactor; vendor candidate leaves all return
    ``MGMT_CORE #2201 Unknown element``).
    """
    prefix: list = None
    field_mapping: dict = None
    serialization_exclude = RPCDataContainer.serialization_exclude

    subinterface: Optional[str] = None
    # Physical port name without the VLAN suffix — derived client-side from
    # ``subinterface`` via
    # :func:`pynetcom.utils.nokia_router_tools.split_sap_id` (Nokia) or
    # :func:`pynetcom.utils.huawei_router_tools.split_if_to_type_id_tag`
    # (Huawei). Vendor YANG models do not expose this as a separate leaf.
    port: Optional[str] = None
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

    Vendor-agnostic semantics
    -------------------------

    * ``virtual_circuit_identifier`` — VC-id (int). Universal.
    * ``sdp_id`` — Nokia SDP identifier (left of the ``"sdp_id:vc_id"`` Nokia
      composite). Always ``None`` for Huawei (Huawei has no SDP concept).
    * ``remote_system`` — IP/loopback of the remote PE. Huawei: free
      (``peer-ip`` on every PW). Nokia: enrich-only (lives on the SDP object,
      not on spoke-sdp/mesh-sdp); populated when
      ``enrich_remote_system=True`` is passed to
      :meth:`pynetcom.ServicesClient.get_l2vpn_services` /
      :meth:`pynetcom.ServicesClient.get_pseudowires`.
    * ``oper_status`` — OpenConfig-canonical ``"up"`` / ``"down"`` only.
      Huawei nuance: the device may emit ``"backup"`` on PW-redundancy slaves
      (PW is operationally up but in standby) — the parser **normalises** that
      to ``oper_status="up"`` and lifts the redundancy semantics to
      :attr:`redundancy_state`. AI/operator code should never see ``"backup"``.
    * ``signaling_type`` — protocol used to signal the PW. One of
      ``ldp`` / ``rsvp`` / ``bgp`` / ``static``. Huawei: free (``signal-type``
      on every PW). Nokia: enrich-only via SDP join (``active-lsp-type`` on
      the SDP; populated alongside ``remote_system`` by
      ``enrich_remote_system=True``).
    * ``encapsulation_type`` — VC encapsulation. ``ether`` / ``vlan``. Huawei:
      free (service-level ``vpls/encapsulation-type``, ONE value for every
      PW in a service). Nokia: enrich-only via the configure-NS RPC
      (``spoke-sdp/vc-type``); populated when ``enrich_config=True`` is passed
      to :meth:`pynetcom.ServicesClient.get_l2vpn_services` /
      :meth:`pynetcom.ServicesClient.get_pseudowires`.
    * ``redundancy_role`` — which leg the PW occupies in the redundancy
      group. ``primary`` / ``secondary`` / ``None``. Huawei: free
      (``pw/role``). Nokia: enrich-only via the configure-NS RPC
      (``spoke-sdp/endpoint/precedence``); populated when
      ``enrich_config=True``.
    * ``redundancy_state`` — current operational role in a paired
      active/standby PW pair. ``active`` / ``standby`` / ``None``. Huawei:
      free, derived from the raw ``pw-info/pw-state``
      (``backup``→``standby``, ``up``→``active``, anything else → ``None``).
      Nokia: not surfaced in the current iteration — Nokia exposes
      redundancy state only via MIBs / counters not accessed by this client.

    Free vs enrich matrix
    ---------------------

    +-------------------+---------------+----------------------------+---------------------+
    | Field             | Huawei free   | Nokia free (state-NS only) | Nokia enrich        |
    +===================+===============+============================+=====================+
    | virtual_circuit_  |               |                            |                     |
    | identifier        | yes           | yes                        | yes                 |
    +-------------------+---------------+----------------------------+---------------------+
    | sdp_id            | n/a (None)    | yes                        | yes                 |
    +-------------------+---------------+----------------------------+---------------------+
    | oper_status       | yes           | yes                        | yes                 |
    +-------------------+---------------+----------------------------+---------------------+
    | remote_system     | yes           | None                       | enrich_remote_system|
    +-------------------+---------------+----------------------------+---------------------+
    | signaling_type    | yes           | None                       | enrich_remote_system|
    +-------------------+---------------+----------------------------+---------------------+
    | encapsulation_    |               |                            |                     |
    | type              | yes (service- | None                       | enrich_config       |
    |                   | level)        |                            |                     |
    +-------------------+---------------+----------------------------+---------------------+
    | redundancy_role   | yes           | None                       | enrich_config       |
    +-------------------+---------------+----------------------------+---------------------+
    | redundancy_state  | yes (derived  | None                       | None (not surfaced) |
    |                   | from raw      |                            |                     |
    |                   | pw-state)     |                            |                     |
    +-------------------+---------------+----------------------------+---------------------+
    """
    prefix: list = None
    field_mapping: dict = None
    serialization_exclude = RPCDataContainer.serialization_exclude

    virtual_circuit_identifier: Optional[int] = None   # pw-id / vc-id
    remote_system: Optional[str] = None                # IP / loopback of the remote PE
    sdp_id: Optional[int] = None                       # Nokia SDP identifier (None for Huawei)
    oper_status: Optional[str] = None                  # OpenConfig: "up" | "down"
    # PW signaling protocol — ldp | rsvp | bgp | static. Free on Huawei
    # (``signal-type`` on each PW); enrich-only on Nokia (read from the SDP
    # join, ``active-lsp-type``, alongside ``remote_system``).
    signaling_type: Optional[str] = None
    # VC encapsulation — ether | vlan. Free on Huawei (service-level
    # ``vpls/encapsulation-type`` — single value applies to every PW in the
    # service); enrich-only on Nokia (configure-NS ``spoke-sdp/vc-type``).
    encapsulation_type: Optional[str] = None
    # Per-PW redundancy role within a redundancy group — primary | secondary.
    # Free on Huawei (``pw/role``); enrich-only on Nokia (configure-NS
    # ``spoke-sdp/endpoint/precedence``).
    redundancy_role: Optional[str] = None
    # Current operational role in a paired active/standby PW pair —
    # active | standby. Free on Huawei (derived from raw ``pw-info/pw-state``:
    # ``backup``→``standby``, ``up``→``active``). Nokia: ``None`` —
    # Nokia exposes redundancy state only via MIBs / counters not accessed
    # here.
    redundancy_state: Optional[str] = None

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
    # Physical port name without the VLAN suffix. Derived client-side from
    # ``interface`` because neither vendor exposes ``port`` as a dedicated
    # YANG leaf on the FDB record (Phase 0 probe of the FDB subtree):
    #   * Nokia SAP-learned (source_type=SAP) — split via
    #     :func:`pynetcom.utils.nokia_router_tools.split_sap_id`, e.g.
    #     ``'1/1/10:1319'`` → ``'1/1/10'`` (port-based ``'1/1/12'`` →
    #     ``'1/1/12'`` with ``vlan=None``).
    #   * Huawei AC-learned (source_type=SAP) — split via
    #     :func:`pynetcom.utils.huawei_router_tools.split_if_to_type_id_tag`,
    #     e.g. ``'GigabitEthernet0/2/31.2414'`` → ``'GigabitEthernet0/2/31'``.
    #   * PW-learned (source_type=PW) — stays ``None`` (no physical port).
    port: Optional[str] = None
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
    explicit ``vprn_name`` and ``interface`` fields so that filtering by VRF
    or by MAC is a simple list comprehension, not an interface walk.

    Field semantics
    ---------------
    ``vprn_name`` — routing-instance name (string). Canonical value
    ``"Base"`` for the global routing table on both vendors (Nokia: native;
    Huawei: ``_public_`` is normalised to ``"Base"`` by the adapter). Any
    other value is a configured L3VPN / VPRN service name.

    ``interface`` — name of the L3 interface owning the ARP entry, exactly
    as the device reports it. This is the **only** vendor-symmetric
    identifier of where the ARP entry lives, and it intentionally carries
    the full L3-IF name (which already encodes the VLAN tag on Huawei
    sub-IFs):

      - Huawei: full sub-IF name like ``Virtual-Ethernet0/2/3.66`` — the
        ``.66`` suffix is the VLAN. Bare physical names like
        ``GigabitEthernet0/0/1`` are also possible for port-based L3
        interfaces.
      - Nokia: bare L3-IF name as configured, possibly an R-VPLS interface
        like ``VPLS_LTE_eNodeB_Oc.JArk2.AC_01``.

    No separate ``port`` / ``vlan`` projection is exposed: OpenConfig models
    neighbors under ``/interfaces/interface/subinterfaces/subinterface/
    ipv4/neighbors/neighbor``, where physical port and VLAN are derived
    from the parent interface hierarchy, not stored on the neighbor itself.
    Surfacing them here would invent a non-OpenConfig contract — callers
    who need the physical port should resolve it from ``interface`` via
    the L3-interface / SAP layer.

    ``oper_state`` — vendor-symmetric health marker of the ARP entry.

      - Nokia: native ``<oper-state>`` leaf under ``<neighbor>``
        (typically ``"up"`` for a healthy resolved entry).
      - Huawei: derived from ``<expire-time>`` — ``"up"`` when the TTL is
        positive (entry is alive in the ARP cache), ``"down"`` when it
        has expired. Strictly speaking this is liveness, not oper-state,
        but we surface it under the same field for cross-vendor symmetry.

    ``age`` — TTL / age-since-learned, vendor-specific semantics. See the
    vendor adapter docstrings.
    """
    prefix: list = None
    field_mapping: dict = None
    serialization_exclude = RPCDataContainer.serialization_exclude

    ip: Optional[str] = None
    link_layer_address: Optional[str] = None
    interface: Optional[str] = None
    origin: Optional[NeighborOrigin] = None
    vprn_name: Optional[str] = None
    age: Optional[int] = None
    oper_state: Optional[str] = None

    def __init__(self, data: Optional[dict] = None):
        if data is not None and self.field_mapping:
            self.populate_from_data(data)


# ---- L3Interface --------------------------------------------------------- #
@dataclass
class L3Interface(RPCDataContainer):
    """An L3 (IP-bearing) interface, flattened with an explicit ``vprn_name``
    field.

    OpenConfig models this as ``/interfaces/interface`` plus the
    ``subinterfaces/.../ipv4/addresses/address`` subtree, cross-referenced
    from ``/network-instances/network-instance/interfaces``. As with
    :class:`Neighbor`, we project it flat: one object per IP interface with
    ``vprn_name`` carried directly, so "list the L3 interfaces of VRF X" is
    a plain query rather than a multi-subtree walk.

    Vendor notes:
      - ``vprn_name`` is the routing-instance name. Canonical value for the
        global instance is ``"Base"`` on both vendors (Nokia: native;
        Huawei: ``_public_`` is normalised to ``"Base"`` by the adapter).
      - ``ipv4_prefix_length`` is populated on Huawei (derived from the
        netmask the device returns) but stays ``None`` on Nokia — the SR OS
        state model exposes the operational address without a mask.
      - ``l2_service`` is populated only when ``enrich_l2_service=True`` is
        passed to ``get_l3_interfaces``. It names the L2 service (VPLS / VSI)
        that this L3 interface routes into. Stays ``None`` for "pure L3"
        interfaces that don't terminate any L2 service. See
        :meth:`ServicesClient.get_l3_interfaces` and
        :meth:`ServicesClient.find_l2_service_by_ip`.

    Binding (vendor-agnostic discriminator)
    ----------------------------------------
    ``binding_type`` + ``parent_port`` + ``vlan`` + ``sdp_bind_id`` describe
    *what* the L3 interface is bound to. The discriminator string is
    consistent across vendors so AI/operator code can answer questions like
    "give me every L3-IF that lives on a physical port" without parsing
    vendor name conventions.

    ``binding_type`` values:

        physical_port  — bare port-based L3 (Huawei ``GigabitEthernet0/2/14``)
        subinterface   — physical/LAG port + dot1q tag
                         (Huawei ``GigabitEthernet0/2/14.3060``, ``Eth-Trunk0.2300``)
        ve_group       — Huawei Virtual-Ethernet / Global-VE (IRB binding)
        l2vpn_routed   — Nokia R-VPLS L3 interface (name = VPLS name)
        sdp_spoke      — Nokia L3 over SDP (spoke-sdp binding)
        sap_physical   — Nokia L3 on a SAP (sap-id ``port:vlan``)
        loopback       — software loopback (both vendors)
        system         — Nokia System interface
        unknown        — name pattern not recognised

    Free vs enrich (filling matrix)
    --------------------------------
    +-----------------------+--------------------+-------------------------+
    | Field                 | Huawei (state-NS)  | Nokia                   |
    +=======================+====================+=========================+
    | name, vprn_name,      | free               | free (state-NS)         |
    | ipv4_*, oper_status,  |                    |                         |
    | admin_status, mtu     |                    |                         |
    +-----------------------+--------------------+-------------------------+
    | binding_type          | free               | name-pattern free:      |
    | (loopback/system/     |                    |   loopback/system/      |
    |  l2vpn_routed/        |                    |   l2vpn_routed/unknown  |
    |  physical_port/       |                    |                         |
    |  subinterface/        |                    |                         |
    |  ve_group)            |                    |                         |
    +-----------------------+--------------------+-------------------------+
    | binding_type          | n/a                | enrich-only (extra      |
    | (sdp_spoke /          |                    | configure-NS RPC):      |
    |  sap_physical),       |                    | ``enrich_config=True``  |
    | parent_port + vlan    |                    | switches them on        |
    | (Nokia SAP),          |                    |                         |
    | sdp_bind_id           |                    |                         |
    +-----------------------+--------------------+-------------------------+
    | parent_port + vlan    | free (via          | n/a (Nokia name does    |
    | (Huawei sub-IF)       | split_if_to_type_  |  not encode VLAN)       |
    |                       |  id_tag)           |                         |
    +-----------------------+--------------------+-------------------------+

    Without ``enrich_config=True`` Nokia ``sdp_spoke`` / ``sap_physical``
    L3 interfaces fall back to ``binding_type='unknown'`` (the name carries
    no signal — operators choose arbitrary names like ``test_sap``).
    """
    prefix: list = None
    field_mapping: dict = None
    serialization_exclude = RPCDataContainer.serialization_exclude

    name: Optional[str] = None
    vprn_name: Optional[str] = None
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
    # Vendor-agnostic discriminator of *what* the L3 interface is bound to.
    # See class docstring for the value set and the free/enrich matrix.
    binding_type: Optional[str] = None
    # Physical port name without the VLAN suffix — populated for bindings
    # where the parent port is meaningful (Huawei physical_port /
    # subinterface; Nokia sap_physical when ``enrich_config=True``).
    # Stays None for software-only bindings (ve_group / l2vpn_routed /
    # sdp_spoke / loopback / system).
    parent_port: Optional[str] = None
    # Outer VLAN tag for tagged sub-interfaces (Huawei sub-IF / ve_group;
    # Nokia sap_physical when ``enrich_config=True``). None for untagged
    # / software bindings.
    vlan: Optional[int] = None
    # Nokia SDP binding identifier ``"<sdp_id>:<vc_id>"`` (e.g. ``"41:666"``).
    # Populated only for ``binding_type='sdp_spoke'`` when
    # ``enrich_config=True``; stays None for every other binding.
    sdp_bind_id: Optional[str] = None

    def __init__(self, data: Optional[dict] = None):
        if data is not None and self.field_mapping:
            self.populate_from_data(data)


# ---- BGP RIB (VPN routes) ----------------------------------------------- #
@dataclass
class BgpRoute(RPCDataContainer):
    """Minimal OpenConfig-aligned BGP RIB route entry.

    Corresponds to ``openconfig-rib-bgp:loc-rib/routes/route`` augmented with
    the L3VPN extension (``openconfig-bgp-l3vpn-ext``). Intentionally narrow —
    only the four leaves an operator needs for a "what PE serves this prefix?"
    lookup. Extension to a full RIB shape is a follow-up task.

    Field semantics
    ---------------
    * :attr:`prefix` — CIDR notation, OpenConfig ``inet:ip-prefix`` shape
      (e.g. ``"11.152.200.0/24"``). On Huawei this is synthesised from the
      pair ``prefix`` + ``mask-length`` returned by
      ``huawei-bgp-routing-table``.
    * :attr:`next_hop` — OpenConfig ``attr-sets/next-hop``. For VPN routes
      this is the remote PE's system-IP (IBGP next-hop-self by convention),
      not the IGP next-hop.
    * :attr:`is_best` — OpenConfig ``state/best-path``. ``True`` for the
      preferred active route, ``False`` for valid alternatives that lost
      the bestpath election, ``None`` if the device did not report the
      attribute. Derived on Huawei from the ``flag-string`` leaf
      (``"*>"`` ⇒ best, anything else ⇒ alternative).
    * :attr:`route_distinguisher` — ``openconfig-bgp-l3vpn-ext`` field.
      RD in ``"asn:nn"`` / ``"ip:nn"`` form; identifies the originating VPN
      on the remote PE.

    Note: this dataclass intentionally does NOT define the base-class
    ``field_mapping`` / XML-prefix machinery — the Huawei parser populates
    fields directly (the vendor leaves don't line up 1:1 with the OpenConfig
    names — ``prefix`` is synthesised from ``prefix`` + ``mask-length``,
    ``is_best`` is derived from ``flag-string``). Falling back to base-class
    ``populate_from_data`` would be misleading; instances are constructed
    field-by-field. The base ``serialization_exclude`` set is overridden to
    drop the ``'prefix'`` entry — here ``prefix`` is the OpenConfig route
    CIDR, NOT the XML-namespace prefix list, and must show up in
    :meth:`to_dict` / :meth:`get_json` output.
    """
    # Override base-class exclusion: ``prefix`` is a real data field on
    # BgpRoute (the CIDR prefix), not the XML-namespace list used by
    # populate_from_data on other containers.
    serialization_exclude = {'field_mapping'}

    prefix: Optional[str] = None
    next_hop: Optional[str] = None
    is_best: Optional[bool] = None
    route_distinguisher: Optional[str] = None

    def __init__(
        self,
        prefix: Optional[str] = None,
        next_hop: Optional[str] = None,
        is_best: Optional[bool] = None,
        route_distinguisher: Optional[str] = None,
    ):
        self.prefix = prefix
        self.next_hop = next_hop
        self.is_best = is_best
        self.route_distinguisher = route_distinguisher


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

    # Device-reported endpoint counters (vendor-agnostic, optional). Populated
    # only when the vendor exposes them as cheap leaves on the service
    # container itself — used to answer "how many SAPs/PWs" without walking
    # the per-endpoint lists. Currently filled by Nokia VPLS/EPIPE adapters
    # (from native ``<sap-count>`` / ``<sdp-bind-count>`` state leaves) in
    # brief enumeration mode where ``connection_points`` is intentionally
    # empty to keep the RPC cheap. Stays ``None`` on Huawei (which always
    # returns full SAP/PW lists, so ``len(saps())`` is authoritative).
    #
    # Authoritative source order:
    #   1. ``len(self.saps())`` / ``len(self.pseudowires())`` when
    #      ``connection_points`` is populated (full payload was fetched).
    #   2. ``sap_count_hint`` / ``pw_count_hint`` when the list is empty
    #      (brief / list mode) — fall back to the device hint.
    sap_count_hint: Optional[int] = None
    pw_count_hint: Optional[int] = None

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
