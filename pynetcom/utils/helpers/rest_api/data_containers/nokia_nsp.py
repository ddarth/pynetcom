"""
Nokia NSP specific data containers.
"""

from typing import Dict, Any, Optional
from datetime import datetime

from pynetcom.utils.helpers.rest_api.data_containers.base import (
    BaseAlarm,
    BaseNetworkElement,
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
        else:
            self.is_cleared = False
            self.severity = raw_severity
        
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


class NspNetworkElement(BaseNetworkElement):
    """
    Nokia NSP network element data container.
    
    Extends BaseNetworkElement with NSP-specific fields.
    """
    
    # NSP-specific fields
    ne_id: Optional[str] = None
    version: Optional[str] = None
    product: Optional[str] = None
    site_id: Optional[str] = None
    site_name: Optional[str] = None
    deployment_state: Optional[str] = None
    communication_state: Optional[str] = None
    topology_group: Optional[str] = None
    
    # Field mapping: API -> Python
    _field_mapping = {
        'name': 'name',
        'ipAddress': 'ip_address',
        'type': 'element_type',
        'managedState': 'managed_state',
        'neId': 'ne_id',
        'version': 'version',
        'product': 'product',
        'siteId': 'site_id',
        'siteName': 'site_name',
        'deploymentState': 'deployment_state',
        'communicationState': 'communication_state',
        'topologyGroup': 'topology_group',
    }
    
    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        """Populate fields from NSP API data."""
        for api_field, python_field in self._field_mapping.items():
            setattr(self, python_field, data.get(api_field))
    
    def details(self) -> str:
        """Get detailed multi-line representation with NSP-specific fields."""
        lines = [
            "=" * 60,
            f"Nokia NSP Network Element: {self.name or 'N/A'}",
            "=" * 60,
            f"  NE ID:              {self.ne_id or 'N/A'}",
            f"  IP Address:         {self.ip_address or 'N/A'}",
            f"  Type:               {self.element_type or 'N/A'}",
            f"  Product:            {self.product or 'N/A'}",
            f"  Version:            {self.version or 'N/A'}",
            "-" * 60,
            f"  Managed State:      {self.managed_state or 'N/A'}",
            f"  Deployment State:   {self.deployment_state or 'N/A'}",
            f"  Communication State:{self.communication_state or 'N/A'}",
            "-" * 60,
            f"  Topology Group:     {self.topology_group or 'N/A'}",
            f"  Site ID:            {self.site_id or 'N/A'}",
            f"  Site Name:          {self.site_name or 'N/A'}",
            "=" * 60,
        ]
        return '\n'.join(lines)

