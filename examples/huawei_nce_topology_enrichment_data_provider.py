"""
Example: Topology enrichment functions for Huawei NCE.

Demonstrates high-level query methods for topology analysis:
- get_links_between(): all links between two NEs
- get_neighbors(): neighbors of an NE with links
- get_links_by_subnet(): links within a subnet
- get_ports_by_ip(): find port by IPv4 address
- get_alarms_for_link(): alarms correlated with a link
"""

import logging
import time
from functools import wraps

from pynetcom import RestNCE, NceDataProvider, RestNMSDataFilter, NCEAuthenticationError
from config import API_NCE_HOST, API_NCE_USER, API_NCE_PASS, API_NCE_NE_NAME, API_NCE_SUBNET_NAME

LOG_LEVEL = logging.DEBUG
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('pynetcom').setLevel(LOG_LEVEL)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def timed(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        print(f"Execution time: {time.time() - start:.2f}s")
        return result
    return wrapper


@timed
def example_links_between():
    """Find all links between two NEs."""
    print("\n" + "=" * 70)
    print("Example 1: Links between two NEs")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    links = provider.get_links_between(
        "IPBB_Bostery_NE40E-1", "IPBB_Bostery_NE40E-2",
        resolve_names=True
    )

    print(f"Links found: {len(links)}")
    for l in links:
        status = 'up' if l.oper_status == '0' else 'down'
        print(f"  {l.source_tp_name} <-> {l.dest_tp_name} | {l.link_type} | {status} | {l.bandwidth} kbps")

    client.close()


@timed
def example_neighbors():
    """Find all neighbors of an NE."""
    print("\n" + "=" * 70)
    print("Example 2: Neighbors of an NE")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    neighbors = provider.get_neighbors(API_NCE_NE_NAME, resolve_names=True)

    print(f"Neighbors of '{API_NCE_NE_NAME}': {len(neighbors)}")
    for n in neighbors:
        print(f"  {n['ne_name']}: {len(n['links'])} links")
        for l in n['links']:
            print(f"    {l.brief()}")

    client.close()


@timed
def example_links_by_subnet():
    """Get all links within a subnet."""
    print("\n" + "=" * 70)
    print("Example 3: Links by subnet")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    links = provider.get_links_by_subnet(API_NCE_SUBNET_NAME)

    print(f"Links in '{API_NCE_SUBNET_NAME}': {len(links)}")
    types = {}
    for l in links:
        types[l.link_type] = types.get(l.link_type, 0) + 1
    for t, c in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")

    client.close()


@timed
def example_ports_by_ip():
    """Find port by IPv4 address."""
    print("\n" + "=" * 70)
    print("Example 4: Port by IP")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    # First find an NE to narrow the search
    elements = provider.get_network_elements(name=API_NCE_NE_NAME)
    if elements:
        ports = provider.get_ports(ne_id=elements[0].node_id)
        with_ip = [p for p in ports if p.ipv4_address]
        if with_ip:
            target_ip = with_ip[0].ipv4_address
            result = provider.get_ports_by_ip(target_ip, ne_id=elements[0].node_id)
            print(f"Port with IP {target_ip}: {len(result)}")
            for p in result:
                print(f"  {p.name} | {p.interface_type} | {p.ipv4_address}/{p.ipv4_prefix_length}")

    client.close()


@timed
def example_alarms_for_link():
    """Get alarms correlated with a down link."""
    print("\n" + "=" * 70)
    print("Example 5: Alarms for a link")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    all_links = provider.get_links()
    down = [l for l in all_links if l.oper_status == '1']
    print(f"Down links: {len(down)}")

    if down:
        provider.resolve_link_names(down[:1])
        link = down[0]
        print(f"Link: {link.name}")

        alarms = provider.get_alarms_for_link(link, is_cleared=False)
        print(f"Active alarms: {len(alarms)}")
        for a in alarms[:8]:
            print(f"  {a.ne_name} | {a.severity} | {a.alarm_name[:60]}")

    client.close()


@timed
def example_alarms_for_ne():
    """Get alarms for a specific NE by name."""
    print("\n" + "=" * 70)
    print("Example 6: Alarms for NE")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    # Active alarms for a specific NE
    alarms = provider.get_alarms(name="IPBB_Bostery_NE40E-2", is_cleared=False)
    print(f"Active alarms: {len(alarms)}")

    sevs = {}
    for a in alarms:
        sevs[a.severity] = sevs.get(a.severity, 0) + 1
    print(f"By severity: {sevs}")

    for a in alarms[:5]:
        print(f"  {a.severity:10s} | {a.alarm_name[:55]}")
        if a.affected_object:
            print(f"             | {a.affected_object[:70]}")

    # Critical only (server-side filter)
    critical = provider.get_alarms(name="IPBB_Bostery_NE40E-2", is_cleared=False, severity=['critical'])
    print(f"\nCritical only: {len(critical)}")

    client.close()


if __name__ == "__main__":
    try:
        example_links_between()
        example_neighbors()
        example_links_by_subnet()
        example_ports_by_ip()
        example_alarms_for_link()
        example_alarms_for_ne()
    except NCEAuthenticationError as e:
        logger.error(f"NCE Authentication Error: {e}")
        print(f"\n*** NCE AUTHENTICATION ERROR ***\n{e}\n")
    except Exception as e:
        logger.error(f"Error: {e}")
        raise
