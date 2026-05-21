"""
High-level facade for retrieving L2VPN services, FDB (MAC tables) and ARP
tables from network devices via NETCONF.

The facade hides vendor differences: callers say "give me VPLS named X" or
"give me ARP for VRF Y" and the client picks the right YANG path, executes
the NETCONF <get>, parses the response through the appropriate vendor adapter
and returns vendor-agnostic OpenConfig-aligned data objects.

Two filtering strategies are used together:

1. **Server-side** — list-key arguments (``service_name`` / ``vsi_name`` /
   ``mac`` / ``ip``) are embedded directly into the NETCONF subtree filter,
   so the device only ships back the matching entries. This is the cheap and
   correct path whenever a YANG list key matches the operator's intent.

2. **Client-side** — anything that isn't a YANG list key (``port`` /
   ``interface`` predicates, MAC wildcard / regex, multi-field combinations)
   is applied after the response is parsed, using :class:`RestNMSDataFilter`
   from the existing REST API filtering layer. We reuse rather than duplicate
   that filter implementation so the operator-facing semantics stay consistent
   between REST and NETCONF call sites.

Typical usage::

    from pynetcom import NetconfClient, ServicesClient

    nc = NetconfClient(host="10.0.0.1", port=830, user="u", password="p",
                       device_params={"name": "sros"})
    sc = ServicesClient(nc, vendor="nokia")

    for svc in sc.get_l2vpn_services():
        print(svc.name, svc.oper_status, len(svc.saps()), "SAPs")

    macs = sc.get_mac_table(service_name="VPLS-100", port="1/1/1")
    arps = sc.get_arp_table(vprn_name="VPRN-200")
"""

from __future__ import annotations

import logging
from typing import List, Literal, Optional

from pynetcom.netconf_client import NetconfClient
from pynetcom.utils.helpers.netconf.rpc_requests import (
    HuaweiArpRPCRequest,
    HuaweiL2vpnRPCRequest,
    HuaweiL3InterfaceRPCRequest,
    HuaweiL3vpnRPCRequest,
    HuaweiMacRPCRequest,
    HuaweiVeGroupRPCRequest,
    NokiaArpRPCRequest,
    NokiaBaseRouterInterfaceVplsRPCRequest,
    NokiaEpipeRPCRequest,
    NokiaFdbRPCRequest,
    NokiaL3InterfaceRPCRequest,
    NokiaSdpRPCRequest,
    NokiaServiceRPCRequest,
    NokiaVprnInterfaceVplsRPCRequest,
    NokiaVprnRPCRequest,
    normalize_mac,
)
from pynetcom.utils.helpers.netconf.rpc_data_containers.services import (
    Endpoint,
    L3Interface,
    MacEntry,
    MacSourceType,
    Neighbor,
    NetworkInstance,
)
from pynetcom.utils.helpers.netconf.rpc_data_containers import nokia_services as nokia
from pynetcom.utils.helpers.netconf.rpc_data_containers import huawei_services as huawei
from pynetcom.utils.helpers.rest_api.base import RestNMSDataFilter


Vendor = Literal["nokia", "huawei"]


class ServicesClient:
    """Vendor-agnostic L2VPN / FDB / ARP facade on top of a NetconfClient.

    Parameters
    ----------
    netconf_client:
        Already-connected :class:`NetconfClient`. The facade does not open or
        close the session — that is the caller's responsibility. This keeps the
        client composable: you can reuse the same NETCONF session for
        services, interfaces, transceivers, etc.
    vendor:
        ``"nokia"`` or ``"huawei"``. The vendor is an explicit parameter
        rather than auto-detection because both vendors share TCP/830 + SSH
        and probing the model to decide would add a round-trip and ambiguity.
    """

    def __init__(self, netconf_client: NetconfClient, vendor: Vendor):
        if vendor not in ("nokia", "huawei"):
            raise ValueError(f"Unsupported vendor: {vendor!r}. Use 'nokia' or 'huawei'.")
        self.nc = netconf_client
        self.vendor = vendor
        self.log = logging.getLogger("pynetcom.services_client")

    # -------------------- L2VPN services -------------------- #
    def get_l2vpn_services(
        self,
        name: Optional[str] = None,
        include_fdb: bool = False,
        enrich_remote_system: bool = True,
    ) -> List[NetworkInstance]:
        """Return all L2 services (VPLS multipoint + VPWS point-to-point).

        Parameters
        ----------
        name:
            Service name to narrow the request server-side. When None, every
            L2 service on the device is returned (both multipoint and p2p).
        include_fdb:
            Nokia-only optimisation — embed the FDB subtree inside the same
            VPLS request so MACs come back together with the service. Ignored
            on Huawei (MAC table is a separate module) and on Nokia EPIPE
            (EPIPE services don't carry an FDB).
        enrich_remote_system:
            Nokia-only. When True (default), after parsing the services the
            client issues one extra brief query against ``/state/service/sdp``
            to learn each SDP's far-end IP and populates
            :attr:`RemoteEndpoint.remote_system` on every PW. Set False to
            skip the extra round-trip when only local endpoints / counters
            matter. Has no effect when ``name`` is None (brief enumeration
            has no remote endpoints to enrich) or on Huawei (the L2VPN
            response there already carries far-end IPs).
        """
        if self.vendor == "nokia":
            return self._get_nokia_l2_services(
                name=name,
                include_fdb=include_fdb,
                enrich_remote_system=enrich_remote_system,
            )

        # huawei
        req = HuaweiL2vpnRPCRequest(name=name)
        resp = self.nc.get(req.get_request_filter())
        return list(huawei.parse_l2vpn_response(resp))

    def _get_nokia_l2_services(
        self,
        *,
        name: Optional[str],
        include_fdb: bool,
        enrich_remote_system: bool,
    ) -> List[NetworkInstance]:
        """Nokia branch of :meth:`get_l2vpn_services`.

        Strategy:
          - ``name is None`` → two brief queries (VPLS + EPIPE), each returning
            ~1–2 KB. Merge into one list. No PW enrichment (brief responses
            have no remote endpoints anyway).
          - ``name`` given → two full-subtree queries, one of which returns
            an empty list (the service is either a VPLS or an EPIPE, not
            both). Optionally enrich any REMOTE endpoints with far-end IP.

        The full-subtree path can be expensive on busy boxes — but the
        server-side narrowing by ``service-name`` (a YANG list key on both
        ``vpls`` and ``epipe``) keeps responses bounded by a single service.
        """
        brief = name is None
        services: List[NetworkInstance] = []

        # VPLS (multipoint)
        vpls_req = NokiaServiceRPCRequest(
            service_name=name,
            brief=brief,
            include_fdb=include_fdb and not brief,
        )
        services.extend(nokia.parse_vpls_response(self.nc.get(vpls_req.get_request_filter())))

        # EPIPE (point-to-point VPWS / VLL)
        epipe_req = NokiaEpipeRPCRequest(service_name=name, brief=brief)
        services.extend(nokia.parse_epipe_response(self.nc.get(epipe_req.get_request_filter())))

        # Optional PW enrichment — only when we have remote endpoints to fill.
        if (
            enrich_remote_system
            and not brief
            and any(svc.pseudowires() for svc in services)
        ):
            sdp_req = NokiaSdpRPCRequest(brief=True)
            sdp_map = nokia.parse_sdp_response(self.nc.get(sdp_req.get_request_filter()))
            far_end = {sid: info.get("far_end_ip") for sid, info in sdp_map.items()}
            for svc in services:
                nokia._attach_sdp_far_end(svc, far_end)

        return services

    def get_endpoints(self, service_name: str) -> List[Endpoint]:
        """Return SAP + PW endpoints for one service.

        Low-level, low-cost convenience wrapper: fetches the service WITHOUT
        any optional enrichment, then flattens connection_points → endpoints
        into a single list. Equivalent to
        ``get_l2vpn_services(name=service_name)[0].saps() + ...pseudowires()``
        but in one call. For SDP-enriched PWs use :meth:`get_pseudowires`.
        """
        services = self.get_l2vpn_services(
            name=service_name, enrich_remote_system=False
        )
        result: List[Endpoint] = []
        for svc in services:
            result.extend(svc.saps())
            result.extend(svc.pseudowires())
        return result

    def get_saps(self, service_name: str) -> List[Endpoint]:
        """Return only the LOCAL endpoints (SAPs / ACs) of one L2 service.

        Lighter than :meth:`get_endpoints` semantically — it filters to the
        local side only and bypasses SDP enrichment entirely (SAPs have no
        remote-system to fill). One :meth:`get_l2vpn_services` RPC.

        :param service_name: VPLS / VSI / EPIPE service name (YANG list key,
            server-side narrowing).
        :type service_name: str
        :return: Flat list of :class:`Endpoint` objects with
            ``type == EndpointType.LOCAL``.
        :rtype: List[Endpoint]
        """
        services = self.get_l2vpn_services(
            name=service_name, enrich_remote_system=False
        )
        result: List[Endpoint] = []
        for svc in services:
            result.extend(svc.saps())
        return result

    def get_pseudowires(
        self,
        service_name: str,
        include_standby: bool = False,
        enrich_remote_system: bool = True,
    ) -> List[Endpoint]:
        """Return only the REMOTE endpoints (PWs / SDP-bindings) of one L2 service.

        :param service_name: VPLS / VSI / VPWS service name.
        :type service_name: str
        :param include_standby: Huawei-only — when ``False`` (default), drop
            PW endpoints whose H-VPLS role is ``slave`` / ``secondary``
            (operationally blocked, no traffic). Set ``True`` to keep them
            (debugging a failover). No effect on Nokia (SR OS does not
            expose a per-spoke-sdp role at this layer; both members of a
            PW-redundancy pair surface uniformly).
        :type include_standby: bool
        :param enrich_remote_system: Nokia-only — when ``True`` (default),
            issue one extra brief query against ``/state/service/sdp`` to
            populate :attr:`RemoteEndpoint.remote_system` (the originating
            PE's loopback IP) on every PW. Set ``False`` to skip the round
            trip; ``remote_system`` will then stay ``None`` on Nokia PWs.
            Huawei publishes peer-IP inline on every PW record, so the
            flag is a no-op on that vendor.
        :type enrich_remote_system: bool
        :return: Flat list of :class:`Endpoint` objects with
            ``type == EndpointType.REMOTE``.
        :rtype: List[Endpoint]
        """
        services = self.get_l2vpn_services(
            name=service_name,
            enrich_remote_system=enrich_remote_system,
        )
        result: List[Endpoint] = []
        for svc in services:
            for pw in svc.pseudowires():
                if not include_standby and self.vendor == "huawei":
                    # PW-redundancy "slave" / "secondary" half is blocked
                    # in hardware — operator usually wants only the active
                    # side. The role is normalised on RemoteEndpoint.role
                    # by the Huawei parser. None = unknown role → keep.
                    role = (pw.remote.role if pw.remote else None) or ""
                    if role in ("slave", "secondary"):
                        continue
                result.append(pw)
        return result

    # -------------------- L3VPN / VRF services -------------------- #
    def get_l3vpn_services(self, name: Optional[str] = None) -> List[NetworkInstance]:
        """Return the L3VPN / VRF instances configured on the device.

        Parameters
        ----------
        name:
            VRF / service name to narrow the request server-side (YANG list
            key on both vendors). When None, every configured VRF is returned.

        Returns ``NetworkInstance`` objects with ``type = L3VPN``.

        Vendor notes
        ------------
        * Nokia — VPRN services from ``/state/service/vprn``. Each carries
          ``name``, ``oper_status`` and ``route_distinguisher`` (the
          operational RD).
        * Huawei — VPN instances from ``huawei-network-instance``. Synthetic /
          system instances (``_public_``, ``__LOCAL_OAM_VPN__``,
          ``__dcn_vpn__``) are filtered out. v1 returns ``name`` only;
          ``oper_status`` / RD are left None.

        The global routing instance (Nokia ``"Base"``, Huawei ``"_public_"``)
        is **not** a VRF and is not returned — only explicitly-configured
        L3VPNs.
        """
        if self.vendor == "nokia":
            req = NokiaVprnRPCRequest(service_name=name)
            resp = self.nc.get(req.get_request_filter())
            return list(nokia.parse_vprn_response(resp))

        # huawei
        req = HuaweiL3vpnRPCRequest(name=name)
        resp = self.nc.get(req.get_request_filter())
        return list(huawei.parse_l3vpn_response(resp))

    # -------------------- L3 interfaces -------------------- #
    def get_l3_interfaces(
        self,
        vprn_name: Optional[str] = None,
        enrich_l2_service: bool = False,
    ) -> List[L3Interface]:
        """Return the L3 (IP-bearing) interfaces, optionally scoped to a VRF.

        Parameters
        ----------
        vprn_name:
            Routing-instance name.

            * Nokia — ``None`` or ``"Base"`` → the global router's interfaces
              (``/state/router/Base/interface``); any other name → that
              VPRN's interfaces (``/state/service/vprn/<name>/interface``).
              Server-side scoped. Note: like :meth:`get_arp_table`, this does
              NOT auto-iterate every VPRN — pass a name to reach one.
            * Huawei — a single ``huawei-ifm`` query returns every interface;
              ``vprn_name`` then filters client-side on each interface's
              ``vrf-name`` (``"_public_"`` is the global instance, normalised
              to ``"Base"``).
        enrich_l2_service:
            When True, populate :attr:`L3Interface.l2_service` on each
            returned interface by resolving the L2-L3 binding:

              * Huawei — read ``huawei-fim-ifm`` ve-groups, build a parent
                pairing map L3→L2, and look up the L2 sub-interface in the
                VSI SAP list (two extra RPCs total).
              * Nokia — query ``/configure/service/vprn[<name>]/interface/vpls``
                for VPRNs, or ``/configure/router[router-name='Base']/interface/vpls``
                for the Base router (one extra RPC; both VRF-scoped VPRN R-VPLS
                and Base-router R-VPLS bindings are covered).

            Pure-L3 interfaces (no L2 binding) leave ``l2_service`` at
            ``None``.

        Only interfaces that actually carry an IPv4 address are returned —
        L1/L2-only ports are excluded.
        """
        if self.vendor == "nokia":
            if vprn_name and vprn_name not in ("Base", "base"):
                req = NokiaL3InterfaceRPCRequest(vprn_service_name=vprn_name)
                scoped_vprn_name = vprn_name
            else:
                req = NokiaL3InterfaceRPCRequest(router_name=vprn_name or "Base")
                scoped_vprn_name = vprn_name or "Base"
            resp = self.nc.get(req.get_request_filter())
            ifaces = list(nokia.parse_l3_interface_response(resp, vprn_name=scoped_vprn_name))
            # Enrichment covers both Base router R-VPLS and per-VPRN bindings —
            # the adapter picks the right configure-namespace path internally
            # based on the VRF name.
            if enrich_l2_service and scoped_vprn_name is not None:
                self._enrich_nokia_l2_service(ifaces, scoped_vprn_name)
            return ifaces

        # huawei — one query for all interfaces, filter by vrf-name client-side
        req = HuaweiL3InterfaceRPCRequest()
        resp = self.nc.get(req.get_request_filter())
        ifaces = list(huawei.parse_l3_interface_response(resp))
        if vprn_name is not None:
            ifaces = [i for i in ifaces if i.vprn_name == vprn_name]
        if enrich_l2_service:
            self._enrich_huawei_l2_service(ifaces, vprn_name=vprn_name)
        return ifaces

    # Class-level flag so we log the "huawei L2VPN dump is unfiltered" warning
    # at most once per ServicesClient instance — repeated warnings on every
    # get_l3_interfaces call would spam structured logs without adding info.
    _huawei_l2vpn_unfiltered_warned: bool = False

    def _enrich_huawei_l2_service(
        self,
        l3_interfaces: List[L3Interface],
        vprn_name: Optional[str] = None,
    ) -> None:
        """Populate ``l2_service`` on Huawei L3 sub-interfaces via VE-group join.

        Algorithm:
          1. Pull ve-groups → ``{l3_parent: l2_parent}`` map.
          2. Pull all VSIs (brief, no FDB) → ``{l2_subif_name: vsi_name}``
             reverse map from each LOCAL endpoint (SAP).
          3. For each L3Interface whose name is ``<parent>.<vlan>``: look up
             the paired L2 parent → form expected ``<l2_parent>.<vlan>`` →
             look up that sub-interface in the VSI SAP map → set
             ``l2_service``. Misses leave the field at None.

        Two RPCs total; cheap regardless of the number of L3 interfaces.

        ``vprn_name`` is accepted for API symmetry with the Nokia path
        (:meth:`_enrich_nokia_l2_service` requires a VRF to scope its
        configure-namespace query). On Huawei neither ``huawei-fim-ifm``
        (VE-groups, /ifm/global) nor ``huawei-l2vpn`` (/l2vpn/instances)
        accepts a ``vrf-name`` filter — they are global subtrees. We log
        a single warning so operators know the L2VPN dump can be heavy on
        big BSC-class boxes, then proceed unfiltered.
        """
        if not l3_interfaces:
            return
        if vprn_name and not self._huawei_l2vpn_unfiltered_warned:
            self.log.warning(
                "Huawei L2VPN dump is unfiltered: huawei-fim-ifm / "
                "huawei-l2vpn YANG models do not support vrf scoping; "
                "this RPC may be heavy on big BSC nodes. (vprn_name=%r)",
                vprn_name,
            )
            self._huawei_l2vpn_unfiltered_warned = True

        # Step 1 — ve-groups → l3_parent → l2_parent
        ve_resp = self.nc.get(HuaweiVeGroupRPCRequest().get_request_filter())
        ve_groups = huawei.parse_ve_group_response(ve_resp)
        l3_to_l2_parent = {g["l3_parent"]: g["l2_parent"]
                           for g in ve_groups
                           if g.get("l3_parent") and g.get("l2_parent")}
        if not l3_to_l2_parent:
            return  # no VE-groups configured — nothing to enrich

        # Step 2 — VSI SAP list → l2_subif_name → vsi_name
        vsi_resp = self.nc.get(HuaweiL2vpnRPCRequest().get_request_filter())
        vsis = huawei.parse_l2vpn_response(vsi_resp)
        sap_to_vsi: dict = {}
        for vsi in vsis:
            for cp in vsi.connection_points or []:
                for ep in cp.endpoints or []:
                    if ep.local and ep.local.subinterface:
                        sap_to_vsi[ep.local.subinterface] = vsi.name

        # Step 3 — resolve per L3 interface
        for iface in l3_interfaces:
            if not iface.name or "." not in iface.name:
                continue  # only sub-interfaces have a VE-group binding
            l3_parent, _, vlan_tag = iface.name.partition(".")
            l2_parent = l3_to_l2_parent.get(l3_parent)
            if not l2_parent:
                continue
            expected_l2_subif = f"{l2_parent}.{vlan_tag}"
            iface.l2_service = sap_to_vsi.get(expected_l2_subif)

    def _enrich_nokia_l2_service(
        self,
        l3_interfaces: List[L3Interface],
        vprn_name: str,
    ) -> None:
        """Populate ``l2_service`` on Nokia router/VPRN interfaces via vpls-binding.

        One ``get-config`` round-trip on the configure namespace, narrowed
        either to ``/router[router-name='Base']/interface/vpls`` (when
        ``vprn_name`` is ``"Base"`` / ``"base"``) or to
        ``/service/vprn[<name>]/interface/vpls`` (any other VRF name).
        Pure-L3 interfaces (no ``vpls`` element) are absent from the
        binding map and leave ``l2_service`` at ``None``.
        """
        if not l3_interfaces:
            return
        if vprn_name and vprn_name.lower() == "base":
            # Base router R-VPLS bindings live under /configure/router[...=Base].
            req = NokiaBaseRouterInterfaceVplsRPCRequest()
            resp = self.nc.get_config(
                source="running",
                filter_subtree=req.get_request_filter(),
            )
            binding_map = nokia.parse_base_router_interface_vpls_response(resp)
            # Adapter keys by ("Base", iface); L3Interface.vprn_name parser sets the
            # same string for Base-router IRBs.
            for iface in l3_interfaces:
                iface.l2_service = binding_map.get(("Base", iface.name))
            return
        # VPRN — configure namespace, scoped by VRF name.
        req = NokiaVprnInterfaceVplsRPCRequest(vprn_service_name=vprn_name)
        resp = self.nc.get_config(
            source="running",
            filter_subtree=req.get_request_filter(),
        )
        binding_map = nokia.parse_vprn_interface_vpls_response(resp)
        for iface in l3_interfaces:
            iface.l2_service = binding_map.get((vprn_name, iface.name))

    # -------------------- FDB / MAC table -------------------- #
    def get_mac_table(
        self,
        service_name: Optional[str] = None,
        mac: Optional[str] = None,
        port: Optional[str] = None,
        entry_type: Optional[str] = None,
        learned_via: Optional[str] = None,
        include_standby: bool = False,
        enrich_remote_system: bool = True,
    ) -> List[MacEntry]:
        """Return MAC table entries with optional filtering.

        Parameters
        ----------
        service_name, mac:
            Server-side filters (YANG list keys: VPLS/VSI name, MAC address).
            Combine for the cheapest possible query. ``mac`` may be supplied
            in any common separator form (``aabbccddeeff``, ``aa:bb:..``,
            ``aa-bb-..``, ``aabb.ccdd.eeff``) — the library normalises it to
            the vendor's expected canonical form before building the filter.
        port, entry_type, learned_via:
            Client-side filters applied after parsing.

            * ``port`` matches against :attr:`MacEntry.interface`
              (case-insensitive substring).
            * ``entry_type`` is one of ``"STATIC"`` / ``"DYNAMIC"`` —
              exact match.
            * ``learned_via`` is one of ``"sap"`` / ``"pw"`` — restricts to
              MAC entries learned over a local SAP (LOCAL endpoint) or a
              remote PW (REMOTE endpoint). Maps to
              :attr:`MacEntry.source_type`.
        include_standby:
            Huawei-only. When False (default), ``pw-role=slave`` FDB records
            are dropped during parsing — they represent the blocked half of
            an H-VPLS PW-redundancy pair and would otherwise mislead callers
            into thinking the MAC is reachable via a path that carries no
            traffic. Set True to include slave entries (useful for debugging
            a failover scenario). No effect on Nokia (the SR OS FDB natively
            surfaces only the active sdp-bind).
        enrich_remote_system:
            Nokia-only. When True (default), after parsing the FDB the client
            issues one extra brief query against ``/state/service/sdp`` and
            populates :attr:`MacEntry.remote_system` on every PW-learned
            entry by joining the parsed ``sdp-id`` (left half of the
            ``sdp-bind`` composite) with the SDP's
            ``oper-tunnel-far-end-inet-address``. Set False to skip the
            extra round-trip — ``remote_system`` will then remain ``None``
            on Nokia PW MACs. No effect on Huawei (peer-IP is already
            embedded in every FDB record there, so no follow-up RPC is
            needed). Same flag name as on :meth:`get_l2vpn_services` /
            :meth:`get_pseudowires` for consistency.

        Notes
        -----
        Asking for the entire FDB without any server-side narrowing on a large
        device can return tens of thousands of entries and several MB of XML —
        a warning is logged in that case so callers notice in dev/test.

        For PW-learned entries every returned :class:`MacEntry` carries
        ``remote_system`` (the originating PE's system / loopback IP, not
        its management IP) and ``pw_id`` (the vendor PW identifier). Use
        ``remote_system`` to skip the brute-force PE walk when locating a
        MAC's true origin in a meshed VPLS topology.
        """
        if service_name is None and mac is None:
            self.log.warning(
                "ServicesClient.get_mac_table called without service_name or "
                "mac — this will pull the entire FDB; consider narrowing on "
                "large devices."
            )

        if self.vendor == "nokia":
            req = NokiaFdbRPCRequest(service_name=service_name, mac_address=mac)
            resp = self.nc.get(req.get_request_filter())
            entries: List[MacEntry] = list(
                nokia.parse_fdb_response(resp, service_name=service_name)
            )
            if enrich_remote_system:
                self._enrich_nokia_pw_remote(entries)
        else:
            req = HuaweiMacRPCRequest(vsi_name=service_name, mac_address=mac)
            resp = self.nc.get(req.get_request_filter())
            entries = list(huawei.parse_mac_response(
                resp, include_standby=include_standby,
            ))

        return self._post_filter_macs(
            entries, port=port, entry_type=entry_type, learned_via=learned_via,
        )

    def _enrich_nokia_pw_remote(self, entries: List[MacEntry]) -> None:
        """Fill ``MacEntry.remote_system`` for Nokia PW-learned MACs in-place.

        Nokia's FDB record stores only the local PW handle (``sdp-bind`` =
        ``<sdp_id>:<vc_id>``); the remote peer's system-IP lives on the
        SDP object itself (``/state/service/sdp/oper-tunnel-far-end-inet-address``).
        We collect every distinct ``sdp_id`` referenced by the PW-learned
        rows, fire one brief SDP query, build the map, then walk the
        entries and stamp ``remote_system``.

        Issues at most one extra RPC; skipped entirely if no PW MACs exist
        or every PW row has a malformed ``sdp-bind`` (no ":" — pre-fix
        Nokia releases or unexpected leaf shapes).
        """
        sdp_ids: set = set()
        for e in entries:
            if e.source_type == MacSourceType.PW and e.interface and ":" in e.interface:
                try:
                    sdp_ids.add(int(e.interface.split(":", 1)[0]))
                except ValueError:
                    continue
        if not sdp_ids:
            return
        sdp_resp = self.nc.get(NokiaSdpRPCRequest(brief=True).get_request_filter())
        sdp_map = nokia.parse_sdp_response(sdp_resp)
        for e in entries:
            if e.source_type != MacSourceType.PW or not e.interface or ":" not in e.interface:
                continue
            try:
                sid = int(e.interface.split(":", 1)[0])
            except ValueError:
                continue
            e.remote_system = sdp_map.get(sid, {}).get("far_end_ip")

    def _post_filter_macs(
        self,
        entries: List[MacEntry],
        *,
        port: Optional[str],
        entry_type: Optional[str],
        learned_via: Optional[str],
    ) -> List[MacEntry]:
        """Apply client-side filters using the shared RestNMSDataFilter."""
        if not (port or entry_type or learned_via):
            return entries

        flt = RestNMSDataFilter()
        if entry_type:
            flt.include(entry_type=[entry_type.upper()])
        if learned_via is not None:
            v = learned_via.strip().lower()
            if v == "sap":
                want = MacSourceType.SAP
            elif v == "pw":
                want = MacSourceType.PW
            else:
                raise ValueError(
                    f"learned_via must be 'sap', 'pw', or None — got {learned_via!r}"
                )
            entries = [e for e in entries if e.source_type == want]

        if not port:
            return flt.apply(entries)

        # RestNMSDataFilter does exact case-insensitive matching; the operator
        # usually thinks "by port" as a substring match (e.g. "1/1/1" against
        # "1/1/1:100"). Implement that as a thin manual pass so we don't
        # invent new wildcard syntax on RestNMSDataFilter.
        port_l = port.lower()
        type_filtered = flt.apply(entries)
        return [e for e in type_filtered if e.interface and port_l in e.interface.lower()]

    # -------------------- ARP / Neighbor -------------------- #
    def get_arp_table(
        self,
        vprn_name: Optional[str] = None,
        ip: Optional[str] = None,
        mac: Optional[str] = None,
        interface: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> List[Neighbor]:
        """Return ARP / neighbor entries with optional filtering.

        Parameters
        ----------
        vprn_name:
            Routing-instance name. Canonical value ``"Base"`` for the global
            routing table on both vendors. On Nokia, ``"Base"`` selects the
            base router; any other name → a VPRN service name (L3VPN). On
            Huawei this is the ``vpn-instance`` name; pass ``None`` for the
            global routing table (Huawei does NOT need an explicit ``"Base"``
            value — its ``/arp/query-entries`` is a global subtree).
        ip:
            Server-side filter on the IPv4 list key.
        mac, interface, origin:
            Client-side filters. ``origin`` is one of ``"STATIC"`` /
            ``"DYNAMIC"`` / ``"OTHER"``.
        """
        if self.vendor == "nokia":
            if vprn_name and vprn_name not in ("Base", "base"):
                # vprn_name on Nokia is a VPRN service name when it's not the
                # base router. The RPC builder will route the request under
                # /service/vprn/<name>/arp accordingly.
                req = NokiaArpRPCRequest(vprn_service_name=vprn_name, ipv4_address=ip)
                scoped_vprn_name = vprn_name
            else:
                req = NokiaArpRPCRequest(router_name=vprn_name or "Base", ipv4_address=ip)
                scoped_vprn_name = vprn_name or "Base"
            resp = self.nc.get(req.get_request_filter())
            neighbors: List[Neighbor] = list(
                nokia.parse_arp_response(resp, vprn_name=scoped_vprn_name)
            )
        else:
            req = HuaweiArpRPCRequest(vpn_instance=vprn_name, ip_address=ip)
            resp = self.nc.get(req.get_request_filter())
            neighbors = list(huawei.parse_arp_response(resp))

        return self._post_filter_neighbors(
            neighbors, mac=mac, interface=interface, origin=origin
        )

    def _post_filter_neighbors(
        self,
        neighbors: List[Neighbor],
        *,
        mac: Optional[str],
        interface: Optional[str],
        origin: Optional[str],
    ) -> List[Neighbor]:
        if not (mac or interface or origin):
            return neighbors

        flt = RestNMSDataFilter()
        if origin:
            flt.include(origin=[origin.upper()])
        filtered = flt.apply(neighbors)

        if mac:
            # Normalise the user-supplied MAC to the colon form used by every
            # parser when storing :attr:`Neighbor.link_layer_address`. Lets
            # operators paste any common separator style (Cisco/Huawei dot,
            # hyphen, no-sep, etc.) and still get a substring hit.
            try:
                mac_l = normalize_mac(mac, "nokia")
            except ValueError:
                mac_l = mac.lower()
            filtered = [
                n for n in filtered
                if n.link_layer_address and mac_l in n.link_layer_address.lower()
            ]
        if interface:
            if_l = interface.lower()
            filtered = [
                n for n in filtered
                if n.interface and if_l in n.interface.lower()
            ]
        return filtered

    # -------------------- L2-L3 binding lookups -------------------- #
    def find_l2_service_by_ip(
        self,
        ip: str,
        vprn_name_candidates: Optional[List[str]] = None,
    ) -> Optional[dict]:
        """Find the L2 service that owns an IP, via the L2-L3 binding.

        Deterministic chain (no MAC-name guessing):
          1. ARP for the IP across one or more VRFs (auto-discover via
             :meth:`get_l3vpn_services` when ``vprn_name_candidates`` is
             None).
          2. Take the matched ARP entry's MAC + interface name.
          3. ``get_l3_interfaces(vprn_name=<arp.vprn_name>,
             enrich_l2_service=True)`` → look up the matching interface, read
             ``l2_service``.

        Returns a dict::

            {"ip": ...,
             "mac": ...,
             "vprn_name": ...,
             "l3_interface": ...,
             "l2_service": <vpls_name> | None}

        ``l2_service`` is ``None`` when:
          * the IP lives on a pure-L3 interface (no L2 binding), or
          * the platform lacks the binding leaves (Huawei without
            VE-groups configured). Nokia Base router is covered by the
            enrichment now (configure/router/Base/interface/vpls).

        Returns ``None`` if the IP is not in ARP on any candidate VRF.
        """
        candidates = vprn_name_candidates
        if candidates is None:
            # Auto-discover: Base + every configured L3VPN.
            if self.vendor == "nokia":
                candidates = ["Base"] + [v.name for v in self.get_l3vpn_services()]
            else:
                # Huawei: vprn_name=None means global routing table.
                candidates = [None] + [v.name for v in self.get_l3vpn_services()]

        arp_hit = None
        matched_vprn_name = None
        for vprn_name in candidates:
            arps = self.get_arp_table(vprn_name=vprn_name, ip=ip)
            if arps:
                arp_hit = arps[0]
                matched_vprn_name = vprn_name
                break
        if arp_hit is None:
            return None

        ifaces = self.get_l3_interfaces(vprn_name=matched_vprn_name, enrich_l2_service=True)
        l2_service = None
        for iface in ifaces:
            # Match by interface name; ARP-side may use the sub-if name
            # like Virtual-Ethernet0/2/3.2300, which is exactly what
            # L3Interface.name carries.
            if iface.name and iface.name == arp_hit.interface:
                l2_service = iface.l2_service
                break

        return {
            "ip": ip,
            "mac": arp_hit.link_layer_address,
            # Prefer the routing-instance name reported by the ARP entry
            # itself; fall back to whatever scope the caller used. On Huawei
            # with vprn_name=None the device returns ARP across all VPNs and
            # the per-row vprn_name is the authoritative answer.
            "vprn_name": arp_hit.vprn_name or matched_vprn_name,
            "l3_interface": arp_hit.interface,
            "l2_service": l2_service,
        }

    def find_l3_gateways_for_l2_service(
        self,
        l2_service_name: str,
    ) -> List[L3Interface]:
        """Find every L3 interface that routes a given L2 service.

        Returns a list of :class:`L3Interface` (possibly empty — pure-L2
        VPLSes are a valid case and produce ``[]`` rather than an error).

        Algorithm
        ---------
        Huawei:
          1. ``get_l2vpn_services(name=l2_service_name)`` → VSI with SAP list.
          2. Filter SAP IDs to ``Virtual-Ethernet*`` sub-interfaces.
          3. Pull ve-groups; build reverse map ``{l2_parent: l3_parent}``.
          4. For each VE-named SAP: extract parent + VLAN → form expected
             ``<l3_parent>.<vlan>`` → look it up in the unified L3 table.

        Nokia:
          1. For each VRF discovered via ``get_l3vpn_services()``: pull the
             VPRN-interface vpls-binding subtree.
          2. Collect every iface whose binding == ``l2_service_name``;
             pull its L3Interface state for the IP / oper-status.
        """
        if self.vendor == "huawei":
            return self._find_huawei_l3_gateways(l2_service_name)
        else:
            return self._find_nokia_l3_gateways(l2_service_name)

    def _find_huawei_l3_gateways(self, l2_service_name: str) -> List[L3Interface]:
        svcs = self.get_l2vpn_services(name=l2_service_name)
        if not svcs:
            return []
        vsi = svcs[0]
        # Collect Virtual-Ethernet SAP sub-interface names from the VSI.
        ve_saps: List[str] = []
        for cp in vsi.connection_points or []:
            for ep in cp.endpoints or []:
                if ep.local and ep.local.subinterface and \
                   ep.local.subinterface.startswith("Virtual-Ethernet"):
                    ve_saps.append(ep.local.subinterface)
        if not ve_saps:
            return []  # no VE-based gateway on this VSI

        # Reverse map: l2_parent → l3_parent.
        ve_resp = self.nc.get(HuaweiVeGroupRPCRequest().get_request_filter())
        l2_to_l3_parent: dict = {}
        for g in huawei.parse_ve_group_response(ve_resp):
            if g.get("l2_parent") and g.get("l3_parent"):
                l2_to_l3_parent[g["l2_parent"]] = g["l3_parent"]
        if not l2_to_l3_parent:
            return []

        # Expected L3 sub-interface names.
        expected_l3: set = set()
        for sap_name in ve_saps:
            l2_parent, _, vlan_tag = sap_name.partition(".")
            l3_parent = l2_to_l3_parent.get(l2_parent)
            if l3_parent and vlan_tag:
                expected_l3.add(f"{l3_parent}.{vlan_tag}")
        if not expected_l3:
            return []

        # Pull every L3 interface (one RPC, no field-select on vrf), filter
        # client-side by name.
        all_l3 = self.get_l3_interfaces()
        gateways = [i for i in all_l3 if i.name in expected_l3]
        # Tag l2_service inline so callers don't re-resolve.
        for i in gateways:
            i.l2_service = l2_service_name
        return gateways

    def _find_nokia_l3_gateways(self, l2_service_name: str) -> List[L3Interface]:
        # Discover all VPRNs once; for each VPRN, fetch its binding map.
        # Also include Base router R-VPLS bindings.
        vrfs = [v.name for v in self.get_l3vpn_services() if v.name]
        gateways: List[L3Interface] = []

        # Base router R-VPLS — check first; small subtree.
        base_req = NokiaBaseRouterInterfaceVplsRPCRequest()
        base_resp = self.nc.get_config(
            source="running",
            filter_subtree=base_req.get_request_filter(),
        )
        base_binding = nokia.parse_base_router_interface_vpls_response(base_resp)
        base_matching = [
            iface_name
            for (router_name, iface_name), vpls in base_binding.items()
            if vpls == l2_service_name and router_name == "Base"
        ]
        if base_matching:
            l3_list = self.get_l3_interfaces(vprn_name="Base")
            for iface in l3_list:
                if iface.name in base_matching:
                    iface.l2_service = l2_service_name
                    gateways.append(iface)

        # Per-VPRN bindings.
        for vprn_name in vrfs:
            req = NokiaVprnInterfaceVplsRPCRequest(vprn_service_name=vprn_name)
            resp = self.nc.get_config(
                source="running",
                filter_subtree=req.get_request_filter(),
            )
            binding = nokia.parse_vprn_interface_vpls_response(resp)
            matching_ifaces = [
                iface_name
                for (vr, iface_name), vpls in binding.items()
                if vpls == l2_service_name and vr == vprn_name
            ]
            if not matching_ifaces:
                continue
            # Pull L3Interface state for the VRF, restrict to matching names.
            l3_list = self.get_l3_interfaces(vprn_name=vprn_name)
            for iface in l3_list:
                if iface.name in matching_ifaces:
                    iface.l2_service = l2_service_name
                    gateways.append(iface)
        return gateways
