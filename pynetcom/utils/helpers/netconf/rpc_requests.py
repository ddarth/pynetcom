from string import Template
from pynetcom.utils.huawei_router_tools import split_if_to_type_id_tag
import re
from typing import Tuple


def normalize_mac(mac: str, vendor: str) -> str:
    """Normalise a MAC address to the form expected by a given vendor's
    NETCONF subtree filter.

    Operators write MAC addresses in many shapes — ``9844ce72dc30``,
    ``98:44:ce:72:dc:30``, ``98-44-ce-72-dc-30``, ``9844.ce72.dc30``. The
    NETCONF list-key filter needs the canonical per-vendor form:

        nokia  ⇒ ``aa:bb:cc:dd:ee:ff`` (lower-case, colon-separated)
        huawei ⇒ ``aabb-ccdd-eeff``   (lower-case, hyphen between u16 groups)

    The function strips every common separator, requires exactly 12 hex
    digits, and re-emits with the vendor's preferred separators. A value
    that is already in canonical form passes through unchanged. Invalid
    input raises ``ValueError`` — better to fail loudly than to send a
    silently broken filter to the device.
    """
    if mac is None:
        return mac
    hex_only = re.sub(r"[:\-\.\s]", "", mac.strip()).lower()
    if not re.fullmatch(r"[0-9a-f]{12}", hex_only):
        raise ValueError(f"Invalid MAC address: {mac!r}")
    v = (vendor or "").strip().lower()
    if v == "huawei":
        return f"{hex_only[0:4]}-{hex_only[4:8]}-{hex_only[8:12]}"
    # default — Nokia / canonical IEEE 802 colon form
    return ":".join(hex_only[i:i + 2] for i in range(0, 12, 2))


class OpenconfigInterfaceRPCRequest():
    """Base class for Openconfig interface RPC request"""
    template : Template = None
    interface : str= """
    <interfaces xmlns="http://openconfig.net/yang/interfaces">
        <interface>
            <name>$port</name>
        </interface>
    </interfaces>"""
    transceiver : str = """
    <components xmlns="http://openconfig.net/yang/platform">
        <component>
            <name>$transceiver_prefix$port</name>
            <transceiver xmlns="http://openconfig.net/yang/platform/transceiver">
            </transceiver>
        </component>
    </components>
    """
    # lldp : str = """
    # <lldp xmlns="http://openconfig.net/yang/lldp">
    #     <interfaces>
    #         <interface>
    #             <name>$port</name>
    #         </interface>
    #     </interfaces>
    # </lldp>
    # """
    lldp : str = """
    <lldp xmlns="http://openconfig.net/yang/lldp">
        <interfaces>
            <interface>
                <name>$port</name>
                <state>
                    <enabled/>
                </state>
                <neighbors>
                    <neighbor>
                        <id/>
                        <state/>
                    </neighbor>
                </neighbors>
            </interface>
        </interfaces>
    </lldp>
    """

    def __init__(self, port: str, transceiver_prefix: str):
        self.port = port
        self.transceiver_prefix = transceiver_prefix
        self.request_filter = self.get_template().substitute(port=self.port, transceiver_prefix=self.transceiver_prefix)

    def get_template(self) -> Template:
        return Template(self.interface + self.transceiver + self.lldp)
    
    def get_request_filter(self):
        return self.request_filter

class HuaweiInterfaceRPCRequest(OpenconfigInterfaceRPCRequest):
    """Class for Huawei interface RPC request"""
    huawei_interface: str = """
        <devm xmlns="urn:huawei:yang:huawei-devm">
            <ports>
                <port>
                    <position>$position</position>
                    <last-up-time/>
                    <last-down-time/>
                    <optical-module xmlns="urn:huawei:yang:huawei-pic">
                    </optical-module>
                    <!-- Request Ethernet state (speed/duplex/negotiation) from Huawei PIC model -->
                    <ethernet xmlns="urn:huawei:yang:huawei-pic">
                        <speed/>
                        <duplex-status/>
                        <negotiation/>
                        <negotiation-mode/>
                    </ethernet>
                    <physical-bandwidth/>
                </port>
            </ports>
        </devm>
        <ifm xmlns="urn:huawei:yang:huawei-ifm">
            <interfaces>
                <interface>
                    <name>$port</name>
                    <qos xmlns="urn:huawei:yang:huawei-qos">
                        <port-shapings/>
                    </qos>
                </interface>
            </interfaces>
        </ifm>
    """
    # OpenConfig-only filter for Eth-Trunk (LAG) interfaces
    eth_trunk_interface: str = """
<interfaces xmlns="http://openconfig.net/yang/interfaces">
  <interface>
    <name>$port</name>
    <state>
    </state>
    <aggregation xmlns="http://openconfig.net/yang/interfaces/aggregate">
    </aggregation>
  </interface>
</interfaces>
"""

    def __init__(self, port: str):
        # Eth-Trunk interfaces: use simplified OpenConfig filter with aggregation info only
        if isinstance(port, str) and port.lower().startswith('eth-trunk'):
            self.port = port
            self.transceiver_prefix = 'TRANSCEIVER:'
            self.request_filter = Template(self.eth_trunk_interface.strip()).substitute(port=self.port)
            return

        self.port = port
        self.transceiver_prefix = 'TRANSCEIVER:'
        self.request_filter = self.get_template().substitute(
            port=self.port,
            transceiver_prefix=self.transceiver_prefix,
            position=self.get_position(),
        )

    def get_template(self) -> Template:
        return Template(self.interface + self.transceiver + self.lldp + self.huawei_interface)

    def get_position(self) -> str:
        """Get position of the interface"""
        return split_if_to_type_id_tag(self.port)['if_pos']


class NokiaInterfaceRPCRequest(OpenconfigInterfaceRPCRequest):
    """Class for Nokia interface RPC request"""
    nokia_interface : str = """
    <state xmlns="urn:nokia.com:sros:ns:yang:sr:state">
        <port>
            <port-id>$connector_port</port-id>
            <transceiver/>
        </port>
        <port>
            <port-id>$breakout_port</port-id>
            <oper-state-last-changed/>
            <ethernet>
                <oper-egress-rate/>
                <lldp>
                    <dest-mac>
                        <mac-type>nearest-bridge</mac-type>
                        <remote-system/>
                    </dest-mac>
                </lldp>
            </ethernet>
        </port>
    </state>
    """
    lag_interface : str = """
<interfaces xmlns="http://openconfig.net/yang/interfaces">
  <interface>
    <name>$port</name>
    <state>
    </state>
    <aggregation  xmlns="http://openconfig.net/yang/interfaces/aggregate">
    </aggregation>
  </interface>
</interfaces>
"""

    def get_connector_port(self) -> str:
        # First check format with /c
        m = re.match(r"^(.+?/c\d+)(?:/(\d+))?$", self.port)
        if m:
            connector = m.group(1)
            breakout_index = m.group(2) or "1"
            breakout = f"{connector}/{breakout_index}"
            return connector, breakout
        # If not match with /c, then assume this is already L/M/P format
        m2 = re.match(r"^(\d+/\d+/\d+)$", self.port)
        if m2:
            connector = self.port
            breakout = self.port
            return connector, breakout
        raise ValueError(f"Unexpected port format: {self.port}")

    def __init__(self, port: str):
        # LAG interfaces: use simplified OpenConfig filter with aggregation info only
        if re.match(r"^lag-\d+$", port, re.IGNORECASE):
            self.port = port
            self.transceiver_prefix = 'transceiver '
            self.request_filter = Template(self.lag_interface).substitute(port=self.port)
            return

        self.port = port
        self.transceiver_prefix = 'transceiver '

        connector_port, breakout_port = self.get_connector_port()
        self.transceiver = self.transceiver.replace('$port', '$connector_port')

        self.request_filter = self.get_template().substitute(
            port=breakout_port, 
            transceiver_prefix=self.transceiver_prefix, 
            connector_port=connector_port,
            breakout_port=breakout_port
        )
        # print(self.request_filter)

    def get_template(self) -> Template:
        return Template(self.interface + self.transceiver + self.lldp + self.nokia_interface)


class OpenconfigInterfacesBriefListRPCRequest:
    """Builds RPC filter to fetch all interface names and descriptions using OpenConfig (state-only)."""
    template: Template = Template(
        """
<interfaces xmlns="http://openconfig.net/yang/interfaces">
  <interface>
    <name/>
    <state>
      <name/>
      <description/>
      <oper-status/>
      <admin-status/>
    </state>
  </interface>
</interfaces>
""".strip()
    )

    def __init__(self):
        self.request_filter = self.get_template().substitute()

    def get_template(self) -> Template:
        return self.template

    def get_request_filter(self):
        return self.request_filter


# =====================================================================
# Service-layer RPC request builders: VPLS/VSI, FDB/MAC, ARP/Neighbor.
# =====================================================================
#
# Each builder accepts optional filter parameters (service name, MAC, VRF, IP)
# and emits a NETCONF subtree filter for ncclient. When a parameter is None,
# the corresponding XML element is omitted so the device returns the full list.
# This is the convention used elsewhere in pynetcom and lets the caller pick
# between server-side narrowing (pass the parameter) and client-side
# post-filtering (omit the parameter, then filter via RestNMSDataFilter).


class NokiaServiceRPCRequest:
    """Filter for Nokia SR OS L2 services (VPLS).

    YANG: ``/state/service/vpls`` (``urn:nokia.com:sros:ns:yang:sr:state``).
    Setting ``service_name`` switches the filter from "list all" to "fetch
    one by list-key", which Nokia handles entirely server-side.

    Operational note (verified on SR OS 23): a true full-subtree query under
    ``/state/service/vpls/<service-name>`` pulls per-SAP statistics counters
    and takes ~45 s for a service with only 6 SAPs (measured on the BSC
    device set). To keep latency predictable this builder *always* emits a
    field-selector even in the non-brief case: VPLS ``oper-state`` plus
    minimal SAP / spoke-sdp / mesh-sdp fields (id + type + oper-state).
    This is sufficient for :class:`~.services.NetworkInstance` reconstruction
    and reduces the same RPC to ~0.3-0.5 s.

    Use ``brief=True`` for cheap enumeration (only service-name + oper-state,
    no SAP / SDP lists at all). ``include_fdb=True`` adds the FDB subtree
    under the named service so a single round-trip can fetch service state +
    MACs together.
    """

    def __init__(
        self,
        service_name: str | None = None,
        brief: bool = False,
        include_fdb: bool = False,
    ):
        self.service_name = service_name
        self.brief = brief
        self.include_fdb = include_fdb
        self.request_filter = self._build()

    def _build(self) -> str:
        name_xml = f"<service-name>{self.service_name}</service-name>" if self.service_name else ""
        if self.brief:
            # Just keys + oper-state for cheap enumeration.
            return (
                f'<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
                f'  <service>'
                f'    <vpls>{name_xml or "<service-name/>"}<oper-state/></vpls>'
                f'  </service>'
                f'</state>'
            )
        fdb_xml = "<fdb><mac/></fdb>" if self.include_fdb else ""
        # Field-selector: avoid pulling per-SAP statistics counters (which add
        # ~45 s on a 6-SAP service). Only the leaves used by the
        # NetworkInstance reconstruction are requested.
        # NB: ``<type/>`` is NOT a leaf under spoke-sdp / mesh-sdp in the
        # Nokia state model — the PW type is conveyed by the parent container
        # name (spoke-sdp vs mesh-sdp), and the parser uses that. Requesting
        # ``<type/>`` here triggers ``MGMT_CORE #2201: Unknown element``.
        return (
            f'<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
            f'  <service>'
            f'    <vpls>'
            f'      {name_xml}'
            f'      <oper-state/>'
            f'      <sap>'
            f'        <sap-id/>'
            f'        <oper-state/>'
            f'      </sap>'
            f'      <spoke-sdp>'
            f'        <sdp-bind-id/>'
            f'        <oper-state/>'
            f'      </spoke-sdp>'
            f'      <mesh-sdp>'
            f'        <sdp-bind-id/>'
            f'        <oper-state/>'
            f'      </mesh-sdp>'
            f'      {fdb_xml}'
            f'    </vpls>'
            f'  </service>'
            f'</state>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class NokiaSdpRPCRequest:
    """Filter for Nokia SDP overlay tunnels (``/state/service/sdp``).

    The SDP is the L2 overlay tunnel referenced by spoke-/mesh-sdp bindings
    on a VPLS / EPIPE. It carries ``oper-tunnel-far-end-inet-address`` (the
    PW peer IP), ``active-lsp-type`` (rsvp / ldp / bgp), and ``sdp-oper-state``.

    Parameters
    ----------
    sdp_id:
        Restrict to one SDP (list key). When omitted, fetches the full list.
    brief:
        Use a compact field-selector filter (``<sdp-id/>`` plus
        ``<oper-tunnel-far-end-inet-address/>``) that returns ~50 bytes per
        SDP rather than the full subtree (~1 KB per SDP). Brief is enough
        for far-end-IP enrichment of remote endpoints; verified to work on
        SR OS 23 (Nokia accepts field-selectors on this list).
    """

    def __init__(self, sdp_id: int | str | None = None, brief: bool = False):
        self.sdp_id = sdp_id
        self.brief = brief
        key_xml = f"<sdp-id>{sdp_id}</sdp-id>" if sdp_id is not None else ""
        if brief:
            inner = (
                key_xml
                + ("<sdp-id/>" if not key_xml else "")
                + "<oper-tunnel-far-end-inet-address/>"
            )
        else:
            inner = key_xml
        self.request_filter = (
            f'<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
            f'  <service>'
            f'    <sdp>{inner}</sdp>'
            f'  </service>'
            f'</state>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class NokiaEpipeRPCRequest:
    """Filter for Nokia EPIPE (point-to-point L2 VPWS / VLL) services.

    YANG: ``/state/service/epipe`` (``urn:nokia.com:sros:ns:yang:sr:state``,
    submodule ``nokia-state-svc-epipe``). Mirrors :class:`NokiaServiceRPCRequest`
    for VPLS — same brief vs full distinction and the same list-key narrowing
    by ``service-name``.

    Note: EPIPE is the Ethernet pipe service; other pipe types
    (ipipe / cpipe / fpipe / apipe) live in sibling containers and would
    need their own request classes if needed.
    """

    def __init__(self, service_name: str | None = None, brief: bool = False):
        self.service_name = service_name
        self.brief = brief
        self.request_filter = self._build()

    def _build(self) -> str:
        name_xml = (
            f"<service-name>{self.service_name}</service-name>"
            if self.service_name
            else ""
        )
        if self.brief:
            return (
                f'<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
                f'  <service>'
                f'    <epipe>{name_xml or "<service-name/>"}<oper-state/></epipe>'
                f'  </service>'
                f'</state>'
            )
        # Field-selector for the same reason as VPLS (see NokiaServiceRPCRequest).
        # EPIPE is point-to-point, so no <mesh-sdp> — only <sap> + <spoke-sdp>.
        # NB: ``<type/>`` is omitted from spoke-sdp for the same reason as
        # VPLS — it's not a leaf in the Nokia state model.
        return (
            f'<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
            f'  <service>'
            f'    <epipe>'
            f'      {name_xml}'
            f'      <oper-state/>'
            f'      <sap>'
            f'        <sap-id/>'
            f'        <oper-state/>'
            f'      </sap>'
            f'      <spoke-sdp>'
            f'        <sdp-bind-id/>'
            f'        <oper-state/>'
            f'      </spoke-sdp>'
            f'    </epipe>'
            f'  </service>'
            f'</state>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class NokiaFdbRPCRequest:
    """Filter for Nokia VPLS FDB (MAC) table.

    YANG: ``/state/service/vpls/<service-name>/fdb/mac``. Service name is
    a list key so when supplied the request narrows entirely server-side.
    The ``<mac>`` list is keyed by ``address``; supplying ``mac_address``
    embeds it as the key and narrows server-side. When neither is supplied
    the request walks *all* VPLS services on the device — on large platforms
    this can be slow, so the high-level client warns when neither filter is
    set.
    """

    def __init__(self, service_name: str | None = None, mac_address: str | None = None):
        self.service_name = service_name
        self.mac_address = normalize_mac(mac_address, "nokia") if mac_address else None

        name_xml = f"<service-name>{service_name}</service-name>" if service_name else ""
        mac_xml = (
            f"<mac><address>{self.mac_address}</address></mac>"
            if self.mac_address else "<mac/>"
        )
        fdb_xml = f"<fdb>{mac_xml}</fdb>"
        self.request_filter = (
            f'<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
            f'  <service>'
            f'    <vpls>{name_xml}{fdb_xml}</vpls>'
            f'  </service>'
            f'</state>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class NokiaArpRPCRequest:
    """Filter for Nokia ARP table — per Base router or per VPRN service.

    YANG path (verified against ``nokia-state-router.yang`` rev 2024-03-06,
    line ~3284): the ARP cache lives one level deeper than you might guess
    from CLI ergonomics::

        /state/router[router-name]/interface[interface-name]
          /ipv4/neighbor-discovery/neighbor[ipv4-address]

    For an L3VPN the same shape sits under
    ``/state/service/vprn[service-name]/interface[interface-name]/ipv4/...``
    (provided by ``nokia-state-svc-vprn.yang``).

    Note: the legacy ``<arp/>`` filter we tried first ("show router arp" CLI
    parlance) returns rpc-error "Unknown element" — Nokia's state model has
    no ``arp`` container, only ``neighbor-discovery/neighbor``. The list key
    is ``ipv4-address`` so passing it narrows server-side. ``interface-name``
    is also a list key and can be passed to scope to one L3 interface.
    """

    def __init__(
        self,
        router_name: str = "Base",
        vprn_service_name: str | None = None,
        interface_name: str | None = None,
        ipv4_address: str | None = None,
    ):
        self.router_name = router_name
        self.vprn_service_name = vprn_service_name
        self.interface_name = interface_name
        self.ipv4_address = ipv4_address

        if_keys = f"<interface-name>{interface_name}</interface-name>" if interface_name else "<interface-name/>"
        ip_xml = f"<ipv4-address>{ipv4_address}</ipv4-address>" if ipv4_address else ""
        nd_inner = f"<neighbor>{ip_xml}</neighbor>" if ipv4_address else "<neighbor/>"
        if_block = (
            f"<interface>"
            f"  {if_keys}"
            f"  <ipv4><neighbor-discovery>{nd_inner}</neighbor-discovery></ipv4>"
            f"</interface>"
        )

        if vprn_service_name:
            self.request_filter = (
                f'<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
                f'  <service>'
                f'    <vprn>'
                f'      <service-name>{vprn_service_name}</service-name>'
                f'      {if_block}'
                f'    </vprn>'
                f'  </service>'
                f'</state>'
            )
        else:
            self.request_filter = (
                f'<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
                f'  <router>'
                f'    <router-name>{router_name}</router-name>'
                f'    {if_block}'
                f'  </router>'
                f'</state>'
            )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiL2vpnRPCRequest:
    """Filter for the Huawei L2VPN instance list.

    YANG: ``/l2vpn/instances/instance[name]`` in
    ``urn:huawei:yang:huawei-l2vpn`` (verified across NE40E / NE8000 / ATN
    in VRP V8). Setting ``name`` narrows server-side via the list key.

    Note: contrary to some legacy Huawei documentation, NE-series boxes do
    NOT advertise a ``huawei-vsi`` module — VPLS and VPWS live together
    under ``huawei-l2vpn``, discriminated by an explicit ``type`` leaf on
    each instance. The OpenConfig adapter handles both shapes.
    """

    def __init__(self, name: str | None = None):
        self.name = name
        name_xml = f"<name>{name}</name>" if name else ""
        self.request_filter = (
            f'<l2vpn xmlns="urn:huawei:yang:huawei-l2vpn">'
            f'  <instances>'
            f'    <instance>{name_xml}</instance>'
            f'  </instances>'
            f'</l2vpn>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


# Back-compat alias — earlier docs referenced VSI naming.
HuaweiVsiRPCRequest = HuaweiL2vpnRPCRequest


class HuaweiMacRPCRequest:
    """Filter for Huawei MAC tables in ``urn:huawei:yang:huawei-mac``.

    The MAC table is exposed as three sibling lists keyed by
    (slot-id, vsi-name, vlan-id, address):

      * ``/mac/vsi-dynamic-macs/vsi-dynamic-mac`` — learned entries.
      * ``/mac/vsi-static-macs/vsi-static-mac`` — operator-configured.
      * ``/mac/vsi-blackhole-macs/vsi-blackhole-mac`` — drop entries.

    This builder by default queries the *dynamic* list (the common case);
    pass ``include_static=True`` to also pull static + blackhole entries
    in one round-trip. ``vsi_name`` and ``mac_address`` are list keys and
    narrow server-side.
    """

    def __init__(
        self,
        vsi_name: str | None = None,
        mac_address: str | None = None,
        include_static: bool = False,
    ):
        self.vsi_name = vsi_name
        self.mac_address = normalize_mac(mac_address, "huawei") if mac_address else None
        self.include_static = include_static

        parts = []
        if vsi_name:
            parts.append(f"<vsi-name>{vsi_name}</vsi-name>")
        if self.mac_address:
            parts.append(f"<address>{self.mac_address}</address>")
        keys = "".join(parts)

        lists = [f"<vsi-dynamic-macs><vsi-dynamic-mac>{keys}</vsi-dynamic-mac></vsi-dynamic-macs>"]
        if include_static:
            lists.append(f"<vsi-static-macs><vsi-static-mac>{keys}</vsi-static-mac></vsi-static-macs>")
            lists.append(
                f"<vsi-blackhole-macs><vsi-blackhole-mac>{keys}</vsi-blackhole-mac></vsi-blackhole-macs>"
            )

        self.request_filter = (
            f'<mac xmlns="urn:huawei:yang:huawei-mac">' + "".join(lists) + "</mac>"
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiArpRPCRequest:
    """Filter for Huawei ARP table.

    YANG: ``/arp/query-entries/query-entry`` in
    ``urn:huawei:yang:huawei-arp``. Filter keys:

      * ``vpn_instance`` → ``ni-name`` (VPN/VRF). Pass an empty string to
        match only entries with an empty ``ni-name`` (rare).
      * ``ip_address`` → ``ip-addr`` (list key — exact IP).
    """

    def __init__(self, vpn_instance: str | None = None, ip_address: str | None = None):
        self.vpn_instance = vpn_instance
        self.ip_address = ip_address

        parts = []
        if vpn_instance is not None:
            parts.append(f"<ni-name>{vpn_instance}</ni-name>")
        if ip_address:
            parts.append(f"<ip-addr>{ip_address}</ip-addr>")
        inner = "".join(parts)

        self.request_filter = (
            f'<arp xmlns="urn:huawei:yang:huawei-arp">'
            f'  <query-entries>'
            f'    <query-entry>{inner}</query-entry>'
            f'  </query-entries>'
            f'</arp>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


# =====================================================================
# L3VPN (VRF) and L3-interface RPC request builders.
# =====================================================================


class NokiaVprnRPCRequest:
    """Filter for the Nokia VPRN (L3VPN / VRF) service list.

    YANG: ``/state/service/vprn[service-name]``
    (``urn:nokia.com:sros:ns:yang:sr:state``).

    Operational note (verified on SR OS 23): the *full* VPRN subtree is the
    entire routing table of the VRF — querying ``<vprn><service-name>X
    </service-name></vprn>`` times out. We therefore always use a
    field-selected filter: ``service-name`` + ``oper-state`` +
    ``oper-route-distinguisher``. ``route-distinguisher`` / ``vrf-target``
    do NOT exist as top-level leaves (rpc-error "Unknown element"); the RD
    we surface is the operational one.

    Known schema constraint
    -----------------------
    The Nokia VPRN state-tree does NOT expose ``<admin-state/>`` as a leaf —
    including it triggers ``MGMT_CORE #2201 Unknown element`` and the whole
    RPC fails (the device returns an empty / error response, so the
    ``service-name`` filter silently yields zero parsed VPRNs). This is a
    schema gap, not a pynetcom bug: only ``oper-state`` is published. As a
    result :attr:`NokiaVprnService.enabled` stays ``None`` for VPRNs —
    vendor-asymmetric with VPLS/EPIPE, but unavoidable.
    """

    # ``oper-state`` carries the runtime status, ``oper-route-distinguisher``
    # the operational RD. ``admin-state`` is deliberately NOT requested — see
    # the class docstring for why.
    _FIELDS = "<oper-state/><oper-route-distinguisher/>"

    def __init__(self, service_name: str | None = None):
        self.service_name = service_name
        name_xml = (
            f"<service-name>{service_name}</service-name>"
            if service_name
            else "<service-name/>"
        )
        self.request_filter = (
            f'<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
            f'  <service>'
            f'    <vprn>{name_xml}{self._FIELDS}</vprn>'
            f'  </service>'
            f'</state>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiL3vpnRPCRequest:
    """Filter for the Huawei L3VPN / VRF instance list.

    YANG: ``/network-instance/instances/instance[name]`` in
    ``urn:huawei:yang:huawei-network-instance`` — NOT ``huawei-l3vpn``
    (verified May 2026: the ``huawei-l3vpn`` module's top container returns
    only a ``<statistics>`` block, no instance list).

    The brief filter selects only the ``name`` list key — cheap (~300 bytes
    for ~6 instances). The response includes synthetic / system instances
    (``_public_``, ``__LOCAL_OAM_VPN__``, ``__dcn_vpn__``) which the
    ``parse_l3vpn_response`` adapter filters out.
    """

    def __init__(self, name: str | None = None):
        self.name = name
        name_xml = f"<name>{name}</name>" if name else "<name/>"
        self.request_filter = (
            f'<network-instance xmlns="urn:huawei:yang:huawei-network-instance">'
            f'  <instances>'
            f'    <instance>{name_xml}</instance>'
            f'  </instances>'
            f'</network-instance>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class NokiaL3InterfaceRPCRequest:
    """Filter for Nokia L3 (IP) interfaces — per Base router or per VPRN.

    YANG: ``/state/router[router-name]/interface[interface-name]`` for the
    base router, ``/state/service/vprn[service-name]/interface[...]`` for a
    VPRN. The full interface subtree carries large statistics blocks, so we
    field-select: ``interface-name`` + ``oper-state`` + ``oper-ip-mtu`` +
    ``ipv4/oper-state`` + ``ipv4/primary`` (the ``primary`` block holds
    ``oper-address``). The SR OS state model exposes no prefix-length here.
    """

    _IF_FIELDS = (
        "<oper-state/><oper-ip-mtu/>"
        "<ipv4><oper-state/><primary/></ipv4>"
    )

    def __init__(
        self,
        router_name: str = "Base",
        vprn_service_name: str | None = None,
        interface_name: str | None = None,
    ):
        self.router_name = router_name
        self.vprn_service_name = vprn_service_name
        self.interface_name = interface_name

        if_keys = (
            f"<interface-name>{interface_name}</interface-name>"
            if interface_name
            else "<interface-name/>"
        )
        if_block = f"<interface>{if_keys}{self._IF_FIELDS}</interface>"

        if vprn_service_name:
            self.request_filter = (
                f'<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
                f'  <service>'
                f'    <vprn>'
                f'      <service-name>{vprn_service_name}</service-name>'
                f'      {if_block}'
                f'    </vprn>'
                f'  </service>'
                f'</state>'
            )
        else:
            self.request_filter = (
                f'<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
                f'  <router>'
                f'    <router-name>{router_name}</router-name>'
                f'    {if_block}'
                f'  </router>'
                f'</state>'
            )

    def get_request_filter(self) -> str:
        return self.request_filter


class NokiaVprnInterfaceVplsRPCRequest:
    """Filter for Nokia R-VPLS interface→VPLS bindings.

    YANG path: ``/configure/service/vprn[service-name]/interface[interface-name]/vpls``
    in the **configure** namespace (``urn:nokia.com:sros:ns:yang:sr:conf``).
    Each VPRN-interface bound to a routed-VPLS carries a ``vpls`` sub-element
    with a single ``vpls-name`` leaf naming the VPLS. Pure-L3 VPRN interfaces
    omit the ``vpls`` element entirely (so the binding map naturally has only
    bound entries).

    ``vprn_service_name`` narrows server-side to one VPRN; without it the
    request returns every VPRN's interfaces. The fetched subtree is tiny —
    only the binding leaves, no IP / counters / VRRP block.

    Note: this RPC uses ``<get-config source="running">`` rather than ``<get>``
    on state, because the binding is configured (and the configure namespace
    on modern SR OS releases also surfaces the running config). The high-level
    ServicesClient layer chooses the right verb.
    """

    def __init__(self, vprn_service_name: str | None = None):
        self.vprn_service_name = vprn_service_name

        svc_key = (
            f"<service-name>{vprn_service_name}</service-name>"
            if vprn_service_name
            else "<service-name/>"
        )
        # Only request the binding-related leaves. <vpls/> is empty -> any
        # nested vpls sub-element comes back; <interface-name/> is the list
        # key so we always get it.
        self.request_filter = (
            f'<configure xmlns="urn:nokia.com:sros:ns:yang:sr:conf">'
            f'  <service>'
            f'    <vprn>'
            f'      {svc_key}'
            f'      <interface>'
            f'        <interface-name/>'
            f'        <vpls/>'
            f'      </interface>'
            f'    </vprn>'
            f'  </service>'
            f'</configure>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class NokiaBaseRouterInterfaceVplsRPCRequest:
    """Filter for Nokia R-VPLS interface→VPLS bindings on the Base router.

    YANG path: ``/configure/router[router-name='Base']/interface[interface-name]/vpls``
    in the **configure** namespace (``urn:nokia.com:sros:ns:yang:sr:conf``).
    This is the Base-router counterpart of
    :class:`NokiaVprnInterfaceVplsRPCRequest` — same binding shape (``vpls``
    sub-element with a single ``vpls-name`` leaf), but the parent is the
    global router rather than a VPRN.

    Always scoped to ``router-name=Base`` (the only router-name on the
    Base namespace). Pure-L3 interfaces omit the ``vpls`` element entirely
    so the binding map naturally contains only bound R-VPLS interfaces.

    Uses ``<get-config source="running">`` (caller-driven via
    :meth:`NetconfClient.get_config`), since the binding is a configured
    leaf.
    """

    def __init__(self):
        self.request_filter = (
            '<configure xmlns="urn:nokia.com:sros:ns:yang:sr:conf">'
            '  <router>'
            '    <router-name>Base</router-name>'
            '    <interface>'
            '      <interface-name/>'
            '      <vpls/>'
            '    </interface>'
            '  </router>'
            '</configure>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiL3InterfaceRPCRequest:
    """Filter for Huawei L3 (IP) interfaces.

    YANG: ``/ifm/interfaces/interface`` in ``urn:huawei:yang:huawei-ifm``.
    Each interface carries ``vrf-name`` (the VRF binding; ``_public_`` for
    the global instance) and, when it has an IP, an ``ipv4`` subtree in the
    ``urn:huawei:yang:huawei-ip`` namespace with ``addresses/address``
    (``ip`` + ``mask`` + ``type``).

    ``interface_name`` is the YANG list key and narrows server-side. There
    is no server-side filter on ``vrf-name`` (not a list key) — the
    high-level client filters by VRF client-side.
    """

    def __init__(self, interface_name: str | None = None):
        self.interface_name = interface_name
        name_xml = (
            f"<name>{interface_name}</name>" if interface_name else "<name/>"
        )
        self.request_filter = (
            f'<ifm xmlns="urn:huawei:yang:huawei-ifm">'
            f'  <interfaces>'
            f'    <interface>'
            f'      {name_xml}<vrf-name/><admin-status/>'
            f'      <ipv4 xmlns="urn:huawei:yang:huawei-ip">'
            f'        <addresses><address><ip/><mask/><type/></address></addresses>'
            f'      </ipv4>'
            f'    </interface>'
            f'  </interfaces>'
            f'</ifm>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiVeGroupRPCRequest:
    """Filter for Huawei VE-group L2-L3 bindings.

    Reads the ``ve-groups`` augment that ``huawei-fim-ifm`` places under
    ``/ifm/global`` (namespace ``urn:huawei:yang:huawei-ifm``, augment
    ``urn:huawei:yang:huawei-fim-ifm``). Each entry pairs an L2 Virtual-
    Ethernet **parent** with its L3 partner via a shared ``ve-group-id``:

      ``{"ve-group-id": "1",
         "slot-id": "0",
         "l2-ve-ifname": "Virtual-Ethernet0/2/2(L2)",
         "l3-ve-ifname": "Virtual-Ethernet0/2/3(L3)"}``

    The pairing is between PARENT interfaces; sub-interfaces inherit it
    through their VLAN tag (e.g. ``Virtual-Ethernet0/2/2.2300`` ↔
    ``Virtual-Ethernet0/2/3.2300`` share ve-group-id 1). The ``(L2)``/``(L3)``
    suffixes are decorative role markers on the interface name string;
    parsers strip them.

    This subtree is tiny (one entry per configured VE-group) so we always
    fetch it whole — no list-key narrowing.
    """

    def __init__(self):
        self.request_filter = (
            '<ifm xmlns="urn:huawei:yang:huawei-ifm" '
            'xmlns:fim-ifm="urn:huawei:yang:huawei-fim-ifm">'
            '<global><fim-ifm:ve-groups/></global>'
            '</ifm>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter