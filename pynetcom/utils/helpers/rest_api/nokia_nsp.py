"""
Nokia NSP Data Provider.

Provides high-level methods for fetching alarms and network elements
from Nokia NSP with filtering and pagination support.
"""

from typing import List, Optional
import logging

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
    
    def get_alarms(
        self,
        name: Optional[str] = None,
        ne_id: Optional[str] = None,
        filters: Optional[RestNMSDataFilter] = None,
        page_size: int = 1000
    ) -> List[NspAlarm]:
        """
        Get alarms from Nokia NSP.
        
        Args:
            name: Filter by network element name (neName).
            ne_id: Filter by network element ID (neId).
            filters: RestNMSDataFilter instance for additional client-side filtering.
            page_size: Number of records per page (default 1000).
        
        Returns:
            List of NspAlarm objects.
        """
        # Build API filter
        api_filters = []
        if name:
            api_filters.append(f"neName='{name}'")
        if ne_id:
            api_filters.append(f"neId='{ne_id}'")
        
        # Build URL
        url = self.ALARMS_ENDPOINT
        if api_filters:
            filter_str = ' AND '.join(api_filters)
            url = f"{url}?alarmFilter={filter_str}"
        
        logger.debug(f"Fetching alarms from: {url}")
        
        # Set page size
        original_limit = self.client.limit
        self.client.limit = page_size
        
        try:
            self.client.clear_data()
            self.client.send_request(url if '?' not in self.ALARMS_ENDPOINT else self.ALARMS_ENDPOINT)
            
            # If we built a custom URL with filters
            if api_filters:
                self.client.clear_data()
                # For NSP, the URL is built in send_request, so we pass the full path
                self.client.send_request(url.replace(self.client.API_NSP_HOST, '').replace(':8544', ''))
            
            raw_data = self.client.get_data()
        finally:
            self.client.limit = original_limit
        
        # Convert to NspAlarm objects
        alarms = [NspAlarm(item) for item in raw_data]
        
        # Apply client-side filters
        if filters:
            alarms = filters.apply(alarms)
        
        logger.info(f"Retrieved {len(alarms)} alarms")
        return alarms
    
    def get_alarms_raw(
        self,
        name: Optional[str] = None,
        ne_id: Optional[str] = None
    ) -> List[dict]:
        """
        Get raw alarm data from Nokia NSP without conversion.
        
        Args:
            name: Filter by network element name.
            ne_id: Filter by network element ID.
        
        Returns:
            List of raw alarm dictionaries.
        """
        api_filters = []
        if name:
            api_filters.append(f"neName='{name}'")
        if ne_id:
            api_filters.append(f"neId='{ne_id}'")
        
        url = self.ALARMS_ENDPOINT
        if api_filters:
            filter_str = ' AND '.join(api_filters)
            url = f"{url}?alarmFilter={filter_str}"
        
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
        filters: Optional[RestNMSDataFilter] = None
    ) -> int:
        """
        Get count of alarms matching the criteria.
        
        Args:
            name: Filter by network element name.
            filters: RestNMSDataFilter instance for additional filtering.
        
        Returns:
            Number of alarms.
        """
        alarms = self.get_alarms(name=name, filters=filters)
        return len(alarms)
    
    def get_alarms_by_severity(
        self,
        severity: str,
        name: Optional[str] = None
    ) -> List[NspAlarm]:
        """
        Get alarms filtered by severity level.
        
        Args:
            severity: Severity level (critical, major, minor, warning, cleared).
            name: Optional NE name filter.
        
        Returns:
            List of NspAlarm objects with specified severity.
        """
        filters = RestNMSDataFilter().include(severity=[severity])
        return self.get_alarms(name=name, filters=filters)
    
    def get_active_alarms(
        self,
        name: Optional[str] = None,
        filters: Optional[RestNMSDataFilter] = None
    ) -> List[NspAlarm]:
        """
        Get only active (non-cleared) alarms.
        
        Args:
            name: Filter by network element name.
            filters: Additional filters to apply.
        
        Returns:
            List of active NspAlarm objects.
        """
        base_filter = RestNMSDataFilter().exclude(severity=['cleared'])
        
        if filters:
            # Combine filters - apply base filter first, then user filters
            alarms = self.get_alarms(name=name, filters=base_filter)
            return filters.apply(alarms)
        
        return self.get_alarms(name=name, filters=base_filter)

