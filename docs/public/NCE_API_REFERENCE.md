# Huawei NCE REST API Reference — PUBLIC

> **Public version** — contains real IPs, credentials, UUIDs, hostnames.
> Public version: `../public/NCE_API_REFERENCE.md`

---

## Connection

**Base URL:** `https://10.x.x.x:26335`
**Auth:** PUT `/rest/plat/smapp/v1/sessions` with body `{"grantType":"password","userName":"api_user","value":"***password***"}`
**Returns:** `{"accessSession": "<token>"}` → use as `X-Auth-Token` header
**Token persistence:** saved to `nce_token.txt`, auto-refresh on HTTP 401

---

## 1. Network Elements (NceNode — RFC 8345)

### API
```
GET /restconf/v2/data/huawei-nce-resource-inventory:network-elements
```

### Server-side filters (query params)
| Parameter | Description | Example |
|-----------|------------|---------|
| `name` | Exact NE name | `name=Router-PE-02` |
| `ref-parent-subnet` | Subnet UUID | `ref-parent-subnet=eed4f41a-...` |
| `product-name` | Device model | `product-name=NE40E-X3` |
| `ip-address` | Management IP | `ip-address=10.x.x.x` |
| `limit` | Page size (max 5000, default 2000) | `limit=1000` |
| `marker` | Next page marker (from response header) | |

### Pagination
Response headers: `is-truncated: true/false`, `next-page: "/restconf/v2/data/...?marker=xxx&limit=2000"`

### Response structure
```json
{"network-elements": {"network-element": [...]}}
```

### Field mapping → BaseNode (RFC 8345)
| API field (kebab-case) | BaseNode field | Real example |
|------------------------|---------------|-------------|
| `res-id` | `node_id` | `c91fc919-b9f9-11ea-ad74-b008759ca76f` |
| `name` | `name` | `Router-PE-02` |
| `ip-address` | `management_address` | `10.x.x.x` |
| `detail-dev-type-name` or `product-name` | `platform_type` | `NE40E-X3` |
| `manufacturer` | `platform_vendor` | `Huawei` |
| `software-version` | `software_version` | `V800R020C05` |
| `communication-state` | `oper_status` | `0`=normal, `1`=interrupted |
| `admin-status` | `admin_status` | `active`, `inactive` |
| `ref-parent-subnet` | `topology_group` | UUID of subnet |

### Real data
- **Total NEs:** 1597
- **Subnets (node-class='subnet'):** 29

| Subnet | NEs |
|--------|-----|
| IP Domain | 111 |
| DWDM | 62 |
| Osh | 31 |
| SDH | 20 |
| Issyk-Kul_Naryn | 8 |
| OMC_SWITCH | 7 |

### vendor_specific_info fields
`res-id`, `lsr-id`, `dev-sys-name`, `physical-id`, `as-number`, `product-name`, `platform-version`, `hardware-version`, `patch-version`, `serial-number` (sn), `mac`, `location`, `remark`, `is-virtual`, `is-gateway`, `container`, `create-time`, `last-modified`

---

## 2. Links (NceLink — RFC 8345)

### API
```
GET /restconf/v2/data/huawei-nce-resource-inventory:links
```

### Server-side filters
| Parameter | Description |
|-----------|------------|
| `a-end-ne-id` | Source NE UUID |
| `z-end-ne-id` | Sink NE UUID |
| `cross-layer` | Multi-layer link type |
| `slice-id` | Network slice ID |
| `limit` / `marker` | Pagination |

### Response structure
```json
{"links": {"link": [...]}}
```

### Field mapping → BaseLink (RFC 8345)
| API field | BaseLink field | Note |
|-----------|---------------|------|
| `res-id` | `link_id` | UUID |
| `name` | `name` | `NE1-Shelf1-7(GE1/0/7)-NE2-Shelf1-7(GE1/0/7)` |
| `a-end-ne-id` | `source_node` | UUID → resolved to `source_node_name` |
| `z-end-ne-id` | `dest_node` | UUID → resolved to `dest_node_name` |
| `a-end-ltp-id` | `source_tp` | UUID → resolved to `source_tp_name` |
| `z-end-ltp-id` | `dest_tp` | UUID → resolved to `dest_tp_name` |
| `operate-status` | `oper_status` | `0`=up, `1`=down, absent=unknown |
| `admin-status` | `admin_status` | `active` |
| `type` | `link_type` | See table below |
| `bandwidth` | `bandwidth` | kbps (float) |
| `layer-rate` | `layer_rate` | `LR_Ethernet`, `LR_PHYSICAL_OPTICAL`, etc. |
| `a-end-ip` | `source_ip` | IP address (may be empty) |
| `z-end-ip` | `dest_ip` | IP address (may be empty) |

### Link types (real data, 4346 total)
| type | count | bandwidth | layer-rate | operate-status |
|------|-------|-----------|------------|----------------|
| Fiber | 1990 | None | LR_PHYSICAL_OPTICAL | absent (unknown) |
| Microwave Link | 1146 | None | LR_PHYSICAL_MEDIALESS | absent (unknown) |
| L2 Link | 1143 | 1G/10G/100G | LR_Ethernet | `0` or `1` |
| Cable | 63 | 1G or None | LR_PHYSICAL_ELECTRICAL | absent |
| IP Link | 2 | 100M | LR_Ethernet | `0` or `1` |
| Dummy Link | 2 | - | - | - |

### Important behavior
- **Links are directional** (a-end → z-end). To find ALL links between two NEs, query BOTH directions.
- `get_links_between(name_a, name_b)` does this automatically.
- Name resolution (`resolve_names=True`) loads ALL NEs (~2s) + ALL ports (~56s) to build UUID→name caches.
- For small subsets, use `resolve_link_names(links)` after filtering — adaptive per-NE loading (threshold=10).

---

## 3. IGP Links (NceIgpLink — RFC 8346)

### API
```
GET /restconf/v3/data/huawei-nce-resource-inventory:igp-links
```

**Real data:** 0 IGP links (not used in this network). API works, returns empty.

**Contains (when populated):** `te-metric`, `latency`, `segment-id`, `bandwidth-bc0`, `total-available-bandwidth`, `max-reserved-bandwidth`, `a-end-ipv4/z-end-ipv4`, `priority-bandwidths[]`, `flex-algo-id[]`, `srlgs`

---

## 4. Termination Points / Ports (NceTerminationPoint — RFC 8345)

### API
```
GET /restconf/v3/data/huawei-nce-resource-inventory:ltps
```

### Server-side filters
| Parameter | Description |
|-----------|------------|
| `ne-id` | NE UUID (**always use when possible — 0.12s vs 56s**) |
| `name` | Port name |
| `card-id` | Board UUID |
| `ltp-type-name` | Port type (Ethernet, Eth-Trunk, WDM Client, OCH, etc.) |
| `sc-ltp-type` | SC type (ETH, Eth-Trunk, WDM, WDM Client, SDH, etc.) |
| `is-physical` | `true`/`false` |
| `is-sub-ltp` | `true`/`false` |
| `parent-ltp-id` | Parent port UUID (for subinterfaces) |
| `ltp-role` | `UNI`/`NNI` |
| `limit` / `marker` | Pagination (max 5000) |

### Response structure
```json
{"ltps": {"ltp": [...]}}
```

### Field mapping → BaseTerminationPoint
| API field | Field | Note |
|-----------|-------|------|
| `res-id` | `tp_id` | UUID |
| `name` | `name` | `GigabitEthernet1/0/0`, `Shelf0-3-U5N402-1(City)` |
| `native-name` | `hardware_port` | Port name on device |
| `ne-id` | `node_id` | UUID → resolved to `node_name` |
| `ltp-type-name` | `interface_type` | See types below |
| `is-physical` | `is_physical` | |
| `is-sub-ltp` | `is_sub_interface` | |
| `operate-status` | `oper_status` | `0`=up, `1`=down |
| `bandwidth` | `bandwidth` | kbps |
| `addrv4` | `ipv4_address` | **IP NEs only** (DWDM ports have no IP) |
| `addrv4-mask` | `ipv4_prefix_length` | |
| `trunk-ltp-id` | `trunk_ltp_id` | For LAG members → points to Eth-Trunk tp_id |
| `parent-ltp-id` | `parent_tp_id` | For sub-interfaces → points to parent |
| `mac` | `mac` | |
| `mtu` | `mtu` | |
| `sn` | `sn` | Serial number |

### Real data: 87,847 ports total

**IP NE (Router-PE-03, 68 ports):**
Ethernet: 35, Global-VE: 21, Tunnel: 4, LoopBack: 3, Aux: 1, Eth-Trunk: 1, NULL: 1, Virtual-Template: 1, Vlanif: 1

**DWDM NE (DWDM-Node-02, 661 ports):**
OCH: 483, OTS: 57, OMS/OTS: 54, WDM: 18, WDM SCA: 15, OSC: 15, MEth: 10, OMS: 9

### Trunk/LAG resolution
```
Eth-Trunk4 (is_physical=False, bandwidth=40G)
  ├── GE6/1/0 (trunk_ltp_id → Eth-Trunk4.tp_id, is_physical=True, 10G Fiber)
  ├── GE6/1/1 (trunk_ltp_id → Eth-Trunk4.tp_id)
  ├── GE6/1/2 (trunk_ltp_id → Eth-Trunk4.tp_id)
  └── GE6/1/3 (trunk_ltp_id → Eth-Trunk4.tp_id)
```

### Rate limiting
Max ~10 concurrent requests to /ltps endpoint. HTTP 429 if exceeded.
pynetcom uses adaptive loading: ≤10 NEs → per-NE with 0.1s delay; >10 NEs → bulk load all ports.

---

## 5. Alarms (NceAlarm)

### API
```
GET /restconf/v1/data/ietf-alarms:alarms/alarm-list
```

### Server-side filters
| Parameter | Description |
|-----------|------------|
| `resource` | NE UUID |
| `perceived-severity` | `critical`, `major`, `minor`, `warning` (multi-value) |
| `start-time` | ISO 8601 UTC |
| `end-time` | ISO 8601 UTC |
| `is-cleared` | `true`/`false` |

### Response structure
```json
[{"alarm": [...]}]  or  {"alarm-list": {"alarm": [...]}}
```

### Key alarm fields
| Field | Description |
|-------|------------|
| `ne-name` (alarm-parameters) | `ne_name` |
| `ip-address` (alarm-parameters) | `ne_id` |
| `perceived-severity` | `severity` (critical/major/minor/warning) |
| `alarm-text` | `alarm_name` |
| `location-info` | `affected_object` — contains port name, IP, session |
| `repair-action` | `additional_text` — repair instructions from NCE KB |
| `is-cleared` | `is_cleared` |
| `time-created` | `time_created` |

### Real data: ~1860 active alarms

**Common IP alarms on down links:**
- `Link Down` (critical) — `If Name=GigabitEthernet1/0/5`
- `The physical port is Down` (critical) — `PhysicalName=GigabitEthernet1/0/5`
- `BFD session change to fault down state` (major) — `SessName=dyn_10020`
- `MPLS LDP session is down` (major) — `LDP Id=11.x.0.8`
- `The state of the OSPF interface changed` (major) — `Interface IP=11.x.1.144`

**DWDM optical alarms (19 active):**
- `Input optical power is too low` (critical) — on OCH/OSC ports
- `Loss of OSC interface input optical power` (critical)
- `Bit errors over threshold before FEC` (minor) — on OTU ports
- `Optical module working temperature over threshold` (major)
- `Alarm of OA gain turn-down` (critical) — on OTS ports

---

## 6. Performance Monitoring — Vendor Specific Raw PM

> **This is the API that works for DWDM optical power!**
> ACTN Standard API (section 7) has limitations for non-OTN ports.

### 6.1 Create Monitor Task

```
POST /restconf/v1/operations/huawei-nce-common-pm-rawdata:create-monitor-tasks
```

```json
{
    "huawei-nce-common-pm-rawdata:input": {
        "monitor-tasks": [
            {
                "task-id": "uuid-generated-by-client",
                "task-name": "descriptive-name",
                "res-type-name": "ltp",
                "res-id": "port-tp_id-uuid",
                "task-cfg": {
                    "period": "per15min",
                    "indicators": {
                        "indicator": [
                            {"indicator-id": "Cur Total Input Optical Power"},
                            {"indicator-id": "Cur Total Output Optical Power"},
                            {"indicator-id": "Temperature"}
                        ]
                    }
                }
            }
        ]
    }
}
```

**res-type-name:** `ltp` (ports), `card` (boards)
**Max:** 10 tasks per request, 10 concurrent calls

**TESTED RESULTS:**
- Board (card-id `50ef519c-c1a4-11ea-9050-b008759ca873`): **200 OK** → Temperature = 61.6°C
- OCH port (`50f03c06-c1a4-11ea-9050-b008759ca873`): **200 OK** → Cur Total Input Optical Power = -10.8 dBm

### 6.2 Query Realtime PM

```
POST /restconf/v1/operations/huawei-nce-common-pm-rawdata:query-realtime-pm-datas
```

```json
{
    "huawei-nce-common-pm-rawdata:input": {
        "res-ids": ["port-tp_id-uuid"]
    }
}
```

**Response:**
```json
{
    "huawei-nce-common-pm-rawdata:output": {
        "pm-datas": {
            "pm-data": [{
                "res-id": "50f03c06-c1a4-11ea-9050-b008759ca873",
                "collect-time": "2026-04-08T11:00:00.000Z",
                "res-name": "DWDM-Node-01-Shelf0-3-WDM_BOARD-1-City-West-OCH:1",
                "res-type-name": "ltp",
                "device-id": "5d114e26-c19e-11ea-92c8-b008759ca873",
                "device-name": "DWDM-Node-01",
                "indicator-datas": {
                    "indicator-data": [{
                        "indicator-id": "Cur Total Input Optical Power",
                        "indicator-double-value": -10.8,
                        "indicator-value-type": "double",
                        "indicator-value-unit": "dBm"
                    }]
                }
            }]
        }
    }
}
```

### 6.3 Query Historical PM

```
POST /restconf/v1/operations/huawei-nce-common-pm-rawdata:query-history-pm-datas
```

```json
{
    "huawei-nce-common-pm-rawdata:input": {
        "res-ids": ["port-tp_id-uuid"],
        "period": "per15min",
        "start-time": "2026-04-08T08:00:00.000Z",
        "end-time": "2026-04-08T09:00:00.000Z"
    }
}
```

**Constraints:** 15min → max 1 day. Daily → max 1 month. Max 10 resources.

### 6.4 Query Monitor Tasks

```
POST /restconf/v1/operations/huawei-nce-common-pm-rawdata:query-monitor-tasks
```

```json
{"huawei-nce-common-pm-rawdata:input": {"res-ids": ["port-tp_id-uuid"]}}
```

### 6.5 Delete Monitor Task

```
POST /restconf/v1/operations/huawei-nce-common-pm-rawdata:delete-monitor-tasks
```

### 6.6 Available PM Indicators

**For `ltp` ports (59 indicators):**

| Category | Indicators | Unit |
|----------|-----------|------|
| **Optical Power** | Cur/Max/Min Total Input Optical Power | dBm |
| | Cur/Max/Min Total Output Optical Power | dBm |
| | Cur Laser Input/Output Optical Power | dBm |
| | Cur Laser Output/Input Power On The Sub-channel | 0.1dBm |
| **Signal Quality** | Average ESNR | dB |
| | Q Value | dB |
| | Pre-FEC BER / Post-FEC BER | % |
| | FEC Corrected 0/1 Bit Count, Byte Count, UnCorrected Block | bit |
| **Transceiver** | Temperature / Max / Min | 0.1°C |
| | Bias Current / Max / Min | mA |
| | Voltage / Max / Min | 0.1V |
| | Cur Bias Current On The Sub-channel | 0.1mA |
| **Dispersion** | Cur Dispersion Compensation Value | ps/nm |
| | Cur Polarization Mode Dispersion Value | pps/nm |
| **OTN** | ODUCn PM Errored/Severely Errored/Unavailable Seconds | s |
| **Traffic** | Receive/Send Byte Count | byte |
| | Receive/Send Packets | packets |
| | PORT_RX/TX_BW_UTILIZATION_AVG | % |
| | ETHFCS (FCS Errors) | frames |
| **Other** | EDFA Cooling Current Avg Value | mA |

**For `card` boards (14 indicators):**
Temperature (°C), Min/Max Temperature, Current CPU Usage (%), Current Input/Output Voltage (V), Cur Input/Output Current (mA), Current Fan Speed (r/s), BD_CUR_POWER (W), BD_MEM_UTILIZATION (bit), XCS Board Temperature Fluctuation (°C), MEMUSAGEAVG (%)

---

## 7. Performance Monitoring — ACTN Standard

> **Limited:** only works for OTN ports. Use Vendor Specific (section 6) for optical power.

### Endpoints (all `/restconf/v2/`)
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/operations/ietf-optical-resource-pm:get-all-current-pm-data` | Current PM |
| POST | `/operations/ietf-optical-resource-pm:get-historic-pm-data` | Historical PM |
| POST | `/operations/ietf-optical-resource-pm:get-ne-monitor-status` | Check PM enabled |
| POST | `/operations/ietf-optical-resource-pm:set-ne-monitor-status` | Enable/disable PM |
| POST | `/data/ietf-optical-resource-pm:performance-monitoring/monitor-tasks` | Create task |
| GET | `/data/.../monitor-tasks/monitor-task={task-id}` | Query task |
| DELETE | `/data/.../monitor-tasks/monitor-task={task-id}` | Delete task |

**PM Monitor Status test (DWDM-Node-02):** 200 OK, 15min=enable (since 2020-07-07), 24h=enable

---

## 8. Subnets

```
GET /restconf/v2/data/huawei-nce-resource-inventory:subnets
```

Response: `{"subnets": {"subnet": [...]}}`
Filter actual subnets: `node-class == 'subnet'` (1606 total entries, 29 real subnets)

---

## 9. Performance Summary

| Operation | Time | Notes |
|-----------|------|-------|
| All NEs (~1600) | ~2s | |
| All links (~4300) | ~2s | 3 pages |
| All ports (~88K) | ~56s | 18 pages |
| Ports for 1 NE | ~0.12s | server-side filter |
| Resolve link names | ~58s | loads NE + all ports |
| Links between 2 NEs | ~0.2s | 2 targeted queries |
| Neighbors of NE | ~0.3s | 2 queries + merge |
| Alarms for NE | ~0.2s | server-side filter |
| PM realtime query | ~0.1s | requires task created first |
| PM task create | ~0.5s | |

### Rate Limits
- `/ltps`: ~10 concurrent, HTTP 429 if exceeded
- PM: 10 concurrent, 10 resources/tasks per request
- Links: 10 concurrent (3K env) / 20 concurrent (6K env)

---

## 10. Source Documentation

| Document | Location |
|----------|----------|
| NCE-IP API Guide | `C:\docs\huawei\NCE\iMaster NCE-IP V100R023C00 NBI Documents 06-C\...\Northbound REST API Guide 06.pdf` |
| NCE-T Vendor Specific API | `C:\docs\huawei\NCE\iMaster NCE-T V100R023C10 NBI Document 07-C\...\(Vendor Specific)\...Guide 05.pdf` (3198 pages) |
| NCE-T ACTN Standard API | `...\(ACTN Standard)\...Guide 07.pdf` (1728 pages) |
| NCE-T PM Event List (ACTN) | `...\(ACTN Standard)\...Performance Event List 02.xlsx` |
| NCE-T PM Event List (Vendor) | `...\(Vendor Specific)\...Performance Event List 01.xlsx` |
| NCE-IP PM Event List | `...\NCE-IP\...Performance Event List 02.xlsx` |
