"""
Nokia NSP specific data containers.
"""

from typing import Dict, Any, Optional
from datetime import datetime

from typing import List

from pynetcom.utils.helpers.rest_api.data_containers.base import (
    BaseAlarm,
    BaseInterface,
    BaseNode,
    parse_datetime,
)


class NspAlarm(BaseAlarm):
    """
    Nokia NSP alarm data container.
    
    Extends BaseAlarm with only common fields.
    All NSP-specific data is stored in vendor_specific_info dict.
    Maps camelCase API field names to snake_case Python attributes.
    """
    
    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        """Populate fields from NSP API data."""
        # Map common BaseAlarm fields
        raw_severity = data.get('severity')
        original_severity = data.get('originalSeverity')
        
        self.alarm_name = data.get('alarmName')
        self.alarm_type = data.get('alarmType')
        self.probable_cause = data.get('probableCause')
        self.ne_name = data.get('neName')
        self.ne_id = data.get('neId')
        self.affected_object = data.get('affectedObject')
        self.acknowledged = data.get('acknowledged')
        self.root_cause = data.get('rootCause')
        self.additional_text = data.get('additionalText')
        
        # Map time fields (per table)
        self.time_created = parse_datetime(data.get('lastTimeDetected'))
        self.last_changed = parse_datetime(data.get('lastTimeSeverityChanged'))
        
        # Map new common fields (per table)
        self.additional_description = data.get('affectedObjectName')
        self.alarm_serial_number = data.get('fdn')
        self.other_info = data.get('objectFullName')
        
        # Determine cleared state and adjust severity for cleared alarms (keep previous logic)
        if (raw_severity or '').lower() == 'cleared':
            self.is_cleared = True
            # Preserve original severity for consumers while flagging cleared
            self.severity = original_severity if original_severity else raw_severity
            # Extract cleared time if alarm is cleared
            self.cleared_time = parse_datetime(data.get('lastTimeCleared'))
        else:
            self.is_cleared = False
            self.severity = raw_severity
            self.cleared_time = None
        
        # Store all Nokia NSP-specific data in vendor_specific_info
        self.vendor_specific_info = {
            # Identifiers
            'fdn': data.get('fdn'),
            'source-type': data.get('sourceType'),
            'source-system': data.get('sourceSystem'),
            
            # Severity tracking
            'previous-severity': data.get('previousSeverity'),
            'original-severity': data.get('originalSeverity'),
            'highest-severity': data.get('highestSeverity'),
            
            # Problem details
            'specific-problem': data.get('specificProblem'),
            'affected-object-type': data.get('affectedObjectType'),
            'affected-object-name': data.get('affectedObjectName'),
            'object-full-name': data.get('objectFullName'),
            
            # Acknowledgement
            'was-acknowledged': data.get('wasAcknowledged'),
            'acknowledged-by': data.get('acknowledgedBy'),
            'cleared-by': data.get('clearedBy'),
            'implicitly-cleared': data.get('implicitlyCleared'),
            
            # Impact
            'service-affecting': data.get('serviceAffecting'),
            'impact': data.get('impact'),
            
            # Timestamps
            'first-time-detected': data.get('firstTimeDetected'),
            'last-time-detected': data.get('lastTimeDetected'),
            'last-time-severity-changed': data.get('lastTimeSeverityChanged'),
            'last-time-cleared': data.get('lastTimeCleared'),
            'last-time-acknowledged': data.get('lastTimeAcknowledged'),
            
            # Occurrence counters
            'number-of-occurrences': data.get('numberOfOccurrences'),
            'number-of-occurrences-since-clear': data.get('numberOfOccurrencesSinceClear'),
            'number-of-occurrences-since-ack': data.get('numberOfOccurrencesSinceAck'),
            
            # Administrative
            'admin-state': data.get('adminState'),
            'user-text': data.get('userText'),
        }
    
    def details(self) -> str:
        """Get detailed multi-line representation with NSP-specific fields from vendor_specific_info."""
        vendor = self.vendor_specific_info or {}
        
        # Helper to parse datetime from vendor_specific_info
        def format_vendor_datetime(key):
            val = vendor.get(key)
            if val:
                dt = parse_datetime(val)
                return self._format_datetime(dt)
            return 'N/A'
        
        lines = [
            "=" * 70,
            f"Nokia NSP Alarm: {self.alarm_name or 'N/A'}",
            "=" * 70,
            f"  Serial Number (FDN):  {self.alarm_serial_number or 'N/A'}",
            f"  Severity:             {self.severity or 'N/A'}",
            f"  Previous Severity:    {vendor.get('previous-severity') or 'N/A'}",
            f"  Original Severity:    {vendor.get('original-severity') or 'N/A'}",
            f"  Highest Severity:     {vendor.get('highest-severity') or 'N/A'}",
            f"  Alarm Type:           {self.alarm_type or 'N/A'}",
            f"  Probable Cause:       {self.probable_cause or 'N/A'}",
            f"  Specific Problem:     {vendor.get('specific-problem') or 'N/A'}",
            "-" * 70,
            f"  NE Name:              {self.ne_name or 'N/A'}",
            f"  NE ID:                {self.ne_id or 'N/A'}",
            f"  Affected Object:      {self.affected_object or 'N/A'}",
            f"  Affected Object Name: {self.additional_description or 'N/A'}",
            f"  Affected Object Type: {vendor.get('affected-object-type') or 'N/A'}",
            "-" * 70,
            f"  Acknowledged:         {self.acknowledged}",
            f"  Was Acknowledged:     {vendor.get('was-acknowledged')}",
            f"  Acknowledged By:      {vendor.get('acknowledged-by') or 'N/A'}",
            f"  Cleared:              {self.is_cleared}",
            f"  Cleared By:           {vendor.get('cleared-by') or 'N/A'}",
            f"  Implicitly Cleared:   {vendor.get('implicitly-cleared')}",
            f"  Root Cause:           {self.root_cause}",
            f"  Service Affecting:    {vendor.get('service-affecting')}",
            "-" * 70,
            f"  Time Created:         {self._format_datetime(self.time_created)}",
            f"  Last Changed:         {self._format_datetime(self.last_changed)}",
            f"  Cleared Time:         {self._format_datetime(self.cleared_time)}",
            f"  First Time Detected:  {format_vendor_datetime('first-time-detected')}",
            f"  Last Time Cleared:    {format_vendor_datetime('last-time-cleared')}",
            "-" * 70,
            f"  Occurrences:          {vendor.get('number-of-occurrences') or 'N/A'}",
            f"  Source Type:          {vendor.get('source-type') or 'N/A'}",
            f"  Admin State:          {vendor.get('admin-state') or 'N/A'}",
            f"  Impact:               {vendor.get('impact') or 'N/A'}",
            "-" * 70,
            f"  Additional Text:      {self.additional_text or 'N/A'}",
            f"  Additional Desc:      {self.additional_description or 'N/A'}",
            f"  User Text:            {vendor.get('user-text') or 'N/A'}",
            f"  Other Info:           {self.other_info or 'N/A'}",
            "=" * 70,
        ]
        return '\n'.join(lines)


class NspNode(BaseNode):
    """
    Nokia NSP network element as RFC 8345 Node.

    API: GET /NetworkSupervision/rest/api/v1/networkElements
    Maps NSP camelCase fields to BaseNode standard fields.
    NSP-specific fields (siteId, clliCode, macAddress, etc.) go to vendor_specific_info.
    """

    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        # BaseNode standard fields
        self.node_id = data.get('neId') or data.get('ipAddress')
        self.name = data.get('name') or data.get('neName')
        self.management_address = data.get('ipAddress')
        self.platform_type = data.get('type')
        self.platform_vendor = 'Nokia'
        self.software_version = data.get('version')
        self.oper_status = data.get('communicationState')
        self.admin_status = data.get('adminState')
        self.topology_group = data.get('topologyGroup')

        # NSP-specific → vendor_specific_info
        self.vendor_specific_info = {
            'fdn': data.get('fdn'),
            'neId': data.get('neId'),
            'product': data.get('product'),
            'managedState': data.get('managedState'),
            'resyncState': data.get('resyncState'),
            'operState': data.get('operState'),
            'standbyState': data.get('standbyState'),
            'networkType': data.get('networkType'),
            'macAddress': data.get('macAddress'),
            'clliCode': data.get('clliCode'),
            'location': data.get('location'),
            'longitude': data.get('longitude'),
            'latitude': data.get('latitude'),
            'sourceType': data.get('sourceType'),
            'sourceSystem': data.get('sourceSystem'),
        }


class NspInterface(BaseInterface):
    """
    Nokia NSP L3 router interface as OpenConfig Interface.

    Source: NETCONF get-config to device at:
        /configure/router[router-name='Base']/interface

    Optionally enriched with state data from NETCONF get:
        /state/router/interface[interface-name='...']/...
        → oper_status, protocols, neighbor IP/MAC

    The data dict passed to __init__ should have keys:
        interface-name, port, ipv4 (with primary.address/prefix-length)
    And optionally (from state):
        oper-state, protocol, neighbor-address, neighbor-mac

    Example:
        iface = NspInterface({
            'interface-name': 'NE1-NE2',
            'port': '1/1/23',
            'ipv4': {'primary': {'address': '172.28.206.133', 'prefix-length': '31'}},
            'oper-state': 'up',
            'protocol': 'ospfv2 mpls rsvp ldp',
            'neighbor-address': '172.28.206.132',
            'neighbor-mac': 'a0:67:d6:87:db:ae',
        })
    """

    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        self.interface_name = data.get('interface-name')

        # Port binding
        port = data.get('port', '')
        self.hardware_port = port
        self.is_lag = port.startswith('lag-') if port else False

        # IPv4 from config: ipv4.primary.address / prefix-length
        ipv4 = data.get('ipv4', {})
        if isinstance(ipv4, dict):
            primary = ipv4.get('primary', {})
            if isinstance(primary, dict):
                self.ipv4_address = primary.get('address')
                pl = primary.get('prefix-length')
                self.ipv4_prefix_length = int(pl) if pl is not None else None

        # State data (optional, from NETCONF get /state/...)
        self.oper_status = data.get('oper-state')
        self.admin_status = data.get('admin-state')

        # MTU from state
        mtu = data.get('oper-ip-mtu')
        self.mtu = int(mtu) if mtu else None

        # Protocols from state (space-separated string)
        proto_str = data.get('protocol', '')
        self.protocols = proto_str.split() if proto_str else None

        # Neighbor from state
        self.neighbor_address = data.get('neighbor-address')
        self.neighbor_mac = data.get('neighbor-mac')

        # QoS and other config → vendor_specific_info
        self.vendor_specific_info = {}
        for key in ('egress', 'ingress', 'ipv4'):
            if key in data:
                self.vendor_specific_info[key] = data[key]

