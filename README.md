# PyNetCom

`pynetcom` is a library designed for connecting to network switches and routers from various vendors via REST API and CLI, as well as for interacting with management systems such as Huawei NCE and Nokia NSP. The library allows you to execute commands, retrieve inventory data, and obtain alarm lists.

## Features

- Connect to network devices using REST API, NETCONF, and CLI.
- Interact with management systems (e.g., Huawei NCE, Nokia NSP).
- Retrieve inventory data.
- Obtain alarm lists.
- Retrieve L2VPN services (VPLS/VPWS), FDB (MAC tables) and ARP tables via
  NETCONF, with vendor-agnostic OpenConfig-shaped responses on Nokia SR OS
  and Huawei VRP — see [`docs/public/SERVICES_CLIENT.md`](docs/public/SERVICES_CLIENT.md).
- Convenient token management for authorization.
- Automatic token refresh upon expiration.

## API references

- [Huawei NCE REST API](docs/public/NCE_API_REFERENCE.md) — `RestNCE` / `NceDataProvider`
- [Nokia NSP REST API](docs/public/NSP_API_REFERENCE.md) — `RestNSP` / `NspDataProvider`
- [NETCONF Services Client](docs/public/SERVICES_CLIENT.md) — `ServicesClient` for L2VPN / FDB / ARP across Nokia + Huawei

## Installation

You can install the package using `pip`:

```bash
pip install pynetcom
```

## Development

To set up the development environment:

```bash
# Install development dependencies
pip install setuptools wheel twine

# Install the package locally
pip install .

# Create wheel and source 
pip install build twine
python -m build

```

## Running Examples

To run examples, follow these steps:

1. Clone the repository:

    ```bash
    git clone https://github.com/ddarth/pynetcom.git
    cd pynetcom
    ```

2. Set up a virtual environment:

    ```bash
    python -m venv .venv
    ```

3. Activate the virtual environment:

    - On Windows:

        ```bash
        .venv\Scripts\activate
        ```

    - On macOS/Linux:

        ```bash
        source .venv/bin/activate
        ```

4. Add your configuration data to config.py:
    ```bash
    cp examples/config.example.py examples/config.py
    vi examples/config.py
    ```
    ```python
    API_NCE_USER =  "your_nce_api_user"
    API_NCE_PASS = "your_nce_password"
    API_NCE_HOST = "https://your_nce_hostip:26335"

    API_NSP_USER =  "your_nsp_api_user"
    API_NSP_PASS = "your_nsp_password"
    API_NSP_HOST = "https://your_nsp_host"

    NETCONF_HOST = "192.168.0.1"
    NETCONF_PORT = 830 # 22 for huawei
    NETCONF_USER = "your_netconf_user"
    NETCONF_PASSWORD = "yout_netconf_password"
    ```

5. Run an example script:

    ```bash
    python examples/huawei_nce.py
    ```


## Usage

### REST API (Huawei NCE)

```python
from pynetcom import RestNCE

# Initialize connection to NCE
nce = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)

# Get subnets from NCE
nce.send_request("/restconf/v2/data/huawei-nce-resource-inventory:subnets")
items = nce.get_data()
print(items)
```

### NETCONF Services Client (Nokia + Huawei)

```python
from pynetcom import NetconfClient, ServicesClient

# Nokia uses port 830, Huawei uses port 22
nc = NetconfClient(
    host=NETCONF_HOST, port=NETCONF_PORT,
    user=NETCONF_USER, password=NETCONF_PASSWORD,
    device_params={"name": "sros"},        # Nokia; use "huaweiyang" for Huawei
)
sc = ServicesClient(nc, vendor="nokia")    # or vendor="huawei"

# List all L2VPN (VPLS) and VPWS services
for svc in sc.get_l2vpn_services():
    print(svc.name, svc.type, svc.oper_status)

# Full detail of one service — SAPs, PWs, and remote_system (far-end IP) populated
detail = sc.get_l2vpn_services(name="VPLS-100")[0]

# MAC table scoped to one service (server-side YANG-key narrowing)
macs = sc.get_mac_table(service_name="VPLS-100")

# ARP table for a VRF (server-side narrowing)
arps = sc.get_arp_table(vrf="VPRN-200")

nc.close()
```

For the full API reference (vendor YANG paths, JSON output shape, performance
notes, filtering strategy) see [`docs/public/SERVICES_CLIENT.md`](docs/public/SERVICES_CLIENT.md).

For additional examples see the `examples/` folder.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Warning
Library use nsp_token.txt and nce_token.txt to store tokens.
Make sure that your have write permission to it.