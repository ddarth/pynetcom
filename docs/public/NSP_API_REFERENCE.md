# Nokia NSP REST API & NETCONF Reference — PUBLIC

> **Public version** — contains real IPs, credentials, hostnames.
> Public version: `../public/NSP_API_REFERENCE.md`

---

## Connection

### NSP REST API
**Gateway URL:** `https://172.x.x.x`
**Data port:** 8544
**Auth:** POST `/rest-gateway/rest/api/v1/auth/token` with Basic auth (base64 of `api_user:***password***`), body `{"grant_type":"client_credentials"}`
**Returns:** `{"access_token":"..."}` → use as `Authorization: Bearer {token}`
**Token persistence:** saved to `nsp_token.txt`

### NETCONF (directly to device)
**Port:** 830
**Credentials:** `netconf_user` / `netconf_user_123`
**Not through NSP** — direct SSH/NETCONF to each router management IP

---

## 1. Network Elements (NspNode — RFC 8345)

### API
```
GET https://172.x.x.x:8544/NetworkSupervision/rest/api/v1/networkElements
```

### Filters
```
?filter=name='Nokia-AC-01'
```

### Response
Standard NSP envelope: `{"response": {"status":0, "totalRows":112, "data":[...]}}`

### Field mapping → BaseNode
| API field (camelCase) | BaseNode field | Real example |
|----------------------|---------------|-------------|
| `neId` or `ipAddress` | `node_id` | `172.x.x.9` |
| `name` / `neName` | `name` | `Nokia-AC-01` |
| `ipAddress` | `management_address` | `172.x.x.9` |
| `type` | `platform_type` | `7250 IXR-e` |
| (hardcoded) | `platform_vendor` | `Nokia` |
| `version` | `software_version` | `TiMOS-C-23.10.R6` |
| `communicationState` | `oper_status` | `up` / `down` |
| `adminState` | `admin_status` | `unlocked` |
| `topologyGroup` | `topology_group` | `fdn:realm:sam:topologyGroup:Network-Osh` |

### Real data
- **Total NEs:** 112
- **Topology groups:** Network-Osh (65 NEs), Network-JA (47 NEs)
- **Device types:** 7210 SAS-Mxp (majority), 7250 IXR-e (few), 7750 SR (core)
- **vendor_specific_info:** fdn, product, managedState, resyncState, operState, macAddress, clliCode, location, longitude, latitude, sourceType, sourceSystem

---

## 2. Physical Links

### API
```
GET https://172.x.x.x:8544/NetworkSupervision/rest/api/v1/physicalLinks
```

### Real data: 325 links (LLDP-discovered)
**No server-side filter by NE** — filter client-side by link `name` field.

### Structure
```json
{
    "name": "Nokia-AC-01:1/1/29--Oc.Sherl.AC_01:1/1/32",
    "type": "cable",
    "operState": "enabled",
    "direction": "biDirectional",
    "objectDetails": {
        "linkDiscoveredFrom": "lldp",
        "isLagMember": "false",
        "cableType": "ethernet",
        "linkType": "pointToPoint"
    },
    "endpoints": [
        {"name": "Port 1/1/29", "parentNeId": "172.x.x.9", "port": "fdn:model:..."},
        {"name": "Port 1/1/32", "parentNeId": "172.x.x.96", "port": "fdn:model:..."}
    ]
}
```

**Key difference from NCE:** Endpoints are an array (not a-end/z-end). Each has `parentNeId` and port FDN.

---

## 3. Ports

### API
```
GET https://172.x.x.x:8544/NetworkSupervision/rest/api/v1/ports
```

### Filters
```
?filter=neName='Nokia-AC-01'
```

### Real data: 4318 ports total
**NO IP ADDRESSES** in port data. Only physical info: name, neId, operState, serialNumber, macAddress, portDetails (portType, rate, actualRate, encapType, mtuValue)

### Example port
```json
{
    "name": "Port 1/1/1",
    "neName": "Nokia-AC-01",
    "neId": "172.x.x.9",
    "operState": "enabled",
    "adminState": "unlocked",
    "serialNumber": "PLD0KWT",
    "macAddress": "A0-67-D6-54-4A-6E",
    "portDetails": {
        "portType": "ethernet",
        "rate": "ethernet100",
        "actualRate": 100000.0,
        "portMode": "access",
        "encapType": "nullEncap",
        "mtuValue": 1514
    }
}
```

---

## 4. LAGs

### API
```
GET https://172.x.x.x:8544/NetworkSupervision/rest/api/v1/lags
```

### Filters
```
?filter=neName='Nokia-AC-01'
```

### Real data: 76 LAGs
Each LAG contains `members[]` with `portFdn` and `portName`.

### Example
```json
{
    "lagId": "2",
    "name": "Lag 2",
    "neName": "Nokia-AC-01",
    "description": "Nokia-CR-01 MMM LAG (OSN 1800)",
    "operationalSpeed": 20000000.0,
    "lagMode": "trunk",
    "operState": "enabled",
    "members": [
        {"portFdn": "fdn:model:equipment:Equipment:745968", "portName": "Port 1/1/32"},
        {"portFdn": "fdn:model:equipment:Equipment:745967", "portName": "Port 1/1/31"}
    ]
}
```

---

## 5. Alarms (NspAlarm)

### API
```
GET https://172.x.x.x:8544/FaultManagement/rest/api/v2/alarms/details
```

### Filters
```
?alarmFilter=neName='Nokia-AC-01' and severity<>'cleared'
```

Multiple conditions: `neName='X' and severity='critical'`
Time: `lastTimeDetected>1765773167000` (milliseconds)

### Real data: 20,385+ total alarms
Test NE (Nokia-AC-01): 53 active alarms including:
- `BootParametersMisconfigured` (critical)
- `PortSfpStatusFailure` (major) — on specific ports
- `EquipmentDown` (major)
- `LabelProblem` (critical)
- `CommunityMisconfiguration` (major)

---

## 6. L3 Interfaces via NETCONF (NspInterface — OpenConfig)

> **This is the ONLY way to get IP addresses from Nokia devices.**
> NSP REST API does NOT expose L3/IP data.

### Connection
```
NETCONF SSH to device management IP, port 830
Credentials: netconf_user / netconf_user_123
```

### 6.1 Config — Interface names, ports, IPs (fast, ~1s)
```xml
<configure xmlns="urn:nokia.com:sros:ns:yang:sr:conf">
  <router>
    <router-name>Base</router-name>
    <interface/>
  </router>
</configure>
```

### Config response fields
| XML field | BaseInterface field | Example |
|-----------|-------------------|---------|
| `interface-name` | `interface_name` | `Nokia-AC-01-Nokia-AC-02` |
| `port` | `hardware_port` | `1/1/23` or `lag-2` |
| `ipv4/primary/address` | `ipv4_address` | `172.x.x.133` |
| `ipv4/primary/prefix-length` | `ipv4_prefix_length` | `31` |

LAG detection: `is_lag = hardware_port.startswith('lag-')`

### 6.2 State — Oper status, protocols, neighbors (~0.5s per interface)
```xml
<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">
  <router>
    <router-name>Base</router-name>
    <interface>
      <interface-name>{name}</interface-name>
    </interface>
  </router>
</state>
```

### State response fields
| XML field | BaseInterface field |
|-----------|-------------------|
| `oper-state` | `oper_status` |
| `oper-ip-mtu` | `mtu` |
| `protocol` (space-separated) | `protocols` (list) |
| `ipv4/neighbor-discovery/neighbor/ipv4-address` | `neighbor_address` |
| `ipv4/neighbor-discovery/neighbor/mac-address` | `neighbor_mac` |

### Real test: Nokia-AC-01 (172.x.x.9) — 7 interfaces

| Interface | Port | IPv4 | Status | Protocols | Neighbor |
|-----------|------|------|--------|-----------|----------|
| Nokia-AC-01-Nokia-AC-02 | 1/1/23 | 172.x.x.133/31 | up | ospfv2,mpls,rsvp,ldp | 172.x.x.132 (a0:67:d6:87:db:ae) |
| Nokia-AC-01-Oc.JArk2.AC_01 | 1/1/c34/1 | 172.x.x.137/31 | up | ospfv2,mpls,rsvp,ldp | 172.x.x.136 (a0:67:d6:55:61:18) |
| Nokia-AC-01-Oc.JArk2.AC_01_1 | 1/1/24 | 172.x.x.141/31 | up | ospfv2,mpls,rsvp,ldp | 172.x.x.140 (a0:67:d6:55:61:0f) |
| Nokia-AC-01-Oc.Kshro.AC_01 | 1/1/30 | 172.x.x.105/31 | up | ospfv2,mpls,rsvp,ldp | 172.x.x.104 (a0:67:d6:8b:50:80) |
| Nokia-AC-01-Nokia-CR-01 | **lag-2** | 172.x.x.138/31 | up | ospfv2,mpls,rsvp,ldp | 172.x.x.139 (a0:f3:e4:84:5b:72) |
| Nokia-AC-01-Oc.Sherl.AC_01 | 1/1/29 | 172.x.x.106/31 | up | ospfv2,mpls,rsvp,ldp | 172.x.x.107 (a0:67:d6:8d:82:d4) |
| system | — | 172.x.x.9/32 | up | ospfv2,mpls,rsvp | — |

### Device NETCONF support
| Device type | NETCONF | Interfaces |
|-------------|---------|-----------|
| 7250 IXR-e | ✅ Works | 3-7 interfaces per NE |
| 7750 SR | ✅ Works | varies |
| 7210 SAS-Mxp | ❌ Fails | Connection refused or session close |

**Multi-NE test (10 NEs):** 2 OK (7250 IXR), 8 FAIL (7210 SAS)

---

## 7. NSP L3 Data Limitations

**NSP REST API does NOT provide:**
- IP addresses on ports
- Routing instances / router interfaces
- OSPF/ISIS/BGP topology
- VRF / L3VPN service data

**Reason:** NSP runs in classic NFM-P mode. RESTCONF modules `nsp-logical-port`, `nsp-l3-unicast`, `nsp-routing`, `nsp-interface`, `nsp-ospf`, `nsp-isis` all return 405 "Not Supported".

**RESTCONF gateway (port 8545):** Available but only exposes `nsp-equipment:network` (physical inventory). MDM (Model-Driven Management) not configured for devices.

**`nsp-inventory:find` RPC:** Works for equipment queries but not for L3 data.

---

## 8. Available NSP REST Services (29 total)

### Inventory (port 8544)
| Service | Endpoints | Key operations |
|---------|-----------|---------------|
| networkElements | 14 | GET all, by FDN, nested shelves/cards/ports/lags |
| ports | 2 | GET all, by FDN |
| lags | 2 | GET all, by FDN |
| physicalLinks | 4 | GET/POST/DELETE |
| cards | 2 | GET all, by FDN |
| cardSlots | 2 | GET all, by FDN |
| shelves | 2 | GET all, by FDN |
| radioEquipment | 2 | GET all, by FDN |

### Fault Management (port 8544)
| Service | Endpoints |
|---------|-----------|
| alarms | 17 (CRUD, details, rootCauses, squelch) |
| historicalAlarms | 3 |
| alarmedObjects | 2 |
| alarmSettings | 22 |

### Other
notifications (6), kpi (3), tca (26), oam (36), groups/views, sessions, access-control

---

## 9. Performance Summary

| Operation | Time | Notes |
|-----------|------|-------|
| All NEs (112) | ~1s | |
| All physical links (325) | ~1s | |
| All ports (4318) | ~2s | |
| Ports for 1 NE | ~0.1s | server-side filter |
| NETCONF interfaces (config only) | ~1-2s/NE | |
| NETCONF interfaces (config+state) | ~5-10s/NE | state query per interface |
| NETCONF to non-supporting NE | ~2s timeout | 7210 SAS |
| Alarms for 1 NE | ~0.2s | |
| All alarms (20K+) | ~3s | paginated |

---

## 10. Source Documentation

| Document | Location |
|----------|----------|
| NSP REST Gateway Swagger | `https://172.x.x.x/rest-gateway/api-docs/` |
| NetworkSupervision Swagger | `https://172.x.x.x:8544/NetworkSupervision/rest/api/api-docs?group=v1` |
| FaultManagement Swagger | `https://172.x.x.x:8544/FaultManagement/rest/api/api-docs?group=v2` |
| Nokia SROS YANG models | NETCONF capabilities on device (nokia-conf, nokia-state) |
