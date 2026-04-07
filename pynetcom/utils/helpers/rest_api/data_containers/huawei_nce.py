"""
Huawei NCE specific data containers.
"""

from typing import Dict, Any, Optional
from datetime import datetime

from pynetcom.utils.helpers.rest_api.data_containers.base import (
    BaseAlarm,
    BaseLink,
    BaseNetworkElement,
    BasePort,
    parse_datetime,
)


class NceAlarm(BaseAlarm):
    """
    Huawei NCE alarm data container.
    
    Extends BaseAlarm with only common fields.
    All NCE-specific data is stored in vendor_specific_info dict.
    Maps kebab-case API field names to snake_case Python attributes.
    
    NCE alarms have nested structure:
    - resource-alarm-parameters
    - x733-alarm-parameters
    - alarm-parameters
    - common-alarm-parameters
    """
    
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
        self.probable_cause = alarm_params.get('native-probable-cause')
        self.additional_description = alarm_params.get('probable-cause')
        
        self.ne_name = alarm_params.get('ne-name')
        self.ne_id = alarm_params.get('ip-address')
        self.affected_object = alarm_params.get('location-info')
        
        self.acknowledged = data.get('is-acked')
        self.is_cleared = resource_params.get('is-cleared')
        self.root_cause = alarm_params.get('root-cause-identifier')
        
        self.time_created = parse_datetime(data.get('time-created'))
        self.last_changed = parse_datetime(resource_params.get('last-changed'))
        
        # Extract cleared time if alarm is cleared
        if resource_params.get('is-cleared'):
            status_changes = resource_params.get('status-change', [])
            if status_changes and len(status_changes) > 0:
                self.cleared_time = parse_datetime(status_changes[0].get('time'))
            else:
                self.cleared_time = None
        else:
            self.cleared_time = None
        
        self.additional_text = alarm_params.get('repair-action')
        self.alarm_serial_number = alarm_params.get('alarm-serial-number')
        self.other_info = alarm_params.get('other-info')
        
        # Store all Huawei NCE-specific data in vendor_specific_info
        self.vendor_specific_info = {
            # Resource identifiers
            'resource': common_params.get('resource'),
            'alt-resource': common_params.get('alt-resource'),
            'resource-url': common_params.get('resource-url'),
            'ietf-resource-url': common_params.get('ietf-resource-url'),
            'product-type': common_params.get('product-type'),
            'layer': common_params.get('layer'),
            'md-name': common_params.get('md-name'),
            
            # Alarm details (NCE-specific format)
            'alarm-text': alarm_params.get('alarm-text'),
            'native-probable-cause': alarm_params.get('native-probable-cause'),
            'probable-cause': alarm_params.get('probable-cause'),
            'location-info': alarm_params.get('location-info'),
            'repair-action': alarm_params.get('repair-action'),
            'other-info': alarm_params.get('other-info'),
            'reason-id': alarm_params.get('reason-id'),
            
            # Network element info
            'ip-address': alarm_params.get('ip-address'),
            
            # Organizational
            'tenant': alarm_params.get('tenant'),
            'tenant-id': alarm_params.get('tenant-id'),
            
            # Alarm classification
            'event-type': x733_params.get('event-type'),
            'alarm-type-qualifier': common_params.get('alarm-type-qualifier'),
            
            # Timestamps
            'ems-time': alarm_params.get('ems-time'),
        }
    
    def brief(self) -> str:
        """Get brief one-line representation of the alarm."""
        parts = [
            self.ne_name or 'N/A',
            self.severity or 'N/A',
            self.alarm_name or 'N/A',
            self.affected_object or 'N/A'
        ]
        return ' | '.join(parts)
    
    def details(self) -> str:
        """Get detailed multi-line representation with NCE-specific fields from vendor_specific_info."""
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
            f"Huawei NCE Alarm: {self.alarm_name or 'N/A'}",
            "=" * 70,
            f"  Serial Number:        {self.alarm_serial_number or 'N/A'}",
            f"  Severity:             {self.severity or 'N/A'}",
            f"  Alarm Type:           {self.alarm_type or 'N/A'}",
            f"  Probable Cause:       {self.probable_cause or 'N/A'}",
            f"  Additional Desc:      {self.additional_description or 'N/A'}",
            "-" * 70,
            f"  NE Name:              {self.ne_name or 'N/A'}",
            f"  NE ID (IP):           {self.ne_id or 'N/A'}",
            f"  Affected Object:      {self.affected_object or 'N/A'}",
            f"  Resource:             {vendor.get('resource') or 'N/A'}",
            f"  Resource URL:         {vendor.get('resource-url') or 'N/A'}",
            f"  Product Type:         {vendor.get('product-type') or 'N/A'}",
            f"  Layer:                {vendor.get('layer') or 'N/A'}",
            "-" * 70,
            f"  Acknowledged:         {self.acknowledged}",
            f"  Cleared:              {self.is_cleared}",
            f"  Root Cause:           {self.root_cause}",
            "-" * 70,
            f"  Time Created:         {self._format_datetime(self.time_created)}",
            f"  Last Changed:         {self._format_datetime(self.last_changed)}",
            f"  Cleared Time:         {self._format_datetime(self.cleared_time)}",
            f"  EMS Time:             {format_vendor_datetime('ems-time')}",
            "-" * 70,
            f"  Reason ID:            {vendor.get('reason-id') or 'N/A'}",
            f"  Event Type:           {vendor.get('event-type') or 'N/A'}",
            f"  MD Name:              {vendor.get('md-name') or 'N/A'}",
            f"  Tenant:               {vendor.get('tenant') or 'N/A'}",
            "-" * 70,
            f"  Additional Text:      {self.additional_text or 'N/A'}",
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


class NceLink(BaseLink):
    """
    Huawei NCE link data container.

    Represents physical/logical links including Fiber, L2 Link,
    Microwave Link, Cable, IP Link, etc.
    """

    # NCE-specific fields
    link_type: Optional[str] = None
    direction: Optional[str] = None
    bandwidth: Optional[float] = None
    remaining_up_bandwidth: Optional[float] = None
    remaining_down_bandwidth: Optional[float] = None
    layer_rate: Optional[str] = None
    length: Optional[float] = None
    medium_type: Optional[str] = None
    design_power_loss: Optional[float] = None
    a_end_ip: Optional[str] = None
    z_end_ip: Optional[str] = None
    user_label: Optional[str] = None
    alias: Optional[str] = None
    remark: Optional[str] = None
    ref_srlg_list: Optional[list] = None

    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        """Populate fields from NCE API data."""
        # Common BaseLink fields
        self.res_id = data.get('res-id')
        self.name = data.get('name')
        self.a_end_ne_id = data.get('a-end-ne-id')
        self.z_end_ne_id = data.get('z-end-ne-id')
        self.a_end_ltp_id = data.get('a-end-ltp-id')
        self.z_end_ltp_id = data.get('z-end-ltp-id')
        self.operate_status = data.get('operate-status')
        self.admin_status = data.get('admin-status')

        # NCE-specific fields
        self.link_type = data.get('type')
        self.direction = data.get('direction')
        self.bandwidth = data.get('bandwidth')
        self.remaining_up_bandwidth = data.get('remaining-up-bandwidth')
        self.remaining_down_bandwidth = data.get('remaining-down-bandwidth')
        self.layer_rate = data.get('layer-rate')
        self.length = data.get('length')
        self.medium_type = data.get('medium-type')
        self.design_power_loss = data.get('design-power-loss')
        self.a_end_ip = data.get('a-end-ip')
        self.z_end_ip = data.get('z-end-ip')
        self.user_label = data.get('user-label')
        self.alias = data.get('alias')
        self.remark = data.get('remark')
        self.ref_srlg_list = data.get('ref-srlg-list')

        # Vendor-specific info
        self.vendor_specific_info = {
            'distinguished-name': data.get('distinguished-name'),
            'ref-a-end-ltp-dn': data.get('ref-a-end-ltp-dn'),
            'ref-z-end-ltp-dn': data.get('ref-z-end-ltp-dn'),
            'cross-layer': data.get('cross-layer'),
            'slice-ids': data.get('slice-ids'),
            'delete-time': data.get('delete-time'),
            'delete-date-and-time': data.get('delete-date-and-time'),
        }

    def _format_status(self) -> str:
        """Format operate-status: 0=up, 1=down, else as-is."""
        if self.operate_status == '0':
            return 'up'
        elif self.operate_status == '1':
            return 'down'
        return self.operate_status or 'unknown'

    def brief(self) -> str:
        """
        Get brief one-line representation of the link.

        If resolved names are available (via resolve_names=True or
        resolve_link_names()), shows NE names instead of UUIDs.

        Format with names:  "name | type | NE_A -> NE_Z | status | bandwidth"
        Format without:     "name | type | status | bandwidth"
        """
        bw = f"{self.bandwidth:.0f} kbps" if self.bandwidth is not None else 'N/A'
        parts = [self.name or 'N/A', self.link_type or 'N/A']
        # Show resolved NE names if available
        if self.a_end_ne_name or self.z_end_ne_name:
            parts.append(f"{self.a_end_ne_name or '?'} -> {self.z_end_ne_name or '?'}")
        parts.extend([self._format_status(), bw])
        return ' | '.join(parts)

    def details(self) -> str:
        """
        Get detailed multi-line representation with NCE-specific fields.

        Shows resolved names alongside UUIDs when available.
        Resolved names appear in parentheses after the UUID.
        """
        status = self._format_status()

        # Format NE/port identifiers — show resolved name if available
        a_ne = self.a_end_ne_id or 'N/A'
        if self.a_end_ne_name:
            a_ne = f"{self.a_end_ne_name} ({self.a_end_ne_id})"
        z_ne = self.z_end_ne_id or 'N/A'
        if self.z_end_ne_name:
            z_ne = f"{self.z_end_ne_name} ({self.z_end_ne_id})"
        a_ltp = self.a_end_ltp_id or 'N/A'
        if self.a_end_ltp_name:
            a_ltp = f"{self.a_end_ltp_name} ({self.a_end_ltp_id})"
        z_ltp = self.z_end_ltp_id or 'N/A'
        if self.z_end_ltp_name:
            z_ltp = f"{self.z_end_ltp_name} ({self.z_end_ltp_id})"

        lines = [
            "=" * 70,
            f"Huawei NCE Link: {self.name or 'N/A'}",
            "=" * 70,
            f"  Resource ID:          {self.res_id or 'N/A'}",
            f"  Link Type:            {self.link_type or 'N/A'}",
            f"  Direction:            {self.direction or 'N/A'}",
            f"  Layer Rate:           {self.layer_rate or 'N/A'}",
            "-" * 70,
            f"  A-End NE:             {a_ne}",
            f"  A-End Port:           {a_ltp}",
            f"  A-End IP:             {self.a_end_ip or 'N/A'}",
            f"  Z-End NE:             {z_ne}",
            f"  Z-End Port:           {z_ltp}",
            f"  Z-End IP:             {self.z_end_ip or 'N/A'}",
            "-" * 70,
            f"  Bandwidth:            {f'{self.bandwidth:.0f} kbps' if self.bandwidth is not None else 'N/A'}",
            f"  Remaining Up BW:      {self.remaining_up_bandwidth if self.remaining_up_bandwidth is not None else 'N/A'}",
            f"  Remaining Down BW:    {self.remaining_down_bandwidth if self.remaining_down_bandwidth is not None else 'N/A'}",
            f"  Length:               {self.length if self.length is not None else 'N/A'}",
            f"  Medium Type:          {self.medium_type or 'N/A'}",
            f"  Design Power Loss:    {self.design_power_loss}",
            "-" * 70,
            f"  Operate Status:       {status}",
            f"  Admin Status:         {self.admin_status or 'N/A'}",
            f"  Alias:                {self.alias or 'N/A'}",
            f"  Remark:               {self.remark or 'N/A'}",
            "=" * 70,
        ]
        return '\n'.join(lines)


class NceIgpLink(BaseLink):
    """
    Huawei NCE IGP link data container.

    Represents IGP (OSPF/IS-IS) topology links with TE attributes.
    """

    # IGP-specific fields
    a_end_ipv4: Optional[str] = None
    z_end_ipv4: Optional[str] = None
    a_end_ipv6: Optional[str] = None
    z_end_ipv6: Optional[str] = None
    a_end_ip_mask: Optional[int] = None
    z_end_ip_mask: Optional[int] = None
    a_end_ipv6_router_id: Optional[str] = None
    z_end_ipv6_router_id: Optional[str] = None
    te_metric: Optional[int] = None
    latency: Optional[int] = None
    latency_ipv6: Optional[int] = None
    segment_id: Optional[int] = None
    bandwidth_bc0: Optional[int] = None
    total_available_bandwidth: Optional[int] = None
    max_reserved_bandwidth: Optional[int] = None
    total_reserved_bandwidth: Optional[str] = None
    affinity_group: Optional[int] = None
    srlgs: Optional[str] = None
    is_optimizable: Optional[bool] = None
    priority_bandwidths: Optional[list] = None
    flex_algo_id: Optional[list] = None
    user_defined_constraints: Optional[str] = None
    remark: Optional[str] = None

    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        """Populate fields from NCE IGP link API data."""
        # Common BaseLink fields
        self.res_id = data.get('res-id')
        self.name = data.get('name')
        self.a_end_ne_id = data.get('a-end-ne-id')
        self.z_end_ne_id = data.get('z-end-ne-id')
        self.a_end_ltp_id = data.get('a-end-ltp-id')
        self.z_end_ltp_id = data.get('z-end-ltp-id')
        self.operate_status = data.get('operate-state')
        self.admin_status = data.get('admin-status')

        # IGP-specific fields
        self.a_end_ipv4 = data.get('a-end-ipv4')
        self.z_end_ipv4 = data.get('z-end-ipv4')
        self.a_end_ipv6 = data.get('a-end-ipv6')
        self.z_end_ipv6 = data.get('z-end-ipv6')
        self.a_end_ip_mask = data.get('a-end-ip-mask')
        self.z_end_ip_mask = data.get('z-end-ip-mask')
        self.a_end_ipv6_router_id = data.get('a-end-ipv6-router-id')
        self.z_end_ipv6_router_id = data.get('z-end-ipv6-router-id')
        self.te_metric = data.get('te-metric')
        self.latency = data.get('latency')
        self.latency_ipv6 = data.get('latency-ipv6')
        self.segment_id = data.get('segment-id')
        self.bandwidth_bc0 = data.get('bandwidth-bc0')
        self.total_available_bandwidth = data.get('total-available-bandwidth')
        self.max_reserved_bandwidth = data.get('max-reserved-bandwidth')
        self.total_reserved_bandwidth = data.get('total-reserved-bandwidth')
        self.affinity_group = data.get('affinity-group')
        self.srlgs = data.get('srlgs')
        self.is_optimizable = data.get('is-optimizable')
        self.priority_bandwidths = data.get('priority-bandwidths')
        self.flex_algo_id = data.get('flex-algo-id')
        self.user_defined_constraints = data.get('user-defined-constraints')
        self.remark = data.get('remark')

    def brief(self) -> str:
        """
        Get brief one-line representation of the IGP link.

        Shows resolved NE names if available (via resolve_names=True).
        """
        status = 'up' if self.operate_status == '0' else 'down' if self.operate_status == '1' else self.operate_status or 'N/A'
        parts = [self.name or 'N/A']
        if self.a_end_ne_name or self.z_end_ne_name:
            parts.append(f"{self.a_end_ne_name or '?'} -> {self.z_end_ne_name or '?'}")
        parts.extend([
            f"{self.a_end_ipv4 or 'N/A'} -> {self.z_end_ipv4 or 'N/A'}",
            status,
            f"metric={self.te_metric}",
        ])
        return ' | '.join(parts)

    def details(self) -> str:
        """
        Get detailed multi-line representation with IGP-specific fields.

        Shows resolved names alongside UUIDs when available.
        """
        status = 'up' if self.operate_status == '0' else 'down' if self.operate_status == '1' else self.operate_status or 'N/A'

        a_ne = self.a_end_ne_id or 'N/A'
        if self.a_end_ne_name:
            a_ne = f"{self.a_end_ne_name} ({self.a_end_ne_id})"
        z_ne = self.z_end_ne_id or 'N/A'
        if self.z_end_ne_name:
            z_ne = f"{self.z_end_ne_name} ({self.z_end_ne_id})"
        a_ltp = self.a_end_ltp_id or 'N/A'
        if self.a_end_ltp_name:
            a_ltp = f"{self.a_end_ltp_name} ({self.a_end_ltp_id})"
        z_ltp = self.z_end_ltp_id or 'N/A'
        if self.z_end_ltp_name:
            z_ltp = f"{self.z_end_ltp_name} ({self.z_end_ltp_id})"

        lines = [
            "=" * 70,
            f"Huawei NCE IGP Link: {self.name or 'N/A'}",
            "=" * 70,
            f"  Resource ID:            {self.res_id or 'N/A'}",
            f"  Admin Status:           {self.admin_status or 'N/A'}",
            f"  Operate Status:         {status}",
            "-" * 70,
            f"  A-End NE:               {a_ne}",
            f"  A-End Port:             {a_ltp}",
            f"  A-End IPv4:             {self.a_end_ipv4 or 'N/A'}",
            f"  A-End IPv6:             {self.a_end_ipv6 or 'N/A'}",
            f"  A-End IP Mask:          {self.a_end_ip_mask}",
            f"  Z-End NE:               {z_ne}",
            f"  Z-End Port:             {z_ltp}",
            f"  Z-End IPv4:             {self.z_end_ipv4 or 'N/A'}",
            f"  Z-End IPv6:             {self.z_end_ipv6 or 'N/A'}",
            f"  Z-End IP Mask:          {self.z_end_ip_mask}",
            "-" * 70,
            f"  TE Metric:              {self.te_metric}",
            f"  Latency:                {self.latency} us",
            f"  Segment ID:             {self.segment_id}",
            f"  Bandwidth BC0:          {self.bandwidth_bc0}",
            f"  Total Available BW:     {self.total_available_bandwidth}",
            f"  Max Reserved BW:        {self.max_reserved_bandwidth}",
            f"  Affinity Group:         {self.affinity_group}",
            f"  SRLGs:                  {self.srlgs or 'N/A'}",
            f"  Is Optimizable:         {self.is_optimizable}",
            f"  Flex Algo ID:           {self.flex_algo_id}",
            "-" * 70,
            f"  Remark:                 {self.remark or 'N/A'}",
            "=" * 70,
        ]
        return '\n'.join(lines)


class NcePort(BasePort):
    """
    Huawei NCE port (LTP — Logical Termination Point) data container.

    Represents ports/interfaces on network elements, including:
    - Physical ports: GigabitEthernet, 100GE, XGE, etc.
    - Logical interfaces: Eth-Trunk, LoopBack, Vlanif, Tunnel, etc.
    - Subinterfaces: VLAN subinterfaces, VC channels
    - WDM/DWDM ports: WDM Client, OCH, ODU, OMS/OTS
    - Access ports: PON, ADSL, VDSL

    API endpoint: GET /restconf/v3/data/huawei-nce-resource-inventory:ltps
    Response structure: {"ltps": {"ltp": [...]}}

    Hierarchical relationships:
    - Physical port -> subinterfaces (parent_ltp_id links child to parent)
    - Port -> board (card_id)
    - Port -> NE (ne_id)
    - Member port -> trunk (trunk_ltp_id)

    Resolved fields:
    - ne_name: populated by resolve_port_names() or resolve_names=True
    """

    # Additional identification
    is_in_ont: Optional[bool] = None
    onu_id: Optional[str] = None

    # Network (extended beyond BasePort)
    addrv6: Optional[list] = None
    mac: Optional[str] = None
    mtu: Optional[str] = None
    medium_type: Optional[str] = None
    layer_rate: Optional[str] = None
    work_mode: Optional[str] = None

    # Hierarchy (extended)
    frame_number: Optional[str] = None
    trunk_ltp_id: Optional[str] = None
    daughter_slot_id: Optional[str] = None
    port_index: Optional[str] = None

    # L2/VLAN
    vlan_type: Optional[str] = None
    direction: Optional[str] = None

    # TE/MPLS
    max_reserved_bandwidth: Optional[float] = None
    available_bandwidth: Optional[float] = None

    # Timing
    create_time: Optional[datetime] = None
    last_modified: Optional[datetime] = None

    # Optical/SN
    sn: Optional[str] = None

    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        """
        Populate fields from NCE port API data.

        Maps kebab-case API field names to snake_case Python attributes.
        Less common or domain-specific fields (DWDM wavelength, QinQ VLAN,
        PON mode, etc.) are stored in vendor_specific_info.
        """
        # BasePort common fields
        self.res_id = data.get('res-id')
        self.name = data.get('name')
        self.native_name = data.get('native-name')
        self.ne_id = data.get('ne-id')
        self.is_physical = data.get('is-physical')
        self.is_sub_ltp = data.get('is-sub-ltp')
        self.ltp_type_name = data.get('ltp-type-name')
        self.sc_ltp_type = data.get('sc-ltp-type')
        self.port_type = data.get('port-type')
        self.ltp_role = data.get('ltp-role')
        self.operate_status = data.get('operate-status')
        self.admin_status = data.get('admin-status')
        self.bandwidth = data.get('bandwidth')
        self.addrv4 = data.get('addrv4')
        self.addrv4_mask = data.get('addrv4-mask')
        self.card_id = data.get('card-id')
        self.slot_number = data.get('slot-number')
        self.port_number = data.get('port-number')
        self.parent_ltp_id = data.get('parent-ltp-id')
        self.description = data.get('description')
        self.alias = data.get('alias')
        self.user_label = data.get('user-label')
        self.remark = data.get('remark')

        # Extended NcePort fields
        self.is_in_ont = data.get('is-in-ont')
        self.onu_id = data.get('onu-id')
        self.addrv6 = data.get('addrv6')
        self.mac = data.get('mac')
        self.mtu = data.get('mtu')
        self.medium_type = data.get('medium-type')
        self.layer_rate = data.get('layer-rate')
        self.work_mode = data.get('work-mode')
        self.frame_number = data.get('frame-number')
        self.trunk_ltp_id = data.get('trunk-ltp-id')
        self.daughter_slot_id = data.get('daughter-slot-id')
        self.port_index = data.get('port-index')
        self.vlan_type = data.get('vlan-type')
        self.direction = data.get('direction')
        self.max_reserved_bandwidth = data.get('max-reserved-bandwidth')
        self.available_bandwidth = data.get('available-bandwidth')
        self.create_time = parse_datetime(data.get('create-time'))
        self.last_modified = parse_datetime(data.get('last-modified'))
        self.sn = data.get('sn')

        # Vendor-specific info: less common fields (DWDM, QinQ, PON, etc.)
        self.vendor_specific_info = {
            'vlan': data.get('vlan'),
            'load-balance-mode': data.get('load-balance-mode'),
            'lag-type': data.get('lag-type'),
            'max-active-link-number': data.get('max-active-link-number'),
            'work-band': data.get('work-band'),
            'work-band-parity': data.get('work-band-parity'),
            'wave-no': data.get('wave-no'),
            'flex-freq': data.get('flex-freq'),
            'freq-width': data.get('freq-width'),
            'optics-bom-code': data.get('optics-bom-code'),
            'optical-module': data.get('optical-module'),
            'signal-type-capability': data.get('signal-type-capability'),
            'level': data.get('level'),
            'contain-layer-rates': data.get('contain-layer-rates'),
            'usage-state': data.get('usage-state'),
            'path-id': data.get('path-id'),
            'path-layer-info': data.get('path-layer-info'),
            'low-path': data.get('low-path'),
            'high-path': data.get('high-path'),
            'timeslot': data.get('timeslot'),
            'port-mapping': data.get('port-mapping'),
            'auto-negotiation': data.get('auto-negotiation'),
            'tpid': data.get('tpid'),
            'default-vlan-id': data.get('default-vlan-id'),
            'revertive-mode': data.get('revertive-mode'),
            'ingress-cir': data.get('ingress-cir'),
            'ingress-pir': data.get('ingress-pir'),
            'egress-cir': data.get('egress-cir'),
            'egress-pir': data.get('egress-pir'),
            'reserved-bandwidth-ratio': data.get('reserved-bandwidth-ratio'),
            'transceiver-enabled': data.get('transceiver-enabled'),
            'laser-auto-shutdown': data.get('laser-auto-shutdown'),
            'ip-assigned-type': data.get('ip-assigned-type'),
            'slice-ids': data.get('slice-ids'),
            'tags': data.get('tags'),
            'delete-time': data.get('delete-time'),
            'create-date-and-time': data.get('create-date-and-time'),
            'last-modified-date-and-time': data.get('last-modified-date-and-time'),
        }

    def brief(self) -> str:
        """
        Get brief one-line representation of the port.

        Format: "name | type | NE | status | bandwidth"
        Shows resolved NE name if available.
        """
        status = 'up' if self.operate_status == '0' else 'down' if self.operate_status == '1' else self.operate_status or 'unknown'
        ne = self.ne_name or self.ne_id or 'N/A'
        bw = f"{self.bandwidth:.0f} kbps" if self.bandwidth is not None else 'N/A'
        parts = [
            self.name or 'N/A',
            self.ltp_type_name or 'N/A',
            ne,
            status,
            bw,
        ]
        return ' | '.join(parts)

    def details(self) -> str:
        """
        Get detailed multi-line representation with NCE-specific fields.

        Shows resolved NE name alongside UUID when available.
        """
        status = 'up' if self.operate_status == '0' else 'down' if self.operate_status == '1' else self.operate_status or 'unknown'
        ne = self.ne_id or 'N/A'
        if self.ne_name:
            ne = f"{self.ne_name} ({self.ne_id})"

        lines = [
            "=" * 70,
            f"Huawei NCE Port: {self.name or 'N/A'}",
            "=" * 70,
            f"  Resource ID:          {self.res_id or 'N/A'}",
            f"  Native Name:          {self.native_name or 'N/A'}",
            f"  Alias:                {self.alias or 'N/A'}",
            f"  Description:          {self.description or 'N/A'}",
            "-" * 70,
            f"  NE:                   {ne}",
            f"  Board (card-id):      {self.card_id or 'N/A'}",
            f"  Slot:                 {self.slot_number or 'N/A'}",
            f"  Port Number:          {self.port_number}",
            f"  Frame:                {self.frame_number or 'N/A'}",
            f"  Parent LTP:           {self.parent_ltp_id or 'N/A'}",
            f"  Trunk LTP:            {self.trunk_ltp_id or 'N/A'}",
            "-" * 70,
            f"  Type:                 {self.ltp_type_name or 'N/A'}",
            f"  SC Type:              {self.sc_ltp_type or 'N/A'}",
            f"  Port Type ID:         {self.port_type}",
            f"  Role:                 {self.ltp_role or 'N/A'}",
            f"  Physical:             {self.is_physical}",
            f"  Sub-interface:        {self.is_sub_ltp}",
            f"  Direction:            {self.direction or 'N/A'}",
            "-" * 70,
            f"  Operate Status:       {status}",
            f"  Admin Status:         {self.admin_status or 'N/A'}",
            f"  Bandwidth:            {f'{self.bandwidth:.0f} kbps' if self.bandwidth is not None else 'N/A'}",
            f"  Work Mode:            {self.work_mode or 'N/A'}",
            f"  Medium Type:          {self.medium_type or 'N/A'}",
            f"  Layer Rate:           {self.layer_rate or 'N/A'}",
            f"  MTU:                  {self.mtu or 'N/A'}",
            "-" * 70,
            f"  IPv4:                 {self.addrv4 or 'N/A'}/{self.addrv4_mask if self.addrv4_mask is not None else 'N/A'}",
            f"  MAC:                  {self.mac or 'N/A'}",
            f"  SN:                   {self.sn or 'N/A'}",
            "-" * 70,
            f"  Created:              {self._format_datetime(self.create_time)}",
            f"  Last Modified:        {self._format_datetime(self.last_modified)}",
            "=" * 70,
        ]
        return '\n'.join(lines)

    def _format_datetime(self, dt: Optional[datetime]) -> str:
        """Format datetime for display."""
        if dt is None:
            return 'N/A'
        return dt.strftime('%Y-%m-%d %H:%M:%S %Z')

