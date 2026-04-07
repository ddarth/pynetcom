"""
Huawei NCE Data Provider.

Provides high-level methods for fetching alarms, network elements,
and topology (links, fibers, IGP links) from Huawei NCE with
filtering, pagination, and UUID-to-name resolution support.
"""

from typing import Dict, List, Optional, Set
from datetime import datetime
import logging

from pynetcom.rest_nce import RestNCE
from pynetcom.utils.helpers.rest_api.base import RestNMSDataFilter
from pynetcom.utils.helpers.rest_api.data_containers.huawei_nce import (
    NceAlarm,
    NceIgpLink,
    NceLink,
    NceNetworkElement,
    NcePort,
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
    LINKS_ENDPOINT = "/restconf/v2/data/huawei-nce-resource-inventory:links"
    IGP_LINKS_ENDPOINT = "/restconf/v3/data/huawei-nce-resource-inventory:igp-links"
    PORTS_ENDPOINT = "/restconf/v3/data/huawei-nce-resource-inventory:ltps"
    
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

    # ─── Topology: Links ───────────────────────────────────────────────

    def _extract_links_from_response(self, response_data: List[dict]) -> List[dict]:
        """
        Extract link list from NCE response structure.

        NCE returns links in nested structure:
        [{"links": {"link": [...]}}]

        Args:
            response_data: Raw response from NCE API.

        Returns:
            Flat list of link dictionaries.
        """
        links = []
        for page in response_data:
            if isinstance(page, dict):
                link_container = page.get('links', {})
                if isinstance(link_container, dict):
                    link_list = link_container.get('link', [])
                    if isinstance(link_list, list):
                        links.extend(link_list)
        return links

    def _extract_igp_links_from_response(self, response_data: List[dict]) -> List[dict]:
        """
        Extract IGP link list from NCE response structure.

        NCE returns IGP links in nested structure:
        [{"igp-links": {"igp-link": [...]}}]

        Args:
            response_data: Raw response from NCE API.

        Returns:
            Flat list of IGP link dictionaries.
        """
        links = []
        for page in response_data:
            if isinstance(page, dict):
                link_container = page.get('igp-links', {})
                if isinstance(link_container, dict):
                    link_list = link_container.get('igp-link', [])
                    if isinstance(link_list, list):
                        links.extend(link_list)
        return links

    def _extract_ltps_from_response(self, response_data: List[dict]) -> List[dict]:
        """
        Extract port (LTP) list from NCE response structure.

        NCE returns ports in nested structure:
        [{"ltps": {"ltp": [...]}}]

        Each LTP dict contains at minimum: res-id, name, ne-id.

        Args:
            response_data: Raw response from NCE API.

        Returns:
            Flat list of port dictionaries.
        """
        ltps = []
        for page in response_data:
            if isinstance(page, dict):
                ltp_container = page.get('ltps', {})
                if isinstance(ltp_container, dict):
                    ltp_list = ltp_container.get('ltp', [])
                    if isinstance(ltp_list, list):
                        ltps.extend(ltp_list)
        return ltps

    # ─── Topology: Ports (LTP) ─────────────────────────────────────────

    def get_ports(
        self,
        ne_id: Optional[str] = None,
        name: Optional[str] = None,
        card_id: Optional[str] = None,
        ltp_type_name: Optional[str] = None,
        sc_ltp_type: Optional[str] = None,
        is_physical: Optional[bool] = None,
        is_sub_ltp: Optional[bool] = None,
        parent_ltp_id: Optional[str] = None,
        ltp_role: Optional[str] = None,
        resolve_names: bool = False,
        filters: Optional[RestNMSDataFilter] = None,
        page_size: int = 5000
    ) -> List[NcePort]:
        """
        Get ports (LTP — Logical Termination Points) from Huawei NCE.

        Ports include physical ports, logical interfaces, subinterfaces,
        channels, and timeslots on network elements.

        Args:
            ne_id: Filter by NE UUID (server-side). Recommended for targeted queries.
            name: Filter by port name (server-side).
            card_id: Filter by board UUID (server-side).
            ltp_type_name: Filter by port type (server-side).
                           Values: 'Ethernet', 'GigabitEthernet', '100GE', '10GE',
                           'Eth-Trunk', 'LoopBack', 'Vlanif', 'Tunnel', 'WDM Client',
                           'SDH', 'VC3', 'VC4', 'ODU2', 'CLIENT', etc.
            sc_ltp_type: Filter by multi-domain port type (server-side).
                         Values: 'ETH', 'Eth-Trunk', 'WDM', 'WDM Client', 'SDH',
                         'Loopback', 'VLANIF', 'Other', etc.
            is_physical: Filter by physical/logical (server-side).
                         True: physical ports only. False: logical interfaces only.
            is_sub_ltp: Filter by subinterface (server-side).
                        True: subinterfaces only. False: main interfaces only.
            parent_ltp_id: Filter by parent interface UUID (server-side).
            ltp_role: Filter by interface role (server-side). Values: 'UNI', 'NNI'.
            resolve_names: If True, resolves NE UUIDs to names (ne_name field).
            filters: RestNMSDataFilter instance for additional client-side filtering.
            page_size: Number of records per page (max 5000).

        Returns:
            List of NcePort objects.

        Performance:
            - All ports (no filters): ~56s for ~88K ports
            - By NE: ~0.12s per NE (~50-100 ports each)
            - By type: server-side filter, fast

        Example:
            # All physical Ethernet ports on a specific NE
            ports = provider.get_ports(ne_id="...", is_physical=True,
                                       ltp_type_name="Ethernet")

            # All Eth-Trunk interfaces with resolved NE names
            trunks = provider.get_ports(ltp_type_name="Eth-Trunk",
                                        resolve_names=True)

            # All subinterfaces of a specific parent port
            subs = provider.get_ports(parent_ltp_id="...")
        """
        # Build query parameters (server-side filters)
        params = []
        if ne_id:
            params.append(f"ne-id={ne_id}")
        if name:
            params.append(f"name={name}")
        if card_id:
            params.append(f"card-id={card_id}")
        if ltp_type_name:
            params.append(f"ltp-type-name={ltp_type_name}")
        if sc_ltp_type:
            params.append(f"sc-ltp-type={sc_ltp_type}")
        if is_physical is not None:
            params.append(f"is-physical={'true' if is_physical else 'false'}")
        if is_sub_ltp is not None:
            params.append(f"is-sub-ltp={'true' if is_sub_ltp else 'false'}")
        if parent_ltp_id:
            params.append(f"parent-ltp-id={parent_ltp_id}")
        if ltp_role:
            params.append(f"ltp-role={ltp_role}")
        params_str = '&'.join(params) if params else ''

        logger.debug(f"Fetching ports from: {self.PORTS_ENDPOINT}")
        if params_str:
            logger.debug(f"With server-side filter: {params_str}")

        original_limit = self.client.limit
        self.client.limit = str(page_size)

        try:
            self.client.clear_data()
            self.client.send_request(self.PORTS_ENDPOINT, params_str)
            raw_data = self.client.get_data()
        finally:
            self.client.limit = original_limit

        # Extract ports from nested response
        ltp_dicts = self._extract_ltps_from_response(raw_data)

        # Convert to NcePort objects
        ports = [NcePort(item) for item in ltp_dicts]

        # Apply client-side filters
        if filters:
            ports = filters.apply(ports)

        # Resolve NE names if requested
        if resolve_names:
            self.resolve_port_names(ports)

        logger.info(f"Retrieved {len(ports)} ports")
        return ports

    def get_port_by_id(self, res_id: str) -> Optional[NcePort]:
        """
        Get a single port by resource ID.

        Args:
            res_id: Resource ID (UUID) of the port.

        Returns:
            NcePort object or None if not found.
        """
        url = f"{self.PORTS_ENDPOINT}/ltp/{res_id}"

        self.client.clear_data()
        self.client.send_request(url)
        raw_data = self.client.get_data()

        if raw_data:
            for page in raw_data:
                if isinstance(page, dict):
                    ltp_data = page.get('ltp')
                    if isinstance(ltp_data, dict):
                        return NcePort(ltp_data)
                    elif isinstance(ltp_data, list) and ltp_data:
                        return NcePort(ltp_data[0])
        return None

    def resolve_port_names(self, ports: list) -> list:
        """
        Resolve NE UUID to human-readable NE name for port objects.

        Populates the ne_name field on each port object. This method
        mutates the port objects in-place and returns the same list.

        Args:
            ports: List of NcePort objects.

        Returns:
            The same list with ne_name populated.

        Example:
            ports = provider.get_ports(ne_id="...")
            provider.resolve_port_names(ports)
            print(ports[0].ne_name)  # "IPBB_Naryn_NE40E-1"
        """
        if not ports:
            return ports

        ne_cache = self._build_ne_name_cache()
        for port in ports:
            port.ne_name = ne_cache.get(port.ne_id)

        logger.info(f"Resolved NE names for {len(ports)} ports")
        return ports

    # ─── Name resolution caches ────────────────────────────────────────

    def _build_ne_name_cache(self) -> Dict[str, str]:
        """
        Build a cache mapping NE resource IDs to NE names.

        Fetches all network elements from NCE and creates a lookup dictionary.
        Used by resolve_link_names() and resolve_port_names().

        Returns:
            Dictionary {ne_res_id: ne_name}, e.g.:
            {"d0cc81df-b9f9-11ea-ad74-b008759ca76f": "IPBB_Naryn_NE40E-1"}

        Performance: ~1-2 seconds for ~1600 NEs.
        """
        logger.debug("Building NE name cache...")
        elements = self.get_network_elements()
        cache = {ne.res_id: ne.name for ne in elements if ne.res_id and ne.name}
        logger.debug(f"NE name cache built: {len(cache)} entries")
        return cache

    def _build_ltp_name_cache(self, ne_ids: Set[str]) -> Dict[str, str]:
        """
        Build a cache mapping port (LTP) resource IDs to port names.

        Uses get_ports() internally — standardized approach instead of
        direct HTTP calls. Adaptive loading strategy:
        - If ne_ids <= 10: loads ports per-NE via get_ports(ne_id=...).
          Faster for small sets. Includes delay to avoid HTTP 429.
        - If ne_ids > 10: loads ALL ports via get_ports() (bulk).
          ~56s for ~88K ports, but avoids rate limiting.

        Threshold of 10 based on NCE API rate limiting:
        - API allows ~10 concurrent calls for /ltps endpoint
        - Per-NE requests without delay trigger HTTP 429 after ~15 requests
        - With 0.1s delay: 10 NEs * 0.22s = ~2.2s (fast and safe)

        Args:
            ne_ids: Set of NE UUIDs whose ports need resolving.

        Returns:
            Dictionary {ltp_res_id: ltp_name}.
        """
        import time
        PER_NE_THRESHOLD = 10
        PER_NE_DELAY = 0.1  # seconds between per-NE requests to avoid HTTP 429

        if len(ne_ids) <= PER_NE_THRESHOLD:
            # Per-NE loading via get_ports() — fast for small sets
            logger.debug(f"Loading ports per-NE for {len(ne_ids)} NEs (threshold={PER_NE_THRESHOLD})")
            cache = {}
            for i, ne_id in enumerate(ne_ids):
                if i > 0:
                    time.sleep(PER_NE_DELAY)
                try:
                    ports = self.get_ports(ne_id=ne_id)
                    for p in ports:
                        if p.res_id and p.name:
                            cache[p.res_id] = p.name
                except Exception as e:
                    logger.warning(f"Failed to load ports for NE {ne_id}: {e}")
        else:
            # Bulk loading via get_ports() — all ports at once
            logger.debug(f"Loading ALL ports (bulk mode, {len(ne_ids)} NEs > threshold={PER_NE_THRESHOLD})")
            all_ports = self.get_ports()
            cache = {p.res_id: p.name for p in all_ports if p.res_id and p.name}

        logger.debug(f"LTP name cache built: {len(cache)} entries")
        return cache

    def resolve_link_names(self, links: list) -> list:
        """
        Resolve UUID fields in link objects to human-readable names.

        Populates the following fields on each link object:
        - a_end_ne_name: name of the source network element
        - z_end_ne_name: name of the sink network element
        - a_end_ltp_name: name of the source port (e.g. "GigabitEthernet1/0/0")
        - z_end_ltp_name: name of the sink port

        This method mutates the link objects in-place and returns the same list.

        Name resolution sources:
        - NE names: GET /restconf/v2/data/huawei-nce-resource-inventory:network-elements
        - Port names: GET /restconf/v3/data/huawei-nce-resource-inventory:ltps

        Usage patterns:
            # Pattern 1: resolve all links at once
            links = provider.get_links(resolve_names=True)

            # Pattern 2: resolve only filtered subset (faster for small sets)
            links = provider.get_links()
            down_links = [l for l in links if l.operate_status == '1']
            provider.resolve_link_names(down_links)  # only 19 links -> per-NE loading

        Args:
            links: List of BaseLink subclass objects (NceLink or NceIgpLink).

        Returns:
            The same list of links with resolved name fields populated.
        """
        if not links:
            return links

        # Step 1: Collect unique NE and LTP UUIDs from links
        ne_ids = set()
        ltp_ids = set()
        for link in links:
            if link.a_end_ne_id:
                ne_ids.add(link.a_end_ne_id)
            if link.z_end_ne_id:
                ne_ids.add(link.z_end_ne_id)
            if link.a_end_ltp_id:
                ltp_ids.add(link.a_end_ltp_id)
            if link.z_end_ltp_id:
                ltp_ids.add(link.z_end_ltp_id)

        logger.info(f"Resolving names for {len(links)} links ({len(ne_ids)} unique NEs, {len(ltp_ids)} unique ports)")

        # Step 2: Build NE name cache (single request, ~1-2s)
        ne_cache = self._build_ne_name_cache()

        # Step 3: Build LTP name cache (adaptive: per-NE or bulk, see _build_ltp_name_cache)
        ltp_cache = self._build_ltp_name_cache(ne_ids)

        # Step 4: Populate resolved fields on each link object
        for link in links:
            link.a_end_ne_name = ne_cache.get(link.a_end_ne_id)
            link.z_end_ne_name = ne_cache.get(link.z_end_ne_id)
            link.a_end_ltp_name = ltp_cache.get(link.a_end_ltp_id)
            link.z_end_ltp_name = ltp_cache.get(link.z_end_ltp_id)

        resolved_ne = sum(1 for l in links if l.a_end_ne_name or l.z_end_ne_name)
        resolved_ltp = sum(1 for l in links if l.a_end_ltp_name or l.z_end_ltp_name)
        logger.info(f"Resolved: {resolved_ne} links with NE names, {resolved_ltp} links with port names")

        return links

    def get_links(
        self,
        a_end_ne_id: Optional[str] = None,
        z_end_ne_id: Optional[str] = None,
        link_type: Optional[str] = None,
        filters: Optional[RestNMSDataFilter] = None,
        resolve_names: bool = False,
        page_size: int = 2000
    ) -> List[NceLink]:
        """
        Get links from Huawei NCE.

        Args:
            a_end_ne_id: Filter by source NE UUID (server-side).
            z_end_ne_id: Filter by sink NE UUID (server-side).
            link_type: Filter by link type (client-side).
                       Values: 'Fiber', 'L2 Link', 'Microwave Link', 'Cable',
                       'IP Link', 'Dummy Link'.
            filters: RestNMSDataFilter instance for additional client-side filtering.
            resolve_names: If True, resolves NE and port UUIDs to human-readable
                           names (a_end_ne_name, z_end_ne_name, a_end_ltp_name,
                           z_end_ltp_name). Adds significant time (~60s for all links)
                           due to port data loading. For faster resolution on a subset,
                           use resolve_link_names() separately after filtering.
            page_size: Number of records per page.

        Returns:
            List of NceLink objects.

        Example:
            # Fast — only UUIDs
            links = provider.get_links()

            # With resolved names (slower, loads NE + port data)
            links = provider.get_links(resolve_names=True)
            print(links[0].a_end_ne_name)   # "IPBB_Naryn_NE40E-1"
            print(links[0].a_end_ltp_name)  # "GigabitEthernet1/0/0"

            # Efficient pattern — resolve only filtered subset
            links = provider.get_links()
            down = [l for l in links if l.operate_status == '1']
            provider.resolve_link_names(down)
        """
        # Build query parameters (server-side filters)
        params = []
        if a_end_ne_id:
            params.append(f"a-end-ne-id={a_end_ne_id}")
        if z_end_ne_id:
            params.append(f"z-end-ne-id={z_end_ne_id}")
        params_str = '&'.join(params) if params else ''

        logger.debug(f"Fetching links from: {self.LINKS_ENDPOINT}")
        if params_str:
            logger.debug(f"With server-side filter: {params_str}")

        original_limit = self.client.limit
        self.client.limit = str(page_size)

        try:
            self.client.clear_data()
            self.client.send_request(self.LINKS_ENDPOINT, params_str)
            raw_data = self.client.get_data()
        finally:
            self.client.limit = original_limit

        # Extract links from nested response
        link_dicts = self._extract_links_from_response(raw_data)

        # Convert to NceLink objects
        links = [NceLink(item) for item in link_dicts]

        # Client-side filter by link type
        if link_type:
            links = [l for l in links if l.link_type == link_type]

        # Apply client-side filters
        if filters:
            links = filters.apply(links)

        # Resolve NE/port UUIDs to human-readable names if requested
        if resolve_names:
            self.resolve_link_names(links)

        logger.info(f"Retrieved {len(links)} links")
        return links

    def get_link_by_id(self, res_id: str) -> Optional[NceLink]:
        """
        Get a single link by resource ID.

        Args:
            res_id: Resource ID of the link.

        Returns:
            NceLink object or None if not found.
        """
        url = f"{self.LINKS_ENDPOINT}/link/{res_id}"

        self.client.clear_data()
        self.client.send_request(url)
        raw_data = self.client.get_data()

        if raw_data:
            for page in raw_data:
                if isinstance(page, dict):
                    link_data = page.get('link')
                    if isinstance(link_data, dict):
                        return NceLink(link_data)
                    elif isinstance(link_data, list) and link_data:
                        return NceLink(link_data[0])
        return None

    def get_fibers(
        self,
        a_end_ne_id: Optional[str] = None,
        z_end_ne_id: Optional[str] = None,
        filters: Optional[RestNMSDataFilter] = None,
        resolve_names: bool = False,
        page_size: int = 2000
    ) -> List[NceLink]:
        """
        Get fiber links from Huawei NCE.

        Convenience method that fetches links and filters by type="Fiber".

        Args:
            a_end_ne_id: Filter by source NE UUID (server-side).
            z_end_ne_id: Filter by sink NE UUID (server-side).
            filters: RestNMSDataFilter instance for additional client-side filtering.
            resolve_names: If True, resolves NE and port UUIDs to names.
                           See get_links() for details.
            page_size: Number of records per page.

        Returns:
            List of NceLink objects with link_type="Fiber".
        """
        return self.get_links(
            a_end_ne_id=a_end_ne_id,
            z_end_ne_id=z_end_ne_id,
            link_type="Fiber",
            filters=filters,
            resolve_names=resolve_names,
            page_size=page_size
        )

    # ─── Topology: IGP Links ──────────────────────────────────────────

    def get_igp_links(
        self,
        a_end_ne_id: Optional[str] = None,
        z_end_ne_id: Optional[str] = None,
        filters: Optional[RestNMSDataFilter] = None,
        resolve_names: bool = False,
        page_size: int = 2000
    ) -> List[NceIgpLink]:
        """
        Get IGP links from Huawei NCE.

        Args:
            a_end_ne_id: Filter by source NE UUID (server-side).
            z_end_ne_id: Filter by sink NE UUID (server-side).
            filters: RestNMSDataFilter instance for additional client-side filtering.
            resolve_names: If True, resolves NE and port UUIDs to names.
                           See get_links() for details.
            page_size: Number of records per page.

        Returns:
            List of NceIgpLink objects.
        """
        # Build query parameters
        params = []
        if a_end_ne_id:
            params.append(f"a-end-ne-id={a_end_ne_id}")
        if z_end_ne_id:
            params.append(f"z-end-ne-id={z_end_ne_id}")
        params_str = '&'.join(params) if params else ''

        logger.debug(f"Fetching IGP links from: {self.IGP_LINKS_ENDPOINT}")
        if params_str:
            logger.debug(f"With server-side filter: {params_str}")

        original_limit = self.client.limit
        self.client.limit = str(page_size)

        try:
            self.client.clear_data()
            self.client.send_request(self.IGP_LINKS_ENDPOINT, params_str)
            raw_data = self.client.get_data()
        finally:
            self.client.limit = original_limit

        # Extract IGP links from nested response
        link_dicts = self._extract_igp_links_from_response(raw_data)

        # Convert to NceIgpLink objects
        links = [NceIgpLink(item) for item in link_dicts]

        # Apply client-side filters
        if filters:
            links = filters.apply(links)

        # Resolve NE/port UUIDs to human-readable names if requested
        if resolve_names:
            self.resolve_link_names(links)

        logger.info(f"Retrieved {len(links)} IGP links")
        return links

    def get_igp_link_by_id(self, res_id: str) -> Optional[NceIgpLink]:
        """
        Get a single IGP link by resource ID.

        Args:
            res_id: Resource ID of the IGP link.

        Returns:
            NceIgpLink object or None if not found.
        """
        url = f"{self.IGP_LINKS_ENDPOINT}/igp-link/{res_id}"

        self.client.clear_data()
        self.client.send_request(url)
        raw_data = self.client.get_data()

        if raw_data:
            for page in raw_data:
                if isinstance(page, dict):
                    link_data = page.get('igp-link')
                    if isinstance(link_data, dict):
                        return NceIgpLink(link_data)
                    elif isinstance(link_data, list) and link_data:
                        return NceIgpLink(link_data[0])
        return None

