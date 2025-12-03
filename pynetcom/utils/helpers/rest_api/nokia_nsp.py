"""
Nokia NSP Data Provider.

Provides high-level methods for fetching alarms and network elements
from Nokia NSP with filtering and pagination support.
"""

from typing import List, Optional
from datetime import datetime
import logging
from urllib.parse import quote

from pynetcom.rest_nsp import RestNSP
from pynetcom.utils.helpers.rest_api.base import RestNMSDataFilter
from pynetcom.utils.helpers.rest_api.data_containers.nokia_nsp import (
    NspAlarm,
    NspNetworkElement,
)


logger = logging.getLogger('pynetcom.nsp_data_provider')


class NspDataProvider:
    """
    High-level data provider for Nokia NSP.
    
    Wraps RestNSP client with convenient methods for fetching alarms
    and network elements with filtering capabilities.
    
    Example:
        from pynetcom import RestNSP
        from pynetcom.utils.helpers.rest_api import NspDataProvider, RestNMSDataFilter
        
        client = RestNSP(host, user, password)
        provider = NspDataProvider(client)
        
        # Get alarms with filtering
        filter = RestNMSDataFilter()
        filter.exclude(severity=['cleared', 'warning'])
        
        alarms = provider.get_alarms(name="Router1", filters=filter)
        for alarm in alarms:
            print(alarm.brief())
    """
    
    # API endpoints
    ALARMS_ENDPOINT = "/FaultManagement/rest/api/v2/alarms/details"
    NETWORK_ELEMENTS_ENDPOINT = "/NetworkSupervision/rest/api/v1/networkElements"
    
    def __init__(self, client: RestNSP):
        """
        Initialize NSP data provider.
        
        Args:
            client: RestNSP client instance.
        """
        self.client = client
    
    def _build_alarm_filter(
        self,
        name: Optional[str] = None,
        ne_id: Optional[str] = None,
        is_cleared: Optional[bool] = None,
        severity: Optional[List[str]] = None
    ) -> Optional[str]:
        """
        Build NSP alarmFilter query string for server-side filtering.
        
        Args:
            name: Filter by network element name (neName).
            ne_id: Filter by network element ID (neId).
            is_cleared: Filter by cleared status.
            severity: Filter by severity levels (critical, major, minor, warning, cleared).
        
        Returns:
            URL-encoded alarmFilter string or None if no filters.
        
        Example filters:
            severity='major'
            (severity='critical' or severity='major')
            neName='Router1' and severity<>'cleared'
        """
        conditions = []
        
        # Filter by NE name
        if name:
            conditions.append(f"neName='{name}'")
        
        # Filter by NE ID
        if ne_id:
            conditions.append(f"neId='{ne_id}'")
        
        # Filter by severity
        if severity:
            if len(severity) == 1:
                conditions.append(f"severity='{severity[0]}'")
            else:
                # Multiple severities: (severity='critical' or severity='major')
                sev_conditions = [f"severity='{s}'" for s in severity]
                conditions.append(f"({' or '.join(sev_conditions)})")
        
        # Filter by cleared status
        if is_cleared is not None:
            if is_cleared:
                # Only cleared alarms
                conditions.append("severity='cleared'")
            else:
                # Only non-cleared alarms (exclude 'cleared' severity)
                conditions.append("severity<>'cleared'")
        
        if not conditions:
            return None
        
        # Join conditions with AND
        filter_str = ' and '.join(conditions)
        
        # URL encode the filter (double encoding as NSP expects)
        return quote(filter_str, safe='')
    
    def get_alarms(
        self,
        name: Optional[str] = None,
        ne_id: Optional[str] = None,
        is_cleared: Optional[bool] = None,
        severity: Optional[List[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        filters: Optional[RestNMSDataFilter] = None,
        page_size: int = 1000
    ) -> List[NspAlarm]:
        """
        Get alarms from Nokia NSP.
        
        Args:
            name: Filter by network element name (neName). Server-side filtering.
            ne_id: Filter by network element ID (neId). Server-side filtering.
            is_cleared: Filter by cleared status. Server-side filtering.
                        True = only cleared alarms, False = only active alarms.
            severity: Filter by severity levels. Server-side filtering.
                      Values: 'critical', 'major', 'minor', 'warning', 'cleared'.
            start_time: Start time for alarm query period. Client-side filtering.
            end_time: End time for alarm query period. Client-side filtering.
            filters: RestNMSDataFilter instance for additional client-side filtering.
            page_size: Number of records per page (default 1000).
        
        Returns:
            List of NspAlarm objects.
        
        Note:
            - name, ne_id, is_cleared, severity are filtered server-side (more efficient)
            - start_time, end_time are filtered client-side via RestNMSDataFilter
            - This API is unified with NceDataProvider.get_alarms() for consistency
        """
        # Build server-side alarm filter
        alarm_filter = self._build_alarm_filter(
            name=name,
            ne_id=ne_id,
            is_cleared=is_cleared,
            severity=severity
        )
        
        # Build URL with filter
        url = self.ALARMS_ENDPOINT
        if alarm_filter:
            url = f"{url}?alarmFilter={alarm_filter}"
        
        logger.debug(f"Fetching alarms from: {url}")
        
        # Set page size
        original_limit = self.client.limit
        self.client.limit = page_size
        
        try:
            self.client.clear_data()
            self.client.send_request(url)
            raw_data = self.client.get_data()
        finally:
            self.client.limit = original_limit
        
        # Convert to NspAlarm objects
        alarms = [NspAlarm(item) for item in raw_data]
        
        # Build client-side filter for time range
        time_filter = None
        if start_time is not None or end_time is not None:
            time_filter = RestNMSDataFilter()
            time_filter.time_range(last_time_detected=(start_time, end_time))
            alarms = time_filter.apply(alarms)
        
        # Apply additional client-side filters
        if filters:
            alarms = filters.apply(alarms)
        
        logger.info(f"Retrieved {len(alarms)} alarms")
        return alarms
    
    def get_alarms_raw(
        self,
        name: Optional[str] = None,
        ne_id: Optional[str] = None,
        is_cleared: Optional[bool] = None,
        severity: Optional[List[str]] = None
    ) -> List[dict]:
        """
        Get raw alarm data from Nokia NSP without conversion.
        
        Args:
            name: Filter by network element name.
            ne_id: Filter by network element ID.
            is_cleared: Filter by cleared status.
            severity: Filter by severity levels.
        
        Returns:
            List of raw alarm dictionaries.
        """
        # Build server-side alarm filter
        alarm_filter = self._build_alarm_filter(
            name=name,
            ne_id=ne_id,
            is_cleared=is_cleared,
            severity=severity
        )
        
        url = self.ALARMS_ENDPOINT
        if alarm_filter:
            url = f"{url}?alarmFilter={alarm_filter}"
        
        self.client.clear_data()
        self.client.send_request(url)
        return self.client.get_data()
    
    def get_network_elements(
        self,
        name: Optional[str] = None,
        filters: Optional[RestNMSDataFilter] = None,
        page_size: int = 1000
    ) -> List[NspNetworkElement]:
        """
        Get network elements from Nokia NSP.
        
        Args:
            name: Filter by network element name.
            filters: RestNMSDataFilter instance for additional client-side filtering.
            page_size: Number of records per page.
        
        Returns:
            List of NspNetworkElement objects.
        """
        url = self.NETWORK_ELEMENTS_ENDPOINT
        
        # NSP doesn't support name filter in URL for NEs, so we filter client-side
        logger.debug(f"Fetching network elements from: {url}")
        
        original_limit = self.client.limit
        self.client.limit = page_size
        
        try:
            self.client.clear_data()
            self.client.send_request(url)
            raw_data = self.client.get_data()
        finally:
            self.client.limit = original_limit
        
        # Convert to NspNetworkElement objects
        elements = [NspNetworkElement(item) for item in raw_data]
        
        # Filter by name if specified
        if name:
            elements = [e for e in elements if e.name and name.lower() in e.name.lower()]
        
        # Apply client-side filters
        if filters:
            elements = filters.apply(elements)
        
        logger.info(f"Retrieved {len(elements)} network elements")
        return elements
    
    def get_network_elements_raw(self) -> List[dict]:
        """
        Get raw network element data from Nokia NSP.
        
        Returns:
            List of raw network element dictionaries.
        """
        self.client.clear_data()
        self.client.send_request(self.NETWORK_ELEMENTS_ENDPOINT)
        return self.client.get_data()
    
    def get_alarms_count(
        self,
        name: Optional[str] = None,
        is_cleared: Optional[bool] = None,
        severity: Optional[List[str]] = None,
        filters: Optional[RestNMSDataFilter] = None
    ) -> int:
        """
        Get count of alarms matching the criteria.
        
        Args:
            name: Filter by network element name.
            is_cleared: Filter by cleared status.
            severity: Filter by severity levels.
            filters: RestNMSDataFilter instance for additional filtering.
        
        Returns:
            Number of alarms.
        """
        alarms = self.get_alarms(
            name=name,
            is_cleared=is_cleared,
            severity=severity,
            filters=filters
        )
        return len(alarms)
    
    def get_alarms_by_severity(
        self,
        severity: str,
        name: Optional[str] = None
    ) -> List[NspAlarm]:
        """
        Get alarms filtered by severity level (server-side filtering).
        
        Args:
            severity: Severity level (critical, major, minor, warning, cleared).
            name: Optional NE name filter.
        
        Returns:
            List of NspAlarm objects with specified severity.
        """
        # Use server-side filtering for efficiency
        return self.get_alarms(name=name, severity=[severity])
    
    def get_active_alarms(
        self,
        name: Optional[str] = None,
        filters: Optional[RestNMSDataFilter] = None
    ) -> List[NspAlarm]:
        """
        Get only active (non-cleared) alarms (server-side filtering).
        
        Args:
            name: Filter by network element name.
            filters: Additional client-side filters to apply.
        
        Returns:
            List of active NspAlarm objects.
        """
        # Use server-side filtering for is_cleared (more efficient)
        return self.get_alarms(name=name, is_cleared=False, filters=filters)

