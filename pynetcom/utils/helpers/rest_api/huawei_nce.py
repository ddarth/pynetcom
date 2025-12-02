"""
Huawei NCE Data Provider.

Provides high-level methods for fetching alarms and network elements
from Huawei NCE with filtering and pagination support.
"""

from typing import List, Optional
from datetime import datetime
import logging

from pynetcom.rest_nce import RestNCE
from pynetcom.utils.helpers.rest_api.base import RestNMSDataFilter
from pynetcom.utils.helpers.rest_api.data_containers.huawei_nce import (
    NceAlarm,
    NceNetworkElement,
)


logger = logging.getLogger('pynetcom.nce_data_provider')


class NceDataProvider:
    """
    High-level data provider for Huawei NCE.
    
    Wraps RestNCE client with convenient methods for fetching alarms
    and network elements with filtering capabilities.
    
    Example:
        from pynetcom import RestNCE
        from pynetcom.utils.helpers.rest_api import NceDataProvider, RestNMSDataFilter
        
        client = RestNCE(host, user, password)
        provider = NceDataProvider(client)
        
        # Get alarms with filtering
        filter = RestNMSDataFilter()
        filter.exclude(severity=['cleared', 'warning'])
        
        alarms = provider.get_alarms(name="TestNE", filters=filter)
        for alarm in alarms:
            print(alarm.brief())
    """
    
    # API endpoints
    ALARMS_ENDPOINT = "/restconf/v1/data/ietf-alarms:alarms/alarm-list"
    NETWORK_ELEMENTS_ENDPOINT = "/restconf/v2/data/huawei-nce-resource-inventory:network-elements"
    SUBNETS_ENDPOINT = "/restconf/v2/data/huawei-nce-resource-inventory:subnets"
    
    def __init__(self, client: RestNCE):
        """
        Initialize NCE data provider.
        
        Args:
            client: RestNCE client instance.
        """
        self.client = client
    
    def _extract_alarms_from_response(self, response_data: List[dict]) -> List[dict]:
        """
        Extract alarm list from NCE response structure.
        
        NCE returns alarms in nested structure:
        [{"alarm": [...]}, {"alarm": [...]}]
        
        Args:
            response_data: Raw response from NCE API.
        
        Returns:
            Flat list of alarm dictionaries.
        """
        alarms = []
        for page in response_data:
            if isinstance(page, dict):
                # Check for 'alarm' key (list endpoint)
                if 'alarm' in page:
                    alarms.extend(page['alarm'])
                # Check for 'alarm-list' key
                elif 'alarm-list' in page:
                    alarm_list = page['alarm-list']
                    if isinstance(alarm_list, dict) and 'alarm' in alarm_list:
                        alarms.extend(alarm_list['alarm'])
                    elif isinstance(alarm_list, list):
                        alarms.extend(alarm_list)
        return alarms
    
    def _extract_network_elements_from_response(self, response_data: List[dict]) -> List[dict]:
        """
        Extract network element list from NCE response structure.
        
        NCE returns NEs in nested structure:
        [{"network-elements": {"network-element": [...]}}]
        
        Args:
            response_data: Raw response from NCE API.
        
        Returns:
            Flat list of network element dictionaries.
        """
        elements = []
        for page in response_data:
            if isinstance(page, dict):
                ne_container = page.get('network-elements', {})
                if isinstance(ne_container, dict):
                    ne_list = ne_container.get('network-element', [])
                    if isinstance(ne_list, list):
                        elements.extend(ne_list)
        return elements
    
    def _format_datetime_for_api(self, dt: datetime) -> str:
        """Format datetime for NCE API (UTC with Z suffix)."""
        from datetime import timezone
        # Convert to UTC if timezone-aware, otherwise assume local time
        if dt.tzinfo is not None:
            dt_utc = dt.astimezone(timezone.utc)
        else:
            # Assume local time, convert to UTC
            dt_utc = dt
        return dt_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    def get_alarms(
        self,
        name: Optional[str] = None,
        resource: Optional[str] = None,
        is_cleared: Optional[bool] = None,
        severity: Optional[List[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        filters: Optional[RestNMSDataFilter] = None,
        page_size: int = 1000
    ) -> List[NceAlarm]:
        """
        Get alarms from Huawei NCE.
        
        Args:
            name: Filter by network element name. Will first lookup NE to get resource ID
                  for efficient server-side filtering.
            resource: Filter by resource ID (server-side).
            is_cleared: Filter by cleared status (server-side).
            severity: Filter by severity levels (server-side). 
                      Values: 'critical', 'major', 'minor', 'warning'.
            start_time: Start time for alarm query period (server-side, UTC).
            end_time: End time for alarm query period (server-side, UTC).
            filters: RestNMSDataFilter instance for additional client-side filtering.
            page_size: Number of records per page.
        
        Returns:
            List of NceAlarm objects.
        """
        # If name is provided but resource is not, lookup NE first to get resource ID
        if name and not resource:
            logger.debug(f"Looking up NE '{name}' to get resource ID for alarm filtering")
            elements = self.get_network_elements(name=name)
            if elements:
                resource = elements[0].res_id
                logger.debug(f"Found NE resource ID: {resource}")
            else:
                logger.warning(f"NE '{name}' not found, will fetch all alarms")
        
        # Build query parameters (server-side filters)
        params = []
        if resource:
            params.append(f"resource={resource}")
        if severity:
            for sev in severity:
                params.append(f"perceived-severity={sev}")
        if start_time:
            params.append(f"start-time={self._format_datetime_for_api(start_time)}")
        if end_time:
            params.append(f"end-time={self._format_datetime_for_api(end_time)}")
        
        params_str = '&'.join(params) if params else ''
        
        # Build request body for additional filters
        body = None
        if is_cleared is not None:
            body = {'is-cleared': is_cleared}
        
        logger.debug(f"Fetching alarms from: {self.ALARMS_ENDPOINT}")
        if params_str:
            logger.debug(f"With server-side filter: {params_str}")
        
        # Set page size
        original_limit = self.client.limit
        self.client.limit = str(page_size)
        
        try:
            self.client.clear_data()
            self.client.send_request(self.ALARMS_ENDPOINT, params_str, body)
            raw_data = self.client.get_data()
        finally:
            self.client.limit = original_limit
        
        # Extract alarms from nested response
        alarm_dicts = self._extract_alarms_from_response(raw_data)
        
        # Convert to NceAlarm objects
        alarms = [NceAlarm(item) for item in alarm_dicts]
        
        # Apply client-side filters
        if filters:
            alarms = filters.apply(alarms)
        
        logger.info(f"Retrieved {len(alarms)} alarms")
        return alarms
    
    def get_alarms_raw(
        self,
        resource: Optional[str] = None,
        is_cleared: Optional[bool] = None
    ) -> List[dict]:
        """
        Get raw alarm data from Huawei NCE without conversion.
        
        Args:
            resource: Filter by resource ID.
            is_cleared: Filter by cleared status.
        
        Returns:
            List of raw alarm dictionaries.
        """
        params = []
        if resource:
            params.append(f"resource={resource}")
        
        params_str = '&'.join(params) if params else ''
        
        body = None
        if is_cleared is not None:
            body = {'is-cleared': is_cleared}
        
        self.client.clear_data()
        self.client.send_request(self.ALARMS_ENDPOINT, params_str, body)
        raw_data = self.client.get_data()
        
        return self._extract_alarms_from_response(raw_data)
    
    def get_network_elements(
        self,
        name: Optional[str] = None,
        filters: Optional[RestNMSDataFilter] = None,
        page_size: int = 1000
    ) -> List[NceNetworkElement]:
        """
        Get network elements from Huawei NCE.
        
        Args:
            name: Filter by network element name.
            filters: RestNMSDataFilter instance for additional client-side filtering.
            page_size: Number of records per page.
        
        Returns:
            List of NceNetworkElement objects.
        """
        # NCE supports name filter in query params
        params = f"name={name}" if name else ''
        
        logger.debug(f"Fetching network elements from: {self.NETWORK_ELEMENTS_ENDPOINT}")
        
        original_limit = self.client.limit
        self.client.limit = str(page_size)
        
        try:
            self.client.clear_data()
            self.client.send_request(self.NETWORK_ELEMENTS_ENDPOINT, params)
            raw_data = self.client.get_data()
        finally:
            self.client.limit = original_limit
        
        # Extract NEs from nested response
        ne_dicts = self._extract_network_elements_from_response(raw_data)
        
        # Convert to NceNetworkElement objects
        elements = [NceNetworkElement(item) for item in ne_dicts]
        
        # Apply client-side filters
        if filters:
            elements = filters.apply(elements)
        
        logger.info(f"Retrieved {len(elements)} network elements")
        return elements
    
    def get_network_elements_raw(
        self,
        name: Optional[str] = None
    ) -> List[dict]:
        """
        Get raw network element data from Huawei NCE.
        
        Args:
            name: Filter by network element name.
        
        Returns:
            List of raw network element dictionaries.
        """
        params = f"name={name}" if name else ''
        
        self.client.clear_data()
        self.client.send_request(self.NETWORK_ELEMENTS_ENDPOINT, params)
        raw_data = self.client.get_data()
        
        return self._extract_network_elements_from_response(raw_data)
    
    def get_network_element_by_id(self, res_id: str) -> Optional[NceNetworkElement]:
        """
        Get a single network element by resource ID.
        
        Args:
            res_id: Resource ID of the network element.
        
        Returns:
            NceNetworkElement object or None if not found.
        """
        url = f"{self.NETWORK_ELEMENTS_ENDPOINT}/network-element/{res_id}"
        
        self.client.clear_data()
        self.client.send_request(url)
        raw_data = self.client.get_data()
        
        if raw_data:
            # Extract the NE from response
            for page in raw_data:
                if isinstance(page, dict):
                    ne_data = page.get('network-element')
                    if isinstance(ne_data, dict):
                        return NceNetworkElement(ne_data)
                    elif isinstance(ne_data, list) and ne_data:
                        return NceNetworkElement(ne_data[0])
        return None
    
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
    ) -> List[NceAlarm]:
        """
        Get alarms filtered by severity level.
        
        Args:
            severity: Severity level (critical, major, minor, warning).
            name: Optional NE name filter.
        
        Returns:
            List of NceAlarm objects with specified severity.
        """
        filters = RestNMSDataFilter().include(severity=[severity])
        return self.get_alarms(name=name, filters=filters)
    
    def get_active_alarms(
        self,
        name: Optional[str] = None,
        filters: Optional[RestNMSDataFilter] = None
    ) -> List[NceAlarm]:
        """
        Get only active (non-cleared) alarms.
        
        Args:
            name: Filter by network element name.
            filters: Additional filters to apply.
        
        Returns:
            List of active NceAlarm objects.
        """
        # Use API filter for is_cleared
        alarms = self.get_alarms(name=name, is_cleared=False)
        
        if filters:
            alarms = filters.apply(alarms)
        
        return alarms
    
    def get_subnets(self) -> List[dict]:
        """
        Get all subnets from NCE.
        
        Returns:
            List of subnet dictionaries.
        """
        self.client.clear_data()
        self.client.send_request(self.SUBNETS_ENDPOINT)
        raw_data = self.client.get_data()
        
        subnets = []
        for page in raw_data:
            if isinstance(page, dict):
                subnet_container = page.get('subnets', {})
                if isinstance(subnet_container, dict):
                    subnet_list = subnet_container.get('subnet', [])
                    if isinstance(subnet_list, list):
                        subnets.extend(subnet_list)
        
        return subnets

