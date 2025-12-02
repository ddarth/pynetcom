"""
Example: Using NceDataProvider for Huawei NCE alarm and network element management.

This example demonstrates:
- Getting alarms with filtering by name, severity, time range
- Getting network elements
- Using RestNMSDataFilter for client-side filtering
- Using brief() and details() methods for display
"""

import logging
from datetime import datetime, timedelta

from pynetcom import RestNCE, NceDataProvider, RestNMSDataFilter, NCEAuthenticationError
from config import API_NCE_HOST, API_NCE_USER, API_NCE_PASS, API_NCE_NE_NAME

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


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


def example_filter_by_severity():
    """Get alarms excluding certain severities."""
    print("\n" + "=" * 70)
    print("Example 4: Filter alarms by severity")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    # Create filter to include only major and critical alarms
    alarm_filter = RestNMSDataFilter()
    alarm_filter.include(severity=['major', 'critical'])
    
    alarms = provider.get_alarms(filters=alarm_filter)
    
    print(f"Major/Critical alarms: {len(alarms)}")
    for alarm in alarms[:5]:
        print(f"  {alarm.brief()}")


def example_filter_by_time_range():
    """Get alarms within a time range."""
    print("\n" + "=" * 70)
    print("Example 5: Filter alarms by time range")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    # Get alarms from the last 7 days
    end_time = datetime.now()
    start_time = end_time - timedelta(days=7)
    
    alarm_filter = RestNMSDataFilter()
    alarm_filter.time_range(time_created=(start_time, end_time))
    
    alarms = provider.get_alarms(filters=alarm_filter)
    
    print(f"Alarms in last 7 days: {len(alarms)}")
    for alarm in alarms[:5]:
        print(f"  {alarm.brief()}")


def example_combined_filters():
    """Use multiple filter conditions."""
    print("\n" + "=" * 70)
    print("Example 6: Combined filters")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    # Complex filter:
    # - Include only major and critical
    # - From the last 30 days
    end_time = datetime.now()
    start_time = end_time - timedelta(days=30)
    
    alarm_filter = RestNMSDataFilter()
    alarm_filter.include(severity=['major', 'critical'])
    alarm_filter.time_range(time_created=(start_time, end_time))
    
    # Get active alarms with additional filter
    alarms = provider.get_active_alarms(filters=alarm_filter)
    
    print(f"Active major/critical alarms (last 30 days): {len(alarms)}")
    for alarm in alarms[:5]:
        print(f"\n{alarm.brief()}")


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
        print(f"  {ne.brief()}")


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


def example_get_subnets():
    """Get subnets from NCE."""
    print("\n" + "=" * 70)
    print("Example 11: Get subnets")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    subnets = provider.get_subnets()
    
    print(f"Total subnets: {len(subnets)}")
    print("\nSubnets:")
    for subnet in subnets[:10]:
        if subnet.get('node-class') == 'subnet':
            print(f"  {subnet.get('name')} (ID: {subnet.get('res-id')})")


def example_export_to_dict():
    """Export alarm data to dictionary/JSON."""
    print("\n" + "=" * 70)
    print("Example 12: Export to dict/JSON")
    print("=" * 70)
    
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)
    
    alarms = provider.get_active_alarms()
    
    if alarms:
        alarm = alarms[0]
        print("Alarm as dictionary:")
        alarm_dict = alarm.to_dict()
        for key, value in list(alarm_dict.items())[:10]:
            print(f"  {key}: {value}")
        
        print("\nAlarm as JSON (truncated):")
        json_str = alarm.to_json()
        print(json_str[:500] + "...")
    else:
        print("No alarms to export")


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
        example_export_to_dict()
    except NCEAuthenticationError as e:
        # Handle NCE authentication errors (locked account, expired password, etc.)
        logger.error(f"NCE Authentication Error: {e}")
        print(f"\n*** NCE AUTHENTICATION ERROR ***\n{e}\n")
    except Exception as e:
        logger.error(f"Error: {e}")
        raise

