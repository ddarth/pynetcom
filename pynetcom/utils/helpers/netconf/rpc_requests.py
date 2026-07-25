from string import Template
from pynetcom.utils.huawei_router_tools import split_if_to_type_id_tag
import re
from typing import Optional, Tuple


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

    def __init__(self, port: str, transceiver_prefix: str, include_lldp: bool = True):
        self.port = port
        self.transceiver_prefix = transceiver_prefix
        # When False, the LLDP subtree is dropped from the filter. Needed for
        # Huawei interfaces that reject the whole <get> with "LLDP is not
        # supported on this port" (loopbacks / logical interfaces) — see
        # :class:`pynetcom.exceptions.HuaweiLldpNotSupported`.
        self.include_lldp = include_lldp
        self.request_filter = self.get_template().substitute(port=self.port, transceiver_prefix=self.transceiver_prefix)

    def get_template(self) -> Template:
        lldp = self.lldp if self.include_lldp else ""
        return Template(self.interface + self.transceiver + lldp)

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
    # Filter for Eth-Trunk (LAG) interfaces: OpenConfig aggregation (state /
    # lag-speed) plus the huawei-ifm-trunk augment that carries the member
    # list. Huawei does NOT populate the OpenConfig ``<member>`` leaf-list,
    # so the members come from ``/ifm/interfaces/interface/trunk/members/
    # member/name`` (device-format names, e.g. ``"50|100GE6/1/2"``). The
    # field-select (``<name/><status/>`` only) keeps the heavy LACP subtree
    # out of the reply. Verified live 24 Jul 2026 on ``Bc.MSC4_.NE_02.X8``
    # (Eth-Trunk1 → members ``50|100GE6/1/2``, ``50|100GE4/0/0``).
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
<ifm xmlns="urn:huawei:yang:huawei-ifm">
  <interfaces>
    <interface>
      <name>$port</name>
      <trunk xmlns="urn:huawei:yang:huawei-ifm-trunk">
        <members>
          <member>
            <name/>
            <status/>
          </member>
        </members>
      </trunk>
    </interface>
  </interfaces>
</ifm>
"""

    def __init__(self, port: str, include_lldp: bool = True):
        self.include_lldp = include_lldp
        # Eth-Trunk interfaces: use simplified OpenConfig + huawei-ifm-trunk
        # filter (aggregation + member list). No LLDP subtree here — LAGs
        # carry no LLDP agent, so this path never hits HuaweiLldpNotSupported.
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
        lldp = self.lldp if self.include_lldp else ""
        return Template(self.interface + self.transceiver + lldp + self.huawei_interface)

    def get_position(self) -> str:
        """Get position of the interface"""
        return split_if_to_type_id_tag(self.port)['if_pos']


class HuaweiMultiPortInterfaceRPCRequest:
    """Batch per-port detail (status + optics) for several Huawei ports in one ``<get>``.

    Motivation
    ----------
    Resolving the optics of every physical member of a LAG would otherwise
    cost one round-trip per member. This builder OR-combines the port keys
    into a single subtree filter (same batching idea as
    :class:`NokiaArpRPCRequest` / :class:`HuaweiMacRPCRequest`) so N members
    cost ONE round-trip. Verified live 24 Jul 2026 on ``Bc.MSC4_.NE_02.X8``
    (two 100G members in one reply).

    Composition (mirrors the single-port :class:`HuaweiInterfaceRPCRequest`
    field-selection, repeated per port):

      * ``/devm/ports/port[position]`` (huawei-devm + huawei-pic) —
        ``optical-module`` (aggregate + per-channel Tx/Rx), ``ethernet``
        (speed / duplex / negotiation), ``physical-bandwidth`` and the
        last-up/down timestamps. This is the optics source.
      * ``/interfaces/interface[name]/state`` (OpenConfig) — oper / admin
        status, description. Keyed by the device-format interface name.
      * ``/components/component[name=TRANSCEIVER:<port>]/transceiver/state/
        present`` (OpenConfig platform) — the module-present flag, keyed by
        the ``TRANSCEIVER:`` + device-format name (same key the single-port
        :class:`HuaweiInterfaceRPCRequest` uses). Without this component the
        parsed ``present`` stays ``None`` and
        :meth:`OpenconfigTranseiver.to_output_dict` drops the measured optics
        as if no module were inserted. Field-selected to ``state/present``
        only — the tx/rx power come from the ``devm`` optical-module, so the
        heavy OC transceiver subtree is intentionally not pulled.

    LLDP is intentionally absent (batch is for physical carriers; the
    per-lane / status data does not need it, and dropping it avoids the
    ``LLDP is not supported`` failure on any non-LLDP member).

    :param ports: device-format interface names (e.g. ``["50|100GE6/1/2",
        "50|100GE4/0/0"]``). The ``position`` for the ``devm`` key is derived
        from each name via ``split_if_to_type_id_tag``. Parse the reply with
        :func:`~pynetcom.utils.helpers.netconf.rpc_data_containers.huawei.parse_multi_port_interface_response`.
    :type ports: list[str]
    """

    def __init__(self, ports: list):
        self.ports = list(ports or [])
        devm_blocks = []
        oc_blocks = []
        comp_blocks = []
        for name in self.ports:
            position = split_if_to_type_id_tag(name)['if_pos']
            devm_blocks.append(
                f'<port>'
                f'<position>{position}</position>'
                f'<last-up-time/><last-down-time/>'
                f'<optical-module xmlns="urn:huawei:yang:huawei-pic"/>'
                f'<ethernet xmlns="urn:huawei:yang:huawei-pic">'
                f'<speed/><duplex-status/><negotiation/><negotiation-mode/>'
                f'</ethernet>'
                f'<physical-bandwidth/>'
                f'</port>'
            )
            oc_blocks.append(
                f'<interface><name>{name}</name><state/></interface>'
            )
            # OpenConfig platform component carrying the module-present flag.
            # Keyed by ``TRANSCEIVER:`` + device-format name — same key the
            # single-port HuaweiInterfaceRPCRequest uses. Field-selected to
            # state/present only (optics come from the devm optical-module).
            comp_blocks.append(
                f'<component>'
                f'<name>TRANSCEIVER:{name}</name>'
                f'<transceiver xmlns="http://openconfig.net/yang/platform/transceiver">'
                f'<state><present/></state>'
                f'</transceiver>'
                f'</component>'
            )
        self.request_filter = (
            '<devm xmlns="urn:huawei:yang:huawei-devm"><ports>'
            + "".join(devm_blocks)
            + '</ports></devm>'
            '<interfaces xmlns="http://openconfig.net/yang/interfaces">'
            + "".join(oc_blocks)
            + '</interfaces>'
            '<components xmlns="http://openconfig.net/yang/platform">'
            + "".join(comp_blocks)
            + '</components>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


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

    def get_connector_port(self) -> Tuple[str, str]:
        # Single-port path is strict: an unexpected port-id must fail loudly
        # rather than silently degrade to (port, port). Shares one regex with
        # the batch helper via ``strict=True``.
        return nokia_connector_breakout(self.port, strict=True)

    def __init__(self, port: str, include_lldp: bool = True):
        # ``include_lldp`` is accepted for cross-vendor API symmetry with
        # :class:`HuaweiInterfaceRPCRequest`. Nokia carries LLDP under
        # ``/state/port/ethernet/lldp`` and never rejects a port for lacking
        # it, so callers rarely need False here.
        self.include_lldp = include_lldp
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
        lldp = self.lldp if self.include_lldp else ""
        return Template(self.interface + self.transceiver + lldp + self.nokia_interface)


def nokia_connector_breakout(port: str, strict: bool = False) -> Tuple[str, str]:
    """Split a Nokia port-id into its (connector, breakout) pair.

    Single implementation shared by the per-port
    :meth:`NokiaInterfaceRPCRequest.get_connector_port` (which calls it with
    ``strict=True``) and the batch
    :class:`NokiaMultiPortInterfaceRPCRequest` (default ``strict=False``):

      * ``"5/1/c2/1"`` → ``("5/1/c2", "5/1/c2/1")`` (connector + breakout).
      * ``"5/1/c2"``   → ``("5/1/c2", "5/1/c2/1")`` (default breakout ``/1``).
      * ``"3/1/1"``    → ``("3/1/1", "3/1/1")`` (plain L/M/P, no breakout).

    :param strict: on an unrecognised port shape, ``True`` raises
        ``ValueError`` (single-port callers want to fail loudly), while
        ``False`` falls back to ``(port, port)`` so the batch path stays
        robust across a whole port list rather than aborting on one odd
        member name.
    """
    m = re.match(r"^(.+?/c\d+)(?:/(\d+))?$", port)
    if m:
        connector = m.group(1)
        breakout = f"{connector}/{m.group(2) or '1'}"
        return connector, breakout
    if re.match(r"^\d+/\d+/\d+$", port):
        return port, port
    if strict:
        raise ValueError(f"Unexpected port format: {port}")
    return port, port


class NokiaMultiPortInterfaceRPCRequest:
    """Batch per-port detail (status + optics) for several Nokia ports in one ``<get>``.

    Nokia counterpart of :class:`HuaweiMultiPortInterfaceRPCRequest`. OR-combines
    several ``/state/port`` keys (plus the OpenConfig interface state) into a
    single subtree filter so the optics of every physical LAG member cost
    ONE round-trip. Verified live 24 Jul 2026 on ``Oc.MSC_3.CR_01``.

    Per requested port the filter emits the same two ``/state/port`` entries
    the single-port :class:`NokiaInterfaceRPCRequest` uses:

      * connector port-id + ``<transceiver/>`` (optics, incl. per-lane
        ``digital-diagnostic-monitoring/lane`` for 100G modules), and
      * breakout port-id + ``oper-state-last-changed`` + ``ethernet``
        (egress-rate),

    plus one OpenConfig ``/interfaces/interface[name]/state`` block for
    oper / admin status. LLDP is omitted (optics/status batch).

    :param ports: Nokia port-ids (e.g. ``["4/2/1", "3/1/1"]``). Parse the
        reply with
        :func:`~pynetcom.utils.helpers.netconf.rpc_data_containers.nokia_sros.parse_multi_port_interface_response`,
        passing the same list.
    :type ports: list[str]
    """

    def __init__(self, ports: list):
        self.ports = list(ports or [])
        state_blocks = []
        oc_blocks = []
        for port in self.ports:
            connector, breakout = nokia_connector_breakout(port)
            state_blocks.append(
                f'<port><port-id>{connector}</port-id><transceiver/></port>'
                f'<port><port-id>{breakout}</port-id>'
                f'<oper-state-last-changed/>'
                f'<ethernet><oper-egress-rate/></ethernet>'
                f'</port>'
            )
            oc_blocks.append(
                f'<interface><name>{breakout}</name><state/></interface>'
            )
        self.request_filter = (
            '<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
            + "".join(state_blocks)
            + '</state>'
            '<interfaces xmlns="http://openconfig.net/yang/interfaces">'
            + "".join(oc_blocks)
            + '</interfaces>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


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


class NokiaPortConfigRPCRequest:
    """Filter for Nokia SR OS port-level configure data (``encap-type``).

    YANG: ``/configure/port[port-id]/ethernet/encap-type``
    (``urn:nokia.com:sros:ns:yang:sr:conf`` — *configure* namespace, not state).

    Purpose
    -------
    The vendor-agnostic
    :attr:`~pynetcom.utils.helpers.netconf.rpc_data_containers.openconfig.OpenconfigInterface.encap_type`
    indicator (``"null"`` / ``"dot1q"`` / ``"qinq"``) needs a Nokia source.
    The state-tree (``urn:nokia.com:sros:ns:yang:sr:state``) does NOT
    expose a port encap-type leaf — there is no equivalent under
    ``/state/port/<port-id>/ethernet/``. The intent lives only in the
    configure datastore.

    Usage
    -----
    Always pair with :meth:`NetconfClient.get_config` and
    ``with_defaults="report-all"`` — otherwise default-valued
    ``<encap-type>null</encap-type>`` leaves are omitted from the response
    and untagged ports drop out silently (verified on SR OS 23: probe of
    32 ports returns 7 ``dot1q`` entries and 0 ``null`` entries without
    ``report-all``; with ``report-all`` returns all 32). Pair with
    :func:`~pynetcom.utils.helpers.netconf.rpc_data_containers.nokia_sros.parse_port_encap_type_map`
    to materialise the response into a ``{port_id: encap_type}`` dict, then
    :func:`~pynetcom.utils.helpers.netconf.rpc_data_containers.nokia_sros.apply_port_encap_type_map`
    to merge into per-port :class:`NokiaInterface` objects::

        req = NokiaPortConfigRPCRequest()              # all ports (bulk)
        resp = nc.get_config(
            source="running",
            filter_subtree=req.get_request_filter(),
            with_defaults="report-all",
        )
        encap_map = parse_port_encap_type_map(resp)    # {port_id: encap_type}
        apply_port_encap_type_map(interfaces, encap_map)

    Cost
    ----
    Bulk get-config over all ports on a 32-port 7250 IXR returns ~2 KB
    and completes in <0.5 s (verified). Per-port narrowing
    (``port_id="1/1/15"``) is available but unnecessary at this size —
    network_entries calls this once per router, not per port.

    Parameters
    ----------
    port_id:
        Optional list-key narrowing. When provided, filters server-side
        to one port; when omitted, returns all ports on the router.
    """

    def __init__(self, port_id: Optional[str] = None):
        self.port_id = port_id
        key_xml = f"<port-id>{port_id}</port-id>" if port_id else "<port-id/>"
        self.request_filter = (
            f'<configure xmlns="urn:nokia.com:sros:ns:yang:sr:conf">'
            f'  <port>'
            f'    {key_xml}'
            f'    <ethernet>'
            f'      <encap-type/>'
            f'    </ethernet>'
            f'  </port>'
            f'</configure>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiSubInterfaceListRPCRequest:
    """Filter for Huawei ``ifm`` interface list with class + parent-name only.

    YANG: ``/ifm/interfaces/interface`` (``urn:huawei:yang:huawei-ifm``).
    Field-selected to three leaves (``name``, ``class``, ``parent-name``)
    so the response is cheap even on big devices (one ~5 KB payload for
    ~115 interfaces verified on an ATN-910C).

    Purpose
    -------
    The vendor-agnostic
    :attr:`~pynetcom.utils.helpers.netconf.rpc_data_containers.openconfig.OpenconfigInterface.encap_type`
    indicator for Huawei is derived from the *presence of sub-interfaces*
    under a parent port — Huawei does not expose an explicit per-port
    encap-type leaf (probed live: no such leaf on
    ``/ifm/interfaces/interface`` or on ``/devm/ports/port/ethernet``).
    A parent port with at least one ``class=sub-interface`` child whose
    ``parent-name`` matches the port name is operating in dot1q mode;
    otherwise it is untagged (``null``).

    The ``parent-name`` leaf is NOT a valid Huawei list filter key
    (probed live: ``<parent-name>$value</parent-name>`` returns
    ``RPCError: This operation is not supported``). The list key is
    ``name``. Therefore we cannot narrow server-side by parent and must
    fetch the whole interface list — but the field-selection keeps it
    cheap.

    Pair with
    :func:`~pynetcom.utils.helpers.netconf.rpc_data_containers.huawei.parse_sub_interface_parents`
    to materialise into a ``{parent_name: [child_names]}`` index, then
    :func:`~pynetcom.utils.helpers.netconf.rpc_data_containers.huawei.apply_sub_interface_index`
    (or :meth:`HuaweiInterface.derive_encap_type`) to stamp ``encap_type``.
    """

    template: str = (
        '<ifm xmlns="urn:huawei:yang:huawei-ifm">'
        '  <interfaces>'
        '    <interface>'
        '      <name/>'
        '      <class/>'
        '      <parent-name/>'
        '    </interface>'
        '  </interfaces>'
        '</ifm>'
    )

    def __init__(self):
        self.request_filter = self.template

    def get_request_filter(self) -> str:
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

    Note: ``admin-state`` leaf is absent on the Nokia VPLS / EPIPE state-tree
    (same as VPRN). A probe RPC requesting ``<admin-state/>`` either at the
    VPLS level or inside ``<sap>`` returns ``MGMT_CORE #2201: Unknown element``
    (``error-path /a:state/a:service/a:vpls[...]/a:admin-state``,
    ``bad-element=admin-state``). Admin intent lives only under
    ``/configure/service/...`` (configure namespace, configure datastore),
    and only with ``with-defaults="report-all"`` (otherwise default-valued
    ``enable`` leaves are omitted from the response). Use
    :class:`NokiaServiceSapAdminStateRPCRequest` together with
    ``ServicesClient.get_l2vpn_services(enrich_admin_state=True)`` to populate
    :attr:`LocalEndpoint.admin_status` on Nokia SAPs.
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
            # Just keys + oper-state + per-service counters for cheap enumeration.
            # ``sap-count`` and ``sdp-bind-count`` are state-tree leaves that
            # Nokia surfaces directly on the <vpls> container (verified live on
            # SR OS 23). Including them in brief lets list-mode answer
            # "how many SAPs/PWs does this service have" without walking the
            # per-SAP / per-PW lists — counts are still authoritative via
            # ``len(svc.saps())`` / ``len(svc.pseudowires())`` whenever the
            # full payload was fetched. See :attr:`NetworkInstance.sap_count_hint`
            # / :attr:`NetworkInstance.pw_count_hint`.
            return (
                f'<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
                f'  <service>'
                f'    <vpls>{name_xml or "<service-name/>"}<oper-state/><sap-count/><sdp-bind-count/></vpls>'
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


class NokiaServiceSapAdminStateRPCRequest:
    """Filter for Nokia SR OS SAP ``admin-state`` in the configure datastore.

    The state-tree (``urn:nokia.com:sros:ns:yang:sr:state``) does NOT expose
    a SAP ``admin-state`` leaf — see :class:`NokiaServiceRPCRequest` docstring.
    The admin intent is only published in the *configure* namespace
    (``urn:nokia.com:sros:ns:yang:sr:conf``), and only via
    ``<get-config source="running">`` with ``with-defaults="report-all"``
    (otherwise default-valued ``<admin-state>enable</admin-state>`` leaves
    are omitted and the operator can't distinguish "implicit enable" from
    "leaf absent because misconfigured").

    The filter covers both VPLS (multipoint) and EPIPE (point-to-point)
    services in a single round-trip. When ``service_name`` is given, the
    list-key narrows server-side; an EPIPE-only or VPLS-only service simply
    returns an empty list for the other container, which the parser tolerates.

    Usage::

        req = NokiaServiceSapAdminStateRPCRequest(service_name="VPLS_X")
        resp = nc.get_config(
            source="running",
            filter_subtree=req.get_request_filter(),
            with_defaults="report-all",
        )
        admin_map = parse_sap_admin_state_response(resp)
        # -> {("VPLS_X", "1/1/11:100"): "enabled", ...}
    """

    def __init__(self, service_name: str | None = None):
        self.service_name = service_name
        name_xml = (
            f"<service-name>{service_name}</service-name>" if service_name else ""
        )
        self.request_filter = (
            f'<configure xmlns="urn:nokia.com:sros:ns:yang:sr:conf">'
            f'  <service>'
            f'    <vpls>'
            f'      {name_xml}'
            f'      <sap>'
            f'        <sap-id/>'
            f'        <admin-state/>'
            f'      </sap>'
            f'    </vpls>'
            f'    <epipe>'
            f'      {name_xml}'
            f'      <sap>'
            f'        <sap-id/>'
            f'        <admin-state/>'
            f'      </sap>'
            f'    </epipe>'
            f'  </service>'
            f'</configure>'
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
        ``<oper-tunnel-far-end-inet-address/>`` plus ``<active-lsp-type/>``)
        that returns ~80 bytes per SDP rather than the full subtree
        (~1 KB per SDP). Brief is enough for both far-end-IP enrichment AND
        signaling-type derivation on remote endpoints; verified to work on
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
                + "<active-lsp-type/>"
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


class NokiaServiceVplsSpokeSdpConfigRPCRequest:
    """Filter for Nokia VPLS spoke-sdp config leaves (configure-NS).

    YANG path: ``/configure/service/vpls[service-name]/spoke-sdp[sdp-bind-id]``
    in ``urn:nokia.com:sros:ns:yang:sr:conf``. Field-selected to the leaves
    needed to populate :attr:`RemoteEndpoint.encapsulation_type` and
    :attr:`RemoteEndpoint.redundancy_role`:

      * ``<vc-type/>`` → ``encapsulation_type`` (``ether`` / ``vlan``).
      * ``<endpoint><precedence/></endpoint>`` → ``redundancy_role``
        (``primary`` / ``secondary``).

    Issue with ``<get-config source="running">`` and
    ``with_defaults="report-all"`` so default-valued leaves
    (``<vc-type>ether</vc-type>`` is the default on most platforms) come
    back instead of being silently dropped.

    ``service_name`` narrows server-side to one VPLS; omit to scan every
    VPLS in one shot.
    """

    def __init__(self, service_name: str | None = None):
        self.service_name = service_name
        name_xml = (
            f"<service-name>{service_name}</service-name>" if service_name else ""
        )
        self.request_filter = (
            f'<configure xmlns="urn:nokia.com:sros:ns:yang:sr:conf">'
            f'  <service>'
            f'    <vpls>'
            f'      {name_xml}'
            f'      <spoke-sdp>'
            f'        <sdp-bind-id/>'
            f'        <vc-type/>'
            f'        <endpoint>'
            f'          <precedence/>'
            f'        </endpoint>'
            f'      </spoke-sdp>'
            f'    </vpls>'
            f'  </service>'
            f'</configure>'
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

    Note: same ``admin-state`` limitation as :class:`NokiaServiceRPCRequest`
    — that leaf is not exposed on Nokia state-tree for L2 services.
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
            # Same rationale as VPLS brief — include the device-side
            # ``sap-count`` / ``sdp-bind-count`` counters so list-mode answers
            # endpoint cardinality questions without walking the lists.
            return (
                f'<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
                f'  <service>'
                f'    <epipe>{name_xml or "<service-name/>"}<oper-state/><sap-count/><sdp-bind-count/></epipe>'
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
    """Filter for Nokia VPLS FDB (MAC) table — list-input batched.

    YANG: ``/state/service/vpls[service-name]/fdb/mac[address]`` in
    ``urn:nokia.com:sros:ns:yang:sr:state``. ``service-name`` is the list
    key for VPLS and narrows server-side; ``address`` is the list key for
    ``<mac>`` and likewise narrows server-side.

    Batch (list-input) semantics — verified live on Nokia SR OS, 26-28 May
    2026, ground-truth XML in ``examples/xml/Nokia 7250/services/``:

      * ``mac_addresses`` non-empty → emit one ``<mac><address>M</address></mac>``
        sibling per MAC inside the single ``<fdb>``. Sibling list-key
        elements are OR-combined server-side (RFC 6241 §6.2.2), so the
        device returns the union of "any of these MACs". Mirrors
        ``get_fdb_by_mac_multi.xml`` exactly.
      * ``mac_addresses`` empty / None → single empty ``<mac/>`` (full FDB
        dump for the scoped VPLS — or for ALL VPLSes if ``service_name``
        is also None, which the high-level client warns against).

    ``service_name`` stays single in this builder by design (Nokia VPLS
    list key) — multi-VPLS FDB fan-out is a higher-level concern. MAC
    normalisation is applied inside the builder via :func:`normalize_mac`
    (Nokia colon-form); idempotent for any common separator style.
    """

    def __init__(
        self,
        service_name: str | None = None,
        mac_addresses: list[str] | None = None,
    ):
        self.service_name = service_name
        # Normalise MACs to Nokia colon-form once at build time. Empty list
        # is treated as None — no per-key filter, single <mac/> placeholder.
        self.mac_addresses = (
            [normalize_mac(m, "nokia") for m in mac_addresses]
            if mac_addresses else None
        )

        name_xml = f"<service-name>{service_name}</service-name>" if service_name else ""
        if self.mac_addresses:
            mac_xml = "".join(
                f"<mac><address>{m}</address></mac>" for m in self.mac_addresses
            )
        else:
            mac_xml = "<mac/>"
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

    Batch (list-input) semantics — verified live on Nokia SR OS, 24-26 May
    2026, ground-truth XML in ``examples/xml/Nokia 7250/services/``
    (``get_arp_by_ip_*.xml``, ``get_arp_by_mac_*.xml``,
    ``get_arp_multi_vprn*.xml``):

      * ``vprn_service_names`` non-empty → repeat ``<vprn>`` for each VPRN
        (RFC 6241 §6.2.2: sibling list keys are OR-combined server-side).
      * ``vprn_service_names`` empty / None → fall back to ``<router>`` with
        ``router_name``.
      * ``ipv4_addresses`` and ``mac_addresses`` non-empty → emit one
        ``<neighbor>`` element per IPv4 address AND one per MAC address
        inside the same ``<neighbor-discovery>``. The server OR-combines
        them so the response is the union of "any of these IPs" and "any
        of these MACs". MAC content-match is supported on Nokia (Huawei
        does NOT — kept asymmetric in :class:`HuaweiArpRPCRequest`).
      * Both lists empty → single empty ``<neighbor/>`` (full dump).

    MAC normalisation is applied inside the builder via
    :func:`normalize_mac` (Nokia colon-form), so the caller does not have
    to pre-format input. Idempotent: passing canonical MAC is a no-op.
    """

    def __init__(
        self,
        router_name: str = "Base",
        vprn_service_names: list[str] | None = None,
        interface_name: str | None = None,
        ipv4_addresses: list[str] | None = None,
        mac_addresses: list[str] | None = None,
    ):
        self.router_name = router_name
        self.vprn_service_names = vprn_service_names or None
        self.interface_name = interface_name
        self.ipv4_addresses = ipv4_addresses or None
        # Normalise MACs to Nokia colon-form once at build time. Cheap,
        # idempotent, lets every caller paste any separator style without
        # leaking malformed input into the device.
        self.mac_addresses = (
            [normalize_mac(m, "nokia") for m in mac_addresses]
            if mac_addresses else None
        )

        if_keys = f"<interface-name>{interface_name}</interface-name>" if interface_name else "<interface-name/>"

        # Build the <neighbor> list — one per IPv4, one per MAC. Sibling
        # <neighbor> elements are OR-combined by the NETCONF server
        # (content-match semantics, RFC 6241 §6.2.2).
        neighbor_xml_parts: list[str] = []
        if self.ipv4_addresses:
            for ip in self.ipv4_addresses:
                neighbor_xml_parts.append(
                    f"<neighbor><ipv4-address>{ip}</ipv4-address></neighbor>"
                )
        if self.mac_addresses:
            for m in self.mac_addresses:
                neighbor_xml_parts.append(
                    f"<neighbor><mac-address>{m}</mac-address></neighbor>"
                )
        if not neighbor_xml_parts:
            # Full-table dump path.
            neighbor_xml_parts.append("<neighbor/>")
        nd_inner = "".join(neighbor_xml_parts)

        if_block = (
            f"<interface>"
            f"  {if_keys}"
            f"  <ipv4><neighbor-discovery>{nd_inner}</neighbor-discovery></ipv4>"
            f"</interface>"
        )

        if self.vprn_service_names:
            vprn_blocks = "".join(
                f"<vprn>"
                f"  <service-name>{name}</service-name>"
                f"  {if_block}"
                f"</vprn>"
                for name in self.vprn_service_names
            )
            self.request_filter = (
                f'<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">'
                f'  <service>'
                f'    {vprn_blocks}'
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

    Note: the AC list under ``huawei-l2vpn`` does NOT carry an
    ``admin-state`` (or ``admin-status``) leaf — the L2VPN module only
    references the interface by ``interface-name``. To learn an AC's
    admin / oper status, query ``huawei-ifm`` separately via
    :class:`HuaweiInterfaceAdminOperStateRPCRequest` and join by interface
    name. The high-level :meth:`ServicesClient.get_l2vpn_services` does this
    when called with ``enrich_admin_state=True``.
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


class HuaweiL2vpnByMemberInterfaceRPCRequest:
    """Filter for the Huawei L2VPN instance that owns a given AC interface.

    Mirrors ``examples/xml/Huawei/services/get_l2vpn_by_member_interface.xml``
    exactly. The wire format is::

        <l2vpn xmlns="urn:huawei:yang:huawei-l2vpn">
          <instances>
            <instance>
              <vpls>
                <acs>
                  <ac>
                    <interface-name>{member_interface}</interface-name>
                  </ac>
                </acs>
              </vpls>
            </instance>
          </instances>
        </l2vpn>

    Server semantics (verified live on VRP V8 NE-series, June 2026):
    the ``<interface-name>`` leaf inside ``<ac>`` acts as a CONTENT-MATCH
    filter — the server returns the single ``<instance>`` whose AC list has
    a matching interface-name, and inside that instance only the matching
    ``<ac>`` (no PWs, no FDB, no statistics — extremely cheap). Probed
    response size: ~900 B vs ~336 KB for an unfiltered dump; ~390 ms vs
    ~8.7 s wall on a 32-VSI BSC-class box (~22x speedup).

    Why this is a SEPARATE class from :class:`HuaweiL2vpnRPCRequest` (which
    supports a ``name=`` list-key narrow): adding field-selectors at the
    ``<instance>`` level (e.g. ``<name/>``, ``<type/>``, ``<state/>``)
    BREAKS the content-match. The server treats those selectors as
    "return these leaves for ALL instances", and ``<interface-name>``
    stops being a whole-instance filter, returning all VSIs instead of
    the one match. The full-dump builder uses such selectors, so it
    cannot accept ``member_interface`` without losing speed. Hence:
    dedicated builder, no shared shape.

    Negative case (no instance owns the AC): the server returns an empty
    ``<instances/>`` element. Parser tolerance covers that — see
    :func:`pynetcom.utils.helpers.netconf.rpc_data_containers.huawei_services.parse_l2vpn_response`.
    """

    def __init__(self, member_interface: str):
        if not member_interface or not isinstance(member_interface, str):
            raise ValueError(
                "HuaweiL2vpnByMemberInterfaceRPCRequest: member_interface "
                "must be a non-empty string (e.g. 'GigabitEthernet0/2/1.100')"
            )
        self.member_interface = member_interface
        self.request_filter = (
            '<l2vpn xmlns="urn:huawei:yang:huawei-l2vpn">'
            '<instances>'
            '<instance>'
            '<vpls>'
            '<acs>'
            '<ac>'
            f'<interface-name>{member_interface}</interface-name>'
            '</ac>'
            '</acs>'
            '</vpls>'
            '</instance>'
            '</instances>'
            '</l2vpn>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiMacRPCRequest:
    """Filter for Huawei MAC tables in ``urn:huawei:yang:huawei-mac`` — batched.

    The MAC table is exposed as three sibling lists keyed by
    (slot-id, vsi-name, vlan-id, address):

      * ``/mac/vsi-dynamic-macs/vsi-dynamic-mac`` — learned entries.
      * ``/mac/vsi-static-macs/vsi-static-mac`` — operator-configured.
      * ``/mac/vsi-blackhole-macs/vsi-blackhole-mac`` — drop entries.

    This builder by default queries only the *dynamic* list (the common
    case); pass ``include_static=True`` to also pull static + blackhole
    entries in one round-trip.

    Batch (list-input) semantics — verified live on Huawei VRP, 26-28 May
    2026, ground-truth XML in ``examples/xml/Huawei/services/``:

      * ``mac_addresses`` non-empty → emit one
        ``<vsi-dynamic-mac>``-block per MAC, each carrying the supplied
        ``<vsi-name>`` (if any) AND ``<address>`` as list keys. Sibling
        blocks are OR-combined server-side. Mirrors
        ``get_fdb_by_mac_multi.xml`` (no ``vsi_name``) and
        ``get_fdb_cartesian.xml`` (with ``vsi_name``) exactly.
      * ``mac_addresses`` empty / None + ``vsi_name`` set → single
        ``<vsi-dynamic-mac><vsi-name>X</vsi-name></vsi-dynamic-mac>``
        (full FDB of the scoped VSI). Mirrors ``get_fdb_multi_vsi.xml``
        shape with one VSI.
      * Both ``vsi_name`` and ``mac_addresses`` empty / None → single
        empty ``<vsi-dynamic-mac/>`` (full MAC table dump — slow, the
        high-level client warns).

    ``vsi_name`` stays single in this builder (Huawei VSI list key);
    multi-VSI fan-out is a higher-level concern. MAC normalisation is
    applied inside the builder via :func:`normalize_mac` (Huawei dash-quad
    form); idempotent for any common separator style.
    """

    def __init__(
        self,
        vsi_name: str | None = None,
        mac_addresses: list[str] | None = None,
        include_static: bool = False,
    ):
        self.vsi_name = vsi_name
        self.mac_addresses = (
            [normalize_mac(m, "huawei") for m in mac_addresses]
            if mac_addresses else None
        )
        self.include_static = include_static

        vsi_key = f"<vsi-name>{vsi_name}</vsi-name>" if vsi_name else ""

        def _block(list_outer: str, list_inner: str) -> str:
            if self.mac_addresses:
                inner = "".join(
                    f"<{list_inner}>{vsi_key}<address>{m}</address></{list_inner}>"
                    for m in self.mac_addresses
                )
            elif vsi_key:
                inner = f"<{list_inner}>{vsi_key}</{list_inner}>"
            else:
                # Self-closing empty element — full-dump path.
                inner = f"<{list_inner}/>"
            return f"<{list_outer}>{inner}</{list_outer}>"

        lists = [_block("vsi-dynamic-macs", "vsi-dynamic-mac")]
        if include_static:
            lists.append(_block("vsi-static-macs", "vsi-static-mac"))
            lists.append(_block("vsi-blackhole-macs", "vsi-blackhole-mac"))

        self.request_filter = (
            f'<mac xmlns="urn:huawei:yang:huawei-mac">' + "".join(lists) + "</mac>"
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiArpRPCRequest:
    """Filter for Huawei ARP table.

    YANG: ``/arp/query-entries/query-entry`` in
    ``urn:huawei:yang:huawei-arp``. Filter keys:

      * ``vpn_instances`` → ``ni-name`` (VPN/VRF list).
      * ``ip_addresses`` → ``ip-addr`` (list key — exact IPv4).

    Batch (list-input) semantics — verified live on Huawei VRP, 24-26 May
    2026, ground-truth XML in ``examples/xml/Huawei/services/``
    (``get_arp_by_ip_*.xml``, ``get_arp_multi_vrf*.xml``):

      * ``vpn_instances`` × ``ip_addresses`` → emit one ``<query-entry>``
        per ``(ni-name, ip-addr)`` Cartesian product (verified empirically:
        sibling ``<query-entry>`` blocks are OR-combined). This is the
        only batch shape Huawei accepts on this list — a single
        ``<query-entry>`` with multiple ``<ip-addr>`` children returns
        ``RPCError: This operation is not supported``.
      * ``ip_addresses`` only → one ``<query-entry>`` per IP (no VRF
        constraint).
      * ``vpn_instances`` only → one ``<query-entry>`` per VRF (no IP
        constraint).
      * Both ``None`` / empty → a single empty ``<query-entry/>`` (global
        full dump).

    MAC content-match: NOT supported by Huawei on this list — verified by
    probe ``arp_mac_filter/13_huawei_multi_mac_request.xml``, server replies
    ``RPCError: This operation is not supported``. Callers wanting MAC
    filtering on Huawei must apply it client-side (see
    :meth:`ServicesClient.get_arp_table`).
    """

    def __init__(
        self,
        vpn_instances: list[str] | None = None,
        ip_addresses: list[str] | None = None,
    ):
        self.vpn_instances = vpn_instances or None
        self.ip_addresses = ip_addresses or None

        # Build the <query-entry> list.
        entries: list[str] = []
        if self.vpn_instances and self.ip_addresses:
            # Cartesian product — only batch shape Huawei accepts here.
            for vpn in self.vpn_instances:
                for ip in self.ip_addresses:
                    entries.append(
                        f"<query-entry>"
                        f"<ni-name>{vpn}</ni-name>"
                        f"<ip-addr>{ip}</ip-addr>"
                        f"</query-entry>"
                    )
        elif self.vpn_instances:
            for vpn in self.vpn_instances:
                entries.append(
                    f"<query-entry><ni-name>{vpn}</ni-name></query-entry>"
                )
        elif self.ip_addresses:
            for ip in self.ip_addresses:
                entries.append(
                    f"<query-entry><ip-addr>{ip}</ip-addr></query-entry>"
                )
        else:
            # Global full dump.
            entries.append("<query-entry/>")

        self.request_filter = (
            f'<arp xmlns="urn:huawei:yang:huawei-arp">'
            f'  <query-entries>'
            f'    {"".join(entries)}'
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
    (the ``huawei-l3vpn`` module's top container only returns a
    ``<statistics>`` block, no instance list).

    Cross-namespace augment (verified May 2026, NE40E / NE8000 / ATN-910C /
    OC-NE-X8X16, VRP V8): the ``huawei-l3vpn`` module **augments** the
    ``instance`` list with an ``afs/af`` sub-container that carries
    ``route-distinguisher`` and ``state/status`` (operational up/down).
    Earlier attempts to pull RD via a cross-namespace filter "proved
    unreliable" because of two issues we now know how to side-step:

      * The list-key on the augmented ``af`` list is ``type`` (values like
        ``"ipv4-unicast"``), NOT ``af-type``. Specifying the wrong key name
        triggers ``RPCError: Unexpected element: af-type``.
      * The single field-selector for RD must be wrapped inside a properly
        namespaced ``<afs xmlns="urn:huawei:yang:huawei-l3vpn">`` element
        nested under ``<instance>``, so the device understands the augment.

    With both issues addressed, a single bulk RPC returns ``name`` + ``RD``
    + ``status`` for every VRF in ~140 ms (17 instances, ~3 KB response on
    BSC-class NE40E). This is the canonical query.

    The brief filter selects only list keys and one leaf per augment, so the
    response stays small. ``parse_l3vpn_response`` filters out the synthetic
    / system instances (``_public_``, ``__LOCAL_OAM_VPN__``, ``__dcn_vpn__``).

    :param name: optional VRF name (``instance/name`` list key) for
        server-side narrowing. ``None`` returns every configured VRF.
    """

    # The cross-namespace augment is constant; field-select RD + oper-status.
    # We intentionally pull ipv4-unicast only — IPv6-unicast augment shape is
    # identical and its presence here would double the row count without any
    # operator value (RD is configured per-VRF, not per AF, on Huawei). Other
    # AFs (vpn-target-list, tunnel-policy, ...) live in the same subtree but
    # we do not surface them in v1 — they belong in a follow-up enrichment.
    _AF_AUGMENT = (
        '<afs xmlns="urn:huawei:yang:huawei-l3vpn">'
        '  <af>'
        '    <type>ipv4-unicast</type>'
        '    <route-distinguisher/>'
        '    <state><status/></state>'
        '  </af>'
        '</afs>'
    )

    def __init__(self, name: str | None = None):
        self.name = name
        name_xml = f"<name>{name}</name>" if name else "<name/>"
        self.request_filter = (
            f'<network-instance xmlns="urn:huawei:yang:huawei-network-instance">'
            f'  <instances>'
            f'    <instance>{name_xml}{self._AF_AUGMENT}</instance>'
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


# NOTE: A Base-router R-VPLS binding request (``/configure/router[Base]/
# interface/vpls``) intentionally does NOT exist. ``<vpls>`` under
# ``/configure/router[Base]/interface`` is rejected by SR OS 23.10 as
# ``MGMT_CORE #2201: Unknown element`` (probed live 24 Jul 2026), and the
# R-VPLS-on-base-router scenario does not exist on our fleet (plan decision
# E1). Base-router L3 interfaces therefore always resolve ``l2_service=None``.
# R-VPLS bindings are a VPRN-only concept here — see
# :class:`NokiaVprnInterfaceVplsRPCRequest`.


class NokiaVprnInterfaceConfigRPCRequest:
    """Filter for Nokia VPRN-interface config leaves (configure-NS).

    YANG path: ``/configure/service/vprn[service-name]/interface[interface-name]``
    in the **configure** namespace (``urn:nokia.com:sros:ns:yang:sr:conf``).
    Field-selected to the leaves that decide *what kind of binding* an
    L3 interface uses, plus ``<admin-state>`` as the admin-status fallback
    for the VPRN state-NS gap (see :class:`NokiaL3Interface` docstring):

      * ``<sap>``         — presence ⇒ SAP-based L3 (``sap_physical``);
                             we also pull ``sap-id`` inside for ``port:vlan``.
      * ``<spoke-sdp>``   — presence ⇒ SDP-spoke L3 (``sdp_spoke``); pull
                             ``sdp-bind-id`` for the ``"<sdp_id>:<vc_id>"`` tag.
      * ``<loopback>``    — boolean leaf (``"true"`` ⇒ ``loopback``).
      * ``<vpls>``        — for completeness (R-VPLS naming convention is
                             already detected by the interface-name parser;
                             keeping the leaf here lets the same RPC double
                             as the binding-config source for R-VPLS too).
      * ``<admin-state>`` — admin intent (``enable`` / ``disable``). Fallback
                             only — see ``NokiaL3Interface.apply_binding_from_config``.
      * ``<ipv4>/<primary>/<prefix-length>`` — the configured netmask the
                             VPRN state-NS ``oper-address`` omits; fills
                             :attr:`L3Interface.ipv4_prefix_length`.

    No state-data is requested — strictly configure-NS leaves. Issue with
    ``<get-config source="running">`` and ``with_defaults="report-all"`` so
    default-valued leaves (``<loopback>false</loopback>``,
    ``<admin-state>enable</admin-state>`` etc.) come back instead of being
    silently dropped.

    ``vprn_service_name`` narrows server-side to one VRF; omit it to fetch
    every VPRN's interfaces in one shot. The cost stays small because we
    field-select aggressively.
    """

    _IF_FIELDS = (
        "<sap>"
        "  <sap-id/>"
        "</sap>"
        "<spoke-sdp>"
        "  <sdp-bind-id/>"
        "</spoke-sdp>"
        "<loopback/>"
        "<vpls>"
        "  <vpls-name/>"
        "</vpls>"
        "<admin-state/>"
        # IPv4 primary carries the configured netmask (prefix-length) that
        # the VPRN state-NS ``oper-address`` omits — fills
        # ``L3Interface.ipv4_prefix_length`` under ``enrich_config``.
        "<ipv4>"
        "  <primary>"
        "    <prefix-length/>"
        "  </primary>"
        "</ipv4>"
    )

    def __init__(self, vprn_service_name: str | None = None):
        self.vprn_service_name = vprn_service_name
        svc_key = (
            f"<service-name>{vprn_service_name}</service-name>"
            if vprn_service_name
            else "<service-name/>"
        )
        self.request_filter = (
            f'<configure xmlns="urn:nokia.com:sros:ns:yang:sr:conf">'
            f'  <service>'
            f'    <vprn>'
            f'      {svc_key}'
            f'      <interface>'
            f'        <interface-name/>'
            f'        {self._IF_FIELDS}'
            f'      </interface>'
            f'    </vprn>'
            f'  </service>'
            f'</configure>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class NokiaBaseRouterInterfaceConfigRPCRequest:
    """Filter for Nokia Base-router interface config leaves (configure-NS).

    Counterpart of :class:`NokiaVprnInterfaceConfigRPCRequest` for the
    global Base router — ``/configure/router[router-name='Base']/interface``.

    The Base-router interface model is **port-based**, not SAP/spoke-based:
    the binding-discriminator leaves used on VPRN interfaces
    (``<sap>`` / ``<spoke-sdp>``) do not exist under
    ``/configure/router[Base]/interface`` on SR OS 23.10 (probed live —
    they return ``MGMT_CORE #2201: Unknown element``). Likewise ``<vpls>``
    (R-VPLS on the base router) is rejected as ``Unknown element`` and the
    scenario does not exist on our fleet, so it is intentionally absent
    here (see plan decision E1).

    Field-selected leaves (all verified live 24 Jul 2026 on
    ``Oc.MSC_3.CR_01`` / ``Oc.JArk2.AC_01``):

      * ``<port>``        — the physical port, LAG or ``port:vlan`` this
                            L3 interface lives on (``"3/1/1"`` /
                            ``"2/1/8:671"`` / ``"lag-3"``). Consumed by
                            :meth:`NokiaL3Interface.apply_binding_from_config`
                            to fill ``parent_port`` / ``vlan`` and refine
                            ``binding_type`` to ``physical_port`` /
                            ``subinterface``.
      * ``<loopback/>``   — boolean leaf (``"true"`` ⇒ ``loopback``).
      * ``<admin-state/>``— admin intent (``enable`` / ``disable``); fills
                            :attr:`L3Interface.admin_status` (state-NS omits
                            it here).
      * ``<ipv4>/<primary>/<address>/<prefix-length>`` — the configured
                            CIDR. ``prefix-length`` is the netmask the
                            state-NS ``oper-address`` lacks; it fills
                            :attr:`L3Interface.ipv4_prefix_length`.

    Issue with ``<get-config source="running">`` and
    ``with_defaults="report-all"`` so the default-valued
    ``<admin-state>enable</admin-state>`` comes back (state-NS present only
    for ``disable``).
    """

    _IF_FIELDS = (
        "<port/>"
        "<loopback/>"
        "<admin-state/>"
        "<ipv4>"
        "  <primary>"
        "    <address/>"
        "    <prefix-length/>"
        "  </primary>"
        "</ipv4>"
    )

    def __init__(self):
        self.request_filter = (
            f'<configure xmlns="urn:nokia.com:sros:ns:yang:sr:conf">'
            f'  <router>'
            f'    <router-name>Base</router-name>'
            f'    <interface>'
            f'      <interface-name/>'
            f'      {self._IF_FIELDS}'
            f'    </interface>'
            f'  </router>'
            f'</configure>'
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

    Field-selected leaves:

      * ``name`` — list key (interface name).
      * ``vrf-name`` — VRF binding (``_public_`` → global).
      * ``admin-status`` — admin intent.
      * ``mtu`` — configured interface MTU (top-level leaf; verified May 2026
        on NE40E / NE8000 / ATN-910C, see ``examples/xml/Huawei/get_intergace
        (response).xml``). Loopback interfaces do not surface this leaf —
        ``None`` is the correct value there.
      * ``dynamic/oper-status`` — runtime oper-state, same shape as on
        :class:`HuaweiInterfaceAdminOperStateRPCRequest`. The huawei-ifm
        model places live runtime leaves inside a ``<dynamic>`` container;
        without this field-selector the subtree filter would not return
        ``oper-status`` and the parsed :attr:`L3Interface.oper_status`
        would stay ``None``.
      * ``ipv4/addresses/address`` — IP/mask/type triple (huawei-ip ns).

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
            f'      {name_xml}<vrf-name/><admin-status/><mtu/>'
            f'      <dynamic><oper-status/></dynamic>'
            f'      <ipv4 xmlns="urn:huawei:yang:huawei-ip">'
            f'        <addresses><address><ip/><mask/><type/></address></addresses>'
            f'      </ipv4>'
            f'    </interface>'
            f'  </interfaces>'
            f'</ifm>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiInterfaceAdminOperStateRPCRequest:
    """Filter for Huawei interface admin / oper state via ``huawei-ifm``.

    YANG: ``/ifm/interfaces/interface`` in ``urn:huawei:yang:huawei-ifm``.
    Used to enrich Huawei L2VPN AC endpoints with authoritative
    admin / oper status — the ``huawei-l2vpn`` AC subtree does NOT carry
    those leaves (a previous heuristic that read ``ac.get("admin-state")``
    always returned None, see ``huawei_services._add_local_endpoint``).

    The filter is bulk (no ``<name>`` list-key narrowing). Empirically the
    full ``ifm`` dump returns in ~140 ms on BSC-class NE40E / NE8000 /
    ATN-910C platforms, which is faster than issuing N per-interface RPCs
    when an L2 service has more than a couple of ACs. Caller-side parsing
    yields a ``{interface_name: {"admin_status": ..., "oper_status": ...}}``
    map; SAP-keyed lookups against that map are O(1).

    Note on Huawei admin canonicalisation: the device exposes ``admin-status``
    as ``"up"`` / ``"down"`` strings (same lexical form as ``oper-status``,
    despite the semantic difference between admin intent and runtime state).
    The parser canonicalises to ``"enabled"`` / ``"disabled"`` for admin to
    match Nokia and OpenConfig conventions, while keeping ``oper`` in its
    native ``"up"`` / ``"down"`` form (already the OpenConfig standard).
    """

    def __init__(self):
        self.request_filter = (
            '<ifm xmlns="urn:huawei:yang:huawei-ifm">'
            '  <interfaces>'
            '    <interface>'
            '      <name/>'
            '      <admin-status/>'
            '      <dynamic>'
            '        <oper-status/>'
            '      </dynamic>'
            '    </interface>'
            '  </interfaces>'
            '</ifm>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiBgpVpnRoutesRPCRequest:
    """Subtree filter for Huawei BGP IPv4 VPN RIB routes (multi-prefix batch).

    YANG path: ``/bgp:bgp/bgp:base-process/bgp-rt:bgp-route/bgp-rt:ipv4-vpn/
    bgp-rt:routes/bgp-rt:route`` — namespaces ``urn:huawei:yang:huawei-bgp``
    plus the routing-table augment ``urn:huawei:yang:huawei-bgp-routing-table``.

    Multiple ``<route>`` entries can be packed into a single filter; the
    device returns the union (server-side ``prefix`` filtering is exact
    match per entry, so LPM is the caller's responsibility). Field-select
    keeps the response small: only ``nexthop`` and ``flag-string`` leaves
    are pulled in addition to the composite list keys returned by default.
    """

    def __init__(self, prefixes: list):
        if not prefixes:
            raise ValueError("prefixes must be a non-empty list")
        self.prefixes = list(prefixes)
        routes_xml = "".join(
            f"<route><prefix>{p}</prefix><nexthop/><flag-string/></route>"
            for p in self.prefixes
        )
        self.request_filter = (
            '<bgp xmlns="urn:huawei:yang:huawei-bgp">'
            '<base-process>'
            '<bgp-route xmlns="urn:huawei:yang:huawei-bgp-routing-table">'
            f'<ipv4-vpn><routes>{routes_xml}</routes></ipv4-vpn>'
            '</bgp-route>'
            '</base-process>'
            '</bgp>'
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


# =========================================================================
# Diagnostic actions: ping / traceroute
# =========================================================================
# Wire-форматы зафиксированы live-probe'ом на боевых роутерах 24 мая 2026.
# Не переписывать по памяти, не "поправить под удобный" YANG-порядок —
# устройство отклонит.
#
# Все классы возвращают XML-фрагмент через get_request_filter() — точно так
# же как остальные *RPCRequest. Для action-RPC фрагмент это уже готовый
# <action> ... </action>, который передаётся в NetconfClient.rpc(...).
# =========================================================================


# ---- Nokia ping / traceroute (sync, structured action) -------------------- #
class NokiaPingActionRequest:
    """Builds Nokia ``<action><global-operations><ping>`` RPC body.

    Namespace ``urn:nokia.com:sros:ns:yang:sr:oper-global``. Lifecycle
    synchronous — один RPC, один rpc-reply со всем результатом, никакого
    polling. RTT в rpc-reply приходит в **МИКРОСЕКУНДАХ** (см.
    :mod:`pynetcom.utils.helpers.netconf.rpc_data_containers.nokia_ping`).

    Поля Nokia: ``destination``, ``router-instance``, ``source-address``,
    ``count``, ``size``, ``timeout`` (в **секундах**!), ``interval`` (в
    **секундах**), ``tos``, ``ttl``, ``do-not-fragment``. Universal request
    хранит interval/timeout в миллисекундах — здесь делим на 1000 с
    минимумом 1с (Nokia не принимает sub-second).

    Negative-case (bad VRF, unreachable) на Nokia **не** даёт rpc-error,
    провал кодируется в response per-probe ``<status>``. Так что отлов
    NetconfActionNotAuthorized — единственная отдельная error-ветка.
    """

    def __init__(self, req):  # PingRequest, без явного type-hint для избежания circular import
        self.req = req
        self.request_filter = self._build()

    def _build(self) -> str:
        r = self.req
        parts = [f"<destination>{r.destination}</destination>"]
        if r.vrf:
            parts.append(f"<router-instance>{r.vrf}</router-instance>")
        if r.source_address:
            parts.append(f"<source-address>{r.source_address}</source-address>")
        parts.append(f"<count>{int(r.count)}</count>")
        parts.append(f"<size>{int(r.packet_size)}</size>")
        # Nokia timeout/interval — в секундах (минимум 1)
        timeout_s = max(1, int(round(r.timeout_ms / 1000)))
        interval_s = max(1, int(round(r.interval_ms / 1000)))
        parts.append(f"<timeout>{timeout_s}</timeout>")
        parts.append(f"<interval>{interval_s}</interval>")
        if r.tos is not None:
            parts.append(f"<tos>{int(r.tos)}</tos>")
        parts.append(f"<ttl>{int(r.ttl)}</ttl>")
        if r.do_not_fragment:
            parts.append("<do-not-fragment>true</do-not-fragment>")
        inner = "".join(parts)
        return (
            '<action xmlns="urn:ietf:params:xml:ns:yang:1">'
            '<global-operations xmlns="urn:nokia.com:sros:ns:yang:sr:oper-global">'
            f'<ping>{inner}</ping>'
            '</global-operations>'
            '</action>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class NokiaTracerouteActionRequest:
    """Builds Nokia ``<action><global-operations><traceroute>`` RPC body.

    Те же ремарки что у :class:`NokiaPingActionRequest`. Поля:
    ``destination``, ``router-instance``, ``source-address``, ``ttl`` (max),
    ``min-ttl``, ``probe-count``, ``wait`` (timeout в **миллисекундах**!),
    ``size``, ``tos``, ``protocol`` (по умолчанию ``udp``).

    Важно: на Nokia ``wait`` уже в миллисекундах (в отличие от ``timeout`` у
    ping в секундах). Поэтому здесь конвертация **не** нужна — отдаём как есть.
    """

    def __init__(self, req):  # TracerouteRequest
        self.req = req
        self.request_filter = self._build()

    def _build(self) -> str:
        r = self.req
        parts = [f"<destination>{r.destination}</destination>"]
        if r.vrf:
            parts.append(f"<router-instance>{r.vrf}</router-instance>")
        if r.source_address:
            parts.append(f"<source-address>{r.source_address}</source-address>")
        parts.append(f"<min-ttl>{int(r.first_ttl)}</min-ttl>")
        parts.append(f"<ttl>{int(r.max_ttl)}</ttl>")
        parts.append(f"<probe-count>{int(r.probes_per_hop)}</probe-count>")
        # Nokia wait в миллисекундах
        parts.append(f"<wait>{int(r.timeout_ms)}</wait>")
        if r.packet_size is not None:
            parts.append(f"<size>{int(r.packet_size)}</size>")
        if r.tos is not None:
            parts.append(f"<tos>{int(r.tos)}</tos>")
        inner = "".join(parts)
        return (
            '<action xmlns="urn:ietf:params:xml:ns:yang:1">'
            '<global-operations xmlns="urn:nokia.com:sros:ns:yang:sr:oper-global">'
            f'<traceroute>{inner}</traceroute>'
            '</global-operations>'
            '</action>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


# ---- Huawei ping (async: action + state-poll + delete) ------------------- #
class HuaweiPingActionRequest:
    """Builds Huawei ``<action><ipv4-start-ip-ping>`` RPC body.

    Namespace ``urn:huawei:yang:huawei-diagnostic-tools``. Submodule
    ``huawei-diagnostic-tools-ipv4`` (под augment ``ipv4``).

    **YANG element order СТРОГО соблюдается** — устройство отклонит XML с
    тэгом ``Invalid element order between X and Y``. Корректный порядок:
    ``test-name, dest-addr, bypass-source-if-name, source-address, vrf-name,
    peer-address, packet-size, packet-size-min, packet-size-max,
    packet-size-step, packet-count, dscp, tos, interval, timeout, ttl,
    pattern, if-name, next-hop, inbound-reply-fast, inbound-if-name,
    service-class, te-class, priority-8021p, force-no-fragment, ignore-mtu,
    record-route, ip-forwarding, debug-option, show-host-name, show-detail,
    show-incoming-if-name, response-vrf-name, ignore-vrf``.

    Здесь вставляем только не-None поля, **но в правильном порядке**. Поля
    ``interval`` и ``timeout`` на Huawei в **миллисекундах** (Nokia было в
    секундах — не путать!). RTT в state-ответе тоже в ms.
    """

    def __init__(self, req, test_name: str):  # req: PingRequest
        self.req = req
        self.test_name = test_name
        self.request_filter = self._build()

    def _build(self) -> str:
        r = self.req
        parts = [f"<test-name>{self.test_name}</test-name>"]
        parts.append(f"<dest-addr>{r.destination}</dest-addr>")
        # bypass-source-if-name — нет
        if r.source_address:
            parts.append(f"<source-address>{r.source_address}</source-address>")
        if r.vrf:
            parts.append(f"<vrf-name>{r.vrf}</vrf-name>")
        # peer-address — нет
        parts.append(f"<packet-size>{int(r.packet_size)}</packet-size>")
        # packet-size-min/max/step — нет
        parts.append(f"<packet-count>{int(r.count)}</packet-count>")
        # dscp — нет; tos — опционально
        if r.tos is not None:
            parts.append(f"<tos>{int(r.tos)}</tos>")
        parts.append(f"<interval>{int(r.interval_ms)}</interval>")
        parts.append(f"<timeout>{int(r.timeout_ms)}</timeout>")
        parts.append(f"<ttl>{int(r.ttl)}</ttl>")
        # pattern, if-name, next-hop ... — нет
        if r.do_not_fragment:
            parts.append("<force-no-fragment>true</force-no-fragment>")
        inner = "".join(parts)
        return (
            '<action xmlns="urn:ietf:params:xml:ns:yang:1">'
            '<ipv4-start-ip-ping xmlns="urn:huawei:yang:huawei-diagnostic-tools">'
            f'{inner}'
            '</ipv4-start-ip-ping>'
            '</action>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiPingStateFilter:
    """Subtree filter for ``<get>`` against Huawei ping-result state.

    Путь: ``/diagnostic-tools/ipv4/ping-results/ping-result[test-name=...]``.
    Внимание — ``<ping-results>`` сидит под augment-ом ``<ipv4>``, не сразу
    под ``<diagnostic-tools>``. Без ``<ipv4>`` фильтр промахнётся.
    """

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.request_filter = (
            '<diagnostic-tools xmlns="urn:huawei:yang:huawei-diagnostic-tools">'
            '<ipv4>'
            '<ping-results>'
            f'<ping-result><test-name>{test_name}</test-name></ping-result>'
            '</ping-results>'
            '</ipv4>'
            '</diagnostic-tools>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiPingDeleteAction:
    """Builds Huawei ``<action><ipv4-delete-ip-ping>`` RPC body.

    Обязательный cleanup. Без него state-таблица копится. На отсутствующий
    test-name приходит ``data-missing 31404`` — глотаем тихо (значит уже
    удалён). На дубликат при start — ``data-exists 31403``.
    """

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.request_filter = (
            '<action xmlns="urn:ietf:params:xml:ns:yang:1">'
            '<ipv4-delete-ip-ping xmlns="urn:huawei:yang:huawei-diagnostic-tools">'
            f'<test-name>{test_name}</test-name>'
            '</ipv4-delete-ip-ping>'
            '</action>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


# ---- Huawei traceroute (action + state-poll + delete) -------------------- #
class HuaweiTracerouteActionRequest:
    """Builds Huawei ``<action><ipv4-start-ip-trace>`` RPC body.

    YANG element order: ``test-name, dest-ip-addr, source-address, first-ttl,
    max-ttl, if-name, source-if-name, timeout, vrf-name, peer-address,
    show-as-num, udp-port, count, packet-size, dscp, tos, service-class,
    te-class, next-hop, show-host-name, pass-route, ttl-mode, response-vrf-name,
    ignore-vrf``.

    Внимание — destination называется ``dest-ip-addr`` (ping ``dest-addr``).
    Timeout в миллисекундах.
    """

    def __init__(self, req, test_name: str):  # req: TracerouteRequest
        self.req = req
        self.test_name = test_name
        self.request_filter = self._build()

    def _build(self) -> str:
        r = self.req
        parts = [f"<test-name>{self.test_name}</test-name>"]
        parts.append(f"<dest-ip-addr>{r.destination}</dest-ip-addr>")
        if r.source_address:
            parts.append(f"<source-address>{r.source_address}</source-address>")
        parts.append(f"<first-ttl>{int(r.first_ttl)}</first-ttl>")
        parts.append(f"<max-ttl>{int(r.max_ttl)}</max-ttl>")
        parts.append(f"<timeout>{int(r.timeout_ms)}</timeout>")
        if r.vrf:
            parts.append(f"<vrf-name>{r.vrf}</vrf-name>")
        parts.append(f"<count>{int(r.probes_per_hop)}</count>")
        if r.packet_size is not None:
            parts.append(f"<packet-size>{int(r.packet_size)}</packet-size>")
        if r.tos is not None:
            parts.append(f"<tos>{int(r.tos)}</tos>")
        inner = "".join(parts)
        return (
            '<action xmlns="urn:ietf:params:xml:ns:yang:1">'
            '<ipv4-start-ip-trace xmlns="urn:huawei:yang:huawei-diagnostic-tools">'
            f'{inner}'
            '</ipv4-start-ip-trace>'
            '</action>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiTracerouteStateFilter:
    """Subtree filter for ``<get>`` against Huawei trace-result state."""

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.request_filter = (
            '<diagnostic-tools xmlns="urn:huawei:yang:huawei-diagnostic-tools">'
            '<ipv4>'
            '<trace-results>'
            f'<trace-result><test-name>{test_name}</test-name></trace-result>'
            '</trace-results>'
            '</ipv4>'
            '</diagnostic-tools>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiTracerouteDeleteAction:
    """Builds Huawei ``<action><ipv4-delete-ip-trace>`` RPC body."""

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.request_filter = (
            '<action xmlns="urn:ietf:params:xml:ns:yang:1">'
            '<ipv4-delete-ip-trace xmlns="urn:huawei:yang:huawei-diagnostic-tools">'
            f'<test-name>{test_name}</test-name>'
            '</ipv4-delete-ip-trace>'
            '</action>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiPingResultsListFilter:
    """Filter to retrieve ping-result entries (housekeeping / preflight).

    Возвращает поля ``test-name`` / ``status`` плюс per-probe
    ``details/detail/system-time``. Result-level ``system-time`` у Huawei
    diagnostic-tools **не существует** (probe 24.05.2026), таймстамп есть
    только у per-probe `<detail>`. Preflight использует timestamp последнего
    detail как «когда тест завершился» — для возрастного фильтра.
    Не для штатной диагностики (для этого :class:`HuaweiPingStateFilter`).
    """

    def __init__(self):
        self.request_filter = (
            '<diagnostic-tools xmlns="urn:huawei:yang:huawei-diagnostic-tools">'
            '<ipv4>'
            '<ping-results>'
            '<ping-result>'
            '<test-name/><status/>'
            '<details><detail><system-time/></detail></details>'
            '</ping-result>'
            '</ping-results>'
            '</ipv4>'
            '</diagnostic-tools>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter


class HuaweiTracerouteResultsListFilter:
    """Filter to retrieve trace-result entries (housekeeping / preflight).

    Поля ``test-name`` / ``status``. У trace-result в Huawei
    ``huawei-diagnostic-tools`` **нет** ``system-time`` ни на result-level,
    ни в ``details/detail`` (probe 24.05.2026 — поля: hop-index, ttl, rtt,
    ds-ip-addr, is-delete). Поэтому preflight для traceroute работает только
    по prefix + status=finished, без age-фильтра.
    """

    def __init__(self):
        self.request_filter = (
            '<diagnostic-tools xmlns="urn:huawei:yang:huawei-diagnostic-tools">'
            '<ipv4>'
            '<trace-results>'
            '<trace-result>'
            '<test-name/><status/>'
            '</trace-result>'
            '</trace-results>'
            '</ipv4>'
            '</diagnostic-tools>'
        )

    def get_request_filter(self) -> str:
        return self.request_filter