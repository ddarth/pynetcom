# NETCONF Services Client Reference — PUBLIC

> **Public version** — IPs and service names are sanitized.
> Internal version: `../internal/SERVICES_CLIENT.md`

> **Audience.** This file is the source-of-truth reference for the
> `ServicesClient` API and the vendor-native YANG paths it sits on top of.
> It is written to be self-contained for both human operators and AI agents:
> every reference includes the Python file path, the class/function name,
> the YANG module + path, and a concrete JSON shape.

---

## Connection

Both vendors expose NETCONF on SSH; the port differs:

| Vendor | Family | Port | `device_params` |
|--------|--------|------|------------------|
| Nokia SR OS | 7750 / 7250 (TimOS) | 830 | `{"name": "sros"}` (or `"alu"`) |
| Huawei VRP | NE40E / NE8000 / NE9000 / ATN-910C / OC-NE-X | 22 | `{"name": "huaweiyang"}` |

The transport is `pynetcom.NetconfClient` (`pynetcom/netconf_client.py`); it
wraps `ncclient.manager.connect()` and provides `.get(subtree_filter)` plus
a `get_raw()` fallback for multi-root subtree filters.

```python
from pynetcom import NetconfClient, ServicesClient

nc = NetconfClient(
    host="192.0.2.x", port=830,
    user="netconf_user", password="***",
    device_params={"name": "sros"},
)
sc = ServicesClient(nc, vendor="nokia")          # or vendor="huawei"
```

`ServicesClient` does **not** own the session — it accepts an already-connected
`NetconfClient` and never closes it. The caller is responsible for `nc.close()`.

---

## 1. L2VPN services (`get_l2vpn_services`)

Returns the list of multipoint **VPLS** and point-to-point **VPWS** L2
services on the device, wrapped in `NetworkInstance` (OpenConfig-aligned).

### API

```python
ServicesClient.get_l2vpn_services(
    name: str | None = None,
    include_fdb: bool = False,
    enrich_remote_system: bool = True,
) -> List[NetworkInstance]
```

| Parameter | Description | Default |
|-----------|-------------|---------|
| `name` | Service name (YANG list key). `None` → brief enumeration of every L2 service. With a name, full subtree is fetched. | `None` |
| `include_fdb` | Nokia VPLS only — embed FDB inside the same request (saves one round-trip). Ignored on EPIPE (no FDB) and Huawei. | `False` |
| `enrich_remote_system` | Nokia only — after parsing, fetch `/state/service/sdp` once and populate `RemoteEndpoint.remote_system` (far-end PE IP) on every PW. No effect on Huawei (`peer-ip` is native there). | `True` |

### Server-side filters

Both vendors narrow server-side on the **service-name** YANG list key. There
is no native filter for "only VPLS" or "only VPWS" — on Nokia we issue two
filtered queries (VPLS + EPIPE) and merge; on Huawei the merged shape is
provided by a single YANG list discriminated by a `type` leaf.

### Output: `NetworkInstance`

`pynetcom.utils.helpers.netconf.rpc_data_containers.services.NetworkInstance`

```json
{
  "name": "VPLS-EXAMPLE-1",
  "type": "L2VPN",                         // "L2VPN" (multipoint) | "L2P2P" (point-to-point) | "L3VPN" | "DEFAULT_INSTANCE"
  "enabled": true,
  "oper_status": "up",
  "route_distinguisher": null,
  "route_targets": [],
  "description": null,
  "connection_points": [
    {
      "connection_point_id": "1/1/11",
      "endpoints": [{
        "endpoint_id": "1/1/11",
        "type": "LOCAL",                   // = SAP (Nokia) or AC (Huawei)
        "local": {
          "subinterface": "1/1/11",
          "vlan": null,
          "oper_status": "up",
          "admin_status": null,
          "encapsulation": null
        },
        "remote": null
      }]
    },
    {
      "connection_point_id": "10:100",
      "endpoints": [{
        "endpoint_id": "10:100",
        "type": "REMOTE",                  // = spoke-sdp / mesh-sdp (Nokia) or PW (Huawei)
        "local": null,
        "remote": {
          "virtual_circuit_identifier": 100,
          "remote_system": "192.0.2.x",       // far-end PE IP
          "sdp_id": 10,                       // Nokia only; null on Huawei
          "oper_status": "up",                // OpenConfig: up | down only
          "signaling_type": "ldp",            // ldp | rsvp | bgp | static
          "encapsulation_type": "vlan",       // ether | vlan
          "redundancy_role": "primary",       // primary | secondary | null
          "redundancy_state": "active"        // active | standby | null
        }
      }]
    }
  ],
  "fdb": null,
  "neighbors": []
}
```

### Vendor → unified field mapping

#### Nokia VPLS (`/state/service/vpls`)
| YANG field | NetworkInstance field |
|------------|----------------------|
| `service-name` | `name` |
| `oper-state` | `oper_status` |
| `admin-state` | `enabled` (bool) |
| `description` | `description` |
| `sap[sap-id]` | LOCAL endpoint (`subinterface = sap-id`) |
| `spoke-sdp[sdp-bind-id]` / `mesh-sdp[sdp-bind-id]` | REMOTE endpoint (`sdp_id` = part before `:`, `virtual_circuit_identifier` = part after) |
| `/state/service/sdp[sdp-id]/oper-tunnel-far-end-inet-address` | `remote.remote_system` (filled via SDP enrichment) |

Type leaf is hard-coded to `L2VPN`.

#### Nokia EPIPE (`/state/service/epipe`)
Identical to VPLS for `sap` + `spoke-sdp`. **No** `mesh-sdp`, **no** `fdb`.
Type leaf is hard-coded to `L2P2P`.

#### Huawei L2VPN (`/l2vpn/instances/instance`)
| YANG field | NetworkInstance field |
|------------|----------------------|
| `name` | `name` |
| `state` | `oper_status` |
| `description` | `description` |
| `type` ("vpls" → `L2VPN`, "vpws-ldp"/"vpws-static"/"vpws-bgp" → `L2P2P`) | `type` |
| `vpls/acs/ac[interface-name]` | LOCAL endpoint |
| `vpls/ldp-signaling/pws/pw[peer-ip,pw-id]` | REMOTE endpoint (`remote_system` = `peer-ip`, `virtual_circuit_identifier` = `pw-id`) |

### Real data

| Host | Vendor | VPLS count | VPWS count |
|------|--------|------------|------------|
| 192.0.2.8 | Nokia SR OS 23 | 8 | 0 |
| 192.0.2.40 | Nokia SR OS 23 | 9 | 2 |
| 192.0.2.147 | Huawei NE-series | 13 | 1 |

---

## 2. Endpoints (`get_endpoints`)

Convenience wrapper — fetches one service and flattens
`connection_points[].endpoints` into a single list.

```python
ServicesClient.get_endpoints(service_name: str) -> List[Endpoint]
```

Equivalent to: `get_l2vpn_services(name=service_name)[0].saps() + .pseudowires()`.

---

## 2a. L3VPN / VRF services (`get_l3vpn_services`)

Returns the L3VPN / VRF instances configured on the device, as
`NetworkInstance` objects with `type = L3VPN`.

### API

```python
ServicesClient.get_l3vpn_services(name: str | None = None) -> List[NetworkInstance]
```

| Parameter | Side | Description |
|-----------|------|-------------|
| `name` | **server** | VRF / service name (YANG list key). `None` → all configured VRFs. |

The **global routing instance** (Nokia `"Base"`, Huawei `"_public_"`) is NOT a
VRF and is never returned — only explicitly-configured L3VPNs. Huawei's
synthetic system instances (`__LOCAL_OAM_VPN__`, `__dcn_vpn__`) are filtered
out as well.

### Output: `NetworkInstance` (type=L3VPN)

```json
{
  "name": "VPRN-EXAMPLE-1",
  "type": "L3VPN",
  "oper_status": "up",
  "route_distinguisher": "192.0.2.x:4003",   // Nokia: operational RD; Huawei: null in v1
  "enabled": true,
  "connection_points": [],
  "fdb": null,
  "neighbors": []
}
```

### Vendor mapping

| Nokia (`/state/service/vprn`) | Huawei (`/network-instance/instances/instance`) | Unified |
|-------------------------------|--------------------------------------------------|---------|
| `service-name` | `name` | `name` |
| `oper-state` | — (None in v1) | `oper_status` |
| `oper-route-distinguisher` | — (None in v1 — RD lives under the `huawei-l3vpn` `afs/af` subtree) | `route_distinguisher` |

### Real data

| Host | Vendor | VRF count |
|------|--------|-----------|
| 192.0.2.8 | Nokia SR OS 23 | 2 (`VPRN_EXAMPLE`, `VPRN_EXAMPLE_OMC_TS`) |
| 192.0.2.40 | Nokia SR OS 23 | 4 |
| 192.0.2.147 | Huawei NE-series | 3 (3 synthetic instances filtered out) |

---

## 2b. L3 interfaces (`get_l3_interfaces`)

Returns the L3 (IP-bearing) interfaces, optionally scoped to one VRF, as
`L3Interface` objects.

### API

```python
ServicesClient.get_l3_interfaces(
    vprn_name: str | None = None,
    enrich_l2_service: bool = False,
) -> List[L3Interface]
```

| Parameter | Side | Description |
|-----------|------|-------------|
| `vprn_name` | **server** (Nokia) / **client** (Huawei) | Routing-instance name. Canonical value `"Base"` for the global routing table on both vendors. Nokia: `None`/`"Base"` → global router; any other name → that VPRN (server-side scoped). Huawei: a single `huawei-ifm` query is filtered client-side on each interface's `vrf-name` (`"_public_"` is normalised to `"Base"` by the adapter). |
| `enrich_l2_service` | **client** | Resolve the L2-L3 binding and populate `L3Interface.l2_service` on each returned interface. Huawei: 2 extra RPCs (`huawei-fim-ifm` ve-groups + L2VPN VSI list). Nokia: 1 extra RPC per VRF (`/configure/service/vprn/<name>/interface/vpls`). Pure-L3 interfaces leave `l2_service` at `None`. |

Only interfaces that actually carry an IPv4 address are returned — L1/L2-only
ports are excluded. Like `get_arp_table`, Nokia does NOT auto-iterate every
VPRN — pass a VRF name to reach one.

### Output: `L3Interface`

```json
{
  "name": "Virtual-Ethernet0/2/3.2300",
  "vprn_name": "VPRN_EXAMPLE",
  "ipv4_address": "198.51.100.11",
  "ipv4_prefix_length": 24,        // Huawei: from netmask; Nokia: null (no mask in state model)
  "oper_status": "up",
  "admin_status": "up",
  "mtu": 1500,
  "l2_service": "VPLS_EXAMPLE_BTS"  // populated only when enrich_l2_service=True; null for pure-L3
}
```

### Vendor mapping

| Nokia (`/state/router|vprn/.../interface`) | Huawei (`/ifm/interfaces/interface`) | Unified |
|--------------------------------------------|--------------------------------------|---------|
| `interface-name` | `name` | `name` |
| router-name / VPRN service-name (list context) | `vrf-name` (`"_public_"` → `"Base"`) | `vprn_name` |
| `ipv4/primary/oper-address` | `ipv4/addresses/address/ip` (huawei-ip ns) | `ipv4_address` |
| — (not in state model) | `ipv4/addresses/address/mask` → prefix length | `ipv4_prefix_length` |
| `oper-state` | — | `oper_status` |
| — | `admin-status` | `admin_status` |
| `oper-ip-mtu` | — | `mtu` |
| `/configure/service/vprn[<name>]/interface[<>]/vpls/vpls-name` (1-step join, opt-in) | `huawei-fim-ifm` ve-group + VSI SAP cross-reference (2-step, opt-in) | `l2_service` |

### L2-L3 binding resolution (`l2_service`)

When `enrich_l2_service=True`, every returned `L3Interface` either gets a
non-empty `l2_service` (the VPLS / VSI it routes into) or stays at `None`
(pure-L3 interface with no L2 binding — a normal case).

* **Nokia** — one extra `get-config` query to
  `/configure/service/vprn[<name>]/interface[...]/vpls/vpls-name`. The
  binding is one-step (the VPRN-interface directly references the VPLS).
* **Huawei** — two extra queries: `huawei-fim-ifm` `/ifm/global/ve-groups`
  for the L3-parent ↔ L2-parent pairing, plus the L2VPN VSI list. The
  L3 sub-interface (e.g. `Virtual-Ethernet0/2/3.2300`) is paired with the
  L2 sub-interface of the matching VE-group parent on the same VLAN tag
  (`Virtual-Ethernet0/2/2.2300`), which appears as a SAP inside one VSI.

### Helpers built on the binding

```python
# Forward: IP → MAC + L2 service (deterministic, no MAC-name guessing)
ServicesClient.find_l2_service_by_ip(
    ip: str,
    vprn_name_candidates: list[str] | None = None,
) -> dict | None
# Returns {"ip", "mac", "vprn_name", "l3_interface", "l2_service"} or None.

# Reverse: VPLS → L3 gateway(s); empty list for pure-L2 VPLSes
ServicesClient.find_l3_gateways_for_l2_service(
    l2_service_name: str,
) -> list[L3Interface]
```

Both walk the same binding underneath; `find_l3_gateways_for_l2_service`
returns `[]` for VPLSes with no IRB gateway — that is the legitimate
"pure L2 transport" case (not an error).

### Real data

| Host | Scope | L3 interfaces |
|------|-------|---------------|
| 192.0.2.8 | global (Base) | 6 |
| 192.0.2.8 | `VPRN_EXAMPLE` | 1 |
| 192.0.2.40 | `VPRN_EXAMPLE` | 10 |
| 192.0.2.147 | global | 8 |

---

## 3. FDB / MAC table (`get_mac_table`)

```python
ServicesClient.get_mac_table(
    service_name: str | None = None,
    macs: list[str] | None = None,
    ports: list[str] | None = None,
    entry_type: str | None = None,
    learned_via: str | None = None,
    include_standby: bool = False,
    enrich_remote_system: bool = True,
) -> List[MacEntry]
```

| Parameter | Side | Description |
|-----------|------|-------------|
| `service_name` | **server** | Single VPLS / VSI name. YANG list key on both vendors. Multi-service fan-out not handled here. |
| `macs` | **server** | List of MAC addresses, OR-combined server-side (one round-trip). Each MAC becomes a sibling list-key entry under `<fdb>` (Nokia) or `<vsi-dynamic-macs>` (Huawei). Any separator style accepted (`aabbccddeeff`, `aa:bb:..`, `aa-bb-..`, `aabb.ccdd.eeff`) — each entry is normalised to the vendor's canonical form internally. `[]` is equivalent to `None`. |
| `ports` | **client** | List of substring patterns, OR-combined. An entry matches if any pattern appears (case-insensitive) in `MacEntry.interface`. |
| `entry_type` | **client** | `"STATIC"` or `"DYNAMIC"` (exact). |
| `learned_via` | **client** | `"sap"` or `"pw"` (exact) — restricts to MACs learned on a local SAP/AC vs. over a remote PW. Maps to `MacEntry.source_type`. |
| `include_standby` | **client** | Huawei-only. When `False` (default), `pw-role=slave` FDB records (the blocked half of an H-VPLS PW-redundancy pair) are filtered out so the table reflects only paths that actually carry traffic. Set `True` for failover debugging. No effect on Nokia (its FDB already exposes only the active sdp-bind). |
| `enrich_remote_system` | **client** | Nokia-only. When `True` (default), after parsing the FDB the client issues one extra brief query against `/state/service/sdp` and stamps `MacEntry.remote_system` on every PW row by joining the parsed `sdp-id` (left half of `sdp-bind`) with the SDP's `oper-tunnel-far-end-inet-address`. Set `False` to skip the extra round-trip. No effect on Huawei (`peer-ip` is already inline on every FDB record there). |

When `service_name is None and not macs` the device returns the entire FDB —
on big boxes that can be tens of MB and tens of seconds. A WARNING is logged in
that case. See [`benchmark_results.md`](../../examples/benchmark_results.md).

### Output: `MacEntry`

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",     // canonical colon notation
  "vlan": null,                            // int or null
  "interface": "10:100",                   // SAP-id, SDP-bind-id, or port-name
  "entry_type": "DYNAMIC",                 // "STATIC" | "DYNAMIC"
  "source_type": "PW",                     // "SAP" (local) | "PW" (remote) | null
  "age": 0,                                // seconds, vendor-specific semantics
  "network_instance": "VPLS-EXAMPLE-1",
  "remote_system": "192.0.2.179",         // peer-IP of originating PE (PW only)
  "pw_id": "1100010331"                    // vendor PW identifier (PW only)
}
```

`source_type` answers "where did the device learn this MAC" — `SAP` = local
Service Access Point (LOCAL endpoint), `PW` = remote pseudo-wire (REMOTE
endpoint). `null` only for rare host/oam entries.

`remote_system` + `pw_id` are populated for PW-learned entries on **both
vendors** and let callers identify the originating remote PE. On Huawei
`peer-ip` is inline in every FDB record (no extra RPC). On Nokia
`remote_system` is filled by a follow-up `/state/service/sdp` join (one
brief query per `get_mac_table` call — controlled by `enrich_remote_system`;
default on). `remote_system` is the remote PE's **system / loopback IP**,
not its management IP — match it against your inventory's router-ID column.

### Vendor mapping

| Nokia (`/state/service/vpls/<n>/fdb/mac`) | Huawei (`/mac/vsi-dynamic-macs/vsi-dynamic-mac`) | Unified |
|-----------|-----------|---------|
| `address` | `address` | `mac_address` |
| `sap` (locale=sap) or `sdp-bind` (locale=sdp-bind) | `out-interface-name` | `interface` |
| `type` (`learned`/`static`/`oam`/…) | parent list (`vsi-dynamic-macs` → DYNAMIC; `vsi-static-macs` → STATIC) | `entry_type` |
| `locale` (`sap` → SAP, `sdp-bind` → PW) | `out-interface-type` (`ac` → SAP, `pw` → PW) | `source_type` |
| `age` or `last-update` | `age` (often null) | `age` |
| context | `vsi-name` | `network_instance` |
| `oper-tunnel-far-end-inet-address` on `/state/service/sdp[sdp-id]` (via `enrich_remote_system` join) | `peer-ip` | `remote_system` |
| `sdp-bind` vc-id half (`"10179:1100010331"` → `"1100010331"`) | `pw-id` | `pw_id` |

### PW-learned duplicates

Huawei reports more than one FDB record for the same PW-learned MAC in
three distinct situations. The parser handles each one explicitly:

* **(A) ECMP / multi-uplink** (`pw-role=null`, NO Tunnel sibling): same
  MAC reachable via the same remote PE over multiple physical egress
  ports (e.g. `GigabitEthernet0/2/0` + `GigabitEthernet0/2/1` to peer
  `192.0.2.179`). Records have **identical** `remote_system` and
  `pw_id`, only `interface` differs. **All records are kept** — operator
  sees the load-balancing visibility, substring `port` filter continues
  to match the right rows.
* **(B) Underlay + Tunnel pair** (`pw-role=null`, with a `Tunnel*`
  sibling): seen on BSC-class boxes (NE40E / NE8000) and on ATN-series
  in some H-VPLS deployments. The same MAC is reported once with the
  underlay interface (an `Eth-Trunk*` LAG or a plain physical port that
  carries the MPLS transport) and once with the logical `Tunnel0/0/N`
  interface — identical `pw-id`, `peer-ip`, every other leaf. The parser
  applies a **prefer-tunnel** rule: when the `(mac, vsi, pw_id,
  remote_system)` group contains any `interface` starting with
  `"Tunnel"`, only the Tunnel record(s) are kept; the underlay siblings
  are dropped. Tunnel is the canonical PW identifier (stable across
  underlay failover, parallel to Nokia's `sdp-bind`).
* **(C) H-VPLS PW-redundancy** (`pw-role=master`/`slave`): same MAC
  reachable via two different remote PEs in an active/standby pair.
  Slave records represent a blocked path. By default the parser drops
  `slave` records (set `include_standby=True` to keep them) — this
  matches Nokia's natural behaviour, which never surfaces the standby
  sdp-bind on the FDB. After the slave-drop, the master is then put
  through the prefer-tunnel rule like any other PW row.

Concrete numbers from `ROUTER_BSC`, service
`VPLS_EXAMPLE_BTS` (raw NETCONF capture in
`examples/xml/Huawei/services/bsc_full_service_macs(response).xml`):
140 raw vsi-dynamic-mac → 72 `MacEntry` after parsing (5 SAP + 67 PW),
73 underlay siblings collapsed by the prefer-tunnel rule.

---

## 4. ARP / Neighbor table (`get_arp_table`)

```python
ServicesClient.get_arp_table(
    vprn_names: list[str] | None = None,
    ips: list[str] | None = None,
    macs: list[str] | None = None,
    interface: str | None = None,
    origin: str | None = None,
) -> List[Neighbor]
```

| Parameter | Side | Description |
|-----------|------|-------------|
| `vprn_names` | **server** | List of routing-instance names. Canonical value `"Base"` for the global routing table on both vendors. Nokia: a single `"Base"` selects the base router; any other name(s) → VPRN service names — note that Nokia cannot mix `"Base"` with named VPRNs in one RPC (hard YANG split). Huawei: `vpn-instance` names; `None` / `[]` = global routing table (Huawei's `/arp/query-entries` is a global subtree). Empty list is equivalent to `None`. |
| `ips` | **server** | List of IPv4 addresses (YANG list key). Expanded into sibling `<neighbor>` (Nokia) / `<query-entry>` (Huawei) elements. |
| `macs` | **mixed** | List of MACs (any separator style accepted, normalised internally). Nokia: **server-side** via content-match on `<mac-address>`. Huawei: **client-side** — server rejects MAC content-match (`This operation is not supported`), pynetcom filters after parse. |
| `interface` | client | Substring match on `Neighbor.interface`. |
| `origin` | client | `"STATIC"`, `"DYNAMIC"`, or `"OTHER"`. |

Batch (list-input) semantics — verified live 24-26 May 2026, ground-truth XML
in `network_entries/examples/probe_artifacts/arp_multi_*` and
`arp_mac_filter/`. One round-trip suffices for any combination of
`(vprn_names × ips × macs)` — collapses former N-way sequential walks into a
single RPC.

### Output: `Neighbor`

```json
{
  "ip": "192.0.2.1",
  "link_layer_address": "aa:bb:cc:dd:ee:ff",
  "interface": "to-core-1",
  "origin": "DYNAMIC",                      // "STATIC" | "DYNAMIC" | "OTHER"
  "vprn_name": "Base",                      // canonical "Base" for global; null on Huawei when row carried a synthetic VPN
  "age": 13864                              // seconds-to-expiry (Nokia) or null (Huawei)
}
```

### Vendor paths

| Field | Nokia | Huawei |
|-------|-------|--------|
| Base router | `/state/router[router-name=Base]/interface/ipv4/neighbor-discovery/neighbor` | `/arp/query-entries/query-entry` (no `vpn-instance` set on the entry) |
| VRF | `/state/service/vprn[service-name=X]/interface/ipv4/neighbor-discovery/neighbor` | `/arp/query-entries/query-entry` with `ni-name=X` |
| YANG namespace | `urn:nokia.com:sros:ns:yang:sr:state` (submodule `nokia-state-router` / `nokia-state-svc-vprn`) | `urn:huawei:yang:huawei-arp` |
| Origin enum | `static`/`dynamic`/`managed`/`evpn`/`other` | `static-arp`/`interface-arp`/`vlanif-arp`/`dynamic-arp`/`vlink-arp` |
| `age` semantic | **TTL until expiry** (`timer` leaf) | age-since-learned (often null) |

### Real data

| Host | Scope | Entries |
|------|-------|---------|
| 192.0.2.8 | Base | 5 |
| 192.0.2.8 | VPRN_EXAMPLE | 17 |
| 192.0.2.147 | global | 46 |

---

## 5. RPC request builders

Located in `pynetcom/utils/helpers/netconf/rpc_requests.py`. Use these directly
when `ServicesClient` doesn't fit (e.g. you want to embed a custom filter, or
issue the request via a non-pynetcom transport). Every builder exposes
`.get_request_filter() -> str`.

| Class | YANG path | Key params |
|-------|-----------|------------|
| `NokiaServiceRPCRequest` | `/state/service/vpls` | `service_name`, `brief`, `include_fdb` |
| `NokiaEpipeRPCRequest` | `/state/service/epipe` | `service_name`, `brief` |
| `NokiaSdpRPCRequest` | `/state/service/sdp` | `sdp_id`, `brief` |
| `NokiaFdbRPCRequest` | `/state/service/vpls/<n>/fdb/mac` | `service_name`, `mac_addresses: list[str]` |
| `NokiaArpRPCRequest` | `/state/router/<n>/interface/.../neighbor-discovery/neighbor` or VPRN variant | `router_name`, `vprn_service_names: list[str]`, `interface_name`, `ipv4_addresses: list[str]`, `mac_addresses: list[str]` |
| `NokiaVprnRPCRequest` | `/state/service/vprn` | `service_name` |
| `NokiaL3InterfaceRPCRequest` | `/state/router/<n>/interface` or `/state/service/vprn/<n>/interface` | `router_name`, `vprn_service_name`, `interface_name` |
| `HuaweiL2vpnRPCRequest` | `/l2vpn/instances/instance` | `name` |
| `HuaweiMacRPCRequest` | `/mac/vsi-dynamic-macs/vsi-dynamic-mac` (+ static/blackhole) | `vsi_name`, `mac_addresses: list[str]`, `include_static` |
| `HuaweiArpRPCRequest` | `/arp/query-entries/query-entry` | `vpn_instances: list[str]`, `ip_addresses: list[str]` (Cartesian-product expanded) |
| `HuaweiL3vpnRPCRequest` | `/network-instance/instances/instance` | `name` |
| `HuaweiL3InterfaceRPCRequest` | `/ifm/interfaces/interface` | `interface_name` |

`brief=True` returns only YANG list keys (cheap enumeration). `brief=False` (or
omitted) returns the full subtree — large on busy boxes; always combine with a
list-key narrowing parameter on those.

---

## 6. Data containers (OpenConfig-aligned)

Defined in `pynetcom/utils/helpers/netconf/rpc_data_containers/services.py`.
All are dataclass-style; `.to_dict()` produces the JSON shape shown above.

| Class | OpenConfig path | Purpose |
|-------|-----------------|---------|
| `NetworkInstance` | `/network-instances/network-instance` | One L2VPN, L3VPN, or default instance |
| `ConnectionPoint` | `/.../connection-points/connection-point` | A SAP + paired PWs grouping |
| `Endpoint` | `/.../endpoints/endpoint` | Single LOCAL (SAP/AC) or REMOTE (PW) endpoint |
| `LocalEndpoint` | `/.../endpoints/endpoint/local` | SAP-side fields (port, VLAN, encapsulation) |
| `RemoteEndpoint` | `/.../endpoints/endpoint/remote` | PW-side fields (vc-id, peer IP, sdp-id) |
| `Fdb` / `MacTable` / `MacEntry` | `/.../fdb/mac-table/entries/entry` | L2 forwarding entries |
| `Neighbor` | `/interfaces/.../ipv4/neighbors/neighbor` (projected flat with `vprn_name`) | ARP / ND entries |
| `L3Interface` | `/interfaces/interface` + ipv4 address (projected flat with `vprn_name`) | L3 (IP-bearing) interfaces |

Enums (in the same module):

| Enum | Values |
|------|--------|
| `NetworkInstanceType` | `DEFAULT_INSTANCE`, `L2VPN`, `L2P2P`, `L3VPN`, `L2L3` |
| `EndpointType` | `LOCAL`, `REMOTE` |
| `MacEntryType` | `STATIC`, `DYNAMIC` |
| `MacSourceType` | `SAP`, `PW` |
| `NeighborOrigin` | `STATIC`, `DYNAMIC`, `OTHER` |

Convenience accessors on `NetworkInstance`:

| Method | Returns |
|--------|---------|
| `saps()` | List of LOCAL endpoints across all connection points |
| `pseudowires()` | List of REMOTE endpoints across all connection points |
| `mac_entries()` | Flat list of MAC entries (empty if FDB not populated) |

---

## 7. Vendor adapters

Located alongside the base containers:

| File | Classes | Purpose |
|------|---------|---------|
| `nokia_services.py` | `NokiaVplsService`, `NokiaEpipeService`, `NokiaMacEntry`, `NokiaMacTable`, `NokiaArpEntry` | Nokia SR OS 23+ |
| `huawei_services.py` | `HuaweiL2vpnInstance`, `HuaweiMacEntry`, `HuaweiArpEntry` | Huawei VRP V8 NE-series |

Top-level parse functions (one per vendor + topic) consume a NETCONF response
dict (produced by `NetconfClient.get`) and return a flat list of OpenConfig
objects:

```python
nokia.parse_vpls_response(resp)        -> List[NokiaVplsService]
nokia.parse_epipe_response(resp)       -> List[NokiaEpipeService]
nokia.parse_sdp_response(resp)         -> dict[int, dict]    # {sdp_id: {far_end_ip, ...}}
nokia.parse_fdb_response(resp, service_name=None)  -> List[NokiaMacEntry]
nokia.parse_arp_response(resp, vprn_name="Base")   -> List[NokiaArpEntry]

huawei.parse_l2vpn_response(resp)      -> List[HuaweiL2vpnInstance]
huawei.parse_mac_response(resp)        -> List[HuaweiMacEntry]
huawei.parse_arp_response(resp)        -> List[HuaweiArpEntry]
```

A helper `nokia._attach_sdp_far_end(service, sdp_far_end_map)` walks a
`NetworkInstance` and populates `RemoteEndpoint.remote_system` from a
`{sdp_id: ip}` dict (built by `parse_sdp_response`). `ServicesClient` does this
automatically when `enrich_remote_system=True`.

---

## 8. Filtering strategy (per-vendor)

`ServicesClient` applies filters in two layers:

1. **Server-side** (cheap) — YANG list keys are embedded in the subtree filter.
   The device returns only the matching entries.
2. **Client-side** (after parsing) — non-key predicates are applied via
   `pynetcom.utils.helpers.rest_api.base.RestNMSDataFilter`. This is the same
   filter framework already used by REST API providers (`NspDataProvider` /
   `NceDataProvider`), so semantics stay consistent.

| Operation | Server-side keys | Client-side predicates |
|-----------|------------------|------------------------|
| `get_l2vpn_services` | `name` (= `service-name` / `instance/name`) | — |
| `get_l3vpn_services` | `name` (= `service-name` / `instance/name`) | — |
| `get_l3_interfaces` | `vprn_name` (Nokia — server; Huawei — client) | — |
| `get_mac_table` | `service_name`, `mac` | `port` (substring), `entry_type`, `learned_via` |
| `get_arp_table` | `vprn_names: list[str]`, `ips: list[str]`, `macs: list[str]` (Nokia only — server-side content-match) | `macs` (Huawei — client-side), `interface` (substring), `origin` |

---

## 8a. Capability matrix

The complete per-parameter breakdown. **Server-side** = embedded in the NETCONF
subtree filter, the device does the filtering (cheap, bounds the response).
**Client-side** = applied after parsing, in the library (you still don't write
it — it's a method parameter — but it does not reduce what the device ships).

| Method | Parameter | Side | Vendors | Match | Notes |
|--------|-----------|------|---------|-------|-------|
| `get_l2vpn_services` | `name` | server | both | exact (YANG key) | `service-name` (Nokia) / `instance/name` (Huawei) |
| `get_l2vpn_services` | `include_fdb` | request shape | Nokia VPLS | — | embeds FDB subtree in the same query |
| `get_l2vpn_services` | `enrich_remote_system` | extra round-trip | Nokia | — | one extra `/state/service/sdp` query to fill `RemoteEndpoint.remote_system` |
| `get_l3vpn_services` | `name` | server | both | exact (YANG key) | VPRN service-name (Nokia) / network-instance name (Huawei) |
| `get_l3_interfaces` | `vprn_name` | server (Nokia) / client (Huawei) | both | exact | Nokia scopes the subtree to one router/VPRN; Huawei filters `vrf-name` after parsing |
| `get_mac_table` | `service_name` | server | both | exact (YANG key) | VPLS/VSI name |
| `get_mac_table` | `mac` | server | both | exact (YANG key) | any separator style accepted, normalised per vendor |
| `get_mac_table` | `port` | client | both | substring, case-insensitive | matched on `MacEntry.interface` |
| `get_mac_table` | `entry_type` | client | both | exact | `STATIC` / `DYNAMIC` |
| `get_mac_table` | `learned_via` | client | both | exact | `sap` / `pw` → `MacEntry.source_type` |
| `get_arp_table` | `vprn_names` | server | both | exact, list | Nokia: `["Base"]` (alone) or any number of VPRN names; Huawei: `ni-name` list. Nokia can NOT mix `"Base"` with named VPRNs in one RPC. |
| `get_arp_table` | `ips` | server | both | exact, list (YANG key) | Each IP becomes a sibling list element; OR-combined. |
| `get_arp_table` | `macs` | server (Nokia) / client (Huawei) | both | exact, list | Nokia: content-match `<mac-address>`; Huawei: post-filter (server rejects `<mac-addr>` content-match). Any separator style accepted. |
| `get_arp_table` | `interface` | client | both | substring | matched on `Neighbor.interface` |
| `get_arp_table` | `origin` | client | both | exact | `STATIC` / `DYNAMIC` / `OTHER` |

**Rule of thumb.** Combine as many server-side keys as the question allows —
they bound the device-side response. Client-side filters then refine what's
left at ~0 cost. Never re-implement these filters in your own code; the
9 worked examples in `examples/services_mac_arp_recipes.py` show the canonical
call for every common MAC / ARP / VRF / L3-interface operation.

---

## 9. Performance notes

Measurements taken on lab routers in May 2026. Times include TCP + SSH +
NETCONF hello + the actual `<get>` round-trip.

| Operation | Time | Notes |
|-----------|------|-------|
| Nokia VPLS brief enumeration (8 services) | ~0.3 s | 1.2 KB response |
| Nokia VPLS full one service (1 SAP + 1 PW + 51 MACs) | ~17 s | 37 KB response; FDB dominates |
| Nokia VPLS full one service (0 SAP + 16 PWs) | ~1.2 s | 9 KB response, no FDB |
| Nokia EPIPE full one service | ~1 s | 10 KB response |
| Nokia SDP brief (4 SDPs) | ~3 s | 0.8 KB response |
| Nokia ARP base router (5 entries) | ~0.9 s | 2.8 KB response |
| Nokia ARP VPRN (17 entries) | ~1 s | 4 KB response |
| Huawei L2VPN brief (14 instances) | ~0.2 s | 2 KB response |
| Huawei L2VPN full one VPLS (10 ACs + 2 PWs) | ~0.8 s | 42 KB response |
| Huawei MAC table by VSI (25 MACs) | ~0.2 s | 14 KB response |
| Huawei MAC table full (~250 MACs) | ~1 s | 130 KB response |
| Huawei ARP full (46 entries) | ~0.2 s | 18 KB response |

### Known limits / quirks

- **Nokia VPLS unfiltered subtree is huge.** A real device can return tens of
  MB and exceed ncclient's default 120 s timeout. `ServicesClient` automatically
  uses `brief=True` when no `name` is supplied — never call the full-subtree
  filter without a list-key.
- **Nokia far-end IP is not on the PW entry.** `RemoteEndpoint.remote_system`
  is populated only when `enrich_remote_system=True` (the default), which costs
  one extra round-trip per `get_l2vpn_services` invocation. Disable to save it
  when only local endpoints / counters matter.
- **`huawei-vsi` module does not exist** on NE40E / NE8000 / ATN-910C boxes.
  Use `huawei-l2vpn` — `HuaweiL2vpnRPCRequest` already does. Older
  documentation referencing `huawei-vsi` is misleading.
- **Huawei runs NETCONF on the SSH port (22)**, not 830. Easy to miss.
- **Nokia `Neighbor.age` is TTL, Huawei's is age-since-learned** (often null).
  Don't compare values across vendors without converting.
- **Nokia VPRN / L3-interface full subtrees time out** — both
  `get_l3vpn_services` and `get_l3_interfaces` use field-selected filters; you
  never get the whole VRF routing table.
- **Huawei VRF list is in `huawei-network-instance`**, not `huawei-l3vpn`.
  `get_l3vpn_services` filters out the synthetic instances (`_public_`,
  `__LOCAL_OAM_VPN__`, `__dcn_vpn__`) — only configured VRFs are returned.
- **`L3Interface.ipv4_prefix_length` is None on Nokia** — the SR OS state
  model exposes the operational IP without a netmask. Huawei provides it.

---

## 10. Examples

Located in `examples/`. Each is < 60 lines, uses `config.py` for credentials,
and prints unified JSON. Each script is self-contained.

| Script | What it shows |
|--------|---------------|
| **`services_mac_arp_recipes.py`** | **AI-agent guide — 9 worked MAC / ARP / VRF / L3-interface operator scenarios, one library call each. Read this first.** |
| `services_get_vpls_nokia.py` | List + JSON of all VPLS on a Nokia router |
| `services_get_vsi_huawei.py` | List + JSON of all L2VPN instances on Huawei |
| `services_macs_by_vsi.py` | MAC table scoped to one service (server-side narrowing) |
| `services_macs_by_port.py` | MAC table filtered by port substring (client-side) |
| `services_arp_by_vrf.py` | ARP for global routing instance or named VRF (`vprn_name="Base"` or a VPRN name) |
| `services_arp_by_mac.py` | "Where is this host?" — find ARP entries by MAC across VRFs |
| `benchmark_services.py` | Performance benchmark — writes `benchmark_results.md` |
| `services_e2e_check.py` | Combined end-to-end check (VPLS + EPIPE + L3VPN + L3 interfaces, both vendors) |
| `services_smoke_test.py` | Offline test with synthetic responses |
| `regression_check.py` | Quick regression — imports + brief interface query |
| `verify_nokia_services.py` | Phase-1 probes; saves raw responses to `examples/xml/Nokia 7750/services/` |
| `verify_huawei_services.py` | Phase-1 probes for Huawei to `examples/xml/Huawei/services/` |
| `probe_nokia_paths.py` | YANG-path discovery helper (used to find ARP path) |
| `probe_huawei_modules.py` | YANG-module discovery — enumerates `huawei-*` modules per device |

---

## 11. Source documentation

| Document | Location |
|----------|----------|
| Nokia SR OS YANG (state model) | `github.com/nokia/7x50_YangModels` → `latest_sros_23.10/nokia-submodule/` |
| Nokia EPIPE state model | `nokia-state-svc-epipe.yang` |
| Nokia VPLS state model | `nokia-state-svc-vpls.yang` |
| Nokia ARP / interface state | `nokia-state-router.yang` (line ~3244 for IPv4 neighbor) |
| Nokia VPRN ARP | `nokia-state-svc-vprn.yang` |
| Nokia SDP | `nokia-state-svc-sdp.yang` |
| Huawei YANG modules | obtained from device hello capabilities (`probe_huawei_modules.py`) — no public repo |
| Sample raw responses | `examples/xml/Nokia 7750/services/`, `examples/xml/Huawei/services/` |
