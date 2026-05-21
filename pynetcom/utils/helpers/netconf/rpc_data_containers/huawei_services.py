"""
Huawei VRP adapters that map the ``urn:huawei:yang:huawei-l2vpn`` /
``huawei-mac`` / ``huawei-arp`` operational state trees onto the
vendor-agnostic OpenConfig-aligned containers defined in
:mod:`pynetcom.utils.helpers.netconf.rpc_data_containers.services`.

Vendor mapping notes (verified against VRP V8 NE40E / NE8000 / ATN-910C /
OC-NE-X8X16 in May 2026)
------------------------------------------------------------------------

Some Huawei documentation talks about a ``huawei-vsi`` module — the NE-series
boxes we tested do NOT advertise it. They expose L2VPN under a single
``huawei-l2vpn`` module that mixes VPLS (multipoint) and VPWS (point-to-point)
under a common ``instance`` list, discriminated by an explicit ``type`` leaf:

    /l2vpn/instances/instance[name]
        name          (list key — the VPLS/VPWS service name)
        type          "vpls" | "vpws-ldp" | "vpws-static" | "vpws-bgp" | ...
        description
        state         "up" | "down"
        last-up-time
        vpls/                             (present when type=vpls)
            acs/ac[]                      (Attachment Circuits — LOCAL endpoints)
                interface-name            e.g. "GE0/3/4.100"
                access-port
                vpls-ac-statistics/
            ldp-signaling/                (for ldp-signaled VPLS)
                vsi-id
                pws/pw[]                  (Pseudo-Wires — REMOTE endpoints)
                    peer-ip
                    negotiation-vc-id
                    encapsulation-type
                    role                  "primary" | "secondary"
                    signal-type
                    pw-info/{session-state, pw-state, ...}
        vpws-ldp/                         (present when type=vpws-ldp)
            ...                           (analogous AC + PW layout)

MAC table — ``urn:huawei:yang:huawei-mac``::

    /mac/vsi-dynamic-macs/vsi-dynamic-mac[]
        slot-id, vsi-name, vlan-id,
        address               (Huawei "aabb-ccdd-eeff" notation)
        pw-role
        out-interface-name    (port or PW interface)

Static and blackhole MACs live in sibling lists ``vsi-static-macs`` /
``vsi-blackhole-macs`` (same schema; we ingest all three when present).

ARP table — ``urn:huawei:yang:huawei-arp``::

    /arp/query-entries/query-entry[]
        ni-name               (VPN/VRF name, "__LOCAL_OAM_VPN__" for OAM)
        ip-addr
        mac-addr
        style-type            "interface-arp" | "vlanif-arp" | "static-arp" | ...
        if-name
        slot-id
        work-if-name

The ``huawei-arp-deviations-<platform>`` modules ship per-platform; the schema
above is the common subset across NE40E / NE8000 / ATN-910C / OC-NE-X.
"""

from __future__ import annotations

import re
from typing import List, Optional

from pynetcom.utils.helpers.netconf.rpc_data_containers.services import (
    ConnectionPoint,
    Endpoint,
    EndpointType,
    L3Interface,
    LocalEndpoint,
    MacEntry,
    MacEntryType,
    MacSourceType,
    Neighbor,
    NeighborOrigin,
    NetworkInstance,
    NetworkInstanceType,
    RemoteEndpoint,
)


# ---- Helpers ------------------------------------------------------------- #
def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _to_bool(value) -> Optional[bool]:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("enable", "enabled", "up", "true", "1"):
        return True
    if s in ("disable", "disabled", "down", "false", "0"):
        return False
    return None


def _normalise_mac(value) -> Optional[str]:
    """Return canonical colon-form ``aa:bb:cc:dd:ee:ff`` for any valid input.

    Accepts every common separator style operators paste/devices return:

      * Huawei ``aabb-ccdd-eeff`` (u16 groups)
      * IEEE colon ``aa:bb:cc:dd:ee:ff``
      * Cisco dot ``aabb.ccdd.eeff``
      * Bare 12 hex digits ``aabbccddeeff``

    Returns ``None`` for anything else (NULL, empty, malformed, wrong length)
    so callers can rely on the field being either canonical or absent —
    never a half-normalised mix. Symmetric with
    :func:`pynetcom.utils.helpers.netconf.rpc_requests.normalize_mac`
    used by the request builders.
    """
    if value is None:
        return None
    hex_only = re.sub(r"[:\-\.\s]", "", str(value).strip()).lower()
    if not re.fullmatch(r"[0-9a-f]{12}", hex_only):
        return None
    return ":".join(hex_only[i:i + 2] for i in range(0, 12, 2))


def _to_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalise_vprn_name(ni: Optional[str]) -> Optional[str]:
    """Canonicalise a Huawei network-instance name to operator-facing form.

    Huawei encodes the global routing table as the pseudo-VPN ``"_public_"``
    and various management constructs as ``"__LOCAL_OAM_VPN__"`` /
    ``"__dcn_vpn__"``. Real operator VRFs are plain names like ``"MGNT_VPN"``.

    Mapping rules:
      * ``"_public_"``                       → ``"Base"``   (vendor-symmetric
        with Nokia, which natively names its global routing instance Base).
      * any name starting with ``"__"`` (synthetic management VPN) → ``None``.
      * any other name starting with ``"_"`` (other synthetic / reserved)
                                             → ``None``.
      * normal operator VRF name             → unchanged.
      * ``None`` / empty                     → ``None``.
    """
    if not ni:
        return None
    if ni == "_public_":
        return "Base"
    if ni.startswith("_"):
        # All other underscore-prefixed names are synthetic / management
        # markers (``__LOCAL_OAM_VPN__``, ``__dcn_vpn__``, ...). Treat them
        # as "no VRF" so they don't pollute the operator's view.
        return None
    return ni


# ---- Service instance → NetworkInstance --------------------------------- #
class HuaweiL2vpnInstance(NetworkInstance):
    """Adapter for one ``<instance>`` list entry under ``/l2vpn/instances``.

    Handles both VPLS (multipoint) and VPWS (point-to-point) — the
    ``type`` leaf decides which subtree is parsed:

      * ``type=vpls`` → reads ACs from ``vpls/acs/ac`` and PWs from
        ``vpls/ldp-signaling/pws/pw`` (or ``vpls/bgp-signaling/pws/pw`` for
        Kompella VPLS — same layout, different parent).
      * ``type=vpws-ldp`` / ``vpws-static`` → analogous extraction from the
        type-specific subtree, surfaced as the same OpenConfig
        ``NetworkInstanceType.L2P2P`` shape so callers don't have to branch.
    """

    _TYPE_MAP = {
        "vpls": NetworkInstanceType.L2VPN,
        "vpws-ldp": NetworkInstanceType.L2P2P,
        "vpws-static": NetworkInstanceType.L2P2P,
        "vpws-bgp": NetworkInstanceType.L2P2P,
    }

    def __init__(self, entry: dict):
        super().__init__(data=None)
        if not isinstance(entry, dict):
            return

        self.name = entry.get("name")
        huawei_type = (entry.get("type") or "").strip().lower()
        self.type = self._TYPE_MAP.get(huawei_type, NetworkInstanceType.L2VPN)
        self.oper_status = entry.get("state")
        self.enabled = _to_bool(entry.get("state"))
        self.description = entry.get("description")

        # Pick the type-specific subtree. Modern releases keep VPLS data under
        # /instance/vpls and VPWS data under /instance/vpws-ldp etc.
        subtree = entry.get("vpls") or entry.get(huawei_type) or {}
        if not isinstance(subtree, dict):
            return

        # ACs → LOCAL endpoints.
        acs_root = (subtree.get("acs") or {}).get("ac") if isinstance(subtree.get("acs"), dict) else None
        for ac in _as_list(acs_root):
            self._add_local_endpoint(ac)

        # PWs are nested under a signaling-mode container (ldp-signaling,
        # bgp-signaling, static-signaling). We accept any of them.
        for sig_key in ("ldp-signaling", "bgp-signaling", "static-signaling"):
            sig_block = subtree.get(sig_key)
            if not isinstance(sig_block, dict):
                continue
            pws_root = (sig_block.get("pws") or {}).get("pw") if isinstance(sig_block.get("pws"), dict) else None
            for pw in _as_list(pws_root):
                self._add_remote_endpoint(pw, signaling=sig_key)

    def _add_local_endpoint(self, ac: dict) -> None:
        iface = ac.get("interface-name") or ac.get("if-name") or ac.get("access-port")
        local = LocalEndpoint()
        local.subinterface = iface
        local.oper_status = ac.get("state") or ac.get("oper-state")
        local.admin_status = ac.get("admin-state")
        # Huawei doesn't always carry encap/vlan on the AC — leave None if absent.
        local.encapsulation = ac.get("encapsulation") or ac.get("access-mode")
        local.vlan = _to_int(ac.get("ce-vlan-id") or ac.get("vlan-id"))

        ep = Endpoint()
        ep.endpoint_id = iface
        ep.type = EndpointType.LOCAL
        ep.local = local

        cp = ConnectionPoint()
        cp.connection_point_id = iface
        cp.endpoints = [ep]
        self.connection_points.append(cp)

    def _add_remote_endpoint(self, pw: dict, signaling: str) -> None:
        peer = pw.get("peer-ip") or pw.get("remote-ip")
        vc_id = _to_int(pw.get("negotiation-vc-id") or pw.get("pw-id") or pw.get("vc-id"))
        info = pw.get("pw-info") if isinstance(pw.get("pw-info"), dict) else {}

        remote = RemoteEndpoint()
        remote.remote_system = peer
        remote.virtual_circuit_identifier = vc_id
        remote.pw_type = info.get("pw-type") or pw.get("encapsulation-type")
        remote.oper_status = info.get("pw-state") or info.get("session-state") or pw.get("state")
        # H-VPLS / PW-redundancy role. Huawei publishes it under several
        # leaf names depending on signaling mode (``role`` is the canonical
        # one on ldp-signaled PWs; some platforms use ``pw-role`` on the
        # endpoint as well). Normalise to lower-case string.
        role = (
            pw.get("role")
            or pw.get("pw-role")
            or info.get("role")
            or info.get("pw-role")
        )
        remote.role = role.strip().lower() if isinstance(role, str) and role.strip() else None

        ep = Endpoint()
        ep.endpoint_id = f"{peer}:{vc_id}" if peer and vc_id else (peer or (str(vc_id) if vc_id else None))
        ep.type = EndpointType.REMOTE
        ep.local = None
        ep.remote = remote

        cp = ConnectionPoint()
        cp.connection_point_id = ep.endpoint_id
        cp.endpoints = [ep]
        self.connection_points.append(cp)


# ---- MAC entries -------------------------------------------------------- #
class HuaweiMacEntry(MacEntry):
    """One entry from ``/mac/vsi-dynamic-macs/vsi-dynamic-mac`` (or the
    sibling ``vsi-static-macs`` / ``vsi-blackhole-macs`` lists).

    The originating list governs ``entry_type``: dynamic lists yield
    ``MacEntryType.DYNAMIC``, the others ``STATIC``.
    """

    def __init__(self, entry: dict, entry_type: MacEntryType = MacEntryType.DYNAMIC):
        super().__init__(data=None)
        if not isinstance(entry, dict):
            return
        self.mac_address = _normalise_mac(entry.get("address") or entry.get("mac-address"))
        self.network_instance = entry.get("vsi-name") or entry.get("bd-name")
        self.interface = entry.get("out-interface-name") or entry.get("learnt-from")
        self.vlan = _to_int(entry.get("vlan-id"))
        self.entry_type = entry_type
        # source_type — distinguishes locally-learned (SAP/AC) from
        # PW-learned (remote) MAC entries. Huawei has no explicit ``locale``
        # leaf like Nokia, but it exposes the equivalent on every FDB record
        # via ``out-interface-type``:
        #   "ac" → AC/SAP (locally-learned at a Service Access Point);
        #   "pw" → PW   (learned over a pseudo-wire, i.e. remote).
        # A previous heuristic (pw-role + physical-prefix on interface name)
        # mis-classified PW-learned MACs that arrived over physical uplink
        # ports (e.g. GigabitEthernet0/2/0 used as IP-MPLS uplink), because
        # ``pw-role`` is always "null" on FDB records — it is a PW-endpoint
        # leaf, not an FDB leaf. ``out-interface-type`` is the authoritative
        # discriminator and is part of the standard subtree returned by the
        # ``huawei-mac`` module on VRP V8 (NE40E/NE8000/ATN-910C and later).
        out_iface_type = (entry.get("out-interface-type") or "").strip().lower()
        if out_iface_type == "pw":
            self.source_type = MacSourceType.PW
        elif out_iface_type == "ac":
            self.source_type = MacSourceType.SAP
        else:
            self.source_type = None
        self.age = _to_int(entry.get("age"))
        # Huawei's standard MAC subtree does not surface a learn timestamp;
        # leave ``last_update`` at its default ``None``. Field is reserved
        # for forward compatibility with platform-specific YANG augments.
        # PW-learned enrichment — both fields ship as native YANG leaves
        # on every vsi-dynamic-mac entry with out-interface-type=pw, so no
        # extra RPC is needed. ``peer-ip`` is the remote PE's system /
        # loopback IP (not its management IP).
        self.pw_id = entry.get("pw-id")
        self.remote_system = entry.get("peer-ip") or entry.get("remote-ip")


# ---- ARP / Neighbor ----------------------------------------------------- #
class HuaweiArpEntry(Neighbor):
    """One entry from ``/arp/query-entries/query-entry``.

    Huawei groups ARP entries into a single ``query-entries`` view that
    enumerates both global and per-VPN entries. The ``ni-name`` field carries
    the originating network-instance — we map it to OpenConfig ``vrf`` and
    leave it None when it equals the device's pseudo-default ``"__"`` markers
    so the caller can tell apart global / per-VRF entries.

    The ``style-type`` value gives the ARP entry kind. We project it onto the
    OpenConfig ``NeighborOrigin`` enum: "static-arp" → STATIC, anything else
    (interface-arp / vlanif-arp / dynamic-arp) → DYNAMIC.
    """

    _ORIGIN_MAP = {
        "static-arp": NeighborOrigin.STATIC,
        "static": NeighborOrigin.STATIC,
        "interface-arp": NeighborOrigin.DYNAMIC,
        "vlanif-arp": NeighborOrigin.DYNAMIC,
        "dynamic-arp": NeighborOrigin.DYNAMIC,
        "vlink-arp": NeighborOrigin.OTHER,
    }

    def __init__(self, entry: dict):
        super().__init__(data=None)
        if not isinstance(entry, dict):
            return
        self.ip = entry.get("ip-addr") or entry.get("ip-address")
        self.link_layer_address = _normalise_mac(
            entry.get("mac-addr") or entry.get("mac-address")
        )
        self.interface = (
            entry.get("if-name")
            or entry.get("interface-name")
            or entry.get("work-if-name")
        )
        ni = entry.get("ni-name") or entry.get("vpn-instance")
        # Canonicalise the routing-instance name across vendors:
        #   * "_public_"            → "Base" (Huawei's global routing instance,
        #                             aligned with Nokia's name for the same).
        #   * "__LOCAL_OAM_VPN__",
        #     "__dcn_vpn__" (any
        #     double-underscore)    → None  (synthetic management constructs;
        #                             not operator-configured VRFs).
        #   * "_other_synth_"       → None  (other single-underscore synthetics).
        #   * normal name           → kept verbatim.
        self.vprn_name = _normalise_vprn_name(ni)
        huawei_type = (entry.get("style-type") or entry.get("type") or "").strip().lower()
        self.origin = self._ORIGIN_MAP.get(huawei_type, NeighborOrigin.OTHER)
        self.age = _to_int(entry.get("age") or entry.get("expire-time"))


# ---- Top-level result parsers ------------------------------------------- #
def _cleaned(response: dict) -> dict:
    container = NetworkInstance()
    return container.remove_namespaces(container._unwrap_data_node(response))


def parse_l2vpn_response(response: dict) -> List[HuaweiL2vpnInstance]:
    """Parse a HuaweiL2vpnRPCRequest reply into NetworkInstance objects."""
    if not isinstance(response, dict):
        return []
    cleaned = _cleaned(response)
    root = (cleaned.get("l2vpn") or {}).get("instances", {}).get("instance")
    return [HuaweiL2vpnInstance(entry) for entry in _as_list(root)]


# Back-compat alias for callers that used the old naming.
parse_vsi_response = parse_l2vpn_response


def _dedup_pw_egress_paths(entries: List[HuaweiMacEntry]) -> List[HuaweiMacEntry]:
    """Collapse underlay siblings when a Tunnel logical-PW sibling exists.

    Huawei N-series (NE40E / NE8000 BSCs and similar) report each PW-learned
    MAC TWICE in the FDB — once with the **underlay** interface name
    (`Eth-Trunk*` LAG, or a plain physical `GigabitEthernet*` port that
    carries the MPLS transport) and once with the **logical** tunnel
    interface (`Tunnel0/0/N`). The two records share `pw-id`, `peer-ip`,
    `pw-role=null` and every other leaf — they describe the SAME logical
    PW egress, only the `out-interface-name` differs.

    The tunnel name is the canonical identifier (stable across underlay
    failover, parallel to Nokia's `sdp-bind`). On the BSC sample this
    pattern produced 73 underlay sibling rows out of 150 raw — half the
    table — distorting `len(get_mac_table(...))` and the PW-learned counter.

    Rule:
        group PW entries by (mac, vsi, pw_id, remote_system).
        if any entry in the group has `interface` starting with "Tunnel" →
            keep only the Tunnel record(s); drop non-Tunnel siblings.
        else
            keep the group as-is.

    The "else" branch preserves legitimate **ECMP**: e.g. two physical
    GE-port records to the same peer with no Tunnel sibling (seen in
    `VPLS_MVD_Radio` on ATN-series, MAC `64:69:bc:2f:dc:f6` via
    `GigabitEthernet0/2/0` + `GigabitEthernet0/2/1` to peer
    `10.255.7.179`) — operator multi-uplink visibility is retained.

    SAP entries (`source_type=SAP`) bypass dedup entirely.

    Discriminator choice
    --------------------
    A field-by-field diff of two raw FDB rows for the same MAC (BSC,
    `9003-2591-2a60`) shows that out of 18 YANG leaves only one differs
    (`out-interface-name`). Huawei does not embed an underlay/tunnel
    discriminator inside the FDB record; the only authoritative source
    is `huawei-ifm /interface[name]/type` (`"Eth-Trunk"` vs `"Tunnel"`).
    We use the cheap name-prefix check (`startswith("Tunnel")`) because
    Huawei's naming convention is universal across NE/ATN platforms; an
    `ifm` cross-reference would cost an extra RPC per service and is held
    in reserve as a future opt-in if a collision is ever observed.
    """
    grouped_keys: dict = {}
    order: list = []
    for e in entries:
        if e.source_type != MacSourceType.PW:
            order.append(("passthrough", e))
            continue
        key = (e.mac_address, e.network_instance, e.pw_id, e.remote_system)
        if key not in grouped_keys:
            grouped_keys[key] = []
            order.append(("group", key))
        grouped_keys[key].append(e)

    out: List[HuaweiMacEntry] = []
    for kind, payload in order:
        if kind == "passthrough":
            out.append(payload)
            continue
        members = grouped_keys[payload]
        tunnels = [m for m in members if (m.interface or "").startswith("Tunnel")]
        out.extend(tunnels if tunnels else members)
    return out


def parse_mac_response(response: dict, include_standby: bool = False) -> List[HuaweiMacEntry]:
    """Parse a HuaweiMacRPCRequest reply into MacEntry objects.

    Walks the three sibling lists Huawei publishes — ``vsi-dynamic-macs``,
    ``vsi-static-macs``, ``vsi-blackhole-macs`` — and tags each entry with
    the right :class:`MacEntryType`.

    Post-processing layers (applied in order):
      1. H-VPLS slave-drop (see ``include_standby``) — H-VPLS standby PW
         records carry no traffic and would mislead callers.
      2. Underlay vs tunnel dedup (:func:`_dedup_pw_egress_paths`) —
         BSC-class boxes report each PW-learned MAC twice (Eth-Trunk LAG
         underlay + Tunnel0/0/N logical); collapse to the Tunnel record.

    H-VPLS PW-redundancy filtering
    -------------------------------
    When a VSI runs PW-redundancy (active/standby), Huawei returns a pair of
    FDB records for every PW-learned MAC: one with ``pw-role: "master"``
    (active path, traffic flows here) and one with ``pw-role: "slave"``
    (standby, operationally blocked, no traffic). By default we drop the
    ``slave`` records — they would otherwise mislead operators into thinking
    the MAC is reachable via a path that is actually blocked, and they have
    no Nokia equivalent (Nokia FDB natively shows only the active sdp-bind).

    Set ``include_standby=True`` to keep ``slave`` entries — useful when
    investigating a failover scenario.

    ECMP duplicates (multiple physical uplinks toward the SAME remote peer,
    all ``pw-role: "null"``, NO Tunnel sibling) are NEVER dropped — those
    represent legitimate load-balanced visibility and are valuable to the
    operator.
    """
    if not isinstance(response, dict):
        return []
    cleaned = _cleaned(response)
    mac_root = cleaned.get("mac") or {}

    out: List[HuaweiMacEntry] = []
    for list_name, kind in (
        ("vsi-dynamic-macs", MacEntryType.DYNAMIC),
        ("vsi-static-macs", MacEntryType.STATIC),
        ("vsi-blackhole-macs", MacEntryType.STATIC),
    ):
        block = mac_root.get(list_name)
        if not isinstance(block, dict):
            continue
        list_key = list_name[:-1]  # drop trailing 's': "vsi-dynamic-mac"
        for entry in _as_list(block.get(list_key)):
            if not include_standby and isinstance(entry, dict):
                if (entry.get("pw-role") or "").strip().lower() == "slave":
                    continue
            out.append(HuaweiMacEntry(entry, entry_type=kind))
    return _dedup_pw_egress_paths(out)


def parse_arp_response(response: dict) -> List[HuaweiArpEntry]:
    """Parse a HuaweiArpRPCRequest reply into Neighbor objects."""
    if not isinstance(response, dict):
        return []
    cleaned = _cleaned(response)
    root = (cleaned.get("arp") or {}).get("query-entries", {}).get("query-entry")
    return [HuaweiArpEntry(entry) for entry in _as_list(root)]


# ---- L3VPN (VRF) instances --------------------------------------------- #
def _is_system_instance(name: str) -> bool:
    """Huawei network-instance names starting with ``_`` are synthetic /
    system instances — ``_public_`` is the global routing table,
    ``__LOCAL_OAM_VPN__`` / ``__dcn_vpn__`` are management constructs.
    None of them are operator-configured VRFs."""
    return bool(name) and name.startswith("_")


class HuaweiL3vpnInstance(NetworkInstance):
    """Adapter for one ``<instance>`` entry under
    ``/network-instance/instances`` (``urn:huawei:yang:huawei-network-instance``).

    This is the VRF / L3VPN list. The brief query selects only ``name``;
    RD / route-targets / oper-status live under the ``afs/af`` subtree in
    the ``huawei-l3vpn`` namespace and are NOT pulled in v1 (cross-namespace
    field-selectors proved unreliable). Type is fixed to L3VPN.
    """

    def __init__(self, entry: dict):
        super().__init__(data=None)
        if not isinstance(entry, dict):
            return
        self.name = entry.get("name")
        self.type = NetworkInstanceType.L3VPN
        # oper_status / route_distinguisher intentionally left None in v1.


def parse_l3vpn_response(response: dict) -> List[HuaweiL3vpnInstance]:
    """Parse a HuaweiL3vpnRPCRequest reply into NetworkInstance (L3VPN) objects.

    Walks ``network-instance/instances/instance`` and **drops synthetic /
    system instances** (names starting with ``_`` — ``_public_``,
    ``__LOCAL_OAM_VPN__``, ``__dcn_vpn__``), returning only the
    operator-configured VRFs.
    """
    if not isinstance(response, dict):
        return []
    cleaned = _cleaned(response)
    root = (
        (cleaned.get("network-instance") or {})
        .get("instances", {})
        .get("instance")
    )
    out: List[HuaweiL3vpnInstance] = []
    for entry in _as_list(root):
        if not isinstance(entry, dict):
            continue
        if _is_system_instance(entry.get("name") or ""):
            continue
        out.append(HuaweiL3vpnInstance(entry))
    return out


# ---- L3 (IP) interfaces ------------------------------------------------- #
def _mask_to_prefix_len(mask: str):
    """Convert a dotted netmask (``255.255.255.0``) to a prefix length (24).

    Returns None for anything that isn't a well-formed IPv4 mask — better a
    null than a misleading number.
    """
    if not mask or not isinstance(mask, str):
        return None
    parts = mask.strip().split(".")
    if len(parts) != 4:
        return None
    try:
        bits = "".join(f"{int(p):08b}" for p in parts)
    except ValueError:
        return None
    # A valid mask is a run of 1s followed by a run of 0s.
    if "01" in bits:
        return None
    return bits.count("1")


class HuaweiL3Interface(L3Interface):
    """One ``<interface>`` entry from ``/ifm/interfaces`` (huawei-ifm).

    Fields consumed (field-selected by :class:`HuaweiL3InterfaceRPCRequest`):

        name          -> name
        vrf-name      -> vprn_name ("_public_" normalised to "Base")
        admin-status  -> admin_status
        ipv4/addresses/address (huawei-ip ns) -> ipv4_address + ipv4_prefix_length

    The ``ipv4`` subtree carries one or more ``address`` entries
    ``{ip, mask, type}``; we surface the ``type == "main"`` address (or the
    first one). Interfaces with no ``ipv4/addresses`` are not L3 interfaces
    and are skipped by :func:`parse_l3_interface_response`.
    """

    def __init__(self, entry: dict):
        super().__init__(data=None)
        if not isinstance(entry, dict):
            return
        self.name = entry.get("name")
        # Same canonicalisation rules as for ARP — "_public_" → "Base",
        # synthetic management VPNs ("__...__") → None.
        self.vprn_name = _normalise_vprn_name(entry.get("vrf-name"))
        self.admin_status = entry.get("admin-status")
        ipv4 = entry.get("ipv4")
        if isinstance(ipv4, dict):
            addrs = (ipv4.get("addresses") or {}).get("address")
            addr_list = _as_list(addrs)
            chosen = None
            for a in addr_list:
                if isinstance(a, dict) and a.get("type") == "main":
                    chosen = a
                    break
            if chosen is None and addr_list:
                chosen = addr_list[0] if isinstance(addr_list[0], dict) else None
            if isinstance(chosen, dict):
                self.ipv4_address = chosen.get("ip")
                self.ipv4_prefix_length = _mask_to_prefix_len(chosen.get("mask"))

    def has_ip(self) -> bool:
        return self.ipv4_address is not None


def parse_l3_interface_response(response: dict) -> List[HuaweiL3Interface]:
    """Parse a HuaweiL3InterfaceRPCRequest reply into L3Interface objects.

    Walks ``ifm/interfaces/interface`` and returns **only interfaces that
    carry an IPv4 address** — the huawei-ifm list contains every interface
    on the box (incl. L1/L2-only ports), and an "L3 interface" by definition
    has an IP.
    """
    if not isinstance(response, dict):
        return []
    cleaned = _cleaned(response)
    root = (
        (cleaned.get("ifm") or {})
        .get("interfaces", {})
        .get("interface")
    )
    out: List[HuaweiL3Interface] = []
    for entry in _as_list(root):
        if not isinstance(entry, dict):
            continue
        l3 = HuaweiL3Interface(entry)
        if l3.has_ip():
            out.append(l3)
    return out


# ---- VE-group (L2-L3 binding) parser ----------------------------------- #
def _strip_ve_suffix(name: str) -> str:
    """Strip the decorative ``(L2)``/``(L3)`` suffix from a VE interface name.

    Huawei's fim-ifm response decorates parent VE names: ``Virtual-Ethernet0/2/2(L2)``
    and ``Virtual-Ethernet0/2/3(L3)``. Operators reference these names without
    the suffix in every other YANG path; we normalise so downstream maps key
    on the canonical ifm name.
    """
    if not isinstance(name, str):
        return ""
    return name.split("(", 1)[0].strip()


def parse_ve_group_response(response: dict) -> List[dict]:
    """Parse a HuaweiVeGroupRPCRequest reply into a list of binding dicts.

    Each VE-group binds a single L2 Virtual-Ethernet parent to a single L3
    Virtual-Ethernet parent. The returned dicts carry the canonical names
    (suffix stripped) plus the numeric group id, so callers can build maps
    in either direction:

        [{"group_id": "1",
          "slot_id": "0",
          "l2_parent": "Virtual-Ethernet0/2/2",
          "l3_parent": "Virtual-Ethernet0/2/3"}]
    """
    if not isinstance(response, dict):
        return []
    cleaned = _cleaned(response)
    root = (
        (cleaned.get("ifm") or {})
        .get("global", {})
        .get("ve-groups", {})
        .get("ve-group")
    )
    out: List[dict] = []
    for entry in _as_list(root):
        if not isinstance(entry, dict):
            continue
        out.append({
            "group_id": entry.get("ve-group-id"),
            "slot_id": entry.get("slot-id"),
            "l2_parent": _strip_ve_suffix(entry.get("l2-ve-ifname") or ""),
            "l3_parent": _strip_ve_suffix(entry.get("l3-ve-ifname") or ""),
        })
    return out
