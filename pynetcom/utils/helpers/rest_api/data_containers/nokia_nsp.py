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
    
    Extends BaseAlarm with NSP-specific fields.
    Maps camelCase API field names to snake_case Python attributes.
    """
    
    # NSP-specific fields
    fdn: Optional[str] = None
    source_type: Optional[str] = None
    source_system: Optional[str] = None
    previous_severity: Optional[str] = None
    original_severity: Optional[str] = None
    highest_severity: Optional[str] = None
    specific_problem: Optional[str] = None
    affected_object_type: Optional[str] = None
    affected_object_name: Optional[str] = None
    
    was_acknowledged: Optional[bool] = None
    acknowledged_by: Optional[str] = None
    cleared_by: Optional[str] = None
    implicitly_cleared: Optional[bool] = None
    service_affecting: Optional[bool] = None
    
    first_time_detected: Optional[datetime] = None
    last_time_detected: Optional[datetime] = None
    last_time_severity_changed: Optional[datetime] = None
    last_time_cleared: Optional[datetime] = None
    last_time_acknowledged: Optional[datetime] = None
    
    number_of_occurrences: Optional[int] = None
    number_of_occurrences_since_clear: Optional[int] = None
    number_of_occurrences_since_ack: Optional[int] = None
    
    admin_state: Optional[str] = None
    impact: Optional[int] = None
    user_text: Optional[str] = None
    
    # Field mapping: API camelCase -> Python snake_case
    _field_mapping = {
        # Common fields
        'severity': 'severity',
        'alarmName': 'alarm_name',
        'alarmType': 'alarm_type',
        'probableCause': 'probable_cause',
        'neName': 'ne_name',
        'neId': 'ne_id',
        'affectedObject': 'affected_object',
        'acknowledged': 'acknowledged',
        'rootCause': 'root_cause',
        'additionalText': 'additional_text',
        
        # NSP-specific fields
        'fdn': 'fdn',
        'sourceType': 'source_type',
        'sourceSystem': 'source_system',
        'previousSeverity': 'previous_severity',
        'originalSeverity': 'original_severity',
        'highestSeverity': 'highest_severity',
        'specificProblem': 'specific_problem',
        'affectedObjectType': 'affected_object_type',
        'affectedObjectName': 'affected_object_name',
        'wasAcknowledged': 'was_acknowledged',
        'acknowledgedBy': 'acknowledged_by',
        'clearedBy': 'cleared_by',
        'implicitlyCleared': 'implicitly_cleared',
        'serviceAffecting': 'service_affecting',
        'firstTimeDetected': 'first_time_detected',
        'lastTimeDetected': 'last_time_detected',
        'lastTimeSeverityChanged': 'last_time_severity_changed',
        'lastTimeCleared': 'last_time_cleared',
        'lastTimeAcknowledged': 'last_time_acknowledged',
        'numberOfOccurrences': 'number_of_occurrences',
        'numberOfOccurrencesSinceClear': 'number_of_occurrences_since_clear',
        'numberOfOccurrencesSinceAck': 'number_of_occurrences_since_ack',
        'adminState': 'admin_state',
        'impact': 'impact',
        'userText': 'user_text',
    }
    
    # Datetime fields for parsing
    _datetime_fields = {
        'first_time_detected', 'last_time_detected', 'last_time_severity_changed',
        'last_time_cleared', 'last_time_acknowledged', 'time_created', 'last_changed'
    }
    
    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        """Populate fields from NSP API data."""
        for api_field, python_field in self._field_mapping.items():
            value = data.get(api_field)
            if python_field in self._datetime_fields:
                value = parse_datetime(value)
            setattr(self, python_field, value)
        
        # Map time_created and last_changed to NSP-specific fields
        self.time_created = self.first_time_detected
        self.last_changed = self.last_time_detected
        
        # Determine is_cleared from severity
        self.is_cleared = (self.severity or '').lower() == 'cleared'
    
    def details(self) -> str:
        """Get detailed multi-line representation with NSP-specific fields."""
        lines = [
            "=" * 70,
            f"Nokia NSP Alarm: {self.alarm_name or 'N/A'}",
            "=" * 70,
            f"  FDN:                  {self.fdn or 'N/A'}",
            f"  Severity:             {self.severity or 'N/A'}",
            f"  Previous Severity:    {self.previous_severity or 'N/A'}",
            f"  Highest Severity:     {self.highest_severity or 'N/A'}",
            f"  Alarm Type:           {self.alarm_type or 'N/A'}",
            f"  Probable Cause:       {self.probable_cause or 'N/A'}",
            f"  Specific Problem:     {self.specific_problem or 'N/A'}",
            "-" * 70,
            f"  NE Name:              {self.ne_name or 'N/A'}",
            f"  NE ID:                {self.ne_id or 'N/A'}",
            f"  Affected Object:      {self.affected_object or 'N/A'}",
            f"  Affected Object Name: {self.affected_object_name or 'N/A'}",
            f"  Affected Object Type: {self.affected_object_type or 'N/A'}",
            "-" * 70,
            f"  Acknowledged:         {self.acknowledged}",
            f"  Was Acknowledged:     {self.was_acknowledged}",
            f"  Acknowledged By:      {self.acknowledged_by or 'N/A'}",
            f"  Cleared:              {self.is_cleared}",
            f"  Cleared By:           {self.cleared_by or 'N/A'}",
            f"  Implicitly Cleared:   {self.implicitly_cleared}",
            f"  Root Cause:           {self.root_cause}",
            f"  Service Affecting:    {self.service_affecting}",
            "-" * 70,
            f"  First Time Detected:  {self._format_datetime(self.first_time_detected)}",
            f"  Last Time Detected:   {self._format_datetime(self.last_time_detected)}",
            f"  Last Severity Changed:{self._format_datetime(self.last_time_severity_changed)}",
            f"  Last Time Cleared:    {self._format_datetime(self.last_time_cleared)}",
            "-" * 70,
            f"  Occurrences:          {self.number_of_occurrences}",
            f"  Source Type:          {self.source_type or 'N/A'}",
            f"  Admin State:          {self.admin_state or 'N/A'}",
            "-" * 70,
            f"  Additional Text:      {self.additional_text or 'N/A'}",
            f"  User Text:            {self.user_text or 'N/A'}",
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
            f"  Site ID:            {self.site_id or 'N/A'}",
            f"  Site Name:          {self.site_name or 'N/A'}",
            "=" * 60,
        ]
        return '\n'.join(lines)

