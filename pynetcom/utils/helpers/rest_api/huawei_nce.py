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


# Enable verbose logging across pynetcom (and allow downstream override via basicConfig)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger('pynetcom.nce_data_provider')
pynetcom_logger = logging.getLogger('pynetcom')
pynetcom_logger.setLevel(logging.DEBUG)
pynetcom_logger.propagate = True



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
        """
        Format datetime for NCE API.
        
        NCE API accepts:
        - UTC format: 2019-07-10T00:00:00Z
        - Local format: 2019-07-10T08:00:00 (without Z suffix)
        
        If datetime is timezone-aware, converts to UTC with Z suffix.
        If datetime is naive (local), uses local format without Z suffix.
        """
        from datetime import timezone
        
        if dt.tzinfo is not None:
            # Timezone-aware: convert to UTC and use Z suffix
            dt_utc = dt.astimezone(timezone.utc)
            return dt_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        else:
            # Naive datetime (local time): use local format without Z
            return dt.strftime('%Y-%m-%dT%H:%M:%S')
    
    def get_alarms(
        self,
        name: Optional[str] = None,
        resource: Optional[str] = None,
        subnet_id: Optional[str] = None,
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
            subnet_id: Filter by subnet ID. Fetches all alarms and filters by NEs in subnet
                       on client side (optimized: single request instead of per-NE requests).
            is_cleared: Filter by cleared status (server-side).
            severity: Filter by severity levels (server-side). 
                      Values: 'critical', 'major', 'minor', 'warning'.
            start_time: Start time for alarm query period (server-side).
            end_time: End time for alarm query period (server-side).
            filters: RestNMSDataFilter instance for additional client-side filtering.
            page_size: Number of records per page.
        
        Returns:
            List of NceAlarm objects.
        """
        # If subnet_id is provided, get alarms for all NEs in the subnet
        if subnet_id and not resource and not name:
            logger.debug(f"Fetching alarms for subnet '{subnet_id}'")
            return self._get_alarms_by_subnet(
                subnet_id=subnet_id,
                is_cleared=is_cleared,
                severity=severity,
                start_time=start_time,
                end_time=end_time,
                filters=filters,
                page_size=page_size
            )
        
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
        if is_cleared is not None:
            # API expects query param is-cleared (not request body)
            params.append(f"is-cleared={'true' if is_cleared else 'false'}")
        
        params_str = '&'.join(params) if params else ''
        
        # No request body needed for GET filters
        body = None
        
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
    
    def _get_alarms_by_subnet(
        self,
        subnet_id: str,
        is_cleared: Optional[bool] = None,
        severity: Optional[List[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        filters: Optional[RestNMSDataFilter] = None,
        page_size: int = 1000
    ) -> List[NceAlarm]:
        """
        Get alarms for all NEs in a subnet using client-side filtering.
        
        Optimized approach: fetches all alarms in a single request, then filters
        by NE resource IDs on the client side. This is ~50x faster than making
        individual requests per NE.
        
        Args:
            subnet_id: Subnet resource ID (ref-parent-subnet).
            Other args: Same as get_alarms.
        
        Returns:
            List of NceAlarm objects for all NEs in the subnet.
        """
        # 1. Get all NEs in the subnet
        elements = self.get_network_elements_by_subnet(subnet_id)
        
        if not elements:
            logger.warning(f"No NEs found in subnet '{subnet_id}'")
            return []
        
        logger.info(f"Found {len(elements)} NEs in subnet '{subnet_id}'")
        
        # 2. Build set of NE resource IDs for fast lookup
        ne_res_ids = {ne.res_id for ne in elements if ne.res_id}
        
        # 3. Fetch all alarms in a single request (with time/severity filters)
        # Call get_alarms without subnet_id to avoid recursion
        all_alarms = self.get_alarms(
            is_cleared=is_cleared,
            severity=severity,
            start_time=start_time,
            end_time=end_time,
            page_size=page_size
        )
        
        # 4. Filter alarms by NE resource IDs (client-side)
        subnet_alarms = [a for a in all_alarms if a.resource_id in ne_res_ids]
        
        # Apply additional client-side filters
        if filters:
            subnet_alarms = filters.apply(subnet_alarms)
        
        logger.info(f"Retrieved {len(subnet_alarms)} alarms for subnet '{subnet_id}' (filtered from {len(all_alarms)} total)")
        return subnet_alarms
    
    def get_network_elements_by_subnet(
        self,
        subnet_id: str,
        page_size: int = 1000
    ) -> List[NceNetworkElement]:
        """
        Get all network elements in a subnet.
        
        Uses server-side filtering via ref-parent-subnet query parameter.
        
        Args:
            subnet_id: Subnet resource ID (ref-parent-subnet).
            page_size: Number of records per page.
        
        Returns:
            List of NceNetworkElement objects in the subnet.
        """
        logger.debug(f"Fetching NEs for subnet: {subnet_id}")
        elements = self.get_network_elements(subnet_id=subnet_id, page_size=page_size)
        logger.info(f"Found {len(elements)} NEs in subnet '{subnet_id}'")
        return elements
    
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
        subnet_id: Optional[str] = None,
        filters: Optional[RestNMSDataFilter] = None,
        page_size: int = 1000
    ) -> List[NceNetworkElement]:
        """
        Get network elements from Huawei NCE.
        
        Args:
            name: Filter by network element name (server-side).
            subnet_id: Filter by subnet ID (server-side, ref-parent-subnet).
            filters: RestNMSDataFilter instance for additional client-side filtering.
            page_size: Number of records per page.
        
        Returns:
            List of NceNetworkElement objects.
        """
        # Build query parameters for server-side filtering
        params = []
        if name:
            params.append(f"name={name}")
        if subnet_id:
            params.append(f"ref-parent-subnet={subnet_id}")
        params_str = '&'.join(params) if params else ''
        
        logger.debug(f"Fetching network elements from: {self.NETWORK_ELEMENTS_ENDPOINT}")
        if params_str:
            logger.debug(f"With server-side filter: {params_str}")
        
        original_limit = self.client.limit
        self.client.limit = str(page_size)
        
        try:
            self.client.clear_data()
            self.client.send_request(self.NETWORK_ELEMENTS_ENDPOINT, params_str)
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
    
    def get_subnet_by_name(self, name: str) -> Optional[dict]:
        """
        Find a subnet by name.
        
        Args:
            name: Subnet name to search for.
        
        Returns:
            Subnet dictionary or None if not found.
        """
        subnets = self.get_subnets()
        for subnet in subnets:
            if subnet.get('name') == name and subnet.get('node-class') == 'subnet':
                return subnet
        return None

