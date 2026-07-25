"""
Nokia SR OS adapters that map the ``urn:nokia.com:sros:ns:yang:sr:state``
operational state tree onto the vendor-agnostic OpenConfig-aligned containers
defined in :mod:`pynetcom.utils.helpers.netconf.rpc_data_containers.services`.

The adapters follow the same ``prefix`` + ``field_mapping`` pattern used by
existing Nokia interface parsers (see :mod:`...nokia_sros`). Each adapter
expects the *response* of a NETCONF <get> issued with one of the subtree
filters built by :class:`NokiaServiceRPCRequest` /
:class:`NokiaFdbRPCRequest` / :class:`NokiaArpRPCRequest`.

Vendor mapping notes
--------------------
The Nokia SR OS state model represents L2VPN multipoint services under
``/state/service/vpls`` (per-service VSI). SAPs sit directly under the VPLS
in ``.../sap``; PWs are split between ``spoke-sdp`` and ``mesh-sdp`` lists
on the VPLS, and reference an SDP overlay tunnel under
``/state/service/sdp`` (carrying ``far-end-ip-address``, ``delivery-type`` —
MPLS/GRE — and ``signaling`` — TLDP/BGP/none).

For ARP, Nokia exposes per-router state under
``/state/router/{router-name}/arp`` (where ``router-name`` is ``Base`` for
the global routing instance or the VPRN service name). Each entry carries
``ipv4-address``, ``mac-address``, ``interface`` and ``type``.

We deliberately keep this module free of NETCONF I/O — adapters only parse
already-fetched dictionaries — so the same code is reusable for live data,
fixtures and CLI replay.
"""

from __future__ import annotations

import re
from typing import List, Optional

from pynetcom.utils.nokia_router_tools import split_sap_id
from pynetcom.utils.helpers.netconf.rpc_data_containers.services import (
    ConnectionPoint,
    Endpoint,
    EndpointType,
    Fdb,
    L3Interface,
    LocalEndpoint,
    MacEntry,
    MacEntryType,
    MacSourceType,
    MacTable,
    Neighbor,
    NeighborOrigin,
    NetworkInstance,
    NetworkInstanceType,
    RemoteEndpoint,
)


# ---- Helpers ------------------------------------------------------------- #
def _as_list(value):
    """xmltodict gives a dict when a YANG list has 1 entry and a list otherwise.
    Normalise to a list to make adapters branch-free."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _to_bool(value) -> Optional[bool]:
    """Nokia returns admin-state/oper-state as strings ('enable'/'up'/...);
    we coerce only the obvious truthy/falsy forms, leave everything else as-is
    in the operator-facing ``oper_status`` text field."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("enable", "enabled", "up", "true"):
        return True
    if s in ("disable", "disabled", "down", "false"):
        return False
    return None


def _normalise_mac(value) -> Optional[str]:
    """Return canonical colon-form ``aa:bb:cc:dd:ee:ff`` for any valid input.

    Nokia state model emits MAC in colon form already, but we still funnel
    through the same canonical helper so the field always has identical
    shape across vendors (Nokia ↔ Huawei) — and so any non-conforming
    legacy YANG leaf produces ``None`` rather than a half-normalised value.
    """
    if value is None:
        return None
    hex_only = re.sub(r"[:\-\.\s]", "", str(value).strip()).lower()
    if not re.fullmatch(r"[0-9a-f]{12}", hex_only):
        return None
    return ":".join(hex_only[i:i + 2] for i in range(0, 12, 2))


# ---- Shared builders for SAP / SDP-bind entries ------------------------- #
# Both VPLS (multipoint) and EPIPE (point-to-point) Nokia services expose
# identical SAP and spoke-sdp leaf structures — only the parent container name
# and the presence of mesh-sdp / fdb differ. Factoring the per-entry conversion
# here keeps NokiaVplsService and NokiaEpipeService thin and prevents drift.

def _connection_point_from_sap(sap: dict) -> ConnectionPoint:
    """Convert one Nokia ``<sap>`` entry into a LOCAL-endpoint ConnectionPoint.

    Nokia SR OS bakes both the physical port and the encapsulation tag into
    a single ``sap-id`` leaf (e.g. ``"1/1/4:1342"`` / ``"lag-15:333"`` /
    ``"1/1/11"``). There are NO separate ``port`` / ``vlan`` leaves on the
    SAP — verified by live YANG probe. We split the composite client-side
    via :func:`pynetcom.utils.nokia_router_tools.split_sap_id` and surface
    ``LocalEndpoint.port`` + ``LocalEndpoint.vlan`` for caller convenience.
    """
    sap_id = sap.get("sap-id")
    local = LocalEndpoint()
    local.subinterface = sap_id
    local.oper_status = sap.get("oper-state")
    local.admin_status = sap.get("admin-state")
    local.encapsulation = sap.get("encap-value")
    if sap_id:
        try:
            parts = split_sap_id(sap_id)
        except ValueError:
            # Malformed sap-id — leave port/vlan at None rather than guess.
            parts = None
        if parts is not None:
            local.port = parts["port"]
            vlan_str = parts["vlan"]
            # Coerce to int only for the common dot1q case (digits). The
            # default-encap catch-all "*" and QinQ "<outer>.<inner>" are NOT
            # numbers — leave .vlan as None for those; the original string
            # is still available via ``encapsulation`` / ``subinterface``.
            if vlan_str and vlan_str.isdigit():
                local.vlan = int(vlan_str)

    ep = Endpoint()
    ep.endpoint_id = sap_id
    ep.type = EndpointType.LOCAL
    ep.local = local

    cp = ConnectionPoint()
    cp.connection_point_id = sap_id
    cp.endpoints = [ep]
    return cp


def _connection_point_from_sdp_bind(sdp_bind: dict, binding_key: str) -> ConnectionPoint:
    """Convert one Nokia ``<spoke-sdp>`` / ``<mesh-sdp>`` entry into a
    REMOTE-endpoint ConnectionPoint.

    Free-tier population (state-NS only). At this stage only ``sdp_id``,
    ``virtual_circuit_identifier`` and ``oper_status`` are filled — every
    other vendor-agnostic leaf on :class:`RemoteEndpoint` is None:

      * ``remote_system`` / ``signaling_type`` — populated later by
        :func:`_attach_sdp_far_end` when ``enrich_remote_system=True``.
        Both values live on the SDP object
        (``/state/service/sdp/<sdp_id>``), not on the spoke-sdp/mesh-sdp
        binding here.
      * ``encapsulation_type`` / ``redundancy_role`` — populated later by
        :func:`_attach_spoke_sdp_config` when ``enrich_config=True``. These
        leaves only exist in the configure-NS
        (``/configure/service/vpls/spoke-sdp/{vc-type,endpoint/precedence}``).
      * ``redundancy_state`` — stays None (no reliable state-tree source
        without MIBs).

    The ``binding_key`` argument is kept for caller context (``"spoke-sdp"``
    vs ``"mesh-sdp"``) but is no longer surfaced on the dataclass —
    the legacy ``pw_type`` field has been removed; topology kind is implicit
    in ``ConnectionPoint.connection_point_id`` shape and the parent
    container in the raw XML.
    """
    bind_id = sdp_bind.get("sdp-bind-id")
    remote = RemoteEndpoint()
    # sdp-bind-id is "sdp-id:vc-id" — split if possible.
    if isinstance(bind_id, str) and ":" in bind_id:
        sdp_str, vc_str = bind_id.split(":", 1)
        try:
            remote.sdp_id = int(sdp_str)
        except ValueError:
            pass
        try:
            remote.virtual_circuit_identifier = int(vc_str)
        except ValueError:
            pass
    remote.oper_status = sdp_bind.get("oper-state")
    # All other vendor-agnostic leaves stay None — see docstring.

    ep = Endpoint()
    ep.endpoint_id = bind_id
    ep.type = EndpointType.REMOTE
    ep.local = None
    ep.remote = remote

    cp = ConnectionPoint()
    cp.connection_point_id = bind_id
    cp.endpoints = [ep]
    return cp


# ---- VPLS service → NetworkInstance ------------------------------------- #
class NokiaVplsService(NetworkInstance):
    """Adapter for one ``<vpls>`` list entry under ``/state/service``.

    Pass the dict produced by xmltodict for *one* <vpls> entry (the one whose
    ``service-name`` you want). The adapter populates the OpenConfig-shaped
    ``NetworkInstance``: name, type=L2VPN, status flags, and the nested
    ``connection_points`` list built from SAPs + spoke-sdp + mesh-sdp.
    """

    def __init__(self, vpls_entry: dict):
        super().__init__(data=None)
        if not isinstance(vpls_entry, dict):
            return

        self.name = vpls_entry.get("service-name")
        self.type = NetworkInstanceType.L2VPN
        self.oper_status = vpls_entry.get("oper-state")
        self.enabled = _to_bool(vpls_entry.get("admin-state"))
        self.description = vpls_entry.get("description")

        # Device-side endpoint counters (state-NS leaves on <vpls>): always
        # consume when present, even in full mode — they cost nothing extra
        # in the parsed dict, and they let downstream code (e.g. bts_api
        # /routers/{name}/services aggregator) answer cardinality questions
        # uniformly across brief and full payloads. ``connection_points``
        # still take precedence — see :class:`NetworkInstance` docstring.
        for leaf, attr in (
            ("sap-count", "sap_count_hint"),
            ("sdp-bind-count", "pw_count_hint"),
        ):
            raw = vpls_entry.get(leaf)
            if raw is not None:
                try:
                    setattr(self, attr, int(raw))
                except (TypeError, ValueError):
                    pass

        # SAPs → LOCAL endpoints
        for sap in _as_list(vpls_entry.get("sap")):
            self.connection_points.append(_connection_point_from_sap(sap))

        # Spoke + mesh SDP bindings → REMOTE endpoints
        for binding_key, binding in (
            ("spoke-sdp", vpls_entry.get("spoke-sdp")),
            ("mesh-sdp", vpls_entry.get("mesh-sdp")),
        ):
            for sdp_bind in _as_list(binding):
                self.connection_points.append(
                    _connection_point_from_sdp_bind(sdp_bind, binding_key)
                )

        # Inline FDB (only present if the caller asked for ../fdb/mac in the
        # same subtree filter — usually we fetch FDB separately).
        fdb_block = vpls_entry.get("fdb")
        if isinstance(fdb_block, dict):
            self.fdb = Fdb()
            self.fdb.mac_table = NokiaMacTable(fdb_block, service_name=self.name)


# ---- EPIPE service → NetworkInstance (point-to-point VPWS / VLL) -------- #
class NokiaEpipeService(NetworkInstance):
    """Adapter for one ``<epipe>`` list entry under ``/state/service``.

    EPIPE is Nokia's name for Ethernet VPWS (industry term: VLL — Virtual
    Leased Line). Schema source: ``nokia-state-svc-epipe.yang``. The entry
    has the same ``sap`` and ``spoke-sdp`` shape as VPLS, but:

      - No ``mesh-sdp`` list (point-to-point services don't mesh).
      - No ``fdb`` subtree (no MAC learning at the pipe service level).
      - At most a handful of endpoints (typically 1 SAP + 1 spoke-sdp for
        a remote-attached pipe, or 2 SAPs for a local cross-connect).

    OpenConfig mapping: ``type = NetworkInstanceType.L2P2P`` (matches the
    Huawei VPWS-LDP / VPWS-Static instances exposed by HuaweiL2vpnInstance).
    """

    def __init__(self, epipe_entry: dict):
        super().__init__(data=None)
        if not isinstance(epipe_entry, dict):
            return

        self.name = epipe_entry.get("service-name")
        self.type = NetworkInstanceType.L2P2P
        self.oper_status = epipe_entry.get("oper-state")
        self.enabled = _to_bool(epipe_entry.get("admin-state"))
        self.description = epipe_entry.get("description")

        # Device-side endpoint counters — see NokiaVplsService for rationale.
        # EPIPE is point-to-point so typical values are ``sap-count=1`` /
        # ``sdp-bind-count=1`` (remote-attached) or ``sap-count=2`` /
        # ``sdp-bind-count=0`` (local cross-connect).
        for leaf, attr in (
            ("sap-count", "sap_count_hint"),
            ("sdp-bind-count", "pw_count_hint"),
        ):
            raw = epipe_entry.get(leaf)
            if raw is not None:
                try:
                    setattr(self, attr, int(raw))
                except (TypeError, ValueError):
                    pass

        for sap in _as_list(epipe_entry.get("sap")):
            self.connection_points.append(_connection_point_from_sap(sap))

        for sdp_bind in _as_list(epipe_entry.get("spoke-sdp")):
            self.connection_points.append(
                _connection_point_from_sdp_bind(sdp_bind, "spoke-sdp")
            )


# ---- SDP enrichment helpers -------------------------------------------- #
def parse_sdp_response(response: dict) -> dict:
    """Parse a Nokia ``/state/service/sdp`` reply into a {sdp_id: info} map.

    The brief flavour of :class:`NokiaSdpRPCRequest` returns
    ``sdp-id`` + ``oper-tunnel-far-end-inet-address`` + ``active-lsp-type``
    per entry. The full flavour adds ``oper-state`` and other fields. This
    parser returns a dict keyed by the integer sdp-id::

        {10179: {"far_end_ip": "10.255.7.179",
                 "oper_state": "up",
                 "delivery_type": "bgp",
                 "active_lsp_type": "bgp"}}

    Both ``delivery_type`` and ``active_lsp_type`` carry the same Nokia
    leaf (``<active-lsp-type>``) — the former kept as the historical key
    name, the latter as the alias used by remote-endpoint enrichment
    (``RemoteEndpoint.signaling_type``). Values are the canonical SR OS
    strings ``rsvp`` / ``ldp`` / ``bgp`` (already lower-case, no mapping
    needed downstream).

    Unknown / missing fields appear as ``None`` so callers can read any
    leaf uniformly without branching on whether the input was brief or full.
    """
    if not isinstance(response, dict):
        return {}
    container = NetworkInstance()
    cleaned = container.remove_namespaces(container._unwrap_data_node(response))
    sdp_root = (cleaned.get("state") or {}).get("service", {}).get("sdp")
    out = {}
    for entry in _as_list(sdp_root):
        if not isinstance(entry, dict):
            continue
        try:
            sid = int(entry.get("sdp-id"))
        except (TypeError, ValueError):
            continue
        active_lsp_type = entry.get("active-lsp-type")
        out[sid] = {
            "far_end_ip": entry.get("oper-tunnel-far-end-inet-address"),
            "oper_state": entry.get("sdp-oper-state") or entry.get("oper-state"),
            # ``delivery_type`` kept for any legacy caller; ``active_lsp_type``
            # is the canonical alias used by :func:`_attach_sdp_far_end`.
            "delivery_type": active_lsp_type,
            "active_lsp_type": active_lsp_type,
        }
    return out


def parse_vprn_interface_vpls_response(response: dict) -> dict:
    """Parse a NokiaVprnInterfaceVplsRPCRequest reply into a binding map.

    Returns ``{(vprn_name, interface_name): vpls_name}`` for every VPRN
    interface that has a ``vpls/vpls-name`` element configured. Pure-L3
    interfaces (no ``vpls`` element) are absent from the map entirely.

    The response shape (configure namespace)::

        configure/service/vprn[<service-name>]/interface[<interface-name>]/vpls/vpls-name

    We key by ``(vprn_name, iface)`` rather than just ``iface`` because the
    same interface name can appear in multiple VPRNs simultaneously on
    different routers — keeping the VPRN qualifier avoids cross-VRF false
    matches.
    """
    if not isinstance(response, dict):
        return {}
    container = NetworkInstance()
    cleaned = container.remove_namespaces(container._unwrap_data_node(response))
    configure_root = (
        cleaned.get("configure")
        or cleaned  # in case caller already unwrapped one level
    )
    vprn_root = (configure_root.get("service") or {}).get("vprn")
    out: dict = {}
    for vp in _as_list(vprn_root):
        if not isinstance(vp, dict):
            continue
        vprn_name = vp.get("service-name")
        for iface in _as_list(vp.get("interface")):
            if not isinstance(iface, dict):
                continue
            iface_name = iface.get("interface-name")
            vpls = iface.get("vpls") or {}
            if isinstance(vpls, dict):
                vpls_name = vpls.get("vpls-name")
            else:
                vpls_name = None
            if vprn_name and iface_name and vpls_name:
                out[(vprn_name, iface_name)] = vpls_name
    return out


# NOTE: a Base-router interface→VPLS binding parser intentionally does not
# exist. R-VPLS on the base router is not a valid scenario on SR OS 23.10
# (the ``<vpls>`` leaf under /configure/router[Base]/interface returns
# Unknown element) and is absent from our fleet (plan E1). Base-router L3
# interfaces always resolve ``l2_service=None``. R-VPLS bindings are parsed
# for VPRN interfaces only — see :func:`parse_vprn_interface_vpls_response`.


def parse_sap_admin_state_response(response: dict) -> dict:
    """Parse a NokiaServiceSapAdminStateRPCRequest reply into an admin-state map.

    Returns ``{(service_name, sap_id): admin_state}`` where ``admin_state``
    is canonicalised to ``"enabled"`` / ``"disabled"`` to match OpenConfig
    semantics (Nokia ships ``"enable"`` / ``"disable"`` on the wire; we map
    them here). Covers both VPLS and EPIPE sibling containers in one pass.

    The map is keyed by ``(service_name, sap_id)`` rather than ``sap_id``
    alone because a SAP identifier (e.g. ``"1/1/11:100"``) is not globally
    unique — it can appear in two different services on the same router.
    Callers downstream join the L2 service object's
    ``(service.name, endpoint.local.subinterface)`` against this map.

    The response shape (configure namespace)::

        configure/service/{vpls,epipe}[service-name]/sap[sap-id]/admin-state

    Defaulted values (``<admin-state>enable</admin-state>``) only appear
    when the caller passed ``with_defaults="report-all"`` to
    :meth:`NetconfClient.get_config`. Without it, enabled SAPs would
    silently drop out of the map.
    """
    if not isinstance(response, dict):
        return {}
    container = NetworkInstance()
    cleaned = container.remove_namespaces(container._unwrap_data_node(response))
    configure_root = cleaned.get("configure") or cleaned
    service_root = configure_root.get("service") or {}

    canon = {"enable": "enabled", "disable": "disabled"}

    out: dict = {}
    for container_key in ("vpls", "epipe"):
        for svc in _as_list(service_root.get(container_key)):
            if not isinstance(svc, dict):
                continue
            svc_name = svc.get("service-name")
            if not svc_name:
                continue
            for sap in _as_list(svc.get("sap")):
                if not isinstance(sap, dict):
                    continue
                sap_id = sap.get("sap-id")
                raw = sap.get("admin-state")
                if not sap_id or raw is None:
                    continue
                # Canonicalise — fall through to the raw value if unexpected
                # (e.g. operator-extended enums) so the operator still sees
                # the original string rather than ``None``.
                normalised = canon.get(str(raw).strip().lower(), str(raw).strip().lower())
                out[(svc_name, sap_id)] = normalised
    return out


def _attach_sdp_far_end(service: NetworkInstance, sdp_map: dict) -> None:
    """Stamp SDP-derived fields on a service's REMOTE endpoints (in-place).

    Populates two leaves on every :class:`RemoteEndpoint`:

      * ``remote_system`` — from SDP ``oper-tunnel-far-end-inet-address``.
      * ``signaling_type`` — from SDP ``active-lsp-type``
        (``rsvp`` / ``ldp`` / ``bgp``); already in canonical lower-case form.

    ``sdp_map`` is the full dict returned by :func:`parse_sdp_response`
    (``{sdp_id: {"far_end_ip": ..., "active_lsp_type": ..., ...}}``). For
    backward compatibility callers that historically pre-projected the map
    to ``{sdp_id: far_end_ip}`` still work — when the per-sdp value is a
    string (not a dict) we treat it as the far-end IP and leave
    ``signaling_type`` untouched.

    Endpoints whose ``remote.sdp_id`` is not in the map are left untouched
    (so missing SDP data degrades gracefully — operator still gets sdp_id
    and vc_id, just without the enrichment).
    """
    if not service or not isinstance(sdp_map, dict):
        return
    for cp in service.connection_points or []:
        for ep in cp.endpoints or []:
            if ep.type != EndpointType.REMOTE or ep.remote is None:
                continue
            sid = ep.remote.sdp_id
            if sid is None:
                continue
            info = sdp_map.get(sid)
            if info is None:
                continue
            if isinstance(info, dict):
                ip = info.get("far_end_ip")
                lsp = info.get("active_lsp_type") or info.get("delivery_type")
            else:
                # Back-compat: caller pre-projected to {sdp_id: far_end_ip}.
                ip = info
                lsp = None
            if ip:
                ep.remote.remote_system = ip
            if lsp:
                ep.remote.signaling_type = lsp


def _attach_spoke_sdp_config(service: NetworkInstance, cfg_map: dict) -> None:
    """Stamp configure-NS spoke-sdp fields on REMOTE endpoints (in-place).

    Populates two leaves on every matching :class:`RemoteEndpoint`:

      * ``encapsulation_type`` — from ``spoke-sdp/vc-type``
        (``ether`` / ``vlan``).
      * ``redundancy_role`` — from ``spoke-sdp/endpoint/precedence``.

    Nokia precedence semantics
    ---------------------------
    Nokia's ``endpoint/precedence`` is a UNION leaf: the special string
    ``"primary"`` (highest priority leg) or a uint16 number (lower = higher
    priority, e.g. ``"4"``). The vendor-agnostic vocabulary on
    :class:`RemoteEndpoint.redundancy_role` is ``primary`` / ``secondary``,
    so we normalise here:

      * ``"primary"`` (string)            → ``"primary"``.
      * any other / numeric value         → ``"secondary"``.

    The numeric ordering information is lost on this mapping — operators
    investigating priorities should look at the raw running-config. For
    AI / operator dashboards the binary primary-vs-secondary view matches
    what Huawei exposes natively (``pw/role`` is ``primary`` or
    ``secondary`` only).

    ``cfg_map`` is keyed by ``(service_name, sdp_bind_id)`` and built by
    :func:`parse_spoke_sdp_config_response`. Endpoints whose composite
    ``(svc.name, ep.remote.sdp_id + ":" + ep.remote.virtual_circuit_identifier)``
    is not in the map are left untouched — defensive against partial
    configure-NS responses.
    """
    if not service or not isinstance(cfg_map, dict):
        return
    svc_name = service.name
    if not svc_name:
        return
    for cp in service.connection_points or []:
        for ep in cp.endpoints or []:
            if ep.type != EndpointType.REMOTE or ep.remote is None:
                continue
            sdp_id = ep.remote.sdp_id
            vc_id = ep.remote.virtual_circuit_identifier
            if sdp_id is None or vc_id is None:
                continue
            bind_id = f"{sdp_id}:{vc_id}"
            entry = cfg_map.get((svc_name, bind_id))
            if not isinstance(entry, dict):
                continue
            vc_type = entry.get("vc-type")
            if isinstance(vc_type, str) and vc_type.strip():
                ep.remote.encapsulation_type = vc_type.strip().lower()
            endpoint_cfg = entry.get("endpoint")
            if isinstance(endpoint_cfg, dict):
                precedence = endpoint_cfg.get("precedence")
                if isinstance(precedence, str) and precedence.strip():
                    norm = precedence.strip().lower()
                    # Nokia union: "primary" or a numeric value (lower =
                    # higher priority). Map anything not "primary" to the
                    # vendor-agnostic "secondary" so RemoteEndpoint.
                    # redundancy_role has a stable vocabulary across vendors.
                    ep.remote.redundancy_role = (
                        "primary" if norm == "primary" else "secondary"
                    )


def parse_spoke_sdp_config_response(response: dict) -> dict:
    """Parse a Nokia configure-NS spoke-sdp dump into a per-PW binding map.

    Consumes the response of :class:`NokiaServiceVplsSpokeSdpConfigRPCRequest`
    and returns::

        {(service_name, sdp_bind_id): {
            "vc-type": "ether" | "vlan" | ...,
            "endpoint": {"precedence": "primary" | "secondary"}}}

    Only entries that actually carry one of the leaves are included
    (a pure-defaults absence is still keyed-in by the device when
    ``with-defaults="report-all"`` is set on the get-config). Missing
    sub-leaves stay absent from the value dict — :func:`_attach_spoke_sdp_config`
    tolerates the gap.

    Each value is the raw configure-NS spoke-sdp dict (after namespace
    stripping). The key ``(service_name, sdp_bind_id)`` mirrors the
    composite used by :class:`RemoteEndpoint` (``sdp_id:vc_id``).
    """
    if not isinstance(response, dict):
        return {}
    container = NetworkInstance()
    cleaned = container.remove_namespaces(container._unwrap_data_node(response))
    configure_root = cleaned.get("configure") or cleaned
    service_root = configure_root.get("service") or {}
    out: dict = {}
    for svc in _as_list(service_root.get("vpls")):
        if not isinstance(svc, dict):
            continue
        svc_name = svc.get("service-name")
        if not svc_name:
            continue
        for spoke in _as_list(svc.get("spoke-sdp")):
            if not isinstance(spoke, dict):
                continue
            bind_id = spoke.get("sdp-bind-id")
            if not bind_id:
                continue
            out[(svc_name, str(bind_id))] = spoke
    return out


# ---- FDB / MAC entries --------------------------------------------------- #
class NokiaMacEntry(MacEntry):
    """One ``<mac>`` entry from ``/state/service/vpls/.../fdb/mac``.

    Nokia SR OS schema (verified on SR OS 23 ``nokia-state`` 2024-03-06):

        address       — MAC, colon-form already.
        locale        — "sap" | "sdp-bind" | "host" | ...; selects which sibling
                        field identifies the learning point.
        sap-id        — when locale = "sap" (e.g. "1/1/11").
        sdp-bind      — when locale = "sdp-bind" (e.g. "10179:1100010331").
        type          — "learned" | "static" | "oam" | "host" | ...
        last-update   — ISO-8601 timestamp of last learn event.
        age           — seconds since the entry's age timer started.

    We project ``sap-id``/``sdp-bind`` (whichever is present) onto the unified
    ``interface`` field, since the operator-facing meaning is "where did the
    device learn this MAC" — port for local learn, PW for remote learn.
    """

    _MAC_TYPE_MAP = {
        "learned": MacEntryType.DYNAMIC,
        "dynamic": MacEntryType.DYNAMIC,
        "static": MacEntryType.STATIC,
        "host": MacEntryType.STATIC,
        "oam": MacEntryType.STATIC,
        "oam-mac": MacEntryType.STATIC,
        "interface": MacEntryType.STATIC,
    }

    _LOCALE_MAP = {
        "sap":      MacSourceType.SAP,
        "sdp-bind": MacSourceType.PW,
    }

    def __init__(self, mac_entry: dict, service_name: Optional[str] = None):
        super().__init__(data=None)
        if not isinstance(mac_entry, dict):
            return
        self.mac_address = _normalise_mac(
            mac_entry.get("address") or mac_entry.get("monitored-mac")
        )
        # The learning source is either a SAP id (locale=sap, field "sap" —
        # e.g. "1/1/11") or an SDP bind id (locale=sdp-bind, field "sdp-bind"
        # — e.g. "10179:1100010331"). We surface whichever is populated.
        # ("sap-id" / "source-id" kept as fallbacks for older releases.)
        sdp_bind = mac_entry.get("sdp-bind")
        self.interface = (
            mac_entry.get("sap")
            or mac_entry.get("sap-id")
            or sdp_bind
            or mac_entry.get("source-id")
        )
        # PW-learned MACs carry the sdp-bind identifier as "<sdp_id>:<vc_id>".
        # Surface the vc-id half as :attr:`MacEntry.pw_id` for symmetry with
        # Huawei (where pw-id is a dedicated leaf on every PW FDB record).
        # ``remote_system`` stays None on Nokia for v1 — populating it would
        # require joining with the VPLS PW list (peer-ip lives there, not on
        # the FDB leaf) and that is deferred to a follow-up iteration.
        if isinstance(sdp_bind, str) and ":" in sdp_bind:
            self.pw_id = sdp_bind.split(":", 1)[1]
        # source_type comes straight from Nokia's ``locale`` leaf. Anything
        # outside the {sap, sdp-bind} pair (e.g. ``host``, ``oam``) is left
        # as None so the operator can recognise the edge case.
        locale = (mac_entry.get("locale") or "").strip().lower()
        self.source_type = self._LOCALE_MAP.get(locale)
        # Port / VLAN derivation. Nokia FDB carries the learning point as a
        # composite identifier (sap-id for SAP-learned, ``<sdp_id>:<vc_id>``
        # for PW-learned). There is no separate port / vlan leaf on the FDB
        # record — verified by live YANG probe (Phase 0). We split the SAP
        # composite via :func:`split_sap_id` for symmetry with SAP parser.
        # PW-learned records leave port/vlan at None — sdp-bind is not a
        # physical port, it is a tunnel binding.
        if self.source_type == MacSourceType.SAP and isinstance(self.interface, str):
            try:
                parts = split_sap_id(self.interface)
            except ValueError:
                parts = None
            if parts is not None:
                self.port = parts.get("port") or None
                vlan_str = parts.get("vlan")
                # Coerce to int only for the common dot1q case (digits). The
                # default-encap catch-all "*" and QinQ "<outer>.<inner>" stay
                # as ``None`` here; the raw composite remains in ``interface``.
                if vlan_str and vlan_str.isdigit():
                    self.vlan = int(vlan_str)
        nokia_type = (mac_entry.get("type") or mac_entry.get("mac-type") or "").strip().lower()
        self.entry_type = self._MAC_TYPE_MAP.get(nokia_type)
        # ``age`` is strictly Optional[int]: int-coerce the leaf when present,
        # ``None`` on missing / garbage. The ISO-8601 ``last-update`` /
        # ``last-update-time`` leaf goes into the dedicated ``last_update``
        # string field instead of overloading ``age`` with mixed types.
        age_raw = mac_entry.get("age")
        if age_raw is not None:
            try:
                self.age = int(age_raw)
            except (TypeError, ValueError):
                self.age = None
        self.last_update = (
            mac_entry.get("last-update") or mac_entry.get("last-update-time")
        )
        self.network_instance = service_name


class NokiaMacTable(MacTable):
    """Wrapper that consumes the ``<fdb>`` block under a VPLS."""

    def __init__(self, fdb_block: dict, service_name: Optional[str] = None):
        super().__init__(data=None)
        if not isinstance(fdb_block, dict):
            return
        for mac in _as_list(fdb_block.get("mac")):
            self.entries.append(NokiaMacEntry(mac, service_name=service_name))


# ---- ARP / Neighbor ----------------------------------------------------- #
class NokiaArpEntry(Neighbor):
    """One entry from the per-interface ``neighbor-discovery/neighbor`` list.

    YANG path (per ``nokia-state-router.yang`` rev 2024-03-06, line 3284):

        /state/router[router-name]
          /interface[interface-name]
            /ipv4/neighbor-discovery/neighbor[ipv4-address]

    The same shape sits under
    ``/state/service/vprn[service-name]/interface[interface-name]/ipv4/...``
    for VPRN-scoped (VRF) ARP.

    Fields on each neighbor entry::

        ipv4-address    list key
        mac-address     learned/static MAC, yang:mac-address
        oper-state      "up" | "down"
        type            other | static | dynamic | managed | evpn
        timer           seconds until the entry expires (NOT seconds since
                        learned — Nokia exposes the TTL, not the age)

    The originating interface name and VRF are not on the entry itself —
    the parser sets them from the list context.
    """

    _ORIGIN_MAP = {
        "dynamic": NeighborOrigin.DYNAMIC,
        "static": NeighborOrigin.STATIC,
        "managed": NeighborOrigin.OTHER,
        "evpn": NeighborOrigin.OTHER,
        "other": NeighborOrigin.OTHER,
    }

    def __init__(
        self,
        arp_entry: dict,
        vprn_name: Optional[str] = None,
        interface: Optional[str] = None,
    ):
        super().__init__(data=None)
        if not isinstance(arp_entry, dict):
            return
        self.ip = arp_entry.get("ipv4-address")
        self.link_layer_address = _normalise_mac(arp_entry.get("mac-address"))
        self.interface = interface
        nokia_type = (arp_entry.get("type") or "").strip().lower()
        self.origin = self._ORIGIN_MAP.get(nokia_type, NeighborOrigin.OTHER)
        # Nokia exposes time-to-expiry as ``timer`` (seconds). We surface it
        # on the OpenConfig ``age`` field for shape parity with Huawei; the
        # semantic difference (TTL vs age-since-learned) is documented in the
        # adapter docstring. Strictly Optional[int] — fall back to None on
        # anything non-numeric rather than letting a string leak through.
        timer = arp_entry.get("timer")
        try:
            self.age = int(timer) if timer is not None else None
        except (TypeError, ValueError):
            self.age = None
        self.vprn_name = vprn_name
        # ---- oper_state --------------------------------------------------
        # Nokia surfaces a native <oper-state> leaf under <neighbor> (Phase 0
        # discovery): typically "up" for a healthy resolved entry. Pass it
        # through verbatim so callers get the same vocabulary the device
        # uses.
        self.oper_state = arp_entry.get("oper-state")
        # NOTE: no port / vlan are surfaced on Neighbor — see the Neighbor
        # docstring. SR OS does not expose them under <neighbor> anyway:
        # the parent <interface> leaf is the L3-IF name (possibly an R-VPLS
        # interface like ``VPLS_LTE_eNodeB_…``), and that is exactly what
        # ``self.interface`` carries. Callers needing the physical port
        # resolve it from the L3-interface / SAP layer.


# ---- Top-level result parsers ------------------------------------------- #
def parse_vpls_response(response: dict) -> List[NokiaVplsService]:
    """Parse a NETCONF reply produced by NokiaServiceRPCRequest into services.

    The response is the dict returned by ``NetconfClient.get`` — i.e. already
    unwrapped to ``{'data': {...}}`` shape by ncclient/xmltodict but still
    carrying ``@xmlns`` attributes. We use the same namespace-stripping logic
    the existing OpenConfig parsers rely on (inherited via RPCDataContainer).
    """
    if not isinstance(response, dict):
        return []
    container = NetworkInstance()
    cleaned = container.remove_namespaces(container._unwrap_data_node(response))

    vpls_root = (
        (cleaned.get("state") or {})
        .get("service", {})
        .get("vpls")
    )
    return [NokiaVplsService(entry) for entry in _as_list(vpls_root)]


def parse_epipe_response(response: dict) -> List[NokiaEpipeService]:
    """Parse a NokiaEpipeRPCRequest reply into NokiaEpipeService objects.

    Mirrors :func:`parse_vpls_response` but walks ``state/service/epipe``.
    Returns an empty list when the device has no EPIPE services configured
    (Nokia's NETCONF returns ``data: null`` in that case).
    """
    if not isinstance(response, dict):
        return []
    container = NetworkInstance()
    cleaned = container.remove_namespaces(container._unwrap_data_node(response))
    if not isinstance(cleaned, dict):
        return []

    epipe_root = (
        (cleaned.get("state") or {})
        .get("service", {})
        .get("epipe")
    )
    return [NokiaEpipeService(entry) for entry in _as_list(epipe_root)]


def parse_fdb_response(response: dict, service_name: Optional[str] = None) -> List[NokiaMacEntry]:
    """Parse a NokiaFdbRPCRequest reply into a flat list of MAC entries.

    If the filter scoped the query to a single VPLS, ``service_name`` should be
    passed so each MacEntry carries the originating ``network_instance`` field.
    """
    if not isinstance(response, dict):
        return []
    container = NetworkInstance()
    cleaned = container.remove_namespaces(container._unwrap_data_node(response))
    vpls_root = cleaned.get("state", {}).get("service", {}).get("vpls")

    entries: List[NokiaMacEntry] = []
    for vpls in _as_list(vpls_root):
        scoped_name = vpls.get("service-name") or service_name
        fdb = vpls.get("fdb")
        if not isinstance(fdb, dict):
            continue
        for mac in _as_list(fdb.get("mac")):
            entries.append(NokiaMacEntry(mac, service_name=scoped_name))
    return entries


def parse_arp_response(response: dict, vprn_name: str = "Base") -> List[NokiaArpEntry]:
    """Parse a NokiaArpRPCRequest reply into a flat list of Neighbor objects.

    Walks the nested structure::

        state/router[router-name]/interface[interface-name]
            /ipv4/neighbor-discovery/neighbor[ipv4-address]

    or, for VPRN/VRF ARP::

        state/service/vprn[service-name]/interface[interface-name]
            /ipv4/neighbor-discovery/neighbor[ipv4-address]

    Each entry carries no interface/routing-instance reference of its own —
    the list keys higher up the path are the only place those names appear.
    The parser propagates them into the flat ``Neighbor.interface`` /
    ``vprn_name`` fields so callers can filter without re-walking the path.

    ``vprn_name`` is the fallback routing-instance name used when the YANG
    list-key is absent from the response (rare). Canonical default is
    ``"Base"`` for the global routing table.
    """
    if not isinstance(response, dict):
        return []
    container = NetworkInstance()
    cleaned = container.remove_namespaces(container._unwrap_data_node(response))

    entries: List[NokiaArpEntry] = []

    def harvest_interfaces(parent: dict, scoped_vprn_name: str) -> None:
        for iface in _as_list(parent.get("interface")):
            if not isinstance(iface, dict):
                continue
            iface_name = iface.get("interface-name")
            nd = (iface.get("ipv4") or {}).get("neighbor-discovery")
            if not isinstance(nd, dict):
                continue
            for nb in _as_list(nd.get("neighbor")):
                entries.append(
                    NokiaArpEntry(nb, vprn_name=scoped_vprn_name, interface=iface_name)
                )

    state = cleaned.get("state") or {}

    # Base / named router instance.
    for router in _as_list(state.get("router")):
        if not isinstance(router, dict):
            continue
        scoped_vprn_name = router.get("router-name") or vprn_name
        harvest_interfaces(router, scoped_vprn_name)

    # VPRN service (L3VPN).
    for vprn in _as_list((state.get("service") or {}).get("vprn")):
        if not isinstance(vprn, dict):
            continue
        scoped_vprn_name = vprn.get("service-name") or vprn_name
        harvest_interfaces(vprn, scoped_vprn_name)

    return entries


# ---- VPRN (L3VPN / VRF) service ---------------------------------------- #
class NokiaVprnService(NetworkInstance):
    """Adapter for one ``<vprn>`` list entry under ``/state/service``.

    Nokia VPRN = a routing-instance / L3VPN. Schema source:
    ``nokia-state-svc-vprn.yang``. The full VPRN subtree is the entire
    routing table (querying it times out) — so :class:`NokiaVprnRPCRequest`
    only field-selects ``service-name`` + ``oper-state`` +
    ``oper-route-distinguisher`` and this adapter consumes exactly those.

    OpenConfig mapping: ``type = NetworkInstanceType.L3VPN``.
    """

    def __init__(self, vprn_entry: dict):
        super().__init__(data=None)
        if not isinstance(vprn_entry, dict):
            return
        self.name = vprn_entry.get("service-name")
        self.type = NetworkInstanceType.L3VPN
        self.oper_status = vprn_entry.get("oper-state")
        # ``enabled`` (admin intent) is intentionally left ``None`` for
        # VPRN: the Nokia VPRN state-tree does not expose ``admin-state``
        # as a leaf — requesting it triggers ``MGMT_CORE #2201 Unknown
        # element`` and breaks the whole RPC (see NokiaVprnRPCRequest).
        # This is vendor-asymmetric with NokiaVplsService / NokiaEpipeService
        # but unavoidable until Nokia ships the leaf in state. ``oper_status``
        # remains the authoritative runtime signal.
        self.route_distinguisher = vprn_entry.get("oper-route-distinguisher")


def parse_vprn_response(response: dict) -> List[NokiaVprnService]:
    """Parse a NokiaVprnRPCRequest reply into NokiaVprnService objects.

    Mirrors :func:`parse_vpls_response` but walks ``state/service/vprn``.
    """
    if not isinstance(response, dict):
        return []
    container = NetworkInstance()
    cleaned = container.remove_namespaces(container._unwrap_data_node(response))
    if not isinstance(cleaned, dict):
        return []
    vprn_root = (
        (cleaned.get("state") or {})
        .get("service", {})
        .get("vprn")
    )
    return [NokiaVprnService(entry) for entry in _as_list(vprn_root)]


# ---- L3 (IP) interfaces ------------------------------------------------- #
class NokiaL3Interface(L3Interface):
    """One ``<interface>`` entry from a Nokia router or VPRN.

    YANG path: ``/state/router[router-name]/interface[interface-name]`` or
    ``/state/service/vprn[service-name]/interface[interface-name]``. Fields
    consumed (field-selected by :class:`NokiaL3InterfaceRPCRequest`):

        interface-name           -> name
        oper-state               -> oper_status
        oper-ip-mtu              -> mtu
        ipv4/primary/oper-address -> ipv4_address

    ``vprn_name`` is set by the parser. ``ipv4_prefix_length`` is left None
    by the parser — the SR OS **state** model exposes only the
    ``oper-address`` without a netmask; the prefix-length is filled from the
    configure-NS under ``enrich_config`` (see below).

    Binding (free vs enrich)
    ------------------------
    The state-tree does NOT expose binding-discriminator leaves
    (``<port>`` / ``<sap>`` / ``<spoke-sdp>`` / ``<loopback>`` live in the
    configure namespace). Without enrichment we derive ``binding_type`` from
    the interface name alone:

        ``LoopBack*``            → ``loopback``
        ``System``               → ``system``
        ``VPLS_*`` (R-VPLS conv) → ``l2vpn_routed`` (+ ``l2_service=name``)
        anything else            → ``unknown``

    When ``apply_binding_from_config()`` is called (by ServicesClient when
    ``enrich_config=True``) we get the precise discriminator from the
    configure-NS payload:

      * VPRN interfaces: ``<spoke-sdp>`` object → ``sdp_spoke``,
        ``<sap>`` object → ``sap_physical`` (with ``parent_port`` + ``vlan``
        derived from ``sap-id`` via :func:`split_sap_id`),
        ``<loopback>true</loopback>`` → ``loopback``.
      * Base-router interfaces: the ``<port>`` leaf names the carrier —
        ``"3/1/1"`` → ``physical_port`` (parent_port), ``"lag-3"`` →
        ``physical_port`` (parent_port=lag), ``"2/1/8:671"`` →
        ``subinterface`` (parent_port + vlan).

    The discriminator only moves the ``unknown`` ones — name-recognised
    types are reaffirmed but not overridden.

    ``admin_status`` and ``ipv4_prefix_length`` are also filled from the
    configure payload as fallbacks: the state-NS omits ``<admin-state>`` on
    Nokia VPRN-bound interfaces and never carries a netmask on either scope.
    ``apply_binding_from_config`` maps ``admin-state`` ``enable→up`` /
    ``disable→down`` and reads ``ipv4/primary/prefix-length``, writing each
    ONLY if state-NS left it None — a valid state-NS value is never
    overwritten.
    """

    # Name-pattern binding rules — applied at construction. Order matters:
    # checked top-to-bottom, first match wins. None means "fall through".
    @staticmethod
    def _derive_binding_from_name(name: Optional[str]) -> tuple:
        """Return ``(binding_type, l2_service)`` derived from the interface name.

        Used as the free-tier fallback when no configure-NS payload is
        available. Returns ``('unknown', None)`` for anything that doesn't
        look like a Nokia-convention IRB / loopback / system interface.
        """
        if not isinstance(name, str) or not name:
            return ("unknown", None)
        if name.startswith("LoopBack"):
            return ("loopback", None)
        if name == "System":
            return ("system", None)
        if name.startswith("VPLS_"):
            # Nokia R-VPLS naming convention — the L3 interface name is
            # exactly the VPLS service name. Surface ``l2_service`` for
            # free here too: no extra RPC required.
            return ("l2vpn_routed", name)
        return ("unknown", None)

    def __init__(self, iface_entry: dict, vprn_name: Optional[str] = None):
        super().__init__(data=None)
        if not isinstance(iface_entry, dict):
            return
        self.name = iface_entry.get("interface-name")
        self.oper_status = iface_entry.get("oper-state")
        mtu = iface_entry.get("oper-ip-mtu")
        try:
            self.mtu = int(mtu) if mtu is not None else None
        except (TypeError, ValueError):
            self.mtu = None
        ipv4 = iface_entry.get("ipv4")
        if isinstance(ipv4, dict):
            primary = ipv4.get("primary")
            if isinstance(primary, dict):
                self.ipv4_address = primary.get("oper-address")
        self.vprn_name = vprn_name
        # Name-pattern binding (free tier). The configure-NS enrichment
        # path (see apply_binding_from_config) may upgrade ``unknown``
        # entries to ``sdp_spoke`` / ``sap_physical`` later.
        binding, l2 = self._derive_binding_from_name(self.name)
        self.binding_type = binding
        if l2 is not None and not self.l2_service:
            self.l2_service = l2

    def apply_binding_from_config(self, config_entry: Optional[dict]) -> None:
        """Refine ``binding_type`` (and friends) using configure-NS payload.

        ``config_entry`` is the dict for this interface as returned under
        ``/configure/service/vprn[...]/interface[interface-name=...]`` (or
        the Base-router equivalent). Pass ``None`` to leave the
        name-pattern binding from ``__init__`` intact.

        Priority (per the Phase 2 plan):
          1. ``<spoke-sdp>`` object present → ``sdp_spoke``,
             ``sdp_bind_id = config_entry['spoke-sdp']['sdp-bind-id']``.
          2. ``<sap>`` object present → ``sap_physical``;
             split ``sap-id`` via :func:`split_sap_id` to fill
             ``parent_port`` + ``vlan``.
          3. ``<loopback>true</loopback>`` (boolean leaf — only the literal
             string ``"true"`` counts; ``"false"`` is *not* a loopback marker)
             → ``loopback``.

        Additionally, ``<admin-state>`` is consumed as an ``admin_status``
        fallback: if state-NS left ``self.admin_status`` at None (known case:
        Nokia VPRN-bound interfaces don't surface ``<admin-state>`` under
        ``/state/service/vprn/.../interface``), the configure leaf is
        mapped ``enable→up`` / ``disable→down`` and written. A valid
        state-NS value is NEVER overwritten — state reflects intent
        correctly for Base-router interfaces.
        """
        if not isinstance(config_entry, dict):
            return

        # admin_status fallback — done before the binding switch so it
        # always runs regardless of whether the discriminator branches
        # return early. Only fills None; never overrides state-NS.
        if self.admin_status is None:
            admin_cfg = config_entry.get("admin-state")
            if isinstance(admin_cfg, str):
                normalised = admin_cfg.strip().lower()
                if normalised == "enable":
                    self.admin_status = "up"
                elif normalised == "disable":
                    self.admin_status = "down"
                # any other value (or absence) → leave None

        # ipv4_prefix_length fallback — the state-NS ``oper-address`` carries
        # no netmask, but the configure-NS ``ipv4/primary/prefix-length``
        # does. Fill it only if state-NS left it None (it always does on
        # Nokia). Runs for both Base and VPRN scope; never overrides an
        # existing value.
        if self.ipv4_prefix_length is None:
            ipv4_cfg = config_entry.get("ipv4")
            if isinstance(ipv4_cfg, dict):
                primary_cfg = ipv4_cfg.get("primary")
                if isinstance(primary_cfg, dict):
                    pfx = primary_cfg.get("prefix-length")
                    if pfx is not None:
                        try:
                            self.ipv4_prefix_length = int(pfx)
                        except (TypeError, ValueError):
                            pass

        # 1. spoke-sdp object presence wins.
        # ``<spoke-sdp>`` is a YANG list — xmltodict may surface it as a
        # single dict (the common 1-spoke case) or a list of dicts. Either
        # way the presence of the element is the discriminator; we read
        # ``sdp-bind-id`` from the first entry only (an L3-IF binding is
        # 1-to-1 in practice).
        spoke_raw = config_entry.get("spoke-sdp")
        spoke = (
            spoke_raw
            if isinstance(spoke_raw, dict)
            else (spoke_raw[0] if isinstance(spoke_raw, list) and spoke_raw else None)
        )
        if isinstance(spoke, dict):
            self.binding_type = "sdp_spoke"
            bind_id = spoke.get("sdp-bind-id")
            if bind_id is not None:
                self.sdp_bind_id = str(bind_id)
            return

        # 2. sap object presence next. Same list-vs-dict normalisation.
        sap_raw = config_entry.get("sap")
        sap = (
            sap_raw
            if isinstance(sap_raw, dict)
            else (sap_raw[0] if isinstance(sap_raw, list) and sap_raw else None)
        )
        if isinstance(sap, dict):
            self.binding_type = "sap_physical"
            sap_id = sap.get("sap-id")
            if isinstance(sap_id, str):
                try:
                    parts = split_sap_id(sap_id)
                except ValueError:
                    parts = None
                if parts is not None:
                    self.parent_port = parts.get("port") or None
                    vlan_str = parts.get("vlan")
                    if vlan_str and vlan_str.isdigit():
                        self.vlan = int(vlan_str)
            return

        # 3. loopback boolean leaf.
        loopback_leaf = config_entry.get("loopback")
        if isinstance(loopback_leaf, str) and loopback_leaf.strip().lower() == "true":
            self.binding_type = "loopback"
            return

        # 4. Base-router port-based binding. On /configure/router[Base]/
        #    interface the carrier is named by a single ``<port>`` leaf —
        #    a physical port (``"3/1/1"``), a LAG (``"lag-3"``) or a
        #    port:vlan sub-interface (``"2/1/8:671"``). VPRN interfaces use
        #    ``<sap>``/``<spoke-sdp>`` instead (handled above), so this
        #    branch only ever fires for Base IRBs. Fills ``parent_port`` /
        #    ``vlan`` and upgrades ``binding_type`` from the name-pattern
        #    ``unknown`` to ``physical_port`` / ``subinterface``.
        port_leaf = config_entry.get("port")
        if isinstance(port_leaf, str) and port_leaf.strip():
            port_val = port_leaf.strip()
            if ":" in port_val:
                parent, _, vlan_str = port_val.partition(":")
                self.parent_port = parent or None
                if vlan_str and vlan_str.isdigit():
                    self.vlan = int(vlan_str)
                self.binding_type = "subinterface"
            else:
                self.parent_port = port_val
                self.binding_type = "physical_port"
            return
        # No discriminator in configure either — keep whatever
        # _derive_binding_from_name() produced.


def parse_vprn_interface_config_response(response: dict) -> dict:
    """Parse a Nokia configure-NS interface dump into a binding-discriminator map.

    Consumes the response of :class:`NokiaVprnInterfaceConfigRPCRequest`
    (or :class:`NokiaBaseRouterInterfaceConfigRPCRequest`) and returns::

        {(vprn_name, interface_name): config_iface_dict}

    Each value is the raw configure-NS interface dict, ready to be fed to
    :meth:`NokiaL3Interface.apply_binding_from_config`. Pure-L3 interfaces
    with no ``<sap>``/``<spoke-sdp>``/``<loopback>`` discriminator are still
    included — the receiver decides what to do with them (typically leaves
    the name-pattern binding intact).

    ``vprn_name`` is the configure-NS list-key (``<service-name>`` under
    ``vprn``, or ``"Base"`` under ``router``). Keying by ``(vprn, iface)``
    rather than ``iface`` alone keeps it safe to merge multiple maps from
    different VRFs.
    """
    if not isinstance(response, dict):
        return {}
    container = NetworkInstance()
    cleaned = container.remove_namespaces(container._unwrap_data_node(response))
    configure_root = cleaned.get("configure") or cleaned
    out: dict = {}

    # /configure/service/vprn[...]/interface[...]
    vprn_root = (configure_root.get("service") or {}).get("vprn")
    for vp in _as_list(vprn_root):
        if not isinstance(vp, dict):
            continue
        vprn_name = vp.get("service-name")
        if not vprn_name:
            continue
        for iface in _as_list(vp.get("interface")):
            if not isinstance(iface, dict):
                continue
            iface_name = iface.get("interface-name")
            if not iface_name:
                continue
            out[(vprn_name, iface_name)] = iface

    # /configure/router[router-name=Base]/interface[...]
    router_root = configure_root.get("router")
    for router in _as_list(router_root):
        if not isinstance(router, dict):
            continue
        router_name = router.get("router-name") or "Base"
        for iface in _as_list(router.get("interface")):
            if not isinstance(iface, dict):
                continue
            iface_name = iface.get("interface-name")
            if not iface_name:
                continue
            out[(router_name, iface_name)] = iface

    return out


def parse_l3_interface_response(
    response: dict, vprn_name: str = "Base"
) -> List[NokiaL3Interface]:
    """Parse a NokiaL3InterfaceRPCRequest reply into L3Interface objects.

    Walks both ``state/router[router-name]/interface`` and
    ``state/service/vprn[service-name]/interface`` (mirrors
    :func:`parse_arp_response`), propagating the router-name / VPRN
    service-name into each interface's ``vprn_name`` field.

    Only interfaces that carry an IPv4 ``primary`` address are returned —
    a Nokia router lists many L1/L2-only ports under the same list, and
    "L3 interfaces" by definition have an IP.

    ``vprn_name`` is the fallback routing-instance name used when the YANG
    list-key is absent from the response (rare). Canonical default is
    ``"Base"`` for the global routing table.
    """
    if not isinstance(response, dict):
        return []
    container = NetworkInstance()
    cleaned = container.remove_namespaces(container._unwrap_data_node(response))
    if not isinstance(cleaned, dict):
        return []

    out: List[NokiaL3Interface] = []

    def harvest(parent: dict, scoped_vprn_name: str) -> None:
        for iface in _as_list(parent.get("interface")):
            if not isinstance(iface, dict):
                continue
            l3 = NokiaL3Interface(iface, vprn_name=scoped_vprn_name)
            if l3.ipv4_address:
                out.append(l3)

    state = cleaned.get("state") or {}
    for router in _as_list(state.get("router")):
        if isinstance(router, dict):
            harvest(router, router.get("router-name") or vprn_name)
    for vprn in _as_list((state.get("service") or {}).get("vprn")):
        if isinstance(vprn, dict):
            harvest(vprn, vprn.get("service-name") or vprn_name)

    return out
