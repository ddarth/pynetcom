"""
Example: Using NceDataProvider for Huawei NCE topology management.

This example demonstrates:
- Getting all links with type statistics
- Getting fiber links (filtered by type="Fiber")
- Getting links by NE (server-side filter by a-end-ne-id)
- Getting IGP links (OSPF/IS-IS topology)
- Using RestNMSDataFilter for client-side filtering
- Using brief() and details() methods for display
- Exporting link data to dict/JSON

API Endpoints used:
- Links: GET /restconf/v2/data/huawei-nce-resource-inventory:links
- IGP Links: GET /restconf/v3/data/huawei-nce-resource-inventory:igp-links

Link types available: Fiber, L2 Link, Microwave Link, Cable, IP Link, Dummy Link

Expected output (masked):
  Total links: ~4300
    Fiber: ~2000
    Microwave Link: ~1100
    L2 Link: ~1100
    Cable: ~60
    IP Link: ~2
"""

import logging
import time
from functools import wraps

from pynetcom import RestNCE, NceDataProvider, RestNMSDataFilter, NCEAuthenticationError
from config import API_NCE_HOST, API_NCE_USER, API_NCE_PASS, API_NCE_NE_NAME

# Configure logging (change LOG_LEVEL as needed)
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
def example_get_all_links():
    """
    Get all links and show statistics by type.

    Expected output:
      Total links: 4346
      By type:
        Fiber: 1990
        Microwave Link: 1146
        L2 Link: 1143
        Cable: 63
        IP Link: 2
        Dummy Link: 2
    """
    print("\n" + "=" * 70)
    print("Example 1: Get all links with type statistics")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    links = provider.get_links()

    print(f"Total links: {len(links)}")

    # Group by type
    types = {}
    for link in links:
        types[link.link_type] = types.get(link.link_type, 0) + 1

    print("By type:")
    for t, count in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t}: {count}")

    # Show first 5 links (brief)
    print("\nFirst 5 links:")
    for link in links[:5]:
        print(f"  {link.brief()}")

    client.close()


@timed
def example_get_fibers():
    """
    Get fiber links using convenience method.

    Expected output:
      Total fibers: ~2000
      Sample brief: f-42 | Fiber | unknown | N/A
      Sample details shows: layer_rate=LR_PHYSICAL_OPTICAL, medium_type=G.652
    """
    print("\n" + "=" * 70)
    print("Example 2: Get fiber links")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    fibers = provider.get_fibers()

    print(f"Total fibers: {len(fibers)}")
    print("\nFirst 5 fibers (brief):")
    for f in fibers[:5]:
        print(f"  {f.brief()}")

    if fibers:
        print(f"\nFirst fiber details:")
        print(fibers[0].details())

    client.close()


@timed
def example_get_links_by_type():
    """
    Get links filtered by specific type.

    Available types: 'Fiber', 'L2 Link', 'Microwave Link', 'Cable', 'IP Link', 'Dummy Link'
    """
    print("\n" + "=" * 70)
    print("Example 3: Get links by type")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    for link_type in ['L2 Link', 'Microwave Link', 'Cable']:
        links = provider.get_links(link_type=link_type)
        print(f"\n{link_type}: {len(links)}")
        for link in links[:3]:
            print(f"  {link.brief()}")

    client.close()


@timed
def example_get_links_by_ne():
    """
    Get links filtered by source NE UUID (server-side filter).

    Uses a-end-ne-id query parameter for efficient server-side filtering.
    """
    print("\n" + "=" * 70)
    print("Example 4: Get links by NE")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    # First, find NE by name
    ne_name = API_NCE_NE_NAME
    elements = provider.get_network_elements(name=ne_name)

    if not elements:
        print(f"NE '{ne_name}' not found")
        client.close()
        return

    ne = elements[0]
    print(f"NE: {ne.name} (res_id={ne.node_id})")

    # Get links where this NE is the source (a-end)
    links = provider.get_links(a_end_ne_id=ne.node_id)
    print(f"Links from this NE: {len(links)}")
    for link in links[:5]:
        print(f"  {link.brief()}")

    # Get links where this NE is the sink (z-end)
    links_sink = provider.get_links(z_end_ne_id=ne.node_id)
    print(f"\nLinks to this NE: {len(links_sink)}")
    for link in links_sink[:5]:
        print(f"  {link.brief()}")

    client.close()


@timed
def example_get_igp_links():
    """
    Get IGP links (OSPF/IS-IS topology).

    Note: IGP links may be empty on networks that don't expose
    IGP topology through the controller API.
    """
    print("\n" + "=" * 70)
    print("Example 5: Get IGP links")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    igp_links = provider.get_igp_links()
    print(f"Total IGP links: {len(igp_links)}")

    for link in igp_links[:5]:
        print(f"  {link.brief()}")

    if igp_links:
        print(f"\nFirst IGP link details:")
        print(igp_links[0].details())

    client.close()


@timed
def example_links_with_filter():
    """
    Use RestNMSDataFilter for client-side filtering of links.

    Examples:
    - Filter active links (operate_status='0' means up)
    - Filter down links (operate_status='1' means down)
    - Exclude specific link types
    """
    print("\n" + "=" * 70)
    print("Example 6: Links with client-side filters")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    # Only active (up) links
    f = RestNMSDataFilter()
    f.include(operate_status=['0'])
    active_links = provider.get_links(filters=f)
    print(f"Active links (status=up): {len(active_links)}")

    # Only down links
    f2 = RestNMSDataFilter()
    f2.include(operate_status=['1'])
    down_links = provider.get_links(filters=f2)
    print(f"Down links (status=down): {len(down_links)}")
    for link in down_links[:5]:
        print(f"  {link.brief()}")

    # Exclude Fiber and Microwave links
    f3 = RestNMSDataFilter()
    f3.exclude(link_type=['Fiber', 'Microwave Link'])
    non_physical = provider.get_links(filters=f3)
    print(f"\nNon-physical links (excl Fiber+Microwave): {len(non_physical)}")

    client.close()


@timed
def example_link_details_and_export():
    """
    Show detailed link info and export to dict/JSON.
    """
    print("\n" + "=" * 70)
    print("Example 7: Link details and export")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    # Get one L2 link with details
    links = provider.get_links(link_type='L2 Link')
    if links:
        link = links[0]
        print("L2 Link details:")
        print(link.details())

        print("\nAs dictionary (first 10 keys):")
        d = link.to_dict()
        for key, value in list(d.items())[:10]:
            print(f"  {key}: {value}")

        print("\nAs JSON (truncated):")
        print(link.to_json()[:500] + "...")

    client.close()


@timed
def example_resolve_names_inline():
    """
    Resolve NE and port UUIDs to names via resolve_names=True.

    When resolve_names=True is passed, the provider automatically:
    1. Fetches all NE names (~1-2s)
    2. Fetches port names (bulk: ~56s for all, or per-NE: ~0.2s each for <=10 NEs)
    3. Populates source_node_name, dest_node_name, source_tp_name, dest_tp_name

    After resolution, brief() and details() show names alongside UUIDs.
    """
    print("\n" + "=" * 70)
    print("Example 8: Resolve names (inline)")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    # Get links for one NE with resolved names (fast: only 1-2 NEs to resolve)
    ne_name = API_NCE_NE_NAME
    elements = provider.get_network_elements(name=ne_name)
    if elements:
        links = provider.get_links(a_end_ne_id=elements[0].node_id, resolve_names=True)
        print(f"Links from '{ne_name}' (resolved): {len(links)}")
        for link in links[:5]:
            print(f"  {link.brief()}")
            print(f"    Source: {link.source_node_name} / {link.source_tp_name}")
            print(f"    Dest: {link.dest_node_name} / {link.dest_tp_name}")

    client.close()


@timed
def example_resolve_names_separate():
    """
    Resolve names on a filtered subset using resolve_link_names().

    Recommended pattern for large datasets:
    1. Fetch all links (fast, ~2s)
    2. Filter to the subset you care about
    3. Call resolve_link_names() only on that subset

    This avoids loading ports for all NEs when you only need a few.
    """
    print("\n" + "=" * 70)
    print("Example 9: Resolve names (separate, on filtered subset)")
    print("=" * 70)

    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    # Step 1: Get all links (fast)
    links = provider.get_links()
    print(f"Total links: {len(links)}")

    # Step 2: Filter to down links only
    down = [l for l in links if l.oper_status == '1']
    print(f"Down links: {len(down)}")

    # Step 3: Resolve names only for down links
    provider.resolve_link_names(down)

    for link in down[:5]:
        print(f"  {link.brief()}")
        print(f"    Source NE: {link.source_node_name}, Port: {link.source_tp_name}")
        print(f"    Dest NE: {link.dest_node_name}, Port: {link.dest_tp_name}")

    client.close()


if __name__ == "__main__":
    try:
        example_get_all_links()
        example_get_fibers()
        example_get_links_by_type()
        example_get_links_by_ne()
        example_get_igp_links()
        example_links_with_filter()
        example_link_details_and_export()
        example_resolve_names_inline()
        example_resolve_names_separate()
    except NCEAuthenticationError as e:
        logger.error(f"NCE Authentication Error: {e}")
        print(f"\n*** NCE AUTHENTICATION ERROR ***\n{e}\n")
    except Exception as e:
        logger.error(f"Error: {e}")
        raise
