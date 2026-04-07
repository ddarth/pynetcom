"""
Example: Using NceDataProvider for Huawei NCE port (LTP) management.

This example demonstrates:
- Getting all ports for an NE with type statistics
- Filtering ports by type, physical/logical, status
- Getting a single port by ID
- Showing port hierarchy (parent -> sub-interfaces)
- Resolving NE UUIDs to names
- Exporting port data to dict/JSON

API Endpoint: GET /restconf/v3/data/huawei-nce-resource-inventory:ltps

Server-side filters: ne-id, name, card-id, ltp-type-name, sc-ltp-type,
    is-physical, is-sub-ltp, parent-ltp-id, ltp-role, alias, port-type

Common port types (ltp-type-name):
    Physical: Ethernet, GigabitEthernet, 100GE, XGigabitEthernet
    Logical:  Eth-Trunk, LoopBack, Vlanif, Tunnel, Virtual-Template
    DWDM:     WDM Client, SDH, VC3, VC4, ODU2, CLIENT, OMS_OTS, OCH
    Access:   PON, ADSL, VDSL
"""

import logging
import time
from functools import wraps

from pynetcom import RestNCE, NceDataProvider, RestNMSDataFilter, NCEAuthenticationError
from config import API_NCE_HOST, API_NCE_USER, API_NCE_PASS, API_NCE_NE_NAME

# Configure logging
LOG_LEVEL = logging.DEBUG
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('pynetcom').setLevel(LOG_LEVEL)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def timed(func):
    """Decorator to measure and print execution time."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        print(f"Execution time: {elapsed:.2f}s")
        return result
    return wrapper


@timed
def example_get_ports_by_ne():
    """
    Get all ports for a specific NE.

    Uses ne-id server-side filter for efficient loading (~0.1s per NE).
    """
    print("\n" + "=" * 70)
    print("Example 1: Get all ports for an NE")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    # Find NE by name
    elements = provider.get_network_elements(name=API_NCE_NE_NAME)
    if not elements:
        print(f"NE '{API_NCE_NE_NAME}' not found")
        client.close()
        return

    ne = elements[0]
    ports = provider.get_ports(ne_id=ne.res_id, resolve_names=True)

    print(f"NE: {ne.name} ({ne.res_id})")
    print(f"Total ports: {len(ports)}")

    # Stats by type
    types = {}
    for p in ports:
        types[p.ltp_type_name] = types.get(p.ltp_type_name, 0) + 1
    print("\nBy type:")
    for t, c in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")

    # Show first 5
    print("\nFirst 5 ports:")
    for p in ports[:5]:
        print(f"  {p.brief()}")

    client.close()


@timed
def example_filter_physical_ports():
    """
    Get only physical ports using server-side filter.

    is_physical=True filters at the API level — only physical ports returned.
    """
    print("\n" + "=" * 70)
    print("Example 2: Physical ports only (server-side filter)")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    elements = provider.get_network_elements(name=API_NCE_NE_NAME)
    if not elements:
        client.close()
        return

    ports = provider.get_ports(ne_id=elements[0].res_id, is_physical=True)

    print(f"Physical ports: {len(ports)}")
    for p in ports[:10]:
        print(f"  {p.name} | {p.ltp_type_name} | BW: {p.bandwidth} | {p.medium_type or 'N/A'}")

    client.close()


@timed
def example_filter_by_type():
    """
    Get ports filtered by ltp-type-name (server-side).

    Common types: Ethernet, Eth-Trunk, LoopBack, Vlanif, Tunnel, WDM Client
    """
    print("\n" + "=" * 70)
    print("Example 3: Filter ports by type")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    elements = provider.get_network_elements(name=API_NCE_NE_NAME)
    if not elements:
        client.close()
        return
    ne_id = elements[0].res_id

    for ltp_type in ['Ethernet', 'Eth-Trunk', 'LoopBack', 'Vlanif']:
        ports = provider.get_ports(ne_id=ne_id, ltp_type_name=ltp_type)
        print(f"\n{ltp_type}: {len(ports)}")
        for p in ports[:3]:
            print(f"  {p.brief()}")

    client.close()


@timed
def example_port_details():
    """
    Show detailed port information.
    """
    print("\n" + "=" * 70)
    print("Example 4: Port details")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    elements = provider.get_network_elements(name=API_NCE_NE_NAME)
    if not elements:
        client.close()
        return

    ports = provider.get_ports(ne_id=elements[0].res_id, ltp_type_name='Ethernet',
                                is_physical=True, resolve_names=True)
    if ports:
        print(ports[0].details())

    client.close()


@timed
def example_sub_interfaces():
    """
    Show parent-child port hierarchy.

    Subinterfaces have is_sub_ltp=True and parent_ltp_id pointing to the parent.
    """
    print("\n" + "=" * 70)
    print("Example 5: Sub-interface hierarchy")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    elements = provider.get_network_elements(name=API_NCE_NE_NAME)
    if not elements:
        client.close()
        return

    # Get all ports for the NE
    all_ports = provider.get_ports(ne_id=elements[0].res_id)

    # Find parent-child relationships
    parent_ids = {p.parent_ltp_id for p in all_ports if p.parent_ltp_id}
    parents = [p for p in all_ports if p.res_id in parent_ids]

    print(f"Ports with sub-interfaces: {len(parents)}")
    for parent in parents[:3]:
        children = [p for p in all_ports if p.parent_ltp_id == parent.res_id]
        print(f"\n  Parent: {parent.name} ({parent.ltp_type_name})")
        for child in children[:5]:
            print(f"    Sub: {child.name} ({child.ltp_type_name})")

    client.close()


@timed
def example_ports_with_ip():
    """
    Find ports with IPv4 addresses assigned.
    """
    print("\n" + "=" * 70)
    print("Example 6: Ports with IP addresses")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    elements = provider.get_network_elements(name=API_NCE_NE_NAME)
    if not elements:
        client.close()
        return

    ports = provider.get_ports(ne_id=elements[0].res_id)
    with_ip = [p for p in ports if p.addrv4]

    print(f"Ports with IPv4: {len(with_ip)}")
    for p in with_ip:
        print(f"  {p.name}: {p.addrv4}/{p.addrv4_mask} | {p.ltp_type_name} | {p.work_mode or 'N/A'}")

    client.close()


@timed
def example_export():
    """
    Export port data to dict/JSON.
    """
    print("\n" + "=" * 70)
    print("Example 7: Export to dict/JSON")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    elements = provider.get_network_elements(name=API_NCE_NE_NAME)
    if not elements:
        client.close()
        return

    ports = provider.get_ports(ne_id=elements[0].res_id, ltp_type_name='Ethernet',
                                is_physical=True)
    if ports:
        p = ports[0]
        d = p.to_dict()
        print(f"to_dict() keys ({len(d)}):")
        for key in sorted(d.keys())[:15]:
            print(f"  {key}: {d[key]}")

        print(f"\nto_json() (truncated):")
        print(p.to_json()[:600] + "...")

    client.close()


if __name__ == "__main__":
    try:
        example_get_ports_by_ne()
        example_filter_physical_ports()
        example_filter_by_type()
        example_port_details()
        example_sub_interfaces()
        example_ports_with_ip()
        example_export()
    except NCEAuthenticationError as e:
        logger.error(f"NCE Authentication Error: {e}")
        print(f"\n*** NCE AUTHENTICATION ERROR ***\n{e}\n")
    except Exception as e:
        logger.error(f"Error: {e}")
        raise
