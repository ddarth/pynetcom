"""
Huawei NCE Data Provider.

Provides high-level methods for fetching alarms, network elements,
and topology (links, fibers, IGP links) from Huawei NCE with
filtering, pagination, and UUID-to-name resolution support.
"""

from typing import Callable, Dict, List, Optional, Set, Tuple
from datetime import datetime
import logging

from pynetcom.rest_nce import RestNCE
from pynetcom.utils.helpers.rest_api.base import RestNMSDataFilter
from pynetcom.utils.helpers.rest_api.data_containers.huawei_nce import (
    NceAlarm,
    NceIgpLink,
    NceInterface,
    NceLink,
    NceNode,
    NceTerminationPoint,
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

    # Performance Monitoring — Vendor Specific Raw PM
    # NOTE: Limited to OCH ports on 9800 M24 only. Requires PM task creation.
    # For DWDM optical power on ALL port types, prefer EML PM (get_eml_pm_for_board).
    # For thresholds, use get_optical_power_thresholds().
    # For reference power, use get_reference_power().
    PM_CREATE_URL = "/restconf/v1/operations/huawei-nce-common-pm-rawdata:create-monitor-tasks"
    PM_REALTIME_URL = "/restconf/v1/operations/huawei-nce-common-pm-rawdata:query-realtime-pm-datas"
    PM_HISTORICAL_URL = "/restconf/v1/operations/huawei-nce-common-pm-rawdata:query-history-pm-datas"
    PM_QUERY_TASKS_URL = "/restconf/v1/operations/huawei-nce-common-pm-rawdata:query-monitor-tasks"
    PM_DELETE_TASKS_URL = "/restconf/v1/operations/huawei-nce-common-pm-rawdata:delete-monitor-tasks"

    # EML Performance Service — works on ALL DWDM port types without PM tasks/license
    EML_PM_CUR_URL = "/rest/emlperfservice/v1/trans/querycurdata"
    EML_PM_HIS_URL = "/rest/emlperfservice/v1/trans/queryhisdata"

    # Optical power thresholds and reference power
    OPTICAL_POWER_URL = "/restconf/v2/operations/ietf-trans-oam:query-optical-power"
    ACTN_NETWORKS_URL = "/restconf/v2/data/ietf-network:networks"

    # NCE-internal pmParameterIds for EML PM (NOT same as Excel indicator IDs)
    EML_PM_INDICATORS = {
        # Temperature
        188: ("Cur Temperature", "Celsius"),
        189: ("Min Temperature", "Celsius"),
        190: ("Max Temperature", "Celsius"),
        # Output optical power
        198: ("Cur Total Output Optical Power", "dBm"),
        199: ("Min Total Output Optical Power", "dBm"),
        200: ("Max Total Output Optical Power", "dBm"),
        # Input optical power (LSIOPCUR in GUI)
        201: ("Cur Total Input Optical Power", "dBm"),
        202: ("Min Total Input Optical Power", "dBm"),
        203: ("Max Total Input Optical Power", "dBm"),
        # Laser temperature
        204: ("Cur Laser Temperature", "Celsius"),
        205: ("Min Laser Temperature", "Celsius"),
        206: ("Max Laser Temperature", "Celsius"),
        # Bias current
        207: ("Cur Bias Current", "mA"),
        208: ("Min Bias Current", "mA"),
        209: ("Max Bias Current", "mA"),
        # Laser optical power (variant for amplifier boards)
        210: ("Cur Laser Input Optical Power", "dBm"),
        211: ("Min Laser Input Optical Power", "dBm"),
        212: ("Max Laser Input Optical Power", "dBm"),
        213: ("Cur Laser Output Optical Power", "dBm"),
        214: ("Min Laser Output Optical Power", "dBm"),
        215: ("Max Laser Output Optical Power", "dBm"),
    }
    # Common indicator sets
    EML_PM_OPTICAL_DEFAULT = list(range(188, 216))  # 188..215 — optical + temperature + bias
    EML_PM_OPTICAL_POWER_ONLY = [198, 199, 200, 201, 202, 203, 210, 211, 212, 213, 214, 215]
    
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
                resource = elements[0].node_id
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
        ne_res_ids = {ne.node_id for ne in elements if ne.node_id}
        
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
        # Filter alarms where the NE resource (from vendor_specific_info) matches subnet NEs
        subnet_alarms = [a for a in all_alarms
                         if (a.vendor_specific_info or {}).get('resource') in ne_res_ids]
        
        # Apply additional client-side filters
        if filters:
            subnet_alarms = filters.apply(subnet_alarms)
        
        logger.info(f"Retrieved {len(subnet_alarms)} alarms for subnet '{subnet_id}' (filtered from {len(all_alarms)} total)")
        return subnet_alarms
    
    def get_network_elements_by_subnet(
        self,
        subnet_id: str,
        page_size: int = 1000
    ) -> List[NceNode]:
        """
        Get all network elements in a subnet.
        
        Uses server-side filtering via ref-parent-subnet query parameter.
        
        Args:
            subnet_id: Subnet resource ID (ref-parent-subnet).
            page_size: Number of records per page.
        
        Returns:
            List of NceNode objects in the subnet.
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
    ) -> List[NceNode]:
        """
        Get network elements from Huawei NCE.
        
        Args:
            name: Filter by network element name (server-side).
            subnet_id: Filter by subnet ID (server-side, ref-parent-subnet).
            filters: RestNMSDataFilter instance for additional client-side filtering.
            page_size: Number of records per page.
        
        Returns:
            List of NceNode objects.
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
        
        # Convert to NceNode objects
        elements = [NceNode(item) for item in ne_dicts]
        
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
    
    def get_network_element_by_id(self, res_id: str) -> Optional[NceNode]:
        """
        Get a single network element by resource ID.
        
        Args:
            res_id: Resource ID of the network element.
        
        Returns:
            NceNode object or None if not found.
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
                        return NceNode(ne_data)
                    elif isinstance(ne_data, list) and ne_data:
                        return NceNode(ne_data[0])
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
    ) -> List[NceTerminationPoint]:
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
            List of NceTerminationPoint objects.

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

        # Convert to NceTerminationPoint objects
        ports = [NceTerminationPoint(item) for item in ltp_dicts]

        # Apply client-side filters
        if filters:
            ports = filters.apply(ports)

        # Resolve NE names if requested
        if resolve_names:
            self.resolve_port_names(ports)

        logger.info(f"Retrieved {len(ports)} ports")
        return ports

    def get_port_by_id(self, res_id: str) -> Optional[NceTerminationPoint]:
        """
        Get a single port by resource ID.

        Args:
            res_id: Resource ID (UUID) of the port.

        Returns:
            NceTerminationPoint object or None if not found.
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
                        return NceTerminationPoint(ltp_data)
                    elif isinstance(ltp_data, list) and ltp_data:
                        return NceTerminationPoint(ltp_data[0])
        return None

    def resolve_port_names(self, ports: list) -> list:
        """
        Resolve NE UUID to human-readable NE name for port objects.

        Populates the ne_name field on each port object. This method
        mutates the port objects in-place and returns the same list.

        Args:
            ports: List of NceTerminationPoint objects.

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
            port.node_name = ne_cache.get(port.node_id)

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
        cache = {ne.node_id: ne.name for ne in elements if ne.node_id and ne.name}
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
                        if p.tp_id and p.name:
                            cache[p.tp_id] = p.name
                except Exception as e:
                    logger.warning(f"Failed to load ports for NE {ne_id}: {e}")
        else:
            # Bulk loading via get_ports() — all ports at once
            logger.debug(f"Loading ALL ports (bulk mode, {len(ne_ids)} NEs > threshold={PER_NE_THRESHOLD})")
            all_ports = self.get_ports()
            cache = {p.tp_id: p.name for p in all_ports if p.tp_id and p.name}

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
            down_links = [l for l in links if l.oper_status == '1']
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
            if link.source_node:
                ne_ids.add(link.source_node)
            if link.dest_node:
                ne_ids.add(link.dest_node)
            if link.source_tp:
                ltp_ids.add(link.source_tp)
            if link.dest_tp:
                ltp_ids.add(link.dest_tp)

        logger.info(f"Resolving names for {len(links)} links ({len(ne_ids)} unique NEs, {len(ltp_ids)} unique ports)")

        # Step 2: Build NE name cache (single request, ~1-2s)
        ne_cache = self._build_ne_name_cache()

        # Step 3: Build LTP name cache (adaptive: per-NE or bulk, see _build_ltp_name_cache)
        ltp_cache = self._build_ltp_name_cache(ne_ids)

        # Step 4: Populate resolved fields on each link object
        for link in links:
            link.source_node_name = ne_cache.get(link.source_node)
            link.dest_node_name = ne_cache.get(link.dest_node)
            link.source_tp_name = ltp_cache.get(link.source_tp)
            link.dest_tp_name = ltp_cache.get(link.dest_tp)

        resolved_ne = sum(1 for l in links if l.source_node_name or l.dest_node_name)
        resolved_ltp = sum(1 for l in links if l.source_tp_name or l.dest_tp_name)
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
            print(links[0].source_node_name)   # "IPBB_Naryn_NE40E-1"
            print(links[0].source_tp_name)  # "GigabitEthernet1/0/0"

            # Efficient pattern — resolve only filtered subset
            links = provider.get_links()
            down = [l for l in links if l.oper_status == '1']
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

    # ─── Topology Enrichment: high-level query methods ─────────────────

    def get_links_between(
        self,
        name_a: str,
        name_b: str,
        resolve_names: bool = False,
        filters: Optional[RestNMSDataFilter] = None,
    ) -> List[NceLink]:
        """
        Get all links between two network elements (both directions).

        NCE links are directional (a-end -> z-end), so this method queries
        both directions and merges results with deduplication by res_id.

        Uses server-side filters (a-end-ne-id + z-end-ne-id) for efficiency —
        does NOT load all links.

        Args:
            name_a: Name of the first NE (exact match, server-side filter).
            name_b: Name of the second NE (exact match, server-side filter).
            resolve_names: If True, resolves NE and port UUIDs to names.
            filters: RestNMSDataFilter for additional client-side filtering.

        Returns:
            List of NceLink objects representing all links between the two NEs.
            Empty list if either NE is not found or no links exist.

        Performance: ~0.2s (2 targeted API calls, no bulk loading).

        Example:
            links = provider.get_links_between("IPBB_Bostery_NE40E-1", "IPBB_Bostery_NE40E-2")
            # Returns 2 links (e.g. GE1/0/7 <-> GE1/0/7, GE3/0/1 <-> GE3/0/1)
        """
        # Resolve NE names to res_ids
        nes_a = self.get_network_elements(name=name_a)
        nes_b = self.get_network_elements(name=name_b)
        if not nes_a or not nes_b:
            logger.warning(f"NE not found: {'name_a' if not nes_a else 'name_b'}")
            return []

        id_a = nes_a[0].node_id
        id_b = nes_b[0].node_id

        # Query both directions (NCE links are directional: a-end -> z-end)
        links_ab = self.get_links(a_end_ne_id=id_a, z_end_ne_id=id_b,
                                   resolve_names=resolve_names, filters=filters)
        links_ba = self.get_links(a_end_ne_id=id_b, z_end_ne_id=id_a,
                                   resolve_names=resolve_names, filters=filters)

        # Deduplicate by res_id (shouldn't overlap, but just in case)
        seen = {l.link_id for l in links_ab}
        for l in links_ba:
            if l.link_id not in seen:
                links_ab.append(l)
                seen.add(l.link_id)

        logger.info(f"Links between '{name_a}' and '{name_b}': {len(links_ab)}")
        return links_ab

    def get_neighbors(
        self,
        name: str,
        resolve_names: bool = False,
        filters: Optional[RestNMSDataFilter] = None,
    ) -> List[dict]:
        """
        Get all neighbors of a network element with their connecting links.

        Queries links in both directions (NE as a-end and z-end) and groups
        results by neighbor NE. Uses server-side NE ID filter.

        Args:
            name: NE name (exact match, server-side filter).
            resolve_names: If True, resolves NE and port UUIDs to names.
            filters: RestNMSDataFilter for additional client-side filtering.

        Returns:
            List of dicts, each representing a neighbor:
            [
                {
                    "ne_id": "uuid-of-neighbor",
                    "ne_name": "NeighborName" or None,
                    "links": [NceLink, ...]  # all links to this neighbor
                },
                ...
            ]
            Empty list if NE not found or has no links.

        Performance: ~0.3s (2 targeted API calls + optional name resolve).

        Example:
            neighbors = provider.get_neighbors("IPBB_Bostery_NE40E-2", resolve_names=True)
            for n in neighbors:
                print(f"{n['ne_name']}: {len(n['links'])} links")
        """
        nes = self.get_network_elements(name=name)
        if not nes:
            logger.warning(f"NE '{name}' not found")
            return []

        ne_id = nes[0].node_id

        # Get all links where this NE is source or sink
        links_out = self.get_links(a_end_ne_id=ne_id, resolve_names=resolve_names, filters=filters)
        links_in = self.get_links(z_end_ne_id=ne_id, resolve_names=resolve_names, filters=filters)

        # Merge and deduplicate
        all_links = list(links_out)
        seen = {l.link_id for l in all_links}
        for l in links_in:
            if l.link_id not in seen:
                all_links.append(l)
                seen.add(l.link_id)

        # Group by neighbor NE
        # For each link, the neighbor is the "other end"
        neighbors_map: Dict[str, dict] = {}
        for link in all_links:
            if link.source_node == ne_id:
                neighbor_id = link.dest_node
                neighbor_name = link.dest_node_name
            else:
                neighbor_id = link.source_node
                neighbor_name = link.source_node_name

            if neighbor_id not in neighbors_map:
                neighbors_map[neighbor_id] = {
                    'ne_id': neighbor_id,
                    'ne_name': neighbor_name,
                    'links': []
                }
            neighbors_map[neighbor_id]['links'].append(link)

        result = list(neighbors_map.values())
        logger.info(f"Neighbors of '{name}': {len(result)} NEs, {len(all_links)} links total")
        return result

    def get_links_by_subnet(
        self,
        subnet_name_or_id: str,
        resolve_names: bool = False,
        filters: Optional[RestNMSDataFilter] = None,
    ) -> List[NceLink]:
        """
        Get all links within a subnet (both ends belong to NEs in the subnet).

        Approach:
        1. Resolve subnet name -> subnet_id (if name given)
        2. Get all NEs in subnet (server-side filter: ref-parent-subnet)
        3. Get all links (paginated)
        4. Client-side filter: keep only links where BOTH a-end and z-end NEs
           are in the subnet

        Note: NCE does NOT support server-side link filtering by subnet.
        All links are loaded once and filtered in memory.

        Args:
            subnet_name_or_id: Subnet name (e.g. "IP Domain", "DWDM", "Osh")
                               or subnet res-id UUID.
            resolve_names: If True, resolves NE and port UUIDs to names.
            filters: RestNMSDataFilter for additional client-side filtering.

        Returns:
            List of NceLink objects where both ends are in the subnet.

        Available subnets (real data):
            IP Domain: 111 NEs, DWDM: 62, Osh: 31, SDH: 20,
            Issyk-Kul_Naryn: 8, OMC_SWITCH: 7, South: 4

        Performance: ~2-60s depending on resolve_names (link loading is ~2s).

        Example:
            links = provider.get_links_by_subnet("IP Domain", resolve_names=True)
            print(f"Links in IP Domain: {len(links)}")
        """
        # Resolve subnet name to ID
        subnet = self.get_subnet_by_name(subnet_name_or_id)
        if subnet:
            subnet_id = subnet.get('res-id')
        else:
            # Assume it's a direct subnet_id
            subnet_id = subnet_name_or_id

        # Get all NEs in this subnet (server-side filter)
        subnet_nes = self.get_network_elements(subnet_id=subnet_id)
        if not subnet_nes:
            logger.warning(f"No NEs found in subnet '{subnet_name_or_id}'")
            return []

        ne_ids = {ne.node_id for ne in subnet_nes}
        logger.info(f"Subnet '{subnet_name_or_id}': {len(ne_ids)} NEs")

        # Get all links and filter by subnet NEs (both ends must be in subnet)
        all_links = self.get_links(resolve_names=resolve_names, filters=filters)
        subnet_links = [l for l in all_links
                        if l.source_node in ne_ids and l.dest_node in ne_ids]

        logger.info(f"Links in subnet '{subnet_name_or_id}': {len(subnet_links)} (from {len(all_links)} total)")
        return subnet_links

    def get_ports_by_ip(
        self,
        ipv4: str,
        ne_id: Optional[str] = None,
    ) -> List[NceTerminationPoint]:
        """
        Find port(s) by IPv4 address.

        NCE does NOT support server-side IP filtering on ports. This method
        loads ports and filters by addrv4 on the client side.

        If ne_id is provided, only that NE's ports are loaded (~0.12s).
        If ne_id is NOT provided, ALL ports are loaded (~56s for ~88K ports).
        Always provide ne_id when possible for performance.

        Args:
            ipv4: IPv4 address to search for (exact match on addrv4 field).
            ne_id: Optional NE UUID to narrow the search.

        Returns:
            List of NceTerminationPoint objects with matching addrv4.

        Performance:
            - With ne_id: ~0.12s (50-100 ports per NE)
            - Without ne_id: ~56s (loads all ~88K ports)

        Example:
            # Fast: search within a known NE
            ports = provider.get_ports_by_ip("11.110.1.114",
                        ne_id="d0cc81df-b9f9-11ea-ad74-b008759ca76f")

            # Slow: search across all NEs (~56s)
            ports = provider.get_ports_by_ip("11.110.1.114")
        """
        if ne_id:
            ports = self.get_ports(ne_id=ne_id)
        else:
            logger.warning("get_ports_by_ip without ne_id loads ALL ports (~56s). "
                           "Provide ne_id for better performance.")
            ports = self.get_ports()

        matching = [p for p in ports if p.ipv4_address == ipv4]
        logger.info(f"Ports with IP {ipv4}: {len(matching)} (searched {len(ports)} ports)")
        return matching

    def get_trunk_members(self, port: NceTerminationPoint) -> List[NceTerminationPoint]:
        """
        Get physical member ports of an Eth-Trunk (LAG) interface.

        Eth-Trunk is a logical aggregation of multiple physical ports.
        Member ports reference their trunk via the trunk_ltp_id field:
            member.trunk_ltp_id == trunk.tp_id

        If the port is already physical (is_physical=True), returns empty list.

        Args:
            port: NceTerminationPoint object (typically an Eth-Trunk).

        Returns:
            List of NceTerminationPoint objects — the physical member ports.
            Empty list if port is physical or has no members.

        Performance: ~0.12s (loads ports for the NE via ne-id server-side filter).

        Example:
            trunk = provider.get_ports_by_ip("11.110.1.116", ne_id="...")[0]
            # trunk.name = "Eth-Trunk4", trunk.is_physical = False
            members = provider.get_trunk_members(trunk)
            # [GE6/1/0 (10G Fiber), GE6/1/1, GE6/1/2, GE6/1/3]
        """
        if port.is_physical:
            return []

        if not port.node_id or not port.tp_id:
            return []

        # Load all ports for this NE (server-side ne-id filter)
        ne_ports = self.get_ports(ne_id=port.node_id)

        # Filter: member ports whose trunk_ltp_id points to this port
        members = [p for p in ne_ports if p.trunk_ltp_id == port.tp_id]
        logger.info(f"Trunk members of '{port.name}': {len(members)}")
        return members

    def get_physical_ports_by_ip(
        self,
        ipv4: str,
        ne_id: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Find physical port(s) by IPv4 address, expanding Eth-Trunk if needed.

        Unified method that handles both cases:
        - Regular physical port (e.g. GigabitEthernet1/0/0 with IP):
          Returns the port itself as the only physical port.
        - Eth-Trunk with IP: Returns the trunk + its physical member ports.

        The result always has the same structure regardless of port type.

        Args:
            ipv4: IPv4 address to search for.
            ne_id: Optional NE UUID for fast lookup (~0.12s).
                   Without ne_id, loads ALL ports (~56s).

        Returns:
            Dict with unified structure, or None if IP not found:
            {
                "port": NceTerminationPoint,             # the port that holds the IP
                "physical_ports": [NceTerminationPoint], # physical port(s)
                "is_trunk": bool,            # True if Eth-Trunk
            }

            For regular port: physical_ports = [port itself]
            For Eth-Trunk:    physical_ports = [member1, member2, ...]

        Performance:
            - With ne_id: ~0.12-0.25s
            - Without ne_id: ~56s (bulk port loading)

        Example:
            # Regular port
            result = provider.get_physical_ports_by_ip("11.110.1.114", ne_id="...")
            # result["port"].name = "GigabitEthernet1/0/0"
            # result["is_trunk"] = False
            # result["physical_ports"] = [GigabitEthernet1/0/0]  (1 port)

            # Eth-Trunk
            result = provider.get_physical_ports_by_ip("11.110.1.116", ne_id="...")
            # result["port"].name = "Eth-Trunk4"
            # result["is_trunk"] = True
            # result["physical_ports"] = [GE6/1/0, GE6/1/1, GE6/1/2, GE6/1/3]
        """
        ports = self.get_ports_by_ip(ipv4, ne_id=ne_id)
        if not ports:
            return None

        port = ports[0]

        if port.is_physical:
            # Regular physical port — it IS the physical port
            return {
                'port': port,
                'physical_ports': [port],
                'is_trunk': False,
            }
        else:
            # Logical port (Eth-Trunk or other) — find physical members
            members = self.get_trunk_members(port)
            return {
                'port': port,
                'physical_ports': members,
                'is_trunk': len(members) > 0,
            }

    def get_alarms_for_link(
        self,
        link: NceLink,
        is_cleared: Optional[bool] = None,
    ) -> List[NceAlarm]:
        """
        Get alarms associated with a link's NEs.

        Fetches alarms for both NEs of the link (a-end and z-end) using
        server-side resource filter for efficiency.

        The returned alarms include all alarms for both NEs, not just
        port-specific ones. To further filter by port name, check
        alarm.affected_object for the port name string.

        Common alarm types seen on down links:
        - "Link Down" (critical) — contains port name in affected_object
        - "The physical port is Down" (critical)
        - "The state of the OSPF interface changed" (major)
        - "BFD session change to fault down state" (major)
        - "Optical Invalid" / "Input optical power is too low"

        Args:
            link: NceLink object (must have a_end_ne_id and z_end_ne_id).
            is_cleared: Filter by alarm cleared status.
                        True: only cleared alarms.
                        False: only active alarms.
                        None: all alarms.

        Returns:
            List of NceAlarm objects for both NEs of the link.

        Performance: ~1-2s (2 server-side filtered alarm queries).

        Example:
            down_links = [l for l in links if l.oper_status == '1']
            if down_links:
                alarms = provider.get_alarms_for_link(down_links[0], is_cleared=False)
                for a in alarms:
                    print(f"{a.ne_name} | {a.severity} | {a.alarm_name}")
        """
        alarms = []

        if link.source_node:
            alarms_a = self.get_alarms(resource=link.source_node, is_cleared=is_cleared)
            alarms.extend(alarms_a)

        if link.dest_node:
            alarms_z = self.get_alarms(resource=link.dest_node, is_cleared=is_cleared)
            alarms.extend(alarms_z)

        logger.info(f"Alarms for link '{link.name}': {len(alarms)} "
                     f"(A-end: {len(alarms_a) if link.source_node else 0}, "
                     f"Z-end: {len(alarms_z) if link.dest_node else 0})")
        return alarms

    # ─── Performance Monitoring (DWDM Optical Power) ──────────────────

    def create_pm_task(
        self,
        tp_id: str,
        indicators: List[str],
        res_type: str = 'ltp',
        period: str = 'per15min',
        task_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create a Performance Monitoring task for a port or board.

        PM tasks must be created before querying realtime or historical PM data.
        Uses Vendor Specific Raw PM API (huawei-nce-common-pm-rawdata).

        Note:
            This API only works on OCH ports of OptiX OSN 9800 M24
            (U5N402 boards). For optical power on ALL DWDM port types
            (amplifiers, FIU, OAU, AST2, etc.) without task creation,
            use get_eml_pm_for_board() / get_eml_pm_for_ne() instead.

        Args:
            tp_id: Resource UUID — port tp_id (for optical power) or
                   board card-id (for temperature/CPU).
            indicators: List of indicator names to monitor. Examples:
                Optical: ["Cur Total Input Optical Power", "Cur Total Output Optical Power"]
                Signal:  ["Average ESNR", "Q Value", "Pre-FEC BER"]
                Health:  ["Temperature", "Bias Current", "Voltage"]
                Board:   ["Temperature", "Current CPU Usage"]
            res_type: Resource type — "ltp" for ports, "card" for boards.
            period: Collection period. Values: "per15min" (default), "per5min",
                    "hourly", "daily", etc.
            task_name: Optional descriptive name. Auto-generated if not provided.

        Returns:
            task_id (str) on success, None on failure.

        Performance: ~0.5s

        Example:
            task_id = provider.create_pm_task(
                "50f03c06-c1a4-11ea-9050-b008759ca873",
                ["Cur Total Input Optical Power", "Temperature"]
            )
            # Then query: provider.get_realtime_pm(["50f03c06-..."])
        """
        import uuid
        task_id = str(uuid.uuid4())
        if not task_name:
            task_name = f"pynetcom-pm-{res_type}-{tp_id[:8]}"

        body = {
            "huawei-nce-common-pm-rawdata:input": {
                "monitor-tasks": [{
                    "task-id": task_id,
                    "task-name": task_name,
                    "res-type-name": res_type,
                    "res-id": tp_id,
                    "task-cfg": {
                        "period": period,
                        "indicators": {
                            "indicator": [{"indicator-id": ind} for ind in indicators]
                        }
                    }
                }]
            }
        }

        result = self.client.send_post_request(self.PM_CREATE_URL, body)
        if not result or result is False:
            logger.error(f"Failed to create PM task for {tp_id}")
            return None

        # Check for errors in response
        errors = result.get('errors', result.get('ietf-restconf:errors'))
        if errors:
            err_msg = str(errors)[:200]
            logger.error(f"PM task creation error: {err_msg}")
            return None

        logger.info(f"Created PM task {task_id} for {res_type} {tp_id}")
        return task_id

    def get_realtime_pm(self, tp_ids: List[str]) -> List[dict]:
        """
        Query realtime Performance Monitoring data for ports or boards.

        Returns current PM values (optical power, temperature, etc.).
        PM task must be created first via create_pm_task().

        Args:
            tp_ids: List of resource UUIDs (max 10). Port tp_id or board card-id.

        Returns:
            List of dicts, each containing:
            {
                "res_id": "uuid",
                "res_name": "DWDM-Node-Shelf0-3-U5N402-1-OCH:1",
                "device_name": "DWDM-Node-01",
                "collect_time": "2026-04-08T11:00:00.000Z",
                "indicators": [
                    {"id": "Cur Total Input Optical Power", "value": -10.8, "unit": "dBm"},
                    {"id": "Temperature", "value": 61.6, "unit": "Celsius"}
                ]
            }
            Empty list if no PM data available.

        Example:
            pm = provider.get_realtime_pm(["50f03c06-c1a4-..."])
            for record in pm:
                for ind in record["indicators"]:
                    print(f"{ind['id']}: {ind['value']} {ind['unit']}")
        """
        body = {"huawei-nce-common-pm-rawdata:input": {"res-ids": tp_ids}}
        result = self.client.send_post_request(self.PM_REALTIME_URL, body)
        return self._parse_pm_response(result)

    def get_historical_pm(
        self,
        tp_ids: List[str],
        period: str = 'per15min',
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[dict]:
        """
        Query historical Performance Monitoring data.

        Args:
            tp_ids: Resource UUIDs (max 10).
            period: "per15min" (max 1 day range) or "daily" (max 1 month range).
            start_time: Start of query period (UTC).
            end_time: End of query period (UTC).

        Returns:
            Same format as get_realtime_pm(), but may contain multiple
            records per resource (one per collection interval).
        """
        body = {"huawei-nce-common-pm-rawdata:input": {
            "res-ids": tp_ids,
            "period": period,
            "start-time": self._format_datetime_for_api(start_time) if start_time else None,
            "end-time": self._format_datetime_for_api(end_time) if end_time else None,
        }}
        # Remove None values
        inp = body["huawei-nce-common-pm-rawdata:input"]
        body["huawei-nce-common-pm-rawdata:input"] = {k: v for k, v in inp.items() if v is not None}

        result = self.client.send_post_request(self.PM_HISTORICAL_URL, body)
        return self._parse_pm_response(result)

    def get_pm_tasks(self, tp_ids: List[str]) -> List[dict]:
        """
        Query existing PM monitoring tasks for resources.

        Args:
            tp_ids: Resource UUIDs to check for PM tasks.

        Returns:
            List of task dicts: [{task_id, task_name, task_status, res_type, res_id}]
        """
        body = {"huawei-nce-common-pm-rawdata:input": {"res-ids": tp_ids}}
        result = self.client.send_post_request(self.PM_QUERY_TASKS_URL, body)
        if not result or isinstance(result, bool):
            return []
        tasks = result.get('huawei-nce-common-pm-rawdata:output', {}).get('monitor-task', [])
        return [{
            'task_id': t.get('task-id'),
            'task_name': t.get('task-name'),
            'task_status': t.get('task-status'),
            'res_type': t.get('res-type-name'),
            'res_id': t.get('res-id'),
        } for t in tasks]

    def get_pm_tasks_for_ne(self, ne_name: str) -> List[dict]:
        """
        Get all existing PM tasks for a network element.

        Automatically fetches NE ports and queries PM tasks in batches of 100.

        Args:
            ne_name: NE name.

        Returns:
            List of PM task dicts (same as get_pm_tasks).
        """
        nes = self.get_network_elements(name=ne_name)
        if not nes:
            return []
        ports = self.get_ports(ne_id=nes[0].node_id)
        if not ports:
            return []

        all_tasks = []
        tp_ids = [p.tp_id for p in ports if p.tp_id]
        # Query in batches of 100
        for i in range(0, len(tp_ids), 100):
            batch = tp_ids[i:i+100]
            tasks = self.get_pm_tasks(batch)
            all_tasks.extend(tasks)

        logger.info(f"PM tasks for NE '{ne_name}': {len(all_tasks)}")
        return all_tasks

    def delete_pm_tasks(self, task_ids: List[str]) -> bool:
        """
        Delete PM monitoring tasks.

        Args:
            task_ids: List of task UUIDs to delete.

        Returns:
            True on success.
        """
        body = {
            "huawei-nce-common-pm-rawdata:input": {
                "task-ids": task_ids
            }
        }
        result = self.client.send_post_request(self.PM_DELETE_TASKS_URL, body)
        if result and not result.get('errors'):
            logger.info(f"Deleted {len(task_ids)} PM tasks")
            return True
        return False

    def _parse_pm_response(self, result) -> List[dict]:
        """Parse PM API response into clean list of dicts."""
        if not result or isinstance(result, bool):
            return []
        if result.get('errors') or result.get('ietf-restconf:errors'):
            return []
        pm_data = (result.get('huawei-nce-common-pm-rawdata:output', {})
                   .get('pm-datas', {}).get('pm-data', []))
        if not pm_data:
            return []
        parsed = []
        for pm in pm_data:
            indicators = []
            for ind in pm.get('indicator-datas', {}).get('indicator-data', []):
                value = ind.get('indicator-double-value',
                        ind.get('indicator-integer-value',
                        ind.get('indicator-string-value')))
                indicators.append({
                    'id': ind.get('indicator-id'),
                    'value': value,
                    'unit': ind.get('indicator-value-unit', ''),
                })
            parsed.append({
                'res_id': pm.get('res-id'),
                'res_name': pm.get('res-name'),
                'device_name': pm.get('device-name'),
                'collect_time': pm.get('collect-time'),
                'indicators': indicators,
            })
        return parsed

    # ─── EML Performance Service (works on ALL DWDM port types) ────────

    def get_eml_pm_for_board(
        self,
        ne_physical_id: int,
        shelf: int,
        slot: int,
        ports: List[int],
        indicators: Optional[List[int]] = None,
        granularity: str = '15min',
        sub_card_id: int = 1,
    ) -> Dict[int, Dict[int, Tuple[str, str]]]:
        """
        Query EML Performance Service current PM data for a single board.

        Uses /rest/emlperfservice/v1/trans/querycurdata — works on ALL DWDM
        boards (OCH, WDM, OTS, OMS, OAU, AST2, FIU) WITHOUT requiring PM tasks
        or PM license. Returns the same data shown in NCE GUI WDM Performance.

        Recommended approach for DWDM optical power monitoring:
            1. get_eml_pm_for_board() / get_eml_pm_for_ne() — current levels
            2. get_reference_power() — baseline expected levels
            3. get_optical_power_thresholds() — alarm thresholds
        These three methods provide complete optical health assessment
        without PM task creation.

        The API requires physical IDs (NOT UUIDs):
          - ne_physical_id: int from ne.vendor_specific_info['physical-id']
          - shelf: from port.vendor_specific_info['frame-number']
          - slot: from port.vendor_specific_info['slot-number']
          - ports: list of port.vendor_specific_info['port-number']

        Constraints (enforced by NCE):
          - One board per request (this method's design)
          - granularity: only "15min" or "24hour"
          - indicators must be non-empty
          - Max ~200 indicators per HTTP request (auto-chunked)

        Args:
            ne_physical_id: Physical NE ID (int).
            shelf: Shelf/frame number (usually 0).
            slot: Board slot number.
            ports: List of physical port numbers to query.
            indicators: List of pmParameterIds (NCE-internal codes).
                Defaults to EML_PM_OPTICAL_DEFAULT (188-215).
                See EML_PM_INDICATORS for known IDs.
            granularity: '15min' (default) or '24hour'.
            sub_card_id: Subboard ID, usually 1 (any value works).

        Returns:
            dict: {port_number: {param_id: (value_str, unit_str)}}
            Empty dict if board not found or no PM data available.

        Example:
            # Sarysogot AST2 board (slot 4), ports 1 and 2 (Gazprom/Karakul)
            pm = provider.get_eml_pm_for_board(638829, 0, 4, [1, 2])
            for port_num, params in pm.items():
                input_power = params.get(201)  # LSIOPCUR
                if input_power:
                    print(f"Port {port_num}: input={input_power[0]} {input_power[1]}")
            # Output:
            #   Port 1: input=-18.00 dBm
            #   Port 2: input=-35.20 dBm
        """
        if indicators is None:
            indicators = list(self.EML_PM_OPTICAL_DEFAULT)
        if not ports:
            return {}

        # Chunk indicators if too many (HTTP 413 limit ~200)
        CHUNK_SIZE = 180
        chunks = [indicators[i:i + CHUNK_SIZE] for i in range(0, len(indicators), CHUNK_SIZE)]

        merged: Dict[int, Dict[int, Tuple[str, str]]] = {}

        for chunk in chunks:
            body = {
                "monitoringObjects": {
                    "neId": int(ne_physical_id),
                    "shelfId": int(shelf),
                    "boardId": int(slot),
                    "subCardId": int(sub_card_id),
                    "physicalPortId": [int(p) for p in ports],
                },
                "granularitys": granularity,
                "pmParameterIds": chunk,
            }

            result = self.client.send_post_request(self.EML_PM_CUR_URL, body)
            if not result or isinstance(result, bool):
                continue

            ec = result.get('errorCode')
            if ec != 0:
                logger.debug(
                    f"EML PM error for ne={ne_physical_id} shelf={shelf} slot={slot}: "
                    f"errorCode={ec} msg={result.get('errorMessage', '')}"
                )
                continue

            # pmStartTime=0 means board not found at this shelf/slot
            if not result.get('pmStartTime'):
                continue

            for port_data in result.get('physicalPort', []):
                port_id = port_data.get('physicalPortID')
                if port_id is None:
                    continue
                merged.setdefault(port_id, {})
                for d in port_data.get('listPMData', []):
                    param_id = d.get('pmParameterId')
                    value = d.get('value', '')
                    unit = d.get('unit', '')
                    if param_id is not None:
                        merged[port_id][param_id] = (value, unit)

        return merged

    def get_eml_pm_for_ports(
        self,
        ports: List['NceTerminationPoint'],
        ne_physical_id: int,
        indicators: Optional[List[int]] = None,
        granularity: str = '15min',
    ) -> Dict[str, Dict[int, Tuple[str, str]]]:
        """
        Query EML PM for a specific list of ports (must all be from one NE).

        Convenience wrapper that:
        - Groups ports by board (frame-number, slot-number) automatically
        - Issues one EML query per (shelf, slot) combination
        - Maps results back to port tp_ids (UUIDs) for easy lookup

        Args:
            ports: List of NceTerminationPoint objects from the same NE.
                   Each port must have frame-number, slot-number, port-number
                   in vendor_specific_info.
            ne_physical_id: Physical ID of the NE these ports belong to.
            indicators: List of pmParameterIds. Defaults to EML_PM_OPTICAL_DEFAULT.
            granularity: '15min' or '24hour'.

        Returns:
            dict: {tp_id (UUID): {param_id: (value, unit)}}
            Only includes ports for which the API returned data.
        """
        if not ports:
            return {}

        # Group ports by (shelf, slot)
        boards: Dict[Tuple[int, int], List[Tuple[int, str]]] = {}
        for p in ports:
            vsi = p.vendor_specific_info or {}
            shelf = vsi.get('frame-number')
            slot = vsi.get('slot-number')
            port_num = vsi.get('port-number')
            if shelf is None or slot is None or port_num is None:
                continue
            try:
                key = (int(shelf), int(slot))
                boards.setdefault(key, []).append((int(port_num), p.tp_id))
            except (ValueError, TypeError):
                continue

        # Reverse map: (shelf, slot, port_number) -> tp_id
        port_to_tpid: Dict[Tuple[int, int, int], str] = {}
        for (shelf, slot), port_list in boards.items():
            for port_num, tp_id in port_list:
                port_to_tpid[(shelf, slot, port_num)] = tp_id

        result: Dict[str, Dict[int, Tuple[str, str]]] = {}

        for (shelf, slot), port_list in boards.items():
            unique_port_nums = sorted({pn for pn, _ in port_list})
            board_pm = self.get_eml_pm_for_board(
                ne_physical_id=ne_physical_id,
                shelf=shelf,
                slot=slot,
                ports=unique_port_nums,
                indicators=indicators,
                granularity=granularity,
            )
            for port_num, params in board_pm.items():
                tp_id = port_to_tpid.get((shelf, slot, port_num))
                if tp_id and params:
                    result[tp_id] = params

        return result

    def get_eml_pm_for_ne(
        self,
        ne: 'NceNode',
        port_filter: Optional[Callable[['NceTerminationPoint'], bool]] = None,
        indicators: Optional[List[int]] = None,
        granularity: str = '15min',
    ) -> Dict[str, Dict[int, Tuple[str, str]]]:
        """
        Query EML PM for all (or filtered) ports on a network element.

        Automatically:
        - Reads physical-id from ne.vendor_specific_info
        - Fetches all ports for the NE
        - Filters to physical ports by default (or use custom filter)
        - Groups by board and queries each board separately

        Args:
            ne: NceNode object (must have physical-id in vendor_specific_info).
            port_filter: Optional callable filter(port) -> bool.
                Default: only physical ports (p.is_physical is True).
                Pass `lambda p: True` to include all ports.
            indicators: List of pmParameterIds. Defaults to EML_PM_OPTICAL_DEFAULT.
            granularity: '15min' or '24hour'.

        Returns:
            dict: {tp_id (UUID): {param_id: (value, unit)}}

        Raises:
            ValueError: if ne has no physical-id (e.g. virtual NE).

        Example:
            ne = provider.get_network_elements(name='Sarysogot')[0]
            pm = provider.get_eml_pm_for_ne(ne)
            for tp_id, params in pm.items():
                input_power = params.get(201)
                if input_power:
                    print(f"Port {tp_id[:8]}: {input_power[0]} {input_power[1]}")
        """
        physical_id = (ne.vendor_specific_info or {}).get('physical-id')
        if physical_id is None:
            raise ValueError(
                f"NE '{ne.name}' has no physical-id; cannot query EML PM. "
                f"Virtual NEs are not supported."
            )

        all_ports = self.get_ports(ne_id=ne.node_id)

        if port_filter is None:
            filtered = [p for p in all_ports if p.is_physical]
        else:
            filtered = [p for p in all_ports if port_filter(p)]

        return self.get_eml_pm_for_ports(
            ports=filtered,
            ne_physical_id=int(physical_id),
            indicators=indicators,
            granularity=granularity,
        )

    # ─── Optical Power Thresholds & Reference ──────────────────────────

    def get_optical_power_thresholds(
        self,
        tp_ids: List[str],
    ) -> Dict[str, dict]:
        """
        Query optical power levels and alarm thresholds for ports.

        Uses ietf-trans-oam:query-optical-power — returns current input/output
        power and configured alarm thresholds in a single call. Auto-batches
        in groups of 20 TPs (API limit).

        No PM task creation needed, works on all active port types.
        Passive boards (FIU) return no data — use the active board tp_id.

        Args:
            tp_ids: List of termination point UUIDs.

        Returns:
            dict: {tp_id: {
                'input_power': float or None,
                'output_power': float or None,
                'input_lower_threshold': float or None,
                'input_upper_threshold': float or None,
                'output_lower_threshold': float or None,
                'output_upper_threshold': float or None,
            }}
            Only includes TPs that returned data.

        Example:
            thresholds = provider.get_optical_power_thresholds([tp1, tp2])
            t = thresholds.get(tp1)
            if t:
                print(f"Input: {t['input_power']} dBm")
                print(f"Alarm range: [{t['input_lower_threshold']}..{t['input_upper_threshold']}]")
        """
        BATCH_SIZE = 20
        result: Dict[str, dict] = {}

        for i in range(0, len(tp_ids), BATCH_SIZE):
            batch = tp_ids[i:i + BATCH_SIZE]
            body = {
                "ietf-trans-oam:input": {
                    "tp-list": [{"tp-id": tp} for tp in batch]
                }
            }
            resp = self.client.send_post_request(self.OPTICAL_POWER_URL, body)
            if not resp or isinstance(resp, bool):
                continue
            for op in (resp.get('ietf-trans-oam:output', {})
                           .get('optical-power', [])):
                tp = op.get('tp-id')
                pw = op.get('optical-power', {})
                if tp:
                    result[tp] = {
                        'input_power': pw.get('input-power'),
                        'output_power': pw.get('output-power'),
                        'input_lower_threshold': pw.get('input-power-lower-threshold'),
                        'input_upper_threshold': pw.get('input-power-upper-threshold'),
                        'output_lower_threshold': pw.get('output-power-lower-threshold'),
                        'output_upper_threshold': pw.get('output-power-upper-threshold'),
                    }

        return result

    def get_reference_power(
        self,
        tp_ids: List[str],
        ne_ids: Dict[str, str],
        network_id: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Query reference (baseline) input power for optical ports.

        Uses ACTN Topology TP endpoint to read the expected input power
        level configured during commissioning. One GET request per TP
        (no batch endpoint available).

        Args:
            tp_ids: List of termination point UUIDs.
            ne_ids: Mapping {tp_id: ne_uuid}. Required to build ACTN URL.
            network_id: ACTN network UUID. Auto-discovered if not provided
                (queries /restconf/v2/data/ietf-network:networks).

        Returns:
            dict: {tp_id: reference_power_float}
            Only includes TPs where reference power is configured.

        Example:
            refs = provider.get_reference_power(
                [tp1, tp2],
                ne_ids={tp1: ne_id, tp2: ne_id}
            )
            if tp1 in refs:
                print(f"Reference: {refs[tp1]} dBm")
        """
        if not tp_ids or not ne_ids:
            return {}

        # Auto-discover ACTN network ID
        if not network_id:
            network_id = self._discover_actn_network_id()
            if not network_id:
                logger.warning("Could not discover ACTN network ID")
                return {}

        result: Dict[str, float] = {}
        seen = set()

        for tp_id in tp_ids:
            if tp_id in seen:
                continue
            seen.add(tp_id)

            ne_id = ne_ids.get(tp_id)
            if not ne_id:
                continue

            url = (f"{self.client.API_NCE_HOST}"
                   f"/restconf/v2/data/ietf-network:networks"
                   f"/network={network_id}"
                   f"/node={ne_id}"
                   f"/ietf-network-topology:termination-point={tp_id}")
            try:
                r = self.client.session.get(
                    url, headers=self.client.header, verify=False)
                if r.status_code != 200:
                    continue
                tps = r.json().get(
                    'ietf-network-topology:termination-point', [])
                if tps:
                    otn = (tps[0].get('ietf-te-topology:te', {})
                                 .get('otn-specific-info', {}))
                    ref = otn.get('input-reference-power')
                    if ref is not None:
                        result[tp_id] = float(ref)
            except Exception:
                continue

        return result

    def _discover_actn_network_id(self) -> Optional[str]:
        """Discover the ACTN network UUID (first available network)."""
        if hasattr(self, '_actn_network_id_cache'):
            return self._actn_network_id_cache

        url = (f"{self.client.API_NCE_HOST}"
               f"{self.ACTN_NETWORKS_URL}"
               f"?limit=5&fields=network-id")
        try:
            r = self.client.session.get(
                url, headers=self.client.header, verify=False)
            if r.status_code == 200:
                nets = (r.json().get('ietf-network:networks', {})
                                .get('network', []))
                if nets:
                    nid = nets[0].get('network-id')
                    self._actn_network_id_cache = nid
                    return nid
        except Exception:
            pass
        return None

