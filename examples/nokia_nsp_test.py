"""
Example: Using NspDataProvider for Nokia NSP alarm and network element management.

This example demonstrates:
- Getting alarms with server-side filtering (name, severity, is_cleared)
- Getting alarms with client-side filtering (time range, RestNMSDataFilter)
- Getting network elements
- Using brief() and details() methods for display

Note: NSP API supports server-side filtering for severity, is_cleared, name, ne_id.
      Time range filtering is done client-side via RestNMSDataFilter.
"""

import logging
from datetime import datetime, timedelta
import json
from pynetcom import RestNSP, NspDataProvider, RestNMSDataFilter
from config import API_NSP_HOST, API_NSP_USER, API_NSP_PASS, API_NSP_NE_NAME

# Configure logging (change to logging.DEBUG or logging.INFO for verbose output)
LOG_LEVEL = logging.WARNING
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('pynetcom').setLevel(LOG_LEVEL)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def example_get_all_alarms():
    """Get all alarms from NSP."""
    print("\n" + "=" * 70)
    print("Example 1: Get all alarms")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    alarms = provider.get_alarms()
    
    print(f"Total alarms: {len(alarms)}")
    print("\nFirst 5 alarms (brief):")
    for alarm in alarms[:5]:
        print(f"  {alarm.brief()}")
    
    client.close()


def example_get_alarms_by_ne_name():
    """Get alarms filtered by network element name."""
    print("\n" + "=" * 70)
    print("Example 2: Get alarms by NE name")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    # NE name from config
    ne_name = API_NSP_NE_NAME
    
    alarms = provider.get_alarms(name=ne_name)
    
    print(f"Alarms for '{ne_name}': {len(alarms)}")
    for alarm in alarms[:3]:
        print(f"\n{json.dumps(alarm.to_dict(), indent=4)}")
    
    client.close()


def example_filter_by_severity():
    """Get alarms filtered by severity (server-side filtering)."""
    print("\n" + "=" * 70)
    print("Example 3: Filter alarms by severity (server-side)")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    # Server-side severity filter - more efficient than client-side
    # Get only major and critical alarms
    alarms = provider.get_alarms(severity=['major', 'critical'])
    
    print(f"Major/Critical alarms: {len(alarms)}")
    
    # Group by severity
    severity_counts = {}
    for alarm in alarms:
        sev = alarm.severity or 'unknown'
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
    
    print("\nBy severity:")
    for sev, count in sorted(severity_counts.items()):
        print(f"  {sev}: {count}")
    
    client.close()


def example_filter_by_time_range():
    """Get alarms within a time range (client-side filtering)."""
    print("\n" + "=" * 70)
    print("Example 4: Filter alarms by time range (client-side)")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    # Get alarms from the last 7 days
    # Note: time filtering is done client-side for NSP
    end_time = datetime.now()
    start_time = end_time - timedelta(days=7)
    
    # Use built-in start_time/end_time parameters
    alarms = provider.get_alarms(start_time=start_time, end_time=end_time)
    
    print(f"Alarms in last 7 days: {len(alarms)}")
    for alarm in alarms[:5]:
        print(f"  {alarm.brief()}")
    
    client.close()


def example_combined_filters():
    """Use combined server-side and client-side filters."""
    print("\n" + "=" * 70)
    print("Example 5: Combined server-side and client-side filters")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    # Complex filter combining:
    # SERVER-SIDE (efficient):
    # - severity: only major and critical
    # - is_cleared: only active alarms
    # CLIENT-SIDE (via RestNMSDataFilter):
    # - time range: last 30 days
    # - exclude specific alarm names
    
    end_time = datetime.now()
    start_time = end_time - timedelta(days=30)
    
    # Client-side filter for additional filtering
    alarm_filter = RestNMSDataFilter()
    alarm_filter.exclude(alarm_name=['LinkDown'])
    
    alarms = provider.get_alarms(
        severity=['major', 'critical'],  # Server-side
        is_cleared=False,                 # Server-side
        start_time=start_time,            # Client-side
        end_time=end_time,                # Client-side
        filters=alarm_filter              # Client-side (exclude LinkDown)
    )
    
    print(f"Active major/critical alarms (last 30 days, excl. LinkDown): {len(alarms)}")
    for alarm in alarms[:5]:
        print(f"\n{alarm.brief()}")
    
    client.close()


def example_get_active_alarms():
    """Get only active (non-cleared) alarms using server-side filtering."""
    print("\n" + "=" * 70)
    print("Example 6: Get active alarms (server-side is_cleared filter)")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    # get_active_alarms() uses server-side is_cleared=False filter
    # This is more efficient than client-side filtering
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


def example_alarm_details():
    """Show detailed alarm information."""
    print("\n" + "=" * 70)
    print("Example 7: Alarm details")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    # Get active alarms (server-side filtering)
    alarms = provider.get_active_alarms()
    
    if alarms:
        print("First active alarm details:")
        print(alarms[0].details())
    else:
        print("No active alarms found")
    
    client.close()


def example_get_network_elements():
    """Get network elements from NSP."""
    print("\n" + "=" * 70)
    print("Example 8: Get network elements")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    elements = provider.get_network_elements()
    
    print(f"Total network elements: {len(elements)}")
    print("\nFirst 10 elements:")
    for ne in elements[:10]:
        print(f"  {ne.brief()}")
    
    client.close()


def example_network_element_details():
    """Show detailed network element information."""
    print("\n" + "=" * 70)
    print("Example 9: Network element details")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    elements = provider.get_network_elements()
    
    if elements:
        print("First network element details:")
        print(elements[0].details())
    else:
        print("No network elements found")
    
    client.close()


def example_export_to_dict():
    """Export alarm data to dictionary/JSON."""
    print("\n" + "=" * 70)
    print("Example 10: Export to dict/JSON")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
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
    
    client.close()


if __name__ == "__main__":
    # Run examples
    try:
        # example_get_all_alarms()
        example_get_alarms_by_ne_name()
        # example_filter_by_severity()
        # example_filter_by_time_range()
        # example_combined_filters()
        # example_get_active_alarms()
        # example_alarm_details()
        # example_get_network_elements()
        # example_network_element_details()
        # example_export_to_dict()
    except Exception as e:
        logger.error(f"Error: {e}")
        raise

