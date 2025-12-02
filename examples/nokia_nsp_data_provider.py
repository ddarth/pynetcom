"""
Example: Using NspDataProvider for Nokia NSP alarm and network element management.

This example demonstrates:
- Getting alarms with filtering by name, severity, time range
- Getting network elements
- Using RestNMSDataFilter for client-side filtering
- Using brief() and details() methods for display
"""

import logging
from datetime import datetime, timedelta

from pynetcom import RestNSP, NspDataProvider, RestNMSDataFilter
from config import API_NSP_HOST, API_NSP_USER, API_NSP_PASS, API_NSP_NE_NAME

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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


def example_get_alarms_by_name():
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
        print(f"\n{alarm.brief()}")


def example_filter_by_severity():
    """Get alarms excluding certain severities."""
    print("\n" + "=" * 70)
    print("Example 3: Filter alarms by severity")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    # Create filter to exclude cleared and warning alarms
    alarm_filter = RestNMSDataFilter()
    alarm_filter.exclude(severity=['cleared', 'warning'])
    
    alarms = provider.get_alarms(filters=alarm_filter)
    
    print(f"Active alarms (excluding cleared/warning): {len(alarms)}")
    
    # Group by severity
    severity_counts = {}
    for alarm in alarms:
        sev = alarm.severity or 'unknown'
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
    
    print("\nBy severity:")
    for sev, count in sorted(severity_counts.items()):
        print(f"  {sev}: {count}")


def example_filter_by_time_range():
    """Get alarms within a time range."""
    print("\n" + "=" * 70)
    print("Example 4: Filter alarms by time range")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    # Get alarms from the last 24 hours
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=24)
    
    alarm_filter = RestNMSDataFilter()
    alarm_filter.time_range(last_time_detected=(start_time, end_time))
    
    alarms = provider.get_alarms(filters=alarm_filter)
    
    print(f"Alarms in last 24 hours: {len(alarms)}")
    for alarm in alarms[:5]:
        print(f"  {alarm.brief()}")


def example_combined_filters():
    """Use multiple filter conditions."""
    print("\n" + "=" * 70)
    print("Example 5: Combined filters")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    # Complex filter:
    # - Exclude cleared and warning alarms
    # - Exclude LinkDown alarms
    # - Only from the last 7 days
    end_time = datetime.now()
    start_time = end_time - timedelta(days=7)
    
    alarm_filter = RestNMSDataFilter()
    alarm_filter.exclude(severity=['cleared', 'warning'])
    alarm_filter.exclude(alarm_name=['LinkDown'])
    alarm_filter.time_range(last_time_detected=(start_time, end_time))
    
    alarms = provider.get_alarms(filters=alarm_filter)
    
    print(f"Filtered alarms: {len(alarms)}")
    for alarm in alarms[:5]:
        print(f"\n{alarm.brief()}")


def example_alarm_details():
    """Show detailed alarm information."""
    print("\n" + "=" * 70)
    print("Example 6: Alarm details")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    # Get active alarms
    alarms = provider.get_active_alarms()
    
    if alarms:
        print("First active alarm details:")
        print(alarms[0].details())
    else:
        print("No active alarms found")


def example_get_network_elements():
    """Get network elements from NSP."""
    print("\n" + "=" * 70)
    print("Example 7: Get network elements")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    elements = provider.get_network_elements()
    
    print(f"Total network elements: {len(elements)}")
    print("\nFirst 10 elements:")
    for ne in elements[:10]:
        print(f"  {ne.brief()}")


def example_network_element_details():
    """Show detailed network element information."""
    print("\n" + "=" * 70)
    print("Example 8: Network element details")
    print("=" * 70)
    
    client = RestNSP(API_NSP_HOST, API_NSP_USER, API_NSP_PASS)
    provider = NspDataProvider(client)
    
    elements = provider.get_network_elements()
    
    if elements:
        print("First network element details:")
        print(elements[0].details())
    else:
        print("No network elements found")


def example_export_to_dict():
    """Export alarm data to dictionary/JSON."""
    print("\n" + "=" * 70)
    print("Example 9: Export to dict/JSON")
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


if __name__ == "__main__":
    # Run examples
    try:
        example_get_all_alarms()
        example_get_alarms_by_name()
        example_filter_by_severity()
        example_filter_by_time_range()
        example_combined_filters()
        example_alarm_details()
        example_get_network_elements()
        example_network_element_details()
        example_export_to_dict()
    except Exception as e:
        logger.error(f"Error: {e}")
        raise

