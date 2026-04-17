"""
Nokia NSP Data Provider.

Provides high-level methods for fetching alarms and network elements
from Nokia NSP with filtering and pagination support.
"""

from typing import Dict, List, Optional
from datetime import datetime
import logging
from urllib.parse import quote

from pynetcom.rest_nsp import RestNSP
from pynetcom.utils.helpers.rest_api.base import RestNMSDataFilter
from pynetcom.utils.helpers.rest_api.data_containers.nokia_nsp import (
    NspAlarm,
    NspInterface,
    NspNode,
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
    
    def _datetime_to_millis(self, dt: datetime) -> int:
        """
        Convert datetime to milliseconds timestamp for NSP API.
        
        NSP API expects lastTimeDetected in milliseconds since Unix epoch (UTC).
        
        Args:
            dt: datetime object. If naive, treated as UTC. If timezone-aware, converted to UTC.
        
        Returns:
            Milliseconds timestamp as integer (UTC+0).
        """
        from datetime import timezone
        
        if dt.tzinfo is not None:
            # Timezone-aware: convert to UTC
            dt_utc = dt.astimezone(timezone.utc)
        else:
            # Naive datetime: treat as UTC by adding UTC timezone
            dt_utc = dt.replace(tzinfo=timezone.utc)
        
        # Convert to milliseconds timestamp (UTC+0)
        return int(dt_utc.timestamp() * 1000)
    
    def _build_alarm_filter(
        self,
        name: Optional[str] = None,
        ne_id: Optional[str] = None,
        is_cleared: Optional[bool] = None,
        severity: Optional[List[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Optional[str]:
        """
        Build NSP alarmFilter query string for server-side filtering.
        
        Args:
            name: Filter by network element name (neName).
            ne_id: Filter by network element ID (neId).
            is_cleared: Filter by cleared status.
            severity: Filter by severity levels (critical, major, minor, warning, cleared).
            start_time: Start time for alarm query (lastTimeDetected >= start_time).
            end_time: End time for alarm query (lastTimeDetected <= end_time).
        
        Returns:
            URL-encoded alarmFilter string or None if no filters.
        
        Example filters:
            severity='major'
            (severity='critical' or severity='major')
            neName='Router1' and severity<>'cleared'
            neName='Router1' and (lastTimeDetected>1765773167000 and lastTimeDetected<1765776767000)
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
        
        # Filter by time range (server-side via lastTimeDetected in milliseconds UTC)
        if start_time is not None or end_time is not None:
            time_conditions = []
            if start_time is not None:
                start_ms = self._datetime_to_millis(start_time)
                time_conditions.append(f"lastTimeDetected>{start_ms}")
            if end_time is not None:
                end_ms = self._datetime_to_millis(end_time)
                time_conditions.append(f"lastTimeDetected<{end_ms}")
            
            # Wrap time conditions in parentheses if both present
            if len(time_conditions) == 2:
                conditions.append(f"({' and '.join(time_conditions)})")
            else:
                conditions.append(time_conditions[0])
        
        if not conditions:
            return None
        
        # Join conditions with AND
        filter_str = ' and '.join(conditions)
        
        # URL encode the filter (double encoding as NSP expects)
        return quote(filter_str, safe='')
    
    def _build_ne_filter(
        self,
        name: Optional[str] = None,
        subnet_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Build NSP filter query string for network elements server-side filtering.
        
        Args:
            name: Filter by network element name.
            subnet_id: Filter by topology group FDN (e.g., 'fdn:realm:sam:topologyGroup:Network-JA').
        
        Returns:
            URL-encoded filter string or None if no filters.
        
        Example filters:
            name='Router1'
            topologyGroup='fdn:realm:sam:topologyGroup:Network-JA'
            name='Router1' and topologyGroup='fdn:realm:sam:topologyGroup:Network-JA'
        """
        conditions = []
        
        # Filter by NE name
        if name:
            conditions.append(f"name='{name}'")
        
        # Filter by topology group (subnet)
        if subnet_id:
            conditions.append(f"topologyGroup='{subnet_id}'")
        
        if not conditions:
            return None
        
        # Join conditions with AND
        filter_str = ' and '.join(conditions)
        
        # URL encode the filter
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
            start_time: Start time for alarm query period (lastTimeDetected). Server-side filtering.
                        Naive datetime treated as UTC, timezone-aware converted to UTC.
            end_time: End time for alarm query period (lastTimeDetected). Server-side filtering.
                      Naive datetime treated as UTC, timezone-aware converted to UTC.
            filters: RestNMSDataFilter instance for additional client-side filtering.
            page_size: Number of records per page (default 1000).
        
        Returns:
            List of NspAlarm objects.
        
        Note:
            - All filters (name, ne_id, is_cleared, severity, start_time, end_time) are 
              applied server-side via alarmFilter for maximum efficiency
            - Additional client-side filtering available via filters parameter
        """
        # Build server-side alarm filter including time range
        alarm_filter = self._build_alarm_filter(
            name=name,
            ne_id=ne_id,
            is_cleared=is_cleared,
            severity=severity,
            start_time=start_time,
            end_time=end_time
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
        subnet_id: Optional[str] = None,
        filters: Optional[RestNMSDataFilter] = None,
        page_size: int = 1000
    ) -> List[NspNode]:
        """
        Get network elements from Nokia NSP.
        
        Args:
            name: Filter by network element name (server-side filtering).
            subnet_id: Filter by topology group FDN (server-side filtering).
                       Example: 'fdn:realm:sam:topologyGroup:Network-JA'
            filters: RestNMSDataFilter instance for additional client-side filtering.
            page_size: Number of records per page.
        
        Returns:
            List of NspNode objects.
        
        Note:
            - name and subnet_id are filtered server-side (more efficient)
            - This API is unified with NceDataProvider.get_network_elements() for consistency
        """
        # Build server-side filter
        ne_filter = self._build_ne_filter(name=name, subnet_id=subnet_id)
        
        # Build URL with filter
        url = self.NETWORK_ELEMENTS_ENDPOINT
        if ne_filter:
            url = f"{url}?filter={ne_filter}"
        
        logger.debug(f"Fetching network elements from: {url}")
        
        original_limit = self.client.limit
        self.client.limit = page_size
        
        try:
            self.client.clear_data()
            self.client.send_request(url)
            raw_data = self.client.get_data()
        finally:
            self.client.limit = original_limit
        
        # Convert to NspNode objects
        elements = [NspNode(item) for item in raw_data]
        
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
    
    def get_subnets(self) -> List[dict]:
        """
        Get all subnets (topology groups) from NSP.
        
        Returns:
            List of subnet dictionaries with 'name' and 'fdn' keys.
            Example: [{'name': 'Network-JA', 'fdn': 'fdn:realm:sam:topologyGroup:Network-JA'}]
        
        Note:
            Nokia NSP doesn't have a dedicated subnets endpoint. This method extracts
            unique topology groups from all network elements.
        """
        logger.debug("Fetching all network elements to extract topology groups")
        
        # Get all network elements
        elements = self.get_network_elements()
        
        # Extract unique topology groups
        topology_groups = set()
        for element in elements:
            if hasattr(element, 'topology_group') and element.topology_group:
                topology_groups.add(element.topology_group)
        
        # Parse FDN to extract subnet names and build result
        subnets = []
        for fdn in sorted(topology_groups):
            # Parse FDN: 'fdn:realm:sam:topologyGroup:Network-JA' -> 'Network-JA'
            if ':topologyGroup:' in fdn:
                name = fdn.split(':topologyGroup:')[-1]
                subnets.append({'name': name, 'fdn': fdn})
            else:
                # Fallback: use full FDN as name if parsing fails
                subnets.append({'name': fdn, 'fdn': fdn})
        
        logger.info(f"Found {len(subnets)} topology groups (subnets)")
        return subnets
    
    def get_subnet_by_name(self, name: str) -> Optional[dict]:
        """
        Find subnet (topology group) by name.
        
        Args:
            name: Subnet name (e.g., 'Network-JA').
        
        Returns:
            Subnet dict {'name': 'Network-JA', 'fdn': 'fdn:realm:sam:topologyGroup:Network-JA'}
            or None if not found.
        """
        subnets = self.get_subnets()
        for subnet in subnets:
            if subnet.get('name') == name:
                return subnet
        return None
    
    def get_network_elements_by_subnet(
        self,
        subnet_id: str,
        page_size: int = 1000
    ) -> List[NspNode]:
        """
        Get network elements in a subnet (server-side filtering).
        
        Args:
            subnet_id: Topology group FDN (e.g., 'fdn:realm:sam:topologyGroup:Network-JA').
            page_size: Number of records per page.
        
        Returns:
            List of NspNode objects in the subnet.
        
        Note:
            This method uses server-side filtering for efficiency.
            Unified API with NceDataProvider.get_network_elements_by_subnet().
        """
        logger.debug(f"Fetching NEs for subnet: {subnet_id}")
        elements = self.get_network_elements(subnet_id=subnet_id, page_size=page_size)
        logger.info(f"Found {len(elements)} NEs in subnet '{subnet_id}'")
        return elements

    # ─── L3 Interfaces via NETCONF ────────────────────────────────────

    def get_interfaces(
        self,
        ne_ip: str,
        netconf_user: str,
        netconf_pass: str,
        router_name: str = 'Base',
        netconf_port: int = 830,
        include_state: bool = False,
        timeout: int = 60,
    ) -> List[NspInterface]:
        """
        Get L3 router interfaces with IPv4 via NETCONF to Nokia SROS device.

        Connects directly to the device (not through NSP) and retrieves
        router interface configuration including port binding and IP address.
        Optionally fetches operational state (oper-status, protocols, neighbor).

        This is the only way to get L3/IP data from Nokia devices when NSP
        does not have NRC/MDM modules activated.

        Source YANG model: nokia-conf:configure/router/interface
        State YANG model: nokia-state:state/router/interface

        Args:
            ne_ip: Device management IP address (from NspNode.management_address).
            netconf_user: NETCONF username (separate from NSP API credentials).
            netconf_pass: NETCONF password.
            router_name: Router instance name (default "Base" = global routing table).
            netconf_port: NETCONF port (default 830).
            include_state: If True, also fetches oper-state, protocols, neighbor
                           for each interface. Adds ~1-2s per interface.
            timeout: NETCONF connection timeout in seconds.

        Returns:
            List of NspInterface objects with OpenConfig-compatible fields:
            - interface_name, hardware_port, is_lag
            - ipv4_address, ipv4_prefix_length
            - oper_status, protocols (if include_state=True)
            - neighbor_address, neighbor_mac (if include_state=True)

        Performance:
            - Config only: ~1-2s per device
            - Config + state: ~3-5s per device (state query per interface)

        Example:
            interfaces = provider.get_interfaces(
                "172.28.205.9", "M2M_user", "M2M_user_123",
                include_state=True
            )
            for iface in interfaces:
                print(f"{iface.interface_name} | {iface.hardware_port} | "
                      f"{iface.ipv4_address}/{iface.ipv4_prefix_length}")
        """
        import xmltodict
        from ncclient import manager

        logger.debug(f"NETCONF connecting to {ne_ip}:{netconf_port}")

        try:
            m = manager.connect(
                host=ne_ip, port=netconf_port,
                username=netconf_user, password=netconf_pass,
                hostkey_verify=False, timeout=timeout,
                device_params={'name': 'default'}
            )
        except Exception as e:
            logger.error(f"NETCONF connection failed to {ne_ip}: {e}")
            return []

        try:
            # Step 1: Get config — interface names, port bindings, IPv4 addresses
            filter_cfg = f"""
<configure xmlns="urn:nokia.com:sros:ns:yang:sr:conf">
  <router>
    <router-name>{router_name}</router-name>
    <interface/>
  </router>
</configure>
"""
            result = m.get_config(source='running', filter=('subtree', filter_cfg))
            data = xmltodict.parse(result.xml)
            router = data.get('rpc-reply', {}).get('data', {}).get('configure', {}).get('router', {})
            raw_interfaces = router.get('interface', [])
            if isinstance(raw_interfaces, dict):
                raw_interfaces = [raw_interfaces]

            interfaces = []
            for raw_iface in raw_interfaces:
                iface_data = dict(raw_iface)

                # Step 2 (optional): Get state for each interface
                if include_state:
                    ifname = iface_data.get('interface-name', '')
                    try:
                        filter_state = f"""
<state xmlns="urn:nokia.com:sros:ns:yang:sr:state">
  <router>
    <router-name>{router_name}</router-name>
    <interface>
      <interface-name>{ifname}</interface-name>
    </interface>
  </router>
</state>
"""
                        state_result = m.get(filter=('subtree', filter_state))
                        state_data = xmltodict.parse(state_result.xml)
                        state_iface = (state_data.get('rpc-reply', {})
                                       .get('data', {}).get('state', {})
                                       .get('router', {}).get('interface', {}))

                        # Merge state into config data
                        iface_data['oper-state'] = state_iface.get('oper-state')
                        iface_data['oper-ip-mtu'] = state_iface.get('oper-ip-mtu')
                        iface_data['protocol'] = state_iface.get('protocol', '')

                        # Extract neighbor from state
                        ipv4_state = state_iface.get('ipv4', {})
                        if isinstance(ipv4_state, dict):
                            nd = ipv4_state.get('neighbor-discovery', {})
                            if isinstance(nd, dict):
                                neighbor = nd.get('neighbor', {})
                                if isinstance(neighbor, dict):
                                    iface_data['neighbor-address'] = neighbor.get('ipv4-address')
                                    iface_data['neighbor-mac'] = neighbor.get('mac-address')
                                elif isinstance(neighbor, list) and neighbor:
                                    iface_data['neighbor-address'] = neighbor[0].get('ipv4-address')
                                    iface_data['neighbor-mac'] = neighbor[0].get('mac-address')
                    except Exception as e:
                        logger.warning(f"Failed to get state for interface '{ifname}': {e}")

                # Set node context
                iface_data['_node_ip'] = ne_ip

                iface = NspInterface(iface_data)
                iface.node_id = ne_ip
                interfaces.append(iface)

            logger.info(f"NETCONF {ne_ip}: {len(interfaces)} router interfaces")
            return interfaces

        except Exception as e:
            logger.error(f"NETCONF error on {ne_ip}: {e}")
            return []
        finally:
            try:
                m.close_session()
            except:
                pass

