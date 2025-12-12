"""
Example: Using NceDataProvider for Huawei NCE alarm and network element management.

This example demonstrates:
- Getting alarms with filtering by name, severity, time range
- Getting network elements
- Using RestNMSDataFilter for client-side filtering
- Using brief() and details() methods for display
"""

import logging
import time
from datetime import datetime, timedelta
from functools import wraps

from pynetcom import RestNCE, NceDataProvider, RestNMSDataFilter, NCEAuthenticationError
from config import API_NCE_HOST, API_NCE_USER, API_NCE_PASS, API_NCE_NE_NAME, API_NCE_SUBNET_NAME

# Configure logging (change LOG_LEVEL as needed)
LOG_LEVEL = logging.DEBUG
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('pynetcom').setLevel(LOG_LEVEL)  # Also set for pynetcom library
logging.getLogger('urllib3').setLevel(logging.WARNING)  # Suppress urllib3 noise
logger = logging.getLogger(__name__)


def timed(func):
    """Decorator to measure and print execution time."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        print(f"⏱ Execution time: {elapsed:.2f}s")
        return result
    return wrapper


@timed
def example_get_all_alarms():
    """Get all alarms from NCE."""
    print("\n" + "=" * 70)
    print("Example 1: Get all alarms")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    alarms = provider.get_alarms()
    
    print(f"Total alarms: {len(alarms)}")
    print("\nFirst 5 alarms (brief):")
    for alarm in alarms[:5]:
        print(f"  {alarm.brief()}")
    
    client.close()


@timed
def example_get_alarms_by_name():
    """Get alarms filtered by network element name."""
    print("\n" + "=" * 70)
    print("Example 2: Get alarms by NE name")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    # NE name from config
    ne_name = API_NCE_NE_NAME
    
    alarms = provider.get_alarms(name=ne_name)
    
    print(f"Alarms for '{ne_name}': {len(alarms)}")
    for alarm in alarms[:3]:
        print(f"\n{alarm.brief()}")
    
    client.close()


@timed
def example_get_active_alarms():
    """Get only active (non-cleared) alarms."""
    print("\n" + "=" * 70)
    print("Example 3: Get active alarms")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    # NCE supports is_cleared filter at API level
    alarms = provider.get_active_alarms()
    
    print(f"Active alarms: {len(alarms)}")
    
    # Group by severity
    severity_counts = {}
    for alarm in alarms:
        sev = alarm.severity or 'unknown'
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
    
    print("\nBy severity:")
    for sev, count in sorted(severity_counts.items()):
        print(f"  {sev}: {count}")
    
    client.close()


@timed
def example_filter_by_severity():
    """Get alarms filtered by severity (server-side)."""
    print("\n" + "=" * 70)
    print("Example 4: Filter alarms by severity (server-side)")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    # Server-side severity filter - more efficient
    # alarms = provider.get_alarms(severity=['major', 'critical'])
    alarms = provider.get_alarms(severity=['major'])
    
    print(f"Major/Critical alarms: {len(alarms)}")
    for alarm in alarms[:5]:
        print(f"  {alarm.brief()}")
    
    client.close()


@timed
def example_filter_by_time_range():
    """Get alarms within a time range (server-side filtering)."""
    print("\n" + "=" * 70)
    print("Example 5: Filter alarms by time range (server-side)")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    # Get alarms from the last 1 days - SERVER-SIDE filtering
    end_time = datetime.now()
    start_time = end_time - timedelta(days=1)
    
    # Use server-side time filtering (more efficient)
    alarms = provider.get_alarms(start_time=start_time, end_time=end_time)
    
    print(f"Alarms in last 1 days: {len(alarms)}")
    for alarm in alarms[:5]:
        print(f"  {alarm.brief()}")
    
    client.close()


@timed
def example_combined_filters():
    """Use multiple server-side filter conditions."""
    print("\n" + "=" * 70)
    print("Example 6: Combined server-side filters")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    # All filters are server-side:
    # - severity: major and critical
    # - time: last 2 days
    # - is_cleared: False (active only)
    end_time = datetime.now()
    start_time = end_time - timedelta(days=2)
    
    alarms = provider.get_alarms(
        severity=['major', 'critical'],
        start_time=start_time,
        end_time=end_time,
        is_cleared=False
    )
    
    print(f"Active major/critical alarms (last 2 days): {len(alarms)}")
    for alarm in alarms[:5]:
        print(f"\n{alarm.brief()}")
    
    client.close()


@timed
def example_alarm_details():
    """Show detailed alarm information."""
    print("\n" + "=" * 70)
    print("Example 7: Alarm details")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    alarms = provider.get_active_alarms()
    
    if alarms:
        print("First active alarm details:")
        print(alarms[0].details())
    else:
        print("No active alarms found")
    
    client.close()


@timed
def example_get_network_elements():
    """Get network elements from NCE."""
    print("\n" + "=" * 70)
    print("Example 8: Get network elements")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    elements = provider.get_network_elements()
    
    print(f"Total network elements: {len(elements)}")
    print("\nFirst 10 elements:")
    for ne in elements[:10]:
        # print(f"  {ne.brief()}")
        print(f"  {ne.details()}")
    
    client.close()


@timed
def example_get_network_element_by_name():
    """Get network element by name."""
    print("\n" + "=" * 70)
    print("Example 9: Get network element by name")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    # NE name from config
    ne_name = API_NCE_NE_NAME
    
    elements = provider.get_network_elements(name=ne_name)
    
    if elements:
        print(f"Found {len(elements)} element(s) matching '{ne_name}':")
        for ne in elements:
            print(ne.details())
    else:
        print(f"No elements found matching '{ne_name}'")
    
    client.close()


@timed
def example_network_element_details():
    """Show detailed network element information."""
    print("\n" + "=" * 70)
    print("Example 10: Network element details")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    elements = provider.get_network_elements()
    
    if elements:
        print("First network element details:")
        print(elements[0].details())
    else:
        print("No network elements found")
    
    client.close()


@timed
def example_get_subnets():
    """Get subnets from NCE."""
    print("\n" + "=" * 70)
    print("Example 11: Get subnets")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    # Get all subnets
    subnets = provider.get_subnets()
    print(f"Total subnets: {len(subnets)}")
    
    # Show first 5 subnets
    print("\nFirst 5 subnets:")
    for subnet in subnets[:5]:
        print(f"  {subnet.get('name')} (ID: {subnet.get('res-id')})")
    
    # Find subnet by name
    target_name = API_NCE_SUBNET_NAME
    subnet = provider.get_subnet_by_name(target_name)
    if subnet:
        print(f"\nFound subnet '{target_name}': ID={subnet.get('res-id')}")
    else:
        print(f"\nSubnet '{target_name}' not found")
    
    client.close()


@timed
def example_get_alarms_by_subnet():
    """Get alarms for all NEs in a subnet."""
    print("\n" + "=" * 70)
    print("Example 12: Get alarms by subnet")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    # Find subnet by name
    subnet = provider.get_subnet_by_name(API_NCE_SUBNET_NAME)
    if not subnet:
        print(f"Subnet '{API_NCE_SUBNET_NAME}' not found")
        client.close()
        return
    
    subnet_id = subnet.get('res-id')
    print(f"Subnet: {API_NCE_SUBNET_NAME} (ID: {subnet_id})")
    
    # Get alarms for the subnet (client-side filtering)
    alarms = provider.get_alarms(
        subnet_id=subnet_id,
        severity=['major', 'critical'],
        is_cleared=False
    )
    
    print(f"\nActive major/critical alarms: {len(alarms)}")
    for alarm in alarms[:5]:
        print(f"  {alarm.brief()}")
    
    client.close()


@timed
def example_export_to_dict():
    """Export alarm data to dictionary/JSON."""
    print("\n" + "=" * 70)
    print("Example 13: Export to dict/JSON")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    alarms = provider.get_active_alarms()
    
    if alarms:
        alarm = alarms[0]
        print("Alarm as dictionary:")
        alarm_dict = alarm.to_dict()
        for key, value in list(alarm_dict.items())[:12]:
            print(f"  {key}: {value}")
        
        vinfo = alarm_dict.get("vendor_specific_info") or {}
        if vinfo:
            print("\nVendor-specific info (first 8 items):")
            for key, value in list(vinfo.items())[:8]:
                print(f"  {key}: {value}")
        
        print("\nAlarm as JSON (truncated):")
        json_str = alarm.to_json()
        print(json_str[:500] + "...")
    else:
        print("No alarms to export")
    
    client.close()


if __name__ == "__main__":
    # Run examples
    try:
        example_get_all_alarms()
        example_get_alarms_by_name()
        example_get_active_alarms()
        example_filter_by_severity()
        example_filter_by_time_range()
        example_combined_filters()
        example_alarm_details()
        example_get_network_elements()
        example_get_network_element_by_name()
        example_network_element_details()
        example_get_subnets()
        example_get_alarms_by_subnet()
        example_export_to_dict()
    except NCEAuthenticationError as e:
        # Handle NCE authentication errors (locked account, expired password, etc.)
        logger.error(f"NCE Authentication Error: {e}")
        print(f"\n*** NCE AUTHENTICATION ERROR ***\n{e}\n")
    except Exception as e:
        logger.error(f"Error: {e}")
        raise

