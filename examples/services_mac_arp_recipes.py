"""
MAC / ARP operational recipes for pynetcom's ServicesClient — AI-agent guide.

================================================================================
PURPOSE
================================================================================
This file is a *teaching example*. Feed it to an AI agent (or read it yourself)
and you will know how to perform every common MAC-table / ARP-table operation
with `pynetcom.ServicesClient` WITHOUT writing custom filtering logic in your
own code. Every scenario below is solved entirely with library calls.

Each recipe is a standalone function. The docstring states:
  - the operator question it answers,
  - which ServicesClient method(s) it uses,
  - which parameters are resolved SERVER-SIDE (embedded in the NETCONF subtree
    filter — cheap, the device does the work) vs CLIENT-SIDE (applied after
    parsing — still a library feature, you don't write it yourself).

================================================================================
THE TWO DATA OBJECTS
================================================================================
`MacEntry`  (one FDB / MAC-table row):
    mac_address       canonical "aa:bb:cc:dd:ee:ff"
    vlan              int or None
    interface         where the MAC was learned — a SAP-id, an SDP-bind-id,
                      or a port/sub-interface name
    entry_type        MacEntryType.STATIC | DYNAMIC
    source_type       MacSourceType.SAP  -> learned locally on a SAP/AC
                      MacSourceType.PW   -> learned remotely over a pseudo-wire
                      None               -> edge case (host/oam), investigate
    age               seconds (vendor-specific semantics)
    network_instance  the VPLS / VSI name this entry belongs to

`Neighbor`  (one ARP / ND row):
    ip                  IPv4 address
    link_layer_address  canonical "aa:bb:cc:dd:ee:ff"
    interface           L3 interface the entry sits on
    origin              NeighborOrigin.STATIC | DYNAMIC | OTHER
    vprn_name           routing instance ("Base" = global on both vendors,
                        any VPRN name, or None on Huawei when scoped globally)
    age                 seconds (Nokia=TTL-to-expiry, Huawei=age, often None)

================================================================================
CAPABILITY MATRIX  (which filter is server-side, which is client-side)
================================================================================
get_mac_table(...)
    service_name   SERVER-SIDE   YANG list key (VPLS/VSI name)
    mac            SERVER-SIDE   YANG list key — any MAC format accepted
    port           CLIENT-SIDE   case-insensitive substring on .interface
    entry_type     CLIENT-SIDE   exact "STATIC" / "DYNAMIC"
    learned_via    CLIENT-SIDE   exact "sap" / "pw"  -> MacEntry.source_type

get_arp_table(...)
    vprn_name      SERVER-SIDE   "Base" (global, both vendors) or a VPRN name
    ip             SERVER-SIDE   YANG list key
    mac            CLIENT-SIDE   substring (any MAC format accepted)
    interface      CLIENT-SIDE   substring
    origin         CLIENT-SIDE   exact "STATIC" / "DYNAMIC" / "OTHER"

Rule of thumb: combine as many SERVER-SIDE keys as you can — they bound the
response at the device. CLIENT-SIDE filters then refine what's left. Never
re-implement these filters in your own code; pass them as parameters.

================================================================================
RUN
================================================================================
    python examples/services_mac_arp_recipes.py
Edit the TARGET_* constants below to point at your own devices/data.
"""

from __future__ import annotations

import json
import logging

from config import NETCONF_USER, NETCONF_PASSWORD

from pynetcom import NetconfClient, ServicesClient

# ---- Silence transport noise --------------------------------------------- #
logging.basicConfig(level=logging.WARNING)
for _n in ("ncclient", "ncclient.transport", "paramiko", "paramiko.transport"):
    logging.getLogger(_n).setLevel(logging.WARNING)
logging.getLogger("pynetcom").setLevel(logging.WARNING)


# ============================================================================
# TEST TARGETS — real lab values. Replace with your own.
# ============================================================================
NOKIA_HOST = "172.28.205.8"
NOKIA_PORT = 830
NOKIA_DEVICE_PARAMS = {"name": "sros"}
NOKIA_TEST_IP = "10.130.202.93"          # an IP expected in the ARP cache
NOKIA_TEST_MAC = "9844ce72dc30"          # any separator style is accepted
NOKIA_TEST_VPRN = "VPRN_UMTS"            # a VPRN (L3VPN) service name
NOKIA_TEST_VPLS = "VPLS_MVD_Radio"       # a VPLS (L2VPN) service name

HUAWEI_HOST = "10.255.77.147"
HUAWEI_PORT = 22                         # NE-series exposes NETCONF on SSH
HUAWEI_DEVICE_PARAMS = {"name": "huaweiyang"}
HUAWEI_TEST_IP = "10.110.202.60"
HUAWEI_TEST_MAC = "c8a7769ace68"
HUAWEI_TEST_VPLS = "VPLS_electro_DGU_Bishkek"
# Real local SAP port on this lab device (out-interface-type=ac). Scenarios 2
# and 6 expect a SAP port — do NOT replace this with an IP-MPLS uplink such as
# GigabitEthernet0/2/0, which carries PW-learned MACs (out-interface-type=pw)
# and would make scenarios 3/6 surface 0 SAP rows. The captured raw response in
# examples/xml/Huawei/services/get_mac_dynamic_all(response).xml shows both
# port kinds side-by-side and is what the smoke test mirrors.
HUAWEI_TEST_PORT = "GigabitEthernet0/2/27"


def _banner(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def _dump(obj) -> None:
    print(json.dumps(obj.to_dict(), indent=2, default=str))


# ============================================================================
# SCENARIO 1 — Find a MAC by IP, then check which port sees that MAC.
# ============================================================================
def scenario_1_find_mac_by_ip(sc: ServicesClient, ip: str, vprn_candidates: list[str]):
    """Q: "I have an IP. What's its MAC, and on which port does the device see it?"

    Two library calls, no custom filtering:
      1. get_arp_table(vprn_names=[...], ips=[...])  — both params SERVER-SIDE.
         On Nokia ARP is per-routing-instance, so we try each candidate VRF
         until we hit one (Huawei returns all VPNs in one query, so a single
         call suffices — pass vprn_names=None there).
      2. get_mac_table(mac=...)          — mac is SERVER-SIDE. With no
         service_name the device walks every service but returns only rows
         matching this MAC, so the response stays small.
    """
    _banner(f"SCENARIO 1 — find MAC for IP {ip}, then locate it in the FDB")

    # Step 1: locate the IP in ARP. [SERVER-SIDE] vprn_names + ips.
    arp_hit = None
    for vprn_name in vprn_candidates:
        vprn_list = [vprn_name] if vprn_name is not None else None
        arps = sc.get_arp_table(vprn_names=vprn_list, ips=[ip])
        if arps:
            arp_hit = arps[0]
            print(f"ARP: {ip} -> {arp_hit.link_layer_address} "
                  f"(vprn_name={arp_hit.vprn_name}, interface={arp_hit.interface})")
            break
    if arp_hit is None:
        print(f"ARP: {ip} not found in any of {vprn_candidates}")
        return
    mac = arp_hit.link_layer_address

    # Step 2: find that MAC in the L2 forwarding database. [SERVER-SIDE] macs.
    macs = sc.get_mac_table(macs=[mac])
    if not macs:
        print(f"FDB: MAC {mac} is not present in any L2 service "
              f"(host is reachable purely at L3)")
        return
    for m in macs:
        print(f"FDB: MAC {mac} in service {m.network_instance!r} "
              f"on {m.interface!r} (source_type={m.source_type}, "
              f"entry_type={m.entry_type})")
        _dump(m)


# ============================================================================
# SCENARIO 2 — Every MAC learned through a given port, across all services.
# ============================================================================
def scenario_2_macs_by_port(sc: ServicesClient, port: str):
    """Q: "Show me every MAC the device learned through port X, in any service."

    One call: get_mac_table(ports=[...]).
      - ports is CLIENT-SIDE (substring match on MacEntry.interface, OR-combined).
      - No service_name -> the device returns the whole FDB; the library logs
        a WARNING for that, and the port filter is applied after parsing.
        On a busy box prefer scenario 6 (add service_name to bound it).
    """
    _banner(f"SCENARIO 2 — all MACs learned via port {port} (every service)")
    macs = sc.get_mac_table(ports=[port])       # [CLIENT-SIDE] ports
    print(f"{len(macs)} MAC(s) on port matching {port!r}")
    for m in macs:
        print(f"  {m.mac_address}  service={m.network_instance}  "
              f"source={m.source_type}")


# ============================================================================
# SCENARIO 3 — All MACs, but only locally-learned ones (via SAP).
# ============================================================================
def scenario_3_macs_sap_only(sc: ServicesClient, service_name: str):
    """Q: "Show me only the MACs learned locally (on a SAP), not over a PW."

    One call: get_mac_table(service_name=..., learned_via="sap").
      - service_name is SERVER-SIDE (bounds the query to one service).
      - learned_via="sap" is CLIENT-SIDE — keeps rows where
        MacEntry.source_type == MacSourceType.SAP.

    SAP vs PW classification is taken from a vendor leaf, NOT from the
    shape of the interface name: Nokia uses `locale`, Huawei uses
    `out-interface-type` (ac/pw). A physical port like GigabitEthernet0/2/0
    can therefore be either SAP or PW depending on the role it plays
    (access port vs IP-MPLS uplink) — the device knows, the library trusts
    the device.
    """
    _banner(f"SCENARIO 3 — SAP-learned MACs only, service {service_name}")
    macs = sc.get_mac_table(service_name=service_name, learned_via="sap")
    print(f"{len(macs)} SAP-learned MAC(s) in {service_name!r}")
    for m in macs[:10]:
        print(f"  {m.mac_address}  iface={m.interface}  source={m.source_type}")


# ============================================================================
# SCENARIO 4 — All MACs, but only remotely-learned ones (via PW).
# ============================================================================
def scenario_4_macs_pw_only(sc: ServicesClient, service_name: str):
    """Q: "Show me only the MACs learned over pseudo-wires (remote sites)."

    One call: get_mac_table(service_name=..., learned_via="pw").
      Same as scenario 3 but learned_via="pw" — the exact inverse selection.
      On Huawei this matches every record with out-interface-type=pw,
      including PW MACs that egress a physical uplink port.
    """
    _banner(f"SCENARIO 4 — PW-learned MACs only, service {service_name}")
    macs = sc.get_mac_table(service_name=service_name, learned_via="pw")
    print(f"{len(macs)} PW-learned MAC(s) in {service_name!r}")
    for m in macs[:10]:
        print(f"  {m.mac_address}  iface={m.interface}  source={m.source_type}")


# ============================================================================
# SCENARIO 5 — All MACs of a service, excluding PW-learned ones.
# ============================================================================
def scenario_5_service_macs_no_remote(sc: ServicesClient, service_name: str):
    """Q: "Give me the FDB of this service but drop anything learned remotely."

    This is identical to scenario 3 — "exclude PW-learned" == "keep SAP-learned".
    Shown separately because operators phrase it both ways; the library call is
    the same: get_mac_table(service_name=..., learned_via="sap").
    """
    _banner(f"SCENARIO 5 — service {service_name} FDB without PW-learned rows")
    macs = sc.get_mac_table(service_name=service_name, learned_via="sap")
    total = sc.get_mac_table(service_name=service_name)
    print(f"{len(macs)} local MAC(s) kept out of {len(total)} total in {service_name!r}")


# ============================================================================
# SCENARIO 6 — All MACs learned through a specific SAP.
# ============================================================================
def scenario_6_macs_by_sap(sc: ServicesClient, service_name: str, sap: str):
    """Q: "Which MACs came in on this exact SAP?"

    One call combining three filters:
      get_mac_table(service_name=..., ports=[<sap-id>], learned_via="sap")
      - service_name  SERVER-SIDE — bounds the device-side walk.
      - ports         CLIENT-SIDE — substring match on the SAP id (OR-combined).
      - learned_via   CLIENT-SIDE — guards against a coincidental substring
                      hit on a PW whose sdp-bind-id happens to contain the
                      same digits.
    """
    _banner(f"SCENARIO 6 — MACs on SAP {sap} of service {service_name}")
    macs = sc.get_mac_table(service_name=service_name, ports=[sap], learned_via="sap")
    print(f"{len(macs)} MAC(s) on SAP {sap!r}")
    for m in macs[:10]:
        print(f"  {m.mac_address}  iface={m.interface}")


# ============================================================================
# SCENARIO 7 — Given a MAC, find its IP inside a specific VRF.
# ============================================================================
def scenario_7_ip_by_mac_in_vrf(sc: ServicesClient, mac: str, vprn_name: str):
    """Q: "I have a MAC. What IP does it have inside VRF X?"

    One call: get_arp_table(vprn_names=[...], macs=[...]).
      - vprn_names is SERVER-SIDE — the device returns only that VRF's ARP
        cache.
      - macs is SERVER-SIDE on Nokia (content-match expanded into sibling
        <neighbor><mac-address> elements), CLIENT-SIDE on Huawei (server
        rejects MAC content-match — pynetcom filters after parse).
        Any MAC format is accepted (normalised internally).
    """
    _banner(f"SCENARIO 7 — IP for MAC {mac} inside VRF {vprn_name}")
    neighbors = sc.get_arp_table(vprn_names=[vprn_name], macs=[mac])
    if not neighbors:
        print(f"MAC {mac} has no ARP entry in {vprn_name}")
        return
    for n in neighbors:
        print(f"  {n.ip}  <-  {n.link_layer_address}  (iface={n.interface})")
        _dump(n)


# ============================================================================
# SCENARIO 8 — End-to-end: IP -> MAC -> service -> port / SAP / PW.
# ============================================================================
def scenario_8_locate_host(sc: ServicesClient, ip: str, vprn_candidates: list[str]):
    """Q: "Where does host <IP> live? Give me MAC, service, and port/SAP/PW."

    The 'complex' workflow. There is intentionally no single find_host() method
    — it is just three library calls composed. This recipe IS the canonical
    composition; copy it verbatim.

      step 1  get_arp_table(vprn_names, ips)  -> MAC                [SERVER-SIDE]
      step 2  get_mac_table(mac=...)          -> service + interface[SERVER-SIDE]
      step 3  get_l2vpn_services(name=svc)    -> classify the endpoint as a
              LOCAL (SAP) or REMOTE (PW) connection point             [SERVER-SIDE]
    """
    _banner(f"SCENARIO 8 — locate host {ip} end-to-end")

    # step 1 — IP -> MAC
    arp_hit = None
    for vprn_name in vprn_candidates:
        vprn_list = [vprn_name] if vprn_name is not None else None
        hits = sc.get_arp_table(vprn_names=vprn_list, ips=[ip])
        if hits:
            arp_hit = hits[0]
            break
    if arp_hit is None:
        print(f"  step 1: {ip} not found in ARP ({vprn_candidates}) — stop")
        return
    mac = arp_hit.link_layer_address
    print(f"  step 1: {ip} -> MAC {mac}  (L3 vprn_name={arp_hit.vprn_name}, "
          f"L3 iface={arp_hit.interface})")

    # step 2 — MAC -> service + L2 interface
    fdb = sc.get_mac_table(macs=[mac])
    if not fdb:
        print(f"  step 2: MAC {mac} not in any L2 FDB — host is L3-only, stop")
        return
    entry = fdb[0]
    print(f"  step 2: MAC {mac} in service {entry.network_instance!r} "
          f"on {entry.interface!r}  (source_type={entry.source_type})")

    # step 3 — service -> endpoint classification
    services = sc.get_l2vpn_services(name=entry.network_instance)
    if services:
        svc = services[0]
        endpoint = None
        for cp in svc.connection_points or []:
            for ep in cp.endpoints or []:
                if ep.endpoint_id == entry.interface:
                    endpoint = ep
                    break
        if endpoint:
            print(f"  step 3: endpoint {endpoint.endpoint_id} is {endpoint.type.value}")
            _dump(endpoint)
        else:
            print(f"  step 3: interface {entry.interface!r} not matched to a "
                  f"named endpoint (still valid — source_type tells you SAP vs PW)")

    print(f"\n  RESULT: {ip} = {mac} in {entry.network_instance} "
          f"via {entry.interface} ({entry.source_type})")


# ============================================================================
# SCENARIO 9 — Discover VRFs, then list the L3 interfaces of one.
# ============================================================================
def scenario_9_vrf_discovery_and_l3_interfaces(sc: ServicesClient):
    """Q: "What VRFs exist, and what L3 interfaces live in one of them?"

    Two library calls, no hardcoded VRF list:
      1. get_l3vpn_services()              — enumerate VRFs.       [SERVER-SIDE]
      2. get_l3_interfaces(vprn_name=...)  — L3 (IP) interfaces of a VRF.
         Nokia: server-side scoped to that VPRN.   [SERVER-SIDE]
         Huawei: one huawei-ifm query, filtered by vrf-name.  [CLIENT-SIDE]

    This is what replaces the old hardcoded ``vprn_candidates`` list used by
    scenarios 1 and 8 — see run_nokia() below.
    """
    _banner("SCENARIO 9 — VRF discovery + L3 interfaces")
    vrfs = sc.get_l3vpn_services()                  # [SERVER-SIDE]
    print(f"{len(vrfs)} VRF(s) on the device:")
    for v in vrfs:
        print(f"  - {v.name}  type={v.type}  rd={v.route_distinguisher}")
    if not vrfs:
        print("  (no configured VRFs)")
        return
    target = vrfs[0].name
    l3 = sc.get_l3_interfaces(vprn_name=target)     # [SERVER/CLIENT-SIDE]
    print(f"\n{len(l3)} L3 interface(s) in VRF {target!r}:")
    for i in l3:
        suffix = f"/{i.ipv4_prefix_length}" if i.ipv4_prefix_length else ""
        print(f"  - {i.name}  {i.ipv4_address}{suffix}  oper={i.oper_status}")
    if l3:
        _dump(l3[0])


# ============================================================================
# SCENARIO 10 — Locate the access PE of a BS without brute-forcing every PW.
# ============================================================================
def scenario_10_locate_bs_via_pw_peer(
    sc_local: ServicesClient,
    ip: str,
    vprn_candidates: list,
    resolve_remote=None,
):
    """Q: "I have a BS IP on a backbone PE. Which remote PE actually owns
    the BS on a local SAP, and on which port?"

    Cross-router chain WITHOUT brute-force:
      1. get_arp_table(vprn_names=[...], ips=[ip])  →  MAC of the BS.
      2. get_mac_table(mac=..., service_name=...)  on the LOCAL PE:
         every PW-learned entry now carries ``remote_system`` (the
         originating PE's system / loopback IP) and ``pw_id`` — server-side
         on Huawei (peer-ip + pw-id leaves), or via a follow-up join on
         Nokia (sdp-bind vc-id ↔ Endpoint.endpoint_id).
      3. ``resolve_remote(system_ip)`` →  remote PE's router name.
         (Whatever inventory/lookup the operator already uses — passed in
         as a callable so the recipe stays library-only.)
      4. get_mac_table(mac=..., learned_via="sap")  on the REMOTE PE: this
         is the local-learn record, returning the actual physical SAP port.

    H-VPLS note: by default get_mac_table drops ``pw-role=slave`` entries
    on Huawei (Nokia is naturally slave-free), so step 2 returns only the
    active PWs. Set ``include_standby=True`` to also see standby paths.
    """
    _banner(f"SCENARIO 10 — locate access PE for BS at {ip} (no brute-force)")

    # Step 1: IP → MAC via ARP.
    arp_hit = None
    for vprn_name in vprn_candidates:
        vprn_list = [vprn_name] if vprn_name is not None else None
        arps = sc_local.get_arp_table(vprn_names=vprn_list, ips=[ip])
        if arps:
            arp_hit = arps[0]
            print(f"  step 1: ARP  {ip}  ->  {arp_hit.link_layer_address}  "
                  f"(vprn_name={arp_hit.vprn_name!r})")
            break
    if arp_hit is None:
        print(f"  step 1: ARP miss for {ip} in {vprn_candidates} — abort")
        return
    mac = arp_hit.link_layer_address

    # Step 2: MAC → service + remote_system on local FDB.
    fdb = sc_local.get_mac_table(mac=mac)                # [SERVER-SIDE] mac
    if not fdb:
        print(f"  step 2: MAC {mac} not in any service FDB on the local PE — abort")
        return
    pw_hits = [m for m in fdb if m.source_type and m.source_type.value == "PW"]
    if not pw_hits:
        print(f"  step 2: MAC {mac} is locally SAP-learned on THIS PE")
        for m in fdb[:3]:
            print(f"          service={m.network_instance!r}  "
                  f"port={m.interface!r}  source={m.source_type}")
        return
    target = pw_hits[0]
    print(f"  step 2: MAC {mac} in service {target.network_instance!r} "
          f"via PW (remote_system={target.remote_system}, pw_id={target.pw_id})")

    # Step 3: peer-IP → router name (caller's inventory).
    remote_router = None
    if resolve_remote and target.remote_system:
        try:
            remote_router = resolve_remote(target.remote_system)
        except Exception as e:
            print(f"  step 3: resolve_remote raised {type(e).__name__}: {e}")
    if remote_router is None:
        print(f"  step 3: cannot resolve remote_system={target.remote_system!r} "
              f"to a router name (pass resolve_remote=callable to enable this step)")
        print(f"\n  RESULT (partial): BS at {ip} = {mac} is reached via PE "
              f"system-IP {target.remote_system} in service "
              f"{target.network_instance!r}.")
        return
    print(f"  step 3: remote PE is {remote_router!r}")

    # Step 4: connect to remote PE → find local SAP record.
    print(f"  step 4: query {remote_router!r} for MAC {mac} learned_via=sap "
          f"(left to the caller — needs a fresh ServicesClient bound to that PE).")
    print(f"\n  RESULT: BS at {ip} = {mac} is locally connected to "
          f"{remote_router!r} in service {target.network_instance!r}. "
          f"No PE walk required.")


# ============================================================================
# SCENARIO 11 — Deterministic IP → L2 service via the L2-L3 binding.
# ============================================================================
def scenario_11_l2_service_by_ip(sc: ServicesClient, ip: str, vprn_candidates: list):
    """Q: "I have an IP. Which L2 service owns it — DETERMINISTICALLY?"

    A single library call: `find_l2_service_by_ip`. The chain walks
    ARP → L3 interface → L2-L3 binding (VE-group on Huawei, vpls binding
    on Nokia) → returns the exact L2 service. No MAC-name guessing across
    services — important because one MAC can legitimately appear in
    multiple VPLSes (multi-tenant / shared-infra configs).
    """
    _banner(f"SCENARIO 11 — IP -> L2 service via L2-L3 binding for {ip}")
    hit = sc.find_l2_service_by_ip(ip, vprn_name_candidates=vprn_candidates)
    if not hit:
        print(f"  {ip} not in ARP across {vprn_candidates}")
        return
    print(f"  IP            = {hit['ip']}")
    print(f"  MAC           = {hit['mac']}")
    print(f"  VPRN          = {hit['vprn_name']}")
    print(f"  L3 interface  = {hit['l3_interface']}")
    print(f"  L2 service    = {hit['l2_service']!r}  "
          f"({'resolved via binding' if hit['l2_service'] else 'pure-L3, no L2 binding'})")


# ============================================================================
# SCENARIO 12 — Reverse: which L3 gateways route a given L2 service?
# ============================================================================
def scenario_12_l3_gateways_for_vpls(sc: ServicesClient, vpls_name: str):
    """Q: "Which L3 interface (if any) routes this VPLS?"

    `find_l3_gateways_for_l2_service(vpls_name)` returns a list of
    :class:`L3Interface` — possibly empty. **Empty is a legitimate result**
    for pure-L2 transport VPLSes (no IRB gateway). Distinguish "no gateway"
    from "lookup error" by the empty list, not by exception.
    """
    _banner(f"SCENARIO 12 — L3 gateways routing L2 service {vpls_name!r}")
    gws = sc.find_l3_gateways_for_l2_service(vpls_name)
    if not gws:
        print(f"  no L3 gateway for {vpls_name!r} (pure-L2 VPLS)")
        return
    print(f"  {len(gws)} gateway(s):")
    for g in gws:
        prefix = f"/{g.ipv4_prefix_length}" if g.ipv4_prefix_length else ""
        print(f"    {g.name}  vprn_name={g.vprn_name}  ip={g.ipv4_address}{prefix}  l2_service={g.l2_service}")


# ============================================================================
# MAIN — run scenarios against the two lab devices.
# ============================================================================
def run_nokia() -> None:
    _banner(f"### NOKIA {NOKIA_HOST}")
    nc = NetconfClient(
        host=NOKIA_HOST, port=NOKIA_PORT,
        user=NETCONF_USER, password=NETCONF_PASSWORD,
        device_params=NOKIA_DEVICE_PARAMS,
    )
    try:
        sc = ServicesClient(nc, vendor="nokia")
        # Nokia ARP is per-routing-instance. Build the candidate VRF list by
        # DISCOVERY — "Base" (the global instance) plus every configured VPRN.
        # No more hardcoding: get_l3vpn_services() enumerates the VRFs.
        vprn_candidates = ["Base"] + [v.name for v in sc.get_l3vpn_services()]
        scenario_1_find_mac_by_ip(sc, NOKIA_TEST_IP, vprn_candidates)
        scenario_3_macs_sap_only(sc, NOKIA_TEST_VPLS)
        scenario_4_macs_pw_only(sc, NOKIA_TEST_VPLS)
        scenario_5_service_macs_no_remote(sc, NOKIA_TEST_VPLS)
        scenario_7_ip_by_mac_in_vrf(sc, NOKIA_TEST_MAC, NOKIA_TEST_VPRN)
        scenario_8_locate_host(sc, NOKIA_TEST_IP, vprn_candidates)
        scenario_9_vrf_discovery_and_l3_interfaces(sc)
        scenario_11_l2_service_by_ip(sc, NOKIA_TEST_IP, vprn_candidates)
        scenario_12_l3_gateways_for_vpls(sc, NOKIA_TEST_VPLS)
    finally:
        nc.close()


def run_huawei() -> None:
    _banner(f"### HUAWEI {HUAWEI_HOST}")
    nc = NetconfClient(
        host=HUAWEI_HOST, port=HUAWEI_PORT,
        user=NETCONF_USER, password=NETCONF_PASSWORD,
        device_params=HUAWEI_DEVICE_PARAMS,
    )
    try:
        sc = ServicesClient(nc, vendor="huawei")
        # Huawei returns all VPNs in one ARP query — vprn_name=None is enough.
        scenario_2_macs_by_port(sc, HUAWEI_TEST_PORT)
        scenario_6_macs_by_sap(sc, HUAWEI_TEST_VPLS, HUAWEI_TEST_PORT)
        scenario_8_locate_host(sc, HUAWEI_TEST_IP, [None])
        scenario_9_vrf_discovery_and_l3_interfaces(sc)
        scenario_11_l2_service_by_ip(sc, HUAWEI_TEST_IP, [None])
        scenario_12_l3_gateways_for_vpls(sc, HUAWEI_TEST_VPLS)
    finally:
        nc.close()


if __name__ == "__main__":
    run_nokia()
    run_huawei()
