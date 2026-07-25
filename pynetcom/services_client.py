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

    macs = sc.get_mac_table(service_name="VPLS-100", ports=["1/1/1"])
    arps = sc.get_arp_table(vprn_names=["VPRN-200"])
"""

from __future__ import annotations

import logging
from typing import List, Literal, Optional

from pynetcom.netconf_client import NetconfClient
from pynetcom.utils.helpers.netconf.rpc_requests import (
    HuaweiArpRPCRequest,
    HuaweiBgpVpnRoutesRPCRequest,
    HuaweiInterfaceAdminOperStateRPCRequest,
    HuaweiL2vpnByMemberInterfaceRPCRequest,
    HuaweiL2vpnRPCRequest,
    HuaweiL3InterfaceRPCRequest,
    HuaweiL3vpnRPCRequest,
    HuaweiMacRPCRequest,
    HuaweiVeGroupRPCRequest,
    NokiaArpRPCRequest,
    NokiaBaseRouterInterfaceConfigRPCRequest,
    NokiaEpipeRPCRequest,
    NokiaFdbRPCRequest,
    NokiaL3InterfaceRPCRequest,
    NokiaSdpRPCRequest,
    NokiaServiceRPCRequest,
    NokiaServiceSapAdminStateRPCRequest,
    NokiaServiceVplsSpokeSdpConfigRPCRequest,
    NokiaVprnInterfaceConfigRPCRequest,
    NokiaVprnInterfaceVplsRPCRequest,
    NokiaVprnRPCRequest,
    normalize_mac,
)
from pynetcom.utils.helpers.netconf.rpc_data_containers.services import (
    BgpRoute,
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
        enrich_admin_state: bool = False,
        enrich_config: bool = False,
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
            to learn each SDP's far-end IP **and active LSP type** and
            populates :attr:`RemoteEndpoint.remote_system` +
            :attr:`RemoteEndpoint.signaling_type` on every PW. Set False to
            skip the extra round-trip when only local endpoints / counters
            matter. Has no effect when ``name`` is None (brief enumeration
            has no remote endpoints to enrich) or on Huawei (the L2VPN
            response there already carries peer-IP and signal-type inline).
        enrich_config:
            Nokia-only. When True, one extra ``<get-config>`` round-trip
            against ``/configure/service/vpls/spoke-sdp`` populates
            :attr:`RemoteEndpoint.encapsulation_type` (from
            ``spoke-sdp/vc-type``) and :attr:`RemoteEndpoint.redundancy_role`
            (from ``spoke-sdp/endpoint/precedence``) on every PW. Default
            False — these leaves are in the configure namespace, not the
            state namespace. No-op on Huawei (both fields ship free in the
            single L2VPN response).
        enrich_admin_state:
            Opt-in. When True, populate :attr:`LocalEndpoint.admin_status`
            on every LOCAL endpoint (SAP / AC) with the canonical
            ``"enabled"`` / ``"disabled"`` form via one extra vendor-specific
            RPC:

              * Nokia — ``<get-config source="running"
                with-defaults="report-all">`` against
                ``/configure/service/{vpls,epipe}/sap/admin-state`` (see
                :class:`NokiaServiceSapAdminStateRPCRequest`). The state
                tree does not expose admin intent at all.
              * Huawei — ``<get>`` against ``/ifm/interfaces`` (see
                :class:`HuaweiInterfaceAdminOperStateRPCRequest`).
                Additionally, ``LocalEndpoint.oper_status`` is **overwritten**
                with the authoritative ``ifm/dynamic/oper-status`` (the
                ``huawei-l2vpn`` AC subtree carries a coarse aggregate that
                can lag behind the per-interface state).

            Default is False to preserve the cheap single-RPC behaviour.
        """
        if self.vendor == "nokia":
            return self._get_nokia_l2_services(
                name=name,
                include_fdb=include_fdb,
                enrich_remote_system=enrich_remote_system,
                enrich_admin_state=enrich_admin_state,
                enrich_config=enrich_config,
            )

        # huawei — enrich_config is a Nokia-only refinement (both
        # encapsulation_type and redundancy_role are free on Huawei via the
        # single L2VPN response); silently accepted for API symmetry.
        req = HuaweiL2vpnRPCRequest(name=name)
        resp = self.nc.get(req.get_request_filter())
        services = list(huawei.parse_l2vpn_response(resp))
        if enrich_admin_state and services:
            self._enrich_huawei_endpoint_state(services)
        return services

    def _get_nokia_l2_services(
        self,
        *,
        name: Optional[str],
        include_fdb: bool,
        enrich_remote_system: bool,
        enrich_admin_state: bool = False,
        enrich_config: bool = False,
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

        When ``enrich_admin_state`` is True, an extra
        ``<get-config source="running" with-defaults="report-all">`` query
        against the configure namespace populates
        :attr:`LocalEndpoint.admin_status` on every SAP.
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
        # Pass the FULL sdp_map (not a far-end-only projection) so the
        # adapter also stamps :attr:`RemoteEndpoint.signaling_type` from
        # the SDP's ``active-lsp-type`` (free: same RPC, same parse).
        if (
            enrich_remote_system
            and not brief
            and any(svc.pseudowires() for svc in services)
        ):
            sdp_req = NokiaSdpRPCRequest(brief=True)
            sdp_map = nokia.parse_sdp_response(self.nc.get(sdp_req.get_request_filter()))
            for svc in services:
                nokia._attach_sdp_far_end(svc, sdp_map)

        # Optional configure-NS enrichment — populate encapsulation_type +
        # redundancy_role on REMOTE endpoints via one extra <get-config>.
        # Same predicate as remote_system enrichment: skip when nothing to
        # stamp (brief-mode, or no PWs in scope).
        if (
            enrich_config
            and not brief
            and any(svc.pseudowires() for svc in services)
        ):
            self._enrich_nokia_spoke_sdp_config(services, name=name)

        # Optional admin-state enrichment — extra get-config to populate
        # LocalEndpoint.admin_status. Skip when there are no LOCAL endpoints
        # to stamp (brief-mode responses carry no SAPs).
        if enrich_admin_state and any(svc.saps() for svc in services):
            self._enrich_nokia_sap_admin_state(services, name=name)

        return services

    def _enrich_nokia_spoke_sdp_config(
        self,
        services: List[NetworkInstance],
        name: Optional[str] = None,
    ) -> None:
        """Stamp ``RemoteEndpoint.encapsulation_type`` + ``redundancy_role``
        on Nokia PWs in-place.

        One ``<get-config source="running" with-defaults="report-all">``
        round-trip against ``/configure/service/vpls/spoke-sdp``. The parsed
        map is keyed by ``(service_name, sdp_bind_id)`` and matched against
        each PW's ``(svc.name, "<sdp_id>:<vc_id>")`` composite.

        ``name`` is passed through so the get-config narrows to a single
        VPLS when the caller asked for one service.
        """
        req = NokiaServiceVplsSpokeSdpConfigRPCRequest(service_name=name)
        resp = self.nc.get_config(
            source="running",
            filter_subtree=req.get_request_filter(),
            with_defaults="report-all",
        )
        cfg_map = nokia.parse_spoke_sdp_config_response(resp)
        if not cfg_map:
            return
        for svc in services:
            nokia._attach_spoke_sdp_config(svc, cfg_map)

    def _enrich_nokia_sap_admin_state(
        self,
        services: List[NetworkInstance],
        name: Optional[str] = None,
    ) -> None:
        """Stamp ``LocalEndpoint.admin_status`` on Nokia SAPs in-place.

        One ``<get-config source="running" with-defaults="report-all">``
        round-trip against ``/configure/service/{vpls,epipe}/sap/admin-state``.
        Each ``(service_name, sap_id)`` pair from the admin-state map is
        matched against ``(svc.name, endpoint.local.subinterface)`` —
        ``LocalEndpoint.subinterface`` carries the Nokia SAP id verbatim
        (e.g. ``"1/1/11:100"``).

        ``name`` is passed through so the get-config narrows to a single
        VPLS / EPIPE when the caller asked for one service.
        """
        req = NokiaServiceSapAdminStateRPCRequest(service_name=name)
        resp = self.nc.get_config(
            source="running",
            filter_subtree=req.get_request_filter(),
            with_defaults="report-all",
        )
        admin_map = nokia.parse_sap_admin_state_response(resp)
        if not admin_map:
            return
        for svc in services:
            for cp in svc.connection_points or []:
                for ep in cp.endpoints or []:
                    if ep.local is None or not ep.local.subinterface:
                        continue
                    key = (svc.name, ep.local.subinterface)
                    val = admin_map.get(key)
                    if val is not None:
                        ep.local.admin_status = val

    def _enrich_huawei_endpoint_state(
        self,
        services: List[NetworkInstance],
    ) -> None:
        """Stamp Huawei AC ``admin_status`` and overwrite ``oper_status`` in-place.

        One ``<get>`` round-trip against ``/ifm/interfaces``. The interface
        name on each :class:`LocalEndpoint` (``subinterface`` field) is the
        join key against the ifm map. Both leaves are canonicalised by
        :func:`huawei_services.parse_interface_status_response`:

          * ``admin_status``: ``"up"`` → ``"enabled"``, ``"down"`` →
            ``"disabled"`` (matches Nokia / OpenConfig admin convention).
          * ``oper_status``: kept as ``"up"`` / ``"down"`` (OpenConfig oper
            canonical form). **Overwrites** the prior value from the L2VPN
            AC subtree — ifm is authoritative for runtime status.

        Interfaces missing from the ifm response (rare — e.g. management
        interfaces filtered by NETCONF ACLs) leave the endpoint untouched,
        so ``admin_status`` stays ``None`` and the operator can spot it.
        """
        req = HuaweiInterfaceAdminOperStateRPCRequest()
        resp = self.nc.get(req.get_request_filter())
        status_map = huawei.parse_interface_status_response(resp)
        if not status_map:
            return
        for svc in services:
            for cp in svc.connection_points or []:
                for ep in cp.endpoints or []:
                    if ep.local is None or not ep.local.subinterface:
                        continue
                    info = status_map.get(ep.local.subinterface)
                    if not info:
                        continue
                    if info.get("admin_status") is not None:
                        ep.local.admin_status = info["admin_status"]
                    if info.get("oper_status") is not None:
                        ep.local.oper_status = info["oper_status"]

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

    def get_saps(
        self,
        service_name: str,
        enrich_admin_state: bool = False,
    ) -> List[Endpoint]:
        """Return only the LOCAL endpoints (SAPs / ACs) of one L2 service.

        Lighter than :meth:`get_endpoints` semantically — it filters to the
        local side only and bypasses SDP enrichment entirely (SAPs have no
        remote-system to fill).

        :param service_name: VPLS / VSI / EPIPE service name (YANG list key,
            server-side narrowing).
        :type service_name: str
        :param enrich_admin_state: Opt-in admin / oper state enrichment.
            Pass through to :meth:`get_l2vpn_services`. When True, each
            returned endpoint's ``local.admin_status`` is filled with the
            canonical ``"enabled"`` / ``"disabled"`` string (one extra RPC),
            and on Huawei ``local.oper_status`` is overwritten from
            ``huawei-ifm`` (authoritative). Default False keeps the
            single-RPC fast path.
        :type enrich_admin_state: bool
        :return: Flat list of :class:`Endpoint` objects with
            ``type == EndpointType.LOCAL``.
        :rtype: List[Endpoint]
        """
        services = self.get_l2vpn_services(
            name=service_name,
            enrich_remote_system=False,
            enrich_admin_state=enrich_admin_state,
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
        enrich_config: bool = False,
    ) -> List[Endpoint]:
        """Return only the REMOTE endpoints (PWs / SDP-bindings) of one L2 service.

        :param service_name: VPLS / VSI / VPWS service name.
        :type service_name: str
        :param include_standby: Huawei-only — when ``False`` (default), drop
            PW endpoints whose H-VPLS redundancy state is ``standby``
            (operationally up but not carrying traffic). Set ``True`` to
            keep them (debugging a failover). No effect on Nokia (Nokia
            does not surface a per-spoke-sdp redundancy state at this layer;
            both members of a PW-redundancy pair surface uniformly).
        :type include_standby: bool
        :param enrich_remote_system: Nokia-only — when ``True`` (default),
            issue one extra brief query against ``/state/service/sdp`` to
            populate :attr:`RemoteEndpoint.remote_system` (the originating
            PE's loopback IP) and :attr:`RemoteEndpoint.signaling_type`
            (``rsvp`` / ``ldp`` / ``bgp``) on every PW. Set ``False`` to
            skip the round trip; both fields will then stay ``None`` on
            Nokia PWs. Huawei publishes both inline, so the flag is a no-op
            on that vendor.
        :type enrich_remote_system: bool
        :param enrich_config: Nokia-only — when ``True``, one extra
            ``<get-config>`` RPC populates
            :attr:`RemoteEndpoint.encapsulation_type` and
            :attr:`RemoteEndpoint.redundancy_role` from the configure
            namespace. Default ``False``. No-op on Huawei (those fields
            ship free in the single L2VPN response).
        :type enrich_config: bool
        :return: Flat list of :class:`Endpoint` objects with
            ``type == EndpointType.REMOTE``.
        :rtype: List[Endpoint]
        """
        services = self.get_l2vpn_services(
            name=service_name,
            enrich_remote_system=enrich_remote_system,
            enrich_config=enrich_config,
        )
        result: List[Endpoint] = []
        for svc in services:
            for pw in svc.pseudowires():
                if not include_standby and self.vendor == "huawei":
                    # PW-redundancy "standby" half is operationally up but
                    # carries no traffic — operator usually wants only the
                    # active side. ``redundancy_state`` is the vendor-agnostic
                    # discriminator (Huawei parser derives it from raw
                    # ``pw-state=backup``). None = unknown → keep.
                    state = (
                        pw.remote.redundancy_state if pw.remote else None
                    ) or ""
                    if state == "standby":
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
        enrich_config: bool = False,
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

        enrich_config:
            Nokia-only refinement (no-op on Huawei — its binding is fully
            derivable from the interface name for free). When True, one
            extra ``<get-config>`` round-trip pulls
            ``/configure/service/vprn[...]/interface`` (or the Base-router
            equivalent) and refines :attr:`L3Interface.binding_type`:

              * ``<spoke-sdp>`` object present → ``sdp_spoke`` (with
                ``sdp_bind_id`` populated).
              * ``<sap>`` object present → ``sap_physical`` (with
                ``parent_port`` + ``vlan`` split from ``sap-id``).
              * ``<loopback>true</loopback>`` → ``loopback``.

            Additionally fills :attr:`L3Interface.admin_status` as a fallback
            when the state-NS did not surface it (known case: Nokia VPRN-bound
            interfaces — the state subtree for ``/state/service/vprn/.../interface``
            omits ``<admin-state>``). The configure-NS ``<admin-state>`` leaf
            is mapped ``enable→up`` / ``disable→down``; if state-NS already
            provided a value it is NOT overwritten.

            Without ``enrich_config`` Nokia ``sdp_spoke`` / ``sap_physical``
            interfaces fall back to ``binding_type='unknown'`` (the
            operator-chosen name carries no signal — e.g. ``test_sap``).

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
            # ``scoped_vprn_name`` is always a concrete string here
            # (``vprn_name or "Base"``), so both enrichments run for the Base
            # router as well as for a named VPRN.
            # L2-service (R-VPLS) enrichment covers per-VPRN bindings; the
            # Base router has no R-VPLS binding on our fleet (plan E1) and the
            # adapter leaves ``l2_service=None`` there without an RPC.
            if enrich_l2_service:
                self._enrich_nokia_l2_service(ifaces, scoped_vprn_name)
            # Configure-NS enrichment (one extra <get-config> RPC). Fills
            # ``parent_port`` / ``vlan`` (Base port-based binding), refines
            # ``binding_type`` for ``sdp_spoke`` / ``sap_physical`` /
            # ``physical_port`` / ``subinterface`` / ``loopback`` cases the
            # name pattern cannot detect, and fills ``admin_status`` +
            # ``ipv4_prefix_length`` which the state-NS omits. Runs for both
            # Base and named-VPRN scope.
            if enrich_config:
                self._enrich_nokia_config(ifaces, scoped_vprn_name)
            return ifaces

        # huawei — one query for all interfaces, filter by vrf-name client-side
        req = HuaweiL3InterfaceRPCRequest()
        resp = self.nc.get(req.get_request_filter())
        ifaces = list(huawei.parse_l3_interface_response(resp))
        if vprn_name is not None:
            ifaces = [i for i in ifaces if i.vprn_name == vprn_name]
        if enrich_l2_service:
            self._enrich_huawei_l2_service(ifaces, vprn_name=vprn_name)
        # ``enrich_config`` is a Nokia-only refinement — Huawei populates
        # binding_type/parent_port/vlan free at parse time via the
        # interface-name parser, and admin_status arrives from state-NS
        # directly. Quietly accept it on Huawei for API symmetry with the
        # cross-vendor callers.
        return ifaces

    def _enrich_huawei_l2_service(
        self,
        l3_interfaces: List[L3Interface],
        vprn_name: Optional[str] = None,
    ) -> None:
        """Populate ``l2_service`` on Huawei L3 sub-interfaces via VE-group join.

        Algorithm:
          1. Pull ve-groups → ``{l3_parent: l2_parent}`` map.
          2. For each L3 sub-interface ``<l3_parent>.<vlan>`` form the
             expected L2 AC name ``<l2_parent>.<vlan>``; collect the unique
             set of L2 AC names actually needed.
          3. For each unique L2 AC name run ONE narrow RPC built by
             :class:`HuaweiL2vpnByMemberInterfaceRPCRequest` — server-side
             content-match by ``interface-name`` returns just the owning
             VSI (and only the matching ``<ac>`` inside it), no PWs / FDB /
             statistics. Build ``{l2_subif_name: vsi_name}`` from the
             responses and apply to every interface that matches.

        Total RPCs: ``1 (ve-groups) + N`` where N is the number of UNIQUE
        L2 ACs the supplied L3 interfaces need to resolve (typically the
        same as the number of L3 sub-interfaces in the supplied list).
        On VRP V8 NE-series each narrow RPC is ~400 ms / ~900 B vs
        ~8.7 s / ~336 KB for an unfiltered ``HuaweiL2vpnRPCRequest`` dump
        (~22x speedup observed on a 32-VSI BSC-class box; see
        ``examples/xml/Huawei/services/get_l2vpn_by_member_interface(response).xml``).

        ``vprn_name`` is accepted for API symmetry with the Nokia path
        (:meth:`_enrich_nokia_l2_service` requires a VRF to scope its
        configure-namespace query). On Huawei neither ``huawei-fim-ifm``
        (VE-groups, /ifm/global) nor ``huawei-l2vpn`` (/l2vpn/instances)
        accepts a ``vrf-name`` filter — they are global subtrees. The
        per-interface narrow RPC obsoletes the previous "heavy unfiltered
        L2VPN dump" warning, which is no longer emitted.
        """
        if not l3_interfaces:
            return

        # Step 1 — ve-groups → l3_parent → l2_parent
        ve_resp = self.nc.get(HuaweiVeGroupRPCRequest().get_request_filter())
        ve_groups = huawei.parse_ve_group_response(ve_resp)
        l3_to_l2_parent = {g["l3_parent"]: g["l2_parent"]
                           for g in ve_groups
                           if g.get("l3_parent") and g.get("l2_parent")}
        if not l3_to_l2_parent:
            return  # no VE-groups configured — nothing to enrich

        # Step 2 — figure out which L2 AC names each L3 sub-IF needs.
        # iface_to_l2_ac: list of (iface, l2_ac) — preserve association so we
        # can map results back without re-deriving.
        iface_to_l2_ac: list = []
        needed_l2_acs: set = set()
        for iface in l3_interfaces:
            if not iface.name or "." not in iface.name:
                continue  # only sub-interfaces have a VE-group binding
            l3_parent, _, vlan_tag = iface.name.partition(".")
            l2_parent = l3_to_l2_parent.get(l3_parent)
            if not l2_parent:
                continue
            expected_l2_subif = f"{l2_parent}.{vlan_tag}"
            iface_to_l2_ac.append((iface, expected_l2_subif))
            needed_l2_acs.add(expected_l2_subif)

        if not needed_l2_acs:
            return  # no L3 sub-IF maps to a VE-group — nothing to query

        # Step 3 — one narrow per-AC RPC per unique L2 AC name.
        # Each RPC returns at most one <instance> (the owning VSI) with
        # only the matching <ac> inside — no PWs / FDB / statistics.
        l2_ac_to_vsi: dict = {}
        for l2_ac in needed_l2_acs:
            req = HuaweiL2vpnByMemberInterfaceRPCRequest(member_interface=l2_ac)
            resp = self.nc.get(req.get_request_filter())
            vsis = huawei.parse_l2vpn_response(resp)
            # Expected: 0 or 1 entries. Defensive: take the first match.
            for vsi in vsis:
                if vsi.name:
                    l2_ac_to_vsi[l2_ac] = vsi.name
                    break

        # Step 4 — apply per-interface
        for iface, l2_ac in iface_to_l2_ac:
            iface.l2_service = l2_ac_to_vsi.get(l2_ac)

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
            # Base-router R-VPLS does not exist on our fleet and the
            # ``<vpls>`` leaf under /configure/router[Base]/interface is
            # rejected by SR OS 23.10 (Unknown element) — see plan E1. No
            # RPC is issued; ``l2_service`` stays None for Base IRBs.
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

    def _enrich_nokia_config(
        self,
        l3_interfaces: List[L3Interface],
        vprn_name: str,
    ) -> None:
        """Refine ``binding_type`` and fill admin_status / prefix on Nokia L3-IFs.

        One ``<get-config>`` round-trip with ``with_defaults="report-all"``
        (so that default-valued ``<loopback>false</loopback>`` does not
        silently drop), narrowed either to the Base router or to a single
        VPRN. The parsed map is keyed by ``(vprn_name, iface_name)``; each
        interface's ``apply_binding_from_config`` upgrades ``binding_type``
        from the name-pattern fallback to the precise discriminator whenever
        the configure payload carries it:

          * ``sdp_spoke`` — interface bound over a spoke-SDP.
          * ``sap_physical`` — interface with an explicit ``<sap>``.
          * ``loopback`` — ``<loopback>true</loopback>``.
          * Base-router port-based binding — the single ``<port>`` leaf names
            the carrier: ``"3/1/1"`` / ``"lag-3"`` → ``physical_port``
            (``parent_port``, lag included), ``"2/1/8:671"`` →
            ``subinterface`` (``parent_port`` + ``vlan``).

        It also fills, as fallbacks when the state-NS omitted them:

          * ``admin_status`` — Nokia VPRN interfaces confirmed not to carry
            ``<admin-state>`` under ``/state/service/vprn/.../interface``.
          * ``ipv4_prefix_length`` — derived from the configure ``<address>``
            prefix (both Base and VPRN), since state ``oper-address`` gives
            the bare host address without a mask.

        Pure-L3 interfaces with no ``<port>``/``<sap>``/``<spoke-sdp>``/
        loopback leaf keep whatever the name-pattern produced (typically
        ``unknown``).
        """
        if not l3_interfaces:
            return
        if vprn_name and vprn_name.lower() == "base":
            req = NokiaBaseRouterInterfaceConfigRPCRequest()
            keyed_name = "Base"
        else:
            req = NokiaVprnInterfaceConfigRPCRequest(vprn_service_name=vprn_name)
            keyed_name = vprn_name
        resp = self.nc.get_config(
            source="running",
            filter_subtree=req.get_request_filter(),
            with_defaults="report-all",
        )
        binding_map = nokia.parse_vprn_interface_config_response(resp)
        for iface in l3_interfaces:
            cfg = binding_map.get((keyed_name, iface.name))
            if cfg is None:
                continue
            # Only NokiaL3Interface instances have apply_binding_from_config —
            # defensive guard in case a future caller passes a plain
            # L3Interface object (parser always returns NokiaL3Interface).
            apply = getattr(iface, "apply_binding_from_config", None)
            if callable(apply):
                apply(cfg)

    # -------------------- FDB / MAC table -------------------- #
    def get_mac_table(
        self,
        service_name: Optional[str] = None,
        macs: Optional[List[str]] = None,
        ports: Optional[List[str]] = None,
        entry_type: Optional[str] = None,
        learned_via: Optional[str] = None,
        include_standby: bool = False,
        enrich_remote_system: bool = True,
    ) -> List[MacEntry]:
        """Return MAC table entries with optional batch filtering.

        Parameters
        ----------
        service_name:
            Server-side filter — single VPLS / VSI name (YANG list key on
            both vendors). Multi-service fan-out is a higher-level concern
            and not handled here.
        macs:
            Server-side batch filter — list of MAC addresses. Each MAC is
            embedded into the request as a separate list-key sibling, so
            the device returns the union "any of these MACs" in one
            round-trip (verified live 26-28 May 2026, ground-truth XML in
            ``examples/xml/{Nokia 7250,Huawei}/services/get_fdb_*``).
            Accepts any common separator style
            (``aabbccddeeff`` / ``aa:bb:..`` / ``aa-bb-..`` /
            ``aabb.ccdd.eeff``); each entry is normalised to the vendor's
            canonical form before the request is built. Pass ``None`` or
            ``[]`` for a full FDB dump of the scoped service.
        ports, entry_type, learned_via:
            Client-side filters applied after parsing.

            * ``ports`` — list of substrings, OR-combined. An entry matches
              if any substring appears (case-insensitive) in
              :attr:`MacEntry.interface`. Useful e.g. for
              ``["1/1/1", "1/1/2"]`` against ``"1/1/1:100"``.
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
        if service_name is None and not macs:
            self.log.warning(
                "ServicesClient.get_mac_table called without service_name or "
                "macs — this will pull the entire FDB; consider narrowing on "
                "large devices."
            )

        if self.vendor == "nokia":
            req = NokiaFdbRPCRequest(
                service_name=service_name, mac_addresses=macs,
            )
            resp = self.nc.get(req.get_request_filter())
            entries: List[MacEntry] = list(
                nokia.parse_fdb_response(resp, service_name=service_name)
            )
            if enrich_remote_system:
                self._enrich_nokia_pw_remote(entries)
        else:
            req = HuaweiMacRPCRequest(
                vsi_name=service_name, mac_addresses=macs, include_static=False,
            )
            resp = self.nc.get(req.get_request_filter())
            entries = list(huawei.parse_mac_response(
                resp, include_standby=include_standby,
            ))

        return self._post_filter_macs(
            entries, ports=ports, entry_type=entry_type, learned_via=learned_via,
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
        ports: Optional[List[str]],
        entry_type: Optional[str],
        learned_via: Optional[str],
    ) -> List[MacEntry]:
        """Apply client-side filters using the shared RestNMSDataFilter.

        ``ports`` is a list of substrings, OR-combined: an entry matches
        when any of the substrings appears (case-insensitive) in
        :attr:`MacEntry.interface`. ``entry_type`` and ``learned_via``
        stay single-value exact-match filters.
        """
        if not (ports or entry_type or learned_via):
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

        if not ports:
            return flt.apply(entries)

        # RestNMSDataFilter does exact case-insensitive matching; the operator
        # usually thinks "by port" as a substring match (e.g. "1/1/1" against
        # "1/1/1:100"). With a list of ports we OR-combine substring matches.
        ports_lower = [p.lower() for p in ports if p]
        type_filtered = flt.apply(entries)
        if not ports_lower:
            return type_filtered
        return [
            e for e in type_filtered
            if e.interface
            and any(p_l in e.interface.lower() for p_l in ports_lower)
        ]

    # -------------------- ARP / Neighbor -------------------- #
    def get_arp_table(
        self,
        vprn_names: Optional[List[str]] = None,
        ips: Optional[List[str]] = None,
        macs: Optional[List[str]] = None,
        interface: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> List[Neighbor]:
        """Return ARP / neighbor entries with optional batch filtering.

        Parameters
        ----------
        vprn_names:
            Routing-instance names. Canonical value ``"Base"`` for the global
            routing table on both vendors. On Nokia, ``"Base"`` selects the
            base router; any other name → a VPRN service name (L3VPN). On
            Huawei these are ``vpn-instance`` names; pass ``None`` / ``[]``
            for the global routing table (Huawei does NOT need an explicit
            ``"Base"`` value — its ``/arp/query-entries`` is a global
            subtree).

            Mixing ``"Base"`` with named VPRNs on Nokia in a single call is
            NOT supported — the YANG split between ``/state/router`` and
            ``/state/service/vprn`` is hard. Callers wanting both must
            either invoke twice or pass only named VPRNs (then Base entries
            won't show). On Huawei this is moot — a single global subtree
            covers everything.
        ips:
            Server-side filter — exact IPv4 list-key matches; expanded into
            one ``<neighbor>`` (Nokia) or one ``<query-entry>`` per IP
            (Huawei).
        macs:
            * Nokia — server-side: content-match expanded into sibling
              ``<neighbor><mac-address>`` elements (OR-combined). Saves
              round-trips for "give me ARP of these N MACs".
            * Huawei — client-side: server returns
              ``RPCError: This operation is not supported`` on
              ``<mac-addr>`` content-match (verified by probe). pynetcom
              normalises the MACs and filters the parser output.
        interface, origin:
            Client-side filters. ``origin`` is one of ``"STATIC"`` /
            ``"DYNAMIC"`` / ``"OTHER"``.

        Empty list (``[]``) is treated identically to ``None`` — full
        unscoped query.
        """
        # Coerce empty list → None for symmetry.
        vprn_names = vprn_names or None
        ips = ips or None
        macs = macs or None

        if self.vendor == "nokia":
            # Nokia: hard split between /state/router and /state/service/vprn.
            # If the caller passes ["Base"] (or just "Base" as the only entry)
            # → go via the <router> branch; otherwise → the <vprn> branch.
            base_only = (
                vprn_names is not None
                and len(vprn_names) == 1
                and (vprn_names[0] in ("Base", "base"))
            )
            if vprn_names and not base_only:
                # Drop any "Base" sentinel — it can't ride alongside named
                # VPRNs in the same RPC. Documented above.
                vprn_filtered = [v for v in vprn_names if v not in ("Base", "base")]
                req = NokiaArpRPCRequest(
                    vprn_service_names=vprn_filtered,
                    ipv4_addresses=ips,
                    mac_addresses=macs,
                )
                # Fallback vprn_name for parser when YANG list-key is absent
                # (rare). With multi-VPRN request the parser uses the
                # per-entry <service-name>; this is just the default.
                scoped_vprn_name = vprn_filtered[0] if vprn_filtered else "Base"
            else:
                # Base router or unscoped global query.
                router_name = "Base"
                if vprn_names and base_only:
                    router_name = vprn_names[0]  # "Base" / "base"
                req = NokiaArpRPCRequest(
                    router_name=router_name,
                    vprn_service_names=None,
                    ipv4_addresses=ips,
                    mac_addresses=macs,
                )
                scoped_vprn_name = router_name
            resp = self.nc.get(req.get_request_filter())
            neighbors: List[Neighbor] = list(
                nokia.parse_arp_response(resp, vprn_name=scoped_vprn_name)
            )
            # MAC was filtered server-side — no client-side post-pass.
        else:
            # Huawei: <vpn-instances> × <ip-addresses> Cartesian product
            # batch. MAC content-match not supported → client-side filter.
            req = HuaweiArpRPCRequest(vpn_instances=vprn_names, ip_addresses=ips)
            resp = self.nc.get(req.get_request_filter())
            neighbors = list(huawei.parse_arp_response(resp))
            if macs:
                # Both sides normalised to colon-form via normalize_mac
                # (Nokia canonical). Parser already stores
                # Neighbor.link_layer_address in colon-form via
                # huawei._normalise_mac, so comparison is straight equality
                # on the canonical view.
                wanted: set[str] = set()
                for m in macs:
                    try:
                        wanted.add(normalize_mac(m, "nokia"))
                    except ValueError:
                        # Malformed input — skip silently rather than
                        # blowing up the whole call; the empty-match path
                        # below will simply not match it.
                        continue
                neighbors = [
                    n for n in neighbors
                    if n.link_layer_address and n.link_layer_address in wanted
                ]

        return self._post_filter_neighbors(
            neighbors, interface=interface, origin=origin
        )

    def _post_filter_neighbors(
        self,
        neighbors: List[Neighbor],
        *,
        interface: Optional[str],
        origin: Optional[str],
    ) -> List[Neighbor]:
        if not (interface or origin):
            return neighbors

        flt = RestNMSDataFilter()
        if origin:
            flt.include(origin=[origin.upper()])
        filtered = flt.apply(neighbors)

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

        The returned dict may carry ``mac=None`` when the ARP entry exists
        but the MAC is not yet resolved (incomplete entry — downstream did
        not answer the ARP request, e.g. port oper-down or silent host).
        ``vprn_name``, ``l3_interface`` and ``l2_service`` are still filled
        in this case. The caller is responsible for distinguishing this
        intermediate ARP-state-machine state from a true "no ARP entry"
        result (the latter is the ``None`` return).
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
            # vprn_name may be None for Huawei global / "Base" for Nokia base.
            vprn_list = [vprn_name] if vprn_name is not None else None
            arps = self.get_arp_table(vprn_names=vprn_list, ips=[ip])
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
        # Base-router R-VPLS is not a valid scenario here (plan E1: ``<vpls>``
        # under /configure/router[Base]/interface is rejected by SR OS 23.10),
        # so only VPRN interfaces can bind a routed VPLS.
        vrfs = [v.name for v in self.get_l3vpn_services() if v.name]
        gateways: List[L3Interface] = []

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

    # ---- BGP RIB (VPN routes) ------------------------------------------ #
    def get_bgp_routes(self, prefixes: List[str]) -> List[BgpRoute]:
        """Resolve BGP IPv4-VPN RIB entries by exact-prefix list.

        :param prefixes: непустой список IPv4-префиксов (host-IP допускается,
            фильтр Huawei проверяет лишь exact match по NLRI prefix-leaf).
        :type prefixes: list[str]
        :return: все matching ``BgpRoute`` (best + non-best); LPM / выбор
            лучшего / dedupe по next_hop делает caller.
        :rtype: list[BgpRoute]
        :raises NotImplementedError: для вендоров, отличных от Huawei.

        Поддерживается только на Huawei (``vendor='huawei'``). Один RPC
        агрегирует все ``prefixes`` через multi-entry subtree filter —
        ходить по списку поштучно не нужно.
        """
        if self.vendor == "huawei":
            req = HuaweiBgpVpnRoutesRPCRequest(prefixes)
            resp = self.nc.get(req.get_request_filter())
            return list(huawei.parse_bgp_vpn_routes_response(resp))
        raise NotImplementedError(
            f"get_bgp_routes is not implemented for vendor={self.vendor!r}"
        )

    # ====================================================================== #
    # Diagnostic actions: ping / traceroute                                   #
    # ====================================================================== #
    #
    # Vendor-agnostic публичный API: caller передаёт PingRequest /
    # TracerouteRequest, получает PingResult / TracerouteResult. Branching по
    # vendor спрятан в _ping_nokia / _ping_huawei / _traceroute_*.
    #
    # Auth-error mapping: на Nokia без `action` в base-op-authorization профиле
    # rpc-error приходит с tag=operation-not-supported и message содержащим
    # "base-op-authorization". Конвертим в NetconfActionNotAuthorized с готовым
    # fix_hint — bts_api дальше отдаст это в HTTP 503 с config-сниппетом.

    def ping(self, request, *, poll_timeout_s: float = 30.0):
        """Запустить ICMP echo с роутера и вернуть :class:`PingResult`.

        :param request: :class:`PingRequest` с параметрами.
        :param poll_timeout_s: верхняя граница ожидания результата (Huawei).
            На Nokia параметр игнорируется (sync-RPC, отдаёт сразу).
        :raises NetconfActionNotAuthorized: если профиль NETCONF на роутере
            не разрешает ``<action>`` (Nokia: расширить
            ``base-op-authorization``).
        :raises NotImplementedError: для vendor не Nokia/Huawei.

        :return: :class:`PingResult` с агрегатами и per-probe детализацией.
        """
        # local imports — иначе circular (PingRequest определяется в rpc_data_containers,
        # сам файл не зависит от services_client, и наоборот)
        from pynetcom.utils.helpers.netconf.rpc_data_containers.ping import PingRequest

        # На случай если caller передал dict — поднимем понятную ошибку
        if not isinstance(request, PingRequest):
            raise TypeError(
                f"ping(request=...) ожидает PingRequest, получено {type(request).__name__}"
            )

        # Поднимаем session.timeout с учётом ожидаемой длительности теста.
        rpc_timeout_needed = max(
            60,
            int(request.count * (request.interval_ms + request.timeout_ms) / 1000 + 10),
        )
        orig_timeout = getattr(self.nc.session, "timeout", None)
        if orig_timeout is not None:
            try:
                self.nc.session.timeout = max(int(orig_timeout), rpc_timeout_needed)
            except Exception:  # noqa: BLE001
                # некоторые ncclient версии могут не поддерживать установку — просто игнорим
                pass
        try:
            if self.vendor == "nokia":
                return self._ping_nokia(request)
            if self.vendor == "huawei":
                return self._ping_huawei(request, poll_timeout_s=poll_timeout_s)
            raise NotImplementedError(
                f"ping is not implemented for vendor={self.vendor!r}"
            )
        finally:
            if orig_timeout is not None:
                try:
                    self.nc.session.timeout = orig_timeout
                except Exception:  # noqa: BLE001
                    pass

    def traceroute(self, request, *, poll_timeout_s: float = 60.0):
        """Запустить traceroute с роутера и вернуть :class:`TracerouteResult`.

        :param request: :class:`TracerouteRequest`.
        :param poll_timeout_s: ожидание Huawei (на Nokia игнорируется).
        :raises NetconfActionNotAuthorized: см. :meth:`ping`.
        :raises NotImplementedError: для vendor не Nokia/Huawei.
        """
        from pynetcom.utils.helpers.netconf.rpc_data_containers.traceroute import TracerouteRequest

        if not isinstance(request, TracerouteRequest):
            raise TypeError(
                f"traceroute(request=...) ожидает TracerouteRequest, "
                f"получено {type(request).__name__}"
            )

        # max_ttl × probes × timeout — верхняя граница длительности
        rpc_timeout_needed = max(
            60,
            int(request.max_ttl * request.probes_per_hop * request.timeout_ms / 1000 + 10),
        )
        orig_timeout = getattr(self.nc.session, "timeout", None)
        if orig_timeout is not None:
            try:
                self.nc.session.timeout = max(int(orig_timeout), rpc_timeout_needed)
            except Exception:  # noqa: BLE001
                pass
        try:
            if self.vendor == "nokia":
                return self._traceroute_nokia(request)
            if self.vendor == "huawei":
                return self._traceroute_huawei(request, poll_timeout_s=poll_timeout_s)
            raise NotImplementedError(
                f"traceroute is not implemented for vendor={self.vendor!r}"
            )
        finally:
            if orig_timeout is not None:
                try:
                    self.nc.session.timeout = orig_timeout
                except Exception:  # noqa: BLE001
                    pass

    # ---- Nokia branch -------------------------------------------------- #
    def _ping_nokia(self, request):
        from pynetcom.utils.helpers.netconf.rpc_requests import NokiaPingActionRequest
        from pynetcom.utils.helpers.netconf.rpc_data_containers.nokia_ping import (
            parse_nokia_ping_response,
        )

        builder = NokiaPingActionRequest(request)
        try:
            raw_xml = self._send_action_raw(builder.get_request_filter())
        except Exception as exc:  # noqa: BLE001
            self._maybe_raise_auth(exc)
            raise
        return parse_nokia_ping_response(raw_xml, request)

    def _traceroute_nokia(self, request):
        from pynetcom.utils.helpers.netconf.rpc_requests import NokiaTracerouteActionRequest
        from pynetcom.utils.helpers.netconf.rpc_data_containers.nokia_ping import (
            parse_nokia_traceroute_response,
        )

        builder = NokiaTracerouteActionRequest(request)
        try:
            raw_xml = self._send_action_raw(builder.get_request_filter())
        except Exception as exc:  # noqa: BLE001
            self._maybe_raise_auth(exc)
            raise
        return parse_nokia_traceroute_response(raw_xml, request)

    # ---- Huawei branch ------------------------------------------------- #
    def _ping_huawei(self, request, *, poll_timeout_s: float):
        import time
        import uuid
        from pynetcom.utils.helpers.netconf.rpc_requests import (
            HuaweiPingActionRequest,
            HuaweiPingStateFilter,
            HuaweiPingDeleteAction,
        )
        from pynetcom.utils.helpers.netconf.rpc_data_containers.huawei_ping import (
            parse_huawei_ping_state,
        )

        # Opportunistic preflight — удаляем осиротевшие наши же тесты.
        # Ошибки preflight никогда не должны прерывать основной ping —
        # cleanup внутри обёрнут в try/except.
        self._preflight_huawei_diagnostic_cleanup(kind="ping", prefix="pc")

        test_name = f"pc{uuid.uuid4().hex[:8]}"
        attempts = 0
        last_partial = None

        while True:
            attempts += 1
            try:
                action = HuaweiPingActionRequest(request, test_name=test_name)
                self._send_action_raw(action.get_request_filter())
                break  # action accepted
            except Exception as exc:  # noqa: BLE001
                self._maybe_raise_auth(exc)
                # data-exists 31403 — повторяем с новым UUID, один раз
                if attempts == 1 and self._is_huawei_data_exists(exc):
                    self.log.warning(
                        "Huawei ping test-name collision на %s — retry с новым UUID",
                        test_name,
                    )
                    test_name = f"pc{uuid.uuid4().hex[:8]}"
                    continue
                # Bad VRF — Huawei отвергает action-start. Возвращаем синтетический
                # PingResult симметрично Nokia (`error_kind=vrf-not-found`),
                # а не голый RPCError — AI/REST-клиент получит uniform контракт.
                if self._is_huawei_vpn_not_exists(exc):
                    self.log.info(
                        "Huawei ping(%s): VRF '%s' не существует — синтетический результат vrf-not-found",
                        test_name, request.vrf,
                    )
                    return self._synth_ping_failure(request, "vrf-not-found", str(exc), vendor="huawei")
                raise

        try:
            deadline = time.time() + poll_timeout_s
            poll_interval = 1.0
            state_filter = HuaweiPingStateFilter(test_name).get_request_filter()
            while True:
                time.sleep(poll_interval)
                try:
                    reply_xml = self._get_raw_state(state_filter)
                except Exception as exc:  # noqa: BLE001
                    self.log.warning(
                        "Huawei ping(%s): state poll сбойнул (%s) — повтор",
                        test_name, exc,
                    )
                    if time.time() >= deadline:
                        # вернём пустой partial и финализируем
                        from pynetcom.utils.helpers.netconf.rpc_data_containers.ping import (
                            PingResult,
                        )
                        return PingResult(
                            success=False,
                            status="partial",
                            sent=0,
                            received=0,
                            lost=0,
                            loss_percent=0.0,
                            rtt_min_ms=None,
                            rtt_avg_ms=None,
                            rtt_max_ms=None,
                            rtt_stddev_ms=None,
                            probes=[],
                            destination=request.destination,
                            source_address=request.source_address,
                            vrf=request.vrf,
                            vendor="huawei",
                            duration_ms=None,
                            raw_response_xml="",
                        )
                    continue
                result = parse_huawei_ping_state(reply_xml, request, test_name)
                if result.status == "completed":
                    return result
                last_partial = result
                if time.time() >= deadline:
                    self.log.warning(
                        "Huawei ping(%s): poll-deadline %.1fs hit, status=%s",
                        test_name, poll_timeout_s, result.status,
                    )
                    return result
        finally:
            # cleanup обязательно — даже на timeout / exception. data-missing
            # 31404 (test-name отсутствует) глотаем тихо.
            try:
                delete = HuaweiPingDeleteAction(test_name)
                self._send_action_raw(delete.get_request_filter())
            except Exception as exc:  # noqa: BLE001
                if not self._is_huawei_data_missing(exc):
                    self.log.warning(
                        "Huawei ping cleanup (test=%s) сбойнул: %s",
                        test_name, exc,
                    )

    def _traceroute_huawei(self, request, *, poll_timeout_s: float):
        import time
        import uuid
        from pynetcom.utils.helpers.netconf.rpc_requests import (
            HuaweiTracerouteActionRequest,
            HuaweiTracerouteStateFilter,
            HuaweiTracerouteDeleteAction,
        )
        from pynetcom.utils.helpers.netconf.rpc_data_containers.huawei_ping import (
            parse_huawei_traceroute_state,
        )

        # Opportunistic preflight — удаляем осиротевшие traceroute-тесты.
        self._preflight_huawei_diagnostic_cleanup(kind="traceroute", prefix="tr")

        test_name = f"tr{uuid.uuid4().hex[:8]}"
        attempts = 0
        while True:
            attempts += 1
            try:
                action = HuaweiTracerouteActionRequest(request, test_name=test_name)
                self._send_action_raw(action.get_request_filter())
                break
            except Exception as exc:  # noqa: BLE001
                self._maybe_raise_auth(exc)
                if attempts == 1 and self._is_huawei_data_exists(exc):
                    self.log.warning(
                        "Huawei traceroute test-name collision на %s — retry",
                        test_name,
                    )
                    test_name = f"tr{uuid.uuid4().hex[:8]}"
                    continue
                if self._is_huawei_vpn_not_exists(exc):
                    self.log.info(
                        "Huawei traceroute(%s): VRF '%s' не существует — vrf-not-found",
                        test_name, request.vrf,
                    )
                    return self._synth_traceroute_failure(request, "vrf-not-found", str(exc))
                raise

        try:
            deadline = time.time() + poll_timeout_s
            state_filter = HuaweiTracerouteStateFilter(test_name).get_request_filter()
            while True:
                time.sleep(1.5)
                try:
                    reply_xml = self._get_raw_state(state_filter)
                except Exception as exc:  # noqa: BLE001
                    self.log.warning(
                        "Huawei traceroute(%s): state poll сбойнул (%s)",
                        test_name, exc,
                    )
                    if time.time() >= deadline:
                        from pynetcom.utils.helpers.netconf.rpc_data_containers.traceroute import (
                            TracerouteResult,
                        )
                        return TracerouteResult(
                            hops=[],
                            status="partial",
                            destination=request.destination,
                            source_address=request.source_address,
                            vrf=request.vrf,
                            vendor="huawei",
                            duration_ms=None,
                            raw_response_xml="",
                        )
                    continue
                result = parse_huawei_traceroute_state(reply_xml, request, test_name)
                if result.status == "completed":
                    return result
                if time.time() >= deadline:
                    return result
        finally:
            try:
                delete = HuaweiTracerouteDeleteAction(test_name)
                self._send_action_raw(delete.get_request_filter())
            except Exception as exc:  # noqa: BLE001
                if not self._is_huawei_data_missing(exc):
                    self.log.warning(
                        "Huawei traceroute cleanup (test=%s) сбойнул: %s",
                        test_name, exc,
                    )

    # ---- Housekeeping (Huawei, internal) ------------------------------ #
    #
    # ВНИМАНИЕ: cleanup-семейство — это vendor-internal hygiene, не публичный
    # контракт. Snaружи pynetcom (REST, AI-агент) знать про state-таблицы
    # Huawei не должны. Метод сохранён private (`_cleanup_orphan_diagnostic_tests`)
    # как back-stop на случай явного запуска оператором или внутреннего вызова
    # из preflight.
    def _cleanup_orphan_diagnostic_tests(
        self,
        prefix: str = "pc",
        *,
        include_traceroute: bool = True,
    ) -> dict:
        """Удалить осиротевшие diagnostic-tools тесты с заданным префиксом.

        Huawei (ATN/NE40E) — list ping-result / trace-result не имеет
        max-elements и auto-expire. Если процесс падает между ``start`` и
        ``delete`` (kill -9, OOM, exception между) — запись копится. Этот
        метод проходит по обоим спискам и удаляет всё что начинается с нашего
        prefix. Чужие тесты (созданные людьми / NSP / NCE) не трогаем —
        фильтр по prefix обязателен.

        :param prefix: префикс собственных тестов. По умолчанию ``"pc"``
            (ping); для traceroute дополнительно проверяется ``"tr"``.
        :param include_traceroute: чистить ли trace-result.
        :return: ``{"ping_deleted": [...], "trace_deleted": [...]}``.
        :raises NotImplementedError: на Nokia (sync action, никаких state-таблиц).
        """
        if self.vendor != "huawei":
            raise NotImplementedError(
                "_cleanup_orphan_diagnostic_tests актуален только для Huawei "
                "(на Nokia ping/traceroute синхронный — state-таблиц нет)."
            )

        from pynetcom.utils.helpers.netconf.rpc_requests import (
            HuaweiPingResultsListFilter,
            HuaweiTracerouteResultsListFilter,
            HuaweiPingDeleteAction,
            HuaweiTracerouteDeleteAction,
        )

        deleted_ping: List[str] = []
        try:
            list_filter = HuaweiPingResultsListFilter().get_request_filter()
            reply = self.nc.get(list_filter)
            names = self._extract_huawei_test_names(reply, "ping-results", "ping-result")
            for n in names:
                if not (n and n.startswith(prefix)):
                    continue
                try:
                    self._send_action_raw(
                        HuaweiPingDeleteAction(n).get_request_filter()
                    )
                    deleted_ping.append(n)
                except Exception as exc:  # noqa: BLE001
                    if not self._is_huawei_data_missing(exc):
                        self.log.warning(
                            "cleanup ping(%s) сбойнул: %s", n, exc,
                        )
        except Exception as exc:  # noqa: BLE001
            self.log.warning("cleanup ping list: %s", exc)

        deleted_trace: List[str] = []
        if include_traceroute:
            tr_prefix = "tr"
            try:
                list_filter = HuaweiTracerouteResultsListFilter().get_request_filter()
                reply = self.nc.get(list_filter)
                names = self._extract_huawei_test_names(
                    reply, "trace-results", "trace-result",
                )
                for n in names:
                    if not (n and (n.startswith(tr_prefix) or n.startswith(prefix))):
                        continue
                    try:
                        self._send_action_raw(
                            HuaweiTracerouteDeleteAction(n).get_request_filter()
                        )
                        deleted_trace.append(n)
                    except Exception as exc:  # noqa: BLE001
                        if not self._is_huawei_data_missing(exc):
                            self.log.warning(
                                "cleanup trace(%s) сбойнул: %s", n, exc,
                            )
            except Exception as exc:  # noqa: BLE001
                self.log.warning("cleanup traceroute list: %s", exc)

        return {"ping_deleted": deleted_ping, "trace_deleted": deleted_trace}

    @staticmethod
    def _extract_huawei_test_names(
        reply: dict, container_key: str, item_key: str,
    ) -> List[str]:
        """Достаёт ``test-name`` из ответа ``<get>`` ping/trace results list.

        ``reply`` — словарь как его отдаёт :meth:`NetconfClient.get` (после
        xmltodict). Структура: ``data/diagnostic-tools/ipv4/<container_key>/
        <item_key>[]/test-name``.
        """
        def _strip(k):
            if not isinstance(k, str):
                return k
            if "}" in k:
                k = k.split("}", 1)[1]
            if ":" in k:
                k = k.split(":", 1)[1]
            return k

        def _walk(node, name):
            if isinstance(node, dict):
                for k, v in node.items():
                    if _strip(k) == name:
                        return v
                for v in node.values():
                    f = _walk(v, name)
                    if f is not None:
                        return f
            elif isinstance(node, list):
                for item in node:
                    f = _walk(item, name)
                    if f is not None:
                        return f
            return None

        container = _walk(reply, container_key)
        if container is None:
            return []
        items = _walk(container, item_key)
        if items is None:
            return []
        if not isinstance(items, list):
            items = [items]
        names: List[str] = []
        for it in items:
            if isinstance(it, dict):
                n = _walk(it, "test-name")
                if isinstance(n, str):
                    names.append(n)
        return names

    @staticmethod
    def _extract_huawei_test_entries(
        reply: dict, container_key: str, item_key: str,
    ) -> List[dict]:
        """Богатый вариант :meth:`_extract_huawei_test_names`.

        Возвращает список словарей ``{"test-name": str, "status": str|None,
        "system-time": str|None}`` по списку ping-result / trace-result.
        Нужен для preflight.

        :param reply: словарь как его отдаёт :meth:`NetconfClient.get`.
        :param container_key: ``"ping-results"`` или ``"trace-results"``.
        :param item_key: ``"ping-result"`` или ``"trace-result"``.

        ``system-time`` Huawei: для ping живёт только в
        ``details/detail/system-time`` (per-probe), берём timestamp последнего
        detail как «когда тест завершился». Для trace-result этого поля
        вообще нет (probe 24.05.2026) — возвращаем ``None``, preflight
        traceroute работает без age-фильтра.
        """
        def _strip(k):
            if not isinstance(k, str):
                return k
            if "}" in k:
                k = k.split("}", 1)[1]
            if ":" in k:
                k = k.split(":", 1)[1]
            return k

        def _walk(node, name):
            """Ищет первое вхождение leaf'а ``name`` сверху вниз."""
            if isinstance(node, dict):
                for k, v in node.items():
                    if _strip(k) == name:
                        return v
                for v in node.values():
                    f = _walk(v, name)
                    if f is not None:
                        return f
            elif isinstance(node, list):
                for item in node:
                    f = _walk(item, name)
                    if f is not None:
                        return f
            return None

        def _extract_last_detail_system_time(entry: dict) -> Optional[str]:
            """Из ``entry`` (ping-result) достаёт system-time последнего detail."""
            details_container = None
            for k, v in entry.items():
                if _strip(k) == "details":
                    details_container = v
                    break
            if not isinstance(details_container, dict):
                return None
            detail_list = None
            for k, v in details_container.items():
                if _strip(k) == "detail":
                    detail_list = v
                    break
            if detail_list is None:
                return None
            if not isinstance(detail_list, list):
                detail_list = [detail_list]
            last_ts: Optional[str] = None
            for d in detail_list:
                if not isinstance(d, dict):
                    continue
                for k, v in d.items():
                    if _strip(k) == "system-time" and isinstance(v, str):
                        last_ts = v  # последнего перезаписываем
                        break
            return last_ts

        container = _walk(reply, container_key)
        if container is None:
            return []
        items = _walk(container, item_key)
        if items is None:
            return []
        if not isinstance(items, list):
            items = [items]
        entries: List[dict] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            name = _walk(it, "test-name")
            if not isinstance(name, str):
                continue
            # status — single leaf на уровне result
            status = None
            for k, v in it.items():
                if _strip(k) == "status" and isinstance(v, str):
                    status = v
                    break
            stime = _extract_last_detail_system_time(it)
            entries.append({
                "test-name": name,
                "status": status,
                "system-time": stime,
            })
        return entries

    @staticmethod
    def _huawei_system_time_age_s(system_time: Optional[str]) -> Optional[float]:
        """Перевести Huawei ``system-time`` (ISO-8601) в возраст в секундах.

        Huawei отдаёт строки вида ``2026-05-24T15:30:42Z`` или
        ``2026-05-24T15:30:42+05:00``. Если не парсится — возвращаем ``None``,
        вызывающий должен считать запись «возраст неизвестен».
        """
        if not system_time:
            return None
        from datetime import datetime, timezone

        s = system_time.strip()
        # Python <3.11 не любит "Z" в fromisoformat → переписываем в +00:00
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        try:
            return (datetime.now(timezone.utc) - dt).total_seconds()
        except Exception:  # noqa: BLE001
            return None

    def _preflight_huawei_diagnostic_cleanup(
        self,
        *,
        kind: str,
        prefix: str,
        min_age_s: float = 60.0,
    ) -> None:
        """Opportunistic cleanup осиротевших diagnostic-tools тестов.

        Вызывается перед каждым ``<action>`` ping/traceroute. Удаляет только
        записи которые **одновременно**:
          * ``test-name`` начинается с нашего ``prefix`` (``pc`` для ping,
            ``tr`` для traceroute);
          * ``status == "finished"`` (тест уже завершён, это точно orphan,
            а не активный наш ping в соседнем процессе);
          * ``system-time`` старше ``min_age_s`` секунд (страховка от race
            с параллельным процессом-сиблингом, который только что запустил
            тест с тем же prefix).

        Все ошибки глотаются — preflight никогда не должен прерывать основной
        ping. data-missing 31404 (race с другим cleanup) — особо тихо на
        DEBUG. Найден хотя бы один orphan → INFO, иначе всё на DEBUG.

        :param kind: ``"ping"`` или ``"traceroute"``.
        :param prefix: префикс собственных тестов (``"pc"`` / ``"tr"``).
        :param min_age_s: минимальный возраст записи в секундах.
        """
        if self.vendor != "huawei":
            return

        try:
            from pynetcom.utils.helpers.netconf.rpc_requests import (
                HuaweiPingResultsListFilter,
                HuaweiTracerouteResultsListFilter,
                HuaweiPingDeleteAction,
                HuaweiTracerouteDeleteAction,
            )

            if kind == "ping":
                list_filter = HuaweiPingResultsListFilter().get_request_filter()
                container_key, item_key = "ping-results", "ping-result"
                DeleteAction = HuaweiPingDeleteAction
            elif kind == "traceroute":
                list_filter = HuaweiTracerouteResultsListFilter().get_request_filter()
                container_key, item_key = "trace-results", "trace-result"
                DeleteAction = HuaweiTracerouteDeleteAction
            else:
                self.log.debug("preflight cleanup: неизвестный kind=%r", kind)
                return

            reply = self.nc.get(list_filter)
            entries = self._extract_huawei_test_entries(
                reply, container_key, item_key,
            )

            # У Huawei trace-result нет system-time нигде (probe 24.05.2026),
            # поэтому для traceroute возрастной фильтр невозможен — только
            # prefix + status=finished. Race-окно остаётся, но prefix `tr` +
            # UUID8 делает коллизию вырожденно маловероятной.
            has_age_signal = kind == "ping"

            candidates: List[str] = []
            for e in entries:
                name = e.get("test-name") or ""
                if not name.startswith(prefix):
                    continue
                status = (e.get("status") or "").strip().lower()
                if status != "finished":
                    # активный (processing) или с ошибкой — не трогаем
                    continue
                if has_age_signal:
                    age_s = self._huawei_system_time_age_s(e.get("system-time"))
                    if age_s is None:
                        # возраст неизвестен — на всякий случай НЕ трогаем
                        # (страховка против race с параллельным процессом)
                        continue
                    if age_s < min_age_s:
                        continue
                candidates.append(name)

            deleted = 0
            for n in candidates:
                try:
                    self._send_action_raw(DeleteAction(n).get_request_filter())
                    deleted += 1
                except Exception as exc:  # noqa: BLE001
                    if self._is_huawei_data_missing(exc):
                        # race — другой процесс уже удалил, тихо
                        self.log.debug(
                            "preflight cleanup %s(%s): уже удалён (race)",
                            kind, n,
                        )
                    else:
                        self.log.debug(
                            "preflight cleanup %s(%s) сбойнул: %s",
                            kind, n, exc,
                        )

            if deleted > 0:
                self.log.info(
                    "Huawei preflight: cleaned up %d orphan %s tests",
                    deleted, kind,
                )
            else:
                self.log.debug(
                    "Huawei preflight %s: no orphans (scanned %d entries)",
                    kind, len(entries),
                )
        except Exception as exc:  # noqa: BLE001
            # Никогда не прерываем основной flow.
            self.log.debug("Huawei preflight cleanup %s сбойнул: %s", kind, exc)

    # ---- shared low-level helpers ------------------------------------- #
    def _send_action_raw(self, action_xml: str) -> str:
        """Отправить ``<action>`` RPC, вернуть сырой rpc-reply как строку.

        Работаем напрямую через ``self.nc.session.rpc(...)`` чтобы получить
        полный XML rpc-reply, который парсеры берут как первоисточник.
        :meth:`NetconfClient.rpc` распарсивает в dict, чего мы не хотим —
        теряются namespace-префиксы которые иногда важны.

        ncclient для ``<action>`` отдаёт :class:`ncclient.xml_.NCElement`
        (а не классический ``RPCReply``). У него ``.data_xml`` — строка с
        полным envelope rpc-reply, ``.xml`` — None. Поэтому пробуем сначала
        data_xml, затем tostring (свойство), затем str(reply).
        """
        from lxml import etree

        rpc_element = etree.fromstring(action_xml.encode("utf-8"))
        reply = self.nc.session.rpc(rpc_element)
        # NCElement.data_xml = строка с полным <rpc-reply>... — то что нужно
        for attr in ("data_xml", "xml"):
            value = getattr(reply, attr, None)
            if isinstance(value, str) and value.strip():
                return value
        # Если объект имеет _NCElement_element / _root, попробуем сериализовать
        try:
            root = getattr(reply, "_root", None) or getattr(reply, "_NCElement_element", None)
            if root is not None:
                return etree.tostring(root, encoding="unicode")
        except Exception:  # noqa: BLE001
            pass
        return str(reply) or ""

    def _get_raw_state(self, subtree_filter_xml: str) -> str:
        """Отправить ``<get>`` со subtree-фильтром, вернуть сырой rpc-reply XML.

        Используется для polling'а Huawei. Возвращаем строку (как
        ``data_xml`` ncclient'а), чтобы parser работал с тем же XML что и в
        probe-артефактах.
        """
        from ncclient.xml_ import to_ele

        reply = self.nc.session.get(("subtree", to_ele(subtree_filter_xml)))
        # У ncclient GetReply есть .data_xml — это и есть содержимое <data>
        # wrapped в <data> tag. Передаём как есть в parse_*_state — там
        # _clean_keys+_walk покрывают оба варианта (с/без rpc-reply envelope).
        data_xml = getattr(reply, "data_xml", None)
        if data_xml:
            return data_xml
        # fallback на полный envelope
        return getattr(reply, "xml", None) or ""

    @staticmethod
    def _maybe_raise_auth(exc):
        """Если ``exc`` — RPCError с признаками отказа auth-профиля, конвертит
        в :class:`NetconfActionNotAuthorized`. Иначе ничего не делает (caller
        re-raise'нет исходное)."""
        from pynetcom.exceptions import NetconfActionNotAuthorized

        # ncclient.operations.rpc.RPCError несёт .tag / .message / .severity
        tag = getattr(exc, "tag", None)
        message = getattr(exc, "message", None) or ""
        text = str(exc)
        marker = "base-op-authorization"
        # Nokia: tag=operation-not-supported + message с base-op-authorization
        if tag == "operation-not-supported" and (marker in message or marker in text):
            raise NetconfActionNotAuthorized(
                vendor="nokia", underlying_error=exc,
            ) from exc
        # запасной матч по тексту — на случай если ncclient версии не пробросили tag
        if "MGMT_CORE" in text and marker in text:
            raise NetconfActionNotAuthorized(
                vendor="nokia", underlying_error=exc,
            ) from exc

    @staticmethod
    def _is_huawei_data_exists(exc) -> bool:
        """Huawei rpc-error code 31403 / tag=data-exists ("The specified test
        instance already exists.")"""
        text = str(exc)
        if "31403" in text:
            return True
        tag = getattr(exc, "tag", None)
        if tag == "data-exists":
            return True
        return False

    @staticmethod
    def _is_huawei_data_missing(exc) -> bool:
        """Huawei rpc-error code 31404 / tag=data-missing — test-name отсутствует.
        Возникает при cleanup уже удалённого / никогда не созданного теста.
        """
        text = str(exc)
        if "31404" in text:
            return True
        tag = getattr(exc, "tag", None)
        if tag == "data-missing":
            return True
        return False

    def _synth_ping_failure(self, request, error_kind: str, raw_msg: str, *, vendor: str):
        """Синтезирует PingResult для случаев, когда action-start был отвергнут
        и реального теста на устройстве не возникло (bad VRF на Huawei и т.п.).
        Возвращает по одному "виртуальному" probe на каждый запрошенный count
        с одинаковыми error_kind/raw_status, чтобы AI-боту контракт был
        идентичен с Nokia per-probe failure-cases."""
        from pynetcom.utils.helpers.netconf.rpc_data_containers.ping import (
            PingResult, PingProbe,
        )
        probes = [
            PingProbe(
                sequence=i,
                success=False,
                rtt_ms=None,
                ttl=None,
                response_address=None,
                error_kind=error_kind,
                raw_status=error_kind,
                timestamp=None,
            )
            for i in range(1, max(1, request.count) + 1)
        ]
        return PingResult(
            success=False,
            status="completed",
            sent=request.count,
            received=0,
            lost=request.count,
            loss_percent=100.0,
            rtt_min_ms=None,
            rtt_avg_ms=None,
            rtt_max_ms=None,
            rtt_stddev_ms=None,
            probes=probes,
            destination=request.destination,
            source_address=request.source_address,
            vrf=request.vrf,
            vendor=vendor,
            duration_ms=0,
            raw_response_xml=f"<synthetic-failure error_kind='{error_kind}'>{raw_msg}</synthetic-failure>",
        )

    def _synth_traceroute_failure(self, request, error_kind: str, raw_msg: str):
        from pynetcom.utils.helpers.netconf.rpc_data_containers.traceroute import (
            TracerouteResult,
        )
        return TracerouteResult(
            hops=[],
            status="failed",
            destination=request.destination,
            source_address=request.source_address,
            vrf=request.vrf,
            vendor="huawei",
            duration_ms=0,
            raw_response_xml=f"<synthetic-failure error_kind='{error_kind}'>{raw_msg}</synthetic-failure>",
        )

    @staticmethod
    def _is_huawei_vpn_not_exists(exc) -> bool:
        """Huawei на action-start ipv4-start-ip-ping/trace отвергает RPC при
        несуществующем vrf-name: ``tag=operation-failed, message="The VPN
        instance does not exist."``. Эмпирически подтверждено probe'ом 24.05.2026
        на NE40E. Нет отдельного error-info-code — определяем по тексту."""
        text = str(exc).lower()
        return "vpn instance does not exist" in text
