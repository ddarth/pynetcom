"""
Huawei NCE specific data containers.
"""

from typing import Dict, Any, Optional
from datetime import datetime

from pynetcom.utils.helpers.rest_api.data_containers.base import (
    BaseAlarm,
    BaseNetworkElement,
    parse_datetime,
)


class NceAlarm(BaseAlarm):
    """
    Huawei NCE alarm data container.
    
    Extends BaseAlarm with NCE-specific fields.
    Maps kebab-case API field names to snake_case Python attributes.
    
    NCE alarms have nested structure:
    - resource-alarm-parameters
    - x733-alarm-parameters
    - alarm-parameters
    - common-alarm-parameters
    """
    
    # NCE-specific fields
    alarm_serial_number: Optional[str] = None
    reason_id: Optional[int] = None
    resource_url: Optional[str] = None
    resource_id: Optional[str] = None
    product_type: Optional[str] = None
    layer: Optional[str] = None
    repair_action: Optional[str] = None
    ems_time: Optional[datetime] = None
    location_info: Optional[str] = None
    native_probable_cause: Optional[str] = None
    event_type: Optional[str] = None
    alarm_type_qualifier: Optional[str] = None
    alarm_text: Optional[str] = None
    other_info: Optional[str] = None
    tenant_id: Optional[str] = None
    tenant: Optional[str] = None
    ip_address_info: Optional[str] = None
    md_name: Optional[str] = None
    
    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        """Populate fields from NCE API data (nested structure)."""
        
        # Extract nested structures
        resource_params = data.get('resource-alarm-parameters', {})
        x733_params = data.get('x733-alarm-parameters', {})
        alarm_params = data.get('alarm-parameters', {})
        common_params = data.get('common-alarm-parameters', {})
        
        # Common fields
        self.severity = resource_params.get('perceived-severity')
        self.alarm_name = alarm_params.get('alarm-text')  # Use alarm-text as alarm_name
        self.alarm_type = common_params.get('alarm-type-id') or x733_params.get('event-type')
        self.probable_cause = alarm_params.get('probable-cause')
        
        self.ne_name = alarm_params.get('ne-name')
        self.ne_id = common_params.get('resource')
        self.affected_object = common_params.get('resource')
        
        self.acknowledged = data.get('is-acked')
        self.is_cleared = resource_params.get('is-cleared')
        self.root_cause = alarm_params.get('root-cause-identifier')
        
        self.time_created = parse_datetime(data.get('time-created'))
        self.last_changed = parse_datetime(resource_params.get('last-changed'))
        
        self.additional_text = alarm_params.get('other-info')
        
        # NCE-specific fields
        self.alarm_serial_number = alarm_params.get('alarm-serial-number')
        self.reason_id = alarm_params.get('reason-id')
        self.resource_url = common_params.get('resource-url')
        self.resource_id = common_params.get('resource')
        self.product_type = common_params.get('product-type')
        self.layer = common_params.get('layer')
        self.repair_action = alarm_params.get('repair-action')
        self.ems_time = parse_datetime(alarm_params.get('ems-time'))
        self.location_info = alarm_params.get('location-info')
        self.native_probable_cause = alarm_params.get('native-probable-cause')
        self.event_type = x733_params.get('event-type')
        self.alarm_type_qualifier = common_params.get('alarm-type-qualifier')
        self.alarm_text = alarm_params.get('alarm-text')
        self.other_info = alarm_params.get('other-info')
        self.tenant_id = alarm_params.get('tenant-id')
        self.tenant = alarm_params.get('tenant')
        self.ip_address_info = alarm_params.get('ip-address')
        self.md_name = common_params.get('md-name')
    
    def brief(self) -> str:
        """Get brief one-line representation of the alarm."""
        parts = [
            self.ne_name or 'N/A',
            self.severity or 'N/A',
            self.alarm_text or self.alarm_name or 'N/A',
            self.location_info or self.affected_object or 'N/A'
        ]
        return ' | '.join(parts)
    
    def details(self) -> str:
        """Get detailed multi-line representation with NCE-specific fields."""
        lines = [
            "=" * 70,
            f"Huawei NCE Alarm: {self.alarm_text or 'N/A'}",
            "=" * 70,
            f"  Serial Number:        {self.alarm_serial_number or 'N/A'}",
            f"  Severity:             {self.severity or 'N/A'}",
            f"  Event Type:           {self.event_type or 'N/A'}",
            f"  Alarm Type:           {self.alarm_type or 'N/A'}",
            f"  Probable Cause:       {self.probable_cause or 'N/A'}",
            f"  Native Probable Cause:{self.native_probable_cause or 'N/A'}",
            "-" * 70,
            f"  NE Name:              {self.ne_name or 'N/A'}",
            f"  Resource ID:          {self.resource_id or 'N/A'}",
            f"  Resource URL:         {self.resource_url or 'N/A'}",
            f"  Product Type:         {self.product_type or 'N/A'}",
            f"  Layer:                {self.layer or 'N/A'}",
            f"  Location Info:        {self.location_info or 'N/A'}",
            "-" * 70,
            f"  Acknowledged:         {self.acknowledged}",
            f"  Cleared:              {self.is_cleared}",
            f"  Root Cause:           {self.root_cause}",
            "-" * 70,
            f"  Time Created:         {self._format_datetime(self.time_created)}",
            f"  Last Changed:         {self._format_datetime(self.last_changed)}",
            f"  EMS Time:             {self._format_datetime(self.ems_time)}",
            "-" * 70,
            f"  Reason ID:            {self.reason_id}",
            f"  MD Name:              {self.md_name or 'N/A'}",
            f"  Tenant:               {self.tenant or 'N/A'}",
            f"  Repair Action:        {self.repair_action or 'N/A'}",
            "-" * 70,
            f"  Alarm Text:           {self.alarm_text or 'N/A'}",
            f"  Other Info:           {self.other_info or 'N/A'}",
            "=" * 70,
        ]
        return '\n'.join(lines)


class NceNetworkElement(BaseNetworkElement):
    """
    Huawei NCE network element data container.
    
    Extends BaseNetworkElement with NCE-specific fields.
    """
    
    # NCE-specific fields
    res_id: Optional[str] = None
    lsr_id: Optional[str] = None
    dev_sys_name: Optional[str] = None
    physical_id: Optional[int] = None
    as_number: Optional[int] = None
    manufacturer: Optional[str] = None
    product_name: Optional[str] = None
    platform_version: Optional[str] = None
    software_version: Optional[str] = None
    hardware_version: Optional[str] = None
    patch_version: Optional[str] = None
    serial_number: Optional[str] = None
    mac: Optional[str] = None
    location: Optional[str] = None
    remark: Optional[str] = None
    ref_parent_subnet: Optional[str] = None
    communication_state: Optional[str] = None
    admin_status: Optional[str] = None
    is_virtual: Optional[bool] = None
    is_gateway: Optional[int] = None
    container: Optional[bool] = None
    create_time: Optional[datetime] = None
    last_modified: Optional[datetime] = None
    
    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        """Populate fields from NCE API data."""
        
        # Common fields
        self.name = data.get('name')
        self.ip_address = data.get('ip-address')
        self.element_type = data.get('detail-dev-type-name') or data.get('product-name')
        self.managed_state = data.get('admin-status')
        
        # NCE-specific fields
        self.res_id = data.get('res-id')
        self.lsr_id = data.get('lsr-id')
        self.dev_sys_name = data.get('dev-sys-name')
        self.physical_id = data.get('physical-id')
        self.as_number = data.get('as-number')
        self.manufacturer = data.get('manufacturer')
        self.product_name = data.get('product-name')
        self.platform_version = data.get('platform-version')
        self.software_version = data.get('software-version')
        self.hardware_version = data.get('hardware-version')
        self.patch_version = data.get('patch-version')
        self.serial_number = data.get('sn')
        self.mac = data.get('mac')
        self.location = data.get('location')
        self.remark = data.get('remark')
        self.ref_parent_subnet = data.get('ref-parent-subnet')
        self.communication_state = data.get('communication-state')
        self.admin_status = data.get('admin-status')
        self.is_virtual = data.get('is-virtual')
        self.is_gateway = data.get('is-gateway')
        self.container = data.get('container')
        self.create_time = parse_datetime(data.get('create-time'))
        self.last_modified = parse_datetime(data.get('last-modified'))
    
    def details(self) -> str:
        """Get detailed multi-line representation with NCE-specific fields."""
        lines = [
            "=" * 70,
            f"Huawei NCE Network Element: {self.name or 'N/A'}",
            "=" * 70,
            f"  Resource ID:        {self.res_id or 'N/A'}",
            f"  IP Address:         {self.ip_address or 'N/A'}",
            f"  LSR ID:             {self.lsr_id or 'N/A'}",
            f"  Device Sys Name:    {self.dev_sys_name or 'N/A'}",
            f"  MAC:                {self.mac or 'N/A'}",
            "-" * 70,
            f"  Manufacturer:       {self.manufacturer or 'N/A'}",
            f"  Product Name:       {self.product_name or 'N/A'}",
            f"  Hardware Version:   {self.hardware_version or 'N/A'}",
            f"  Software Version:   {self.software_version or 'N/A'}",
            f"  Platform Version:   {self.platform_version or 'N/A'}",
            f"  Patch Version:      {self.patch_version or 'N/A'}",
            f"  Serial Number:      {self.serial_number or 'N/A'}",
            "-" * 70,
            f"  Admin Status:       {self.admin_status or 'N/A'}",
            f"  Communication State:{self.communication_state or 'N/A'}",
            f"  AS Number:          {self.as_number}",
            f"  Is Virtual:         {self.is_virtual}",
            "-" * 70,
            f"  Location:           {self.location or 'N/A'}",
            f"  Remark:             {self.remark or 'N/A'}",
            f"  Parent Subnet:      {self.ref_parent_subnet or 'N/A'}",
            "-" * 70,
            f"  Created:            {self._format_datetime(self.create_time) if hasattr(self, '_format_datetime') else str(self.create_time)}",
            f"  Last Modified:      {self._format_datetime(self.last_modified) if hasattr(self, '_format_datetime') else str(self.last_modified)}",
            "=" * 70,
        ]
        return '\n'.join(lines)
    
    def _format_datetime(self, dt: Optional[datetime]) -> str:
        """Format datetime for display."""
        if dt is None:
            return 'N/A'
        return dt.strftime('%Y-%m-%d %H:%M:%S %Z')

