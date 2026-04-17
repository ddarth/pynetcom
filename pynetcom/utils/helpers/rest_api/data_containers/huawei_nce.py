"""
Huawei NCE specific data containers.

Maps NCE REST API responses to IETF/OpenConfig-aligned base classes:
- NceNode (BaseNode) — RFC 8345 network node
- NceLink (BaseLink) — RFC 8345 network link (source/dest naming)
- NceIgpLink (BaseLink) — RFC 8346 L3 IGP link
- NceTerminationPoint (BaseTerminationPoint) — RFC 8345 termination point
- NceInterface (BaseInterface) — OpenConfig L3 interface
- NceAlarm (BaseAlarm) — alarm data
"""

from typing import Dict, Any, Optional, List
from datetime import datetime

from pynetcom.utils.helpers.rest_api.data_containers.base import (
    BaseAlarm,
    BaseInterface,
    BaseLink,
    BaseNode,
    BaseTerminationPoint,
    parse_datetime,
    _format_dt,
)


# ─── Alarm ────────────────────────────────────────────────────────────


class NceAlarm(BaseAlarm):
    """
    Huawei NCE alarm data container.

    NCE alarms have nested structure:
    - resource-alarm-parameters
    - x733-alarm-parameters
    - alarm-parameters
    - common-alarm-parameters

    All NCE-specific data is stored in vendor_specific_info dict.
    """

    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        resource_params = data.get('resource-alarm-parameters', {})
        x733_params = data.get('x733-alarm-parameters', {})
        alarm_params = data.get('alarm-parameters', {})
        common_params = data.get('common-alarm-parameters', {})

        self.severity = resource_params.get('perceived-severity')
        self.alarm_name = alarm_params.get('alarm-text')
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

        if resource_params.get('is-cleared'):
            status_changes = resource_params.get('status-change', [])
            if status_changes:
                self.cleared_time = parse_datetime(status_changes[0].get('time'))

        self.additional_text = alarm_params.get('repair-action')
        self.alarm_serial_number = alarm_params.get('alarm-serial-number')
        self.other_info = alarm_params.get('other-info')

        self.vendor_specific_info = {
            'resource': common_params.get('resource'),
            'alt-resource': common_params.get('alt-resource'),
            'resource-url': common_params.get('resource-url'),
            'product-type': common_params.get('product-type'),
            'layer': common_params.get('layer'),
            'md-name': common_params.get('md-name'),
            'alarm-text': alarm_params.get('alarm-text'),
            'native-probable-cause': alarm_params.get('native-probable-cause'),
            'location-info': alarm_params.get('location-info'),
            'repair-action': alarm_params.get('repair-action'),
            'reason-id': alarm_params.get('reason-id'),
            'ip-address': alarm_params.get('ip-address'),
            'tenant': alarm_params.get('tenant'),
            'event-type': x733_params.get('event-type'),
            'ems-time': alarm_params.get('ems-time'),
        }


# ─── Node (RFC 8345) ─────────────────────────────────────────────────


class NceNode(BaseNode):
    """
    Huawei NCE network element as RFC 8345 Node.

    API: GET /restconf/v2/data/huawei-nce-resource-inventory:network-elements

    NCE-specific fields go to vendor_specific_info:
    res_id, lsr_id, as_number, serial_number, mac, hardware_version, etc.
    """

    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        # BaseNode standard fields
        self.node_id = data.get('res-id')
        self.name = data.get('name')
        self.management_address = data.get('ip-address')
        self.platform_type = data.get('detail-dev-type-name') or data.get('product-name')
        self.platform_vendor = data.get('manufacturer')
        self.software_version = data.get('software-version')
        self.oper_status = data.get('communication-state')
        self.admin_status = data.get('admin-status')
        self.topology_group = data.get('ref-parent-subnet')

        # NCE-specific → vendor_specific_info
        self.vendor_specific_info = {
            'res-id': data.get('res-id'),
            'lsr-id': data.get('lsr-id'),
            'dev-sys-name': data.get('dev-sys-name'),
            'physical-id': data.get('physical-id'),
            'as-number': data.get('as-number'),
            'product-name': data.get('product-name'),
            'platform-version': data.get('platform-version'),
            'hardware-version': data.get('hardware-version'),
            'patch-version': data.get('patch-version'),
            'serial-number': data.get('sn'),
            'mac': data.get('mac'),
            'location': data.get('location'),
            'remark': data.get('remark'),
            'is-virtual': data.get('is-virtual'),
            'is-gateway': data.get('is-gateway'),
            'container': data.get('container'),
            'create-time': data.get('create-time'),
            'last-modified': data.get('last-modified'),
        }


# ─── Link (RFC 8345) ─────────────────────────────────────────────────


class NceLink(BaseLink):
    """
    Huawei NCE link as RFC 8345 Link.

    Uses IETF naming: source_node/dest_node instead of a-end/z-end.

    API: GET /restconf/v2/data/huawei-nce-resource-inventory:links
    Link types: Fiber, L2 Link, Microwave Link, Cable, IP Link, Dummy Link
    """

    # NCE-specific fields (not in IETF base)
    link_type: Optional[str] = None
    direction: Optional[str] = None
    bandwidth: Optional[float] = None
    layer_rate: Optional[str] = None
    length: Optional[float] = None
    medium_type: Optional[str] = None
    source_ip: Optional[str] = None
    dest_ip: Optional[str] = None

    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        # RFC 8345 BaseLink fields (IETF naming)
        self.link_id = data.get('res-id')
        self.name = data.get('name')
        self.source_node = data.get('a-end-ne-id')
        self.dest_node = data.get('z-end-ne-id')
        self.source_tp = data.get('a-end-ltp-id')
        self.dest_tp = data.get('z-end-ltp-id')
        self.oper_status = data.get('operate-status')
        self.admin_status = data.get('admin-status')

        # NCE-specific
        self.link_type = data.get('type')
        self.direction = data.get('direction')
        self.bandwidth = data.get('bandwidth')
        self.layer_rate = data.get('layer-rate')
        self.length = data.get('length')
        self.medium_type = data.get('medium-type')
        self.source_ip = data.get('a-end-ip')
        self.dest_ip = data.get('z-end-ip')

        self.vendor_specific_info = {
            'remaining-up-bandwidth': data.get('remaining-up-bandwidth'),
            'remaining-down-bandwidth': data.get('remaining-down-bandwidth'),
            'design-power-loss': data.get('design-power-loss'),
            'user-label': data.get('user-label'),
            'alias': data.get('alias'),
            'remark': data.get('remark'),
            'ref-srlg-list': data.get('ref-srlg-list'),
            'distinguished-name': data.get('distinguished-name'),
            'cross-layer': data.get('cross-layer'),
            'slice-ids': data.get('slice-ids'),
            'delete-time': data.get('delete-time'),
        }

    def _status_str(self) -> str:
        if self.oper_status == '0':
            return 'up'
        if self.oper_status == '1':
            return 'down'
        return self.oper_status or 'unknown'

    def brief(self) -> str:
        bw = f"{self.bandwidth:.0f} kbps" if self.bandwidth is not None else 'N/A'
        parts = [self.name or 'N/A', self.link_type or 'N/A']
        src = self.source_node_name or self.source_node or '?'
        dst = self.dest_node_name or self.dest_node or '?'
        parts.append(f"{src} -> {dst}")
        parts.extend([self._status_str(), bw])
        return ' | '.join(parts)

    def details(self) -> str:
        src_n = f"{self.source_node_name} ({self.source_node})" if self.source_node_name else (self.source_node or 'N/A')
        dst_n = f"{self.dest_node_name} ({self.dest_node})" if self.dest_node_name else (self.dest_node or 'N/A')
        src_tp = f"{self.source_tp_name} ({self.source_tp})" if self.source_tp_name else (self.source_tp or 'N/A')
        dst_tp = f"{self.dest_tp_name} ({self.dest_tp})" if self.dest_tp_name else (self.dest_tp or 'N/A')
        bw = f"{self.bandwidth:.0f} kbps" if self.bandwidth is not None else 'N/A'
        lines = [
            "=" * 70,
            f"NCE Link: {self.name or 'N/A'}",
            "=" * 70,
            f"  Link ID:          {self.link_id or 'N/A'}",
            f"  Link Type:        {self.link_type or 'N/A'}",
            f"  Direction:        {self.direction or 'N/A'}",
            f"  Layer Rate:       {self.layer_rate or 'N/A'}",
            "-" * 70,
            f"  Source Node:      {src_n}",
            f"  Source TP:        {src_tp}",
            f"  Source IP:        {self.source_ip or 'N/A'}",
            f"  Dest Node:        {dst_n}",
            f"  Dest TP:          {dst_tp}",
            f"  Dest IP:          {self.dest_ip or 'N/A'}",
            "-" * 70,
            f"  Bandwidth:        {bw}",
            f"  Length:           {self.length if self.length is not None else 'N/A'}",
            f"  Medium Type:      {self.medium_type or 'N/A'}",
            f"  Oper Status:      {self._status_str()}",
            f"  Admin Status:     {self.admin_status or 'N/A'}",
            "=" * 70,
        ]
        return '\n'.join(lines)


class NceIgpLink(BaseLink):
    """
    Huawei NCE IGP link as RFC 8346 L3 topology link.

    API: GET /restconf/v3/data/huawei-nce-resource-inventory:igp-links
    Contains TE metrics, bandwidth, latency, segment routing data.
    """

    # L3/TE attributes (RFC 8346 augment)
    source_ipv4: Optional[str] = None
    dest_ipv4: Optional[str] = None
    te_metric: Optional[int] = None
    latency: Optional[int] = None
    segment_id: Optional[int] = None
    bandwidth_bc0: Optional[int] = None
    total_available_bandwidth: Optional[int] = None
    max_reserved_bandwidth: Optional[int] = None

    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        # RFC 8345 BaseLink
        self.link_id = data.get('res-id')
        self.name = data.get('name')
        self.source_node = data.get('a-end-ne-id')
        self.dest_node = data.get('z-end-ne-id')
        self.source_tp = data.get('a-end-ltp-id')
        self.dest_tp = data.get('z-end-ltp-id')
        self.oper_status = data.get('operate-state')
        self.admin_status = data.get('admin-status')

        # RFC 8346 L3 attributes
        self.source_ipv4 = data.get('a-end-ipv4')
        self.dest_ipv4 = data.get('z-end-ipv4')
        self.te_metric = data.get('te-metric')
        self.latency = data.get('latency')
        self.segment_id = data.get('segment-id')
        self.bandwidth_bc0 = data.get('bandwidth-bc0')
        self.total_available_bandwidth = data.get('total-available-bandwidth')
        self.max_reserved_bandwidth = data.get('max-reserved-bandwidth')

        self.vendor_specific_info = {
            'source-ipv6': data.get('a-end-ipv6'),
            'dest-ipv6': data.get('z-end-ipv6'),
            'source-ip-mask': data.get('a-end-ip-mask'),
            'dest-ip-mask': data.get('z-end-ip-mask'),
            'source-ipv6-router-id': data.get('a-end-ipv6-router-id'),
            'dest-ipv6-router-id': data.get('z-end-ipv6-router-id'),
            'latency-ipv6': data.get('latency-ipv6'),
            'total-reserved-bandwidth': data.get('total-reserved-bandwidth'),
            'affinity-group': data.get('affinity-group'),
            'srlgs': data.get('srlgs'),
            'is-optimizable': data.get('is-optimizable'),
            'priority-bandwidths': data.get('priority-bandwidths'),
            'flex-algo-id': data.get('flex-algo-id'),
            'user-defined-constraints': data.get('user-defined-constraints'),
            'remark': data.get('remark'),
        }

    def brief(self) -> str:
        status = 'up' if self.oper_status == '0' else 'down' if self.oper_status == '1' else self.oper_status or 'N/A'
        src = self.source_node_name or self.source_node or '?'
        dst = self.dest_node_name or self.dest_node or '?'
        return ' | '.join([
            self.name or 'N/A',
            f"{src} -> {dst}",
            f"{self.source_ipv4 or '?'} -> {self.dest_ipv4 or '?'}",
            status,
            f"metric={self.te_metric}",
        ])


# ─── Termination Point (RFC 8345) ────────────────────────────────────


class NceTerminationPoint(BaseTerminationPoint):
    """
    Huawei NCE port/interface as RFC 8345 Termination Point.

    API: GET /restconf/v3/data/huawei-nce-resource-inventory:ltps
    Includes physical ports, logical interfaces, subinterfaces, WDM ports.

    NCE-specific fields go to vendor_specific_info dict. Key fields used
    by EML Performance Service (get_eml_pm_for_ports):
      - 'frame-number': shelf ID (int) — used as shelfId
      - 'slot-number': board slot (int) — used as boardId
      - 'port-number': physical port (int) — used as physicalPortId
      - 'alias': user-defined label; on FIU ports can contain 'shelf/slot/port'
        reference to the corresponding active board
      - 'sc-ltp-type': port category ('WDM', 'OMS/OTS', 'ETH', etc.)
      - 'card-id': UUID of the board (for board-level PM queries)

    Other vendor_specific_info fields: native-name, port-type, ltp-role,
    port-index, user-label, layer-rate, etc.
    """

    # Fields needed by provider logic but not in base TP
    trunk_ltp_id: Optional[str] = None
    parent_tp_id: Optional[str] = None
    is_sub_interface: Optional[bool] = None
    mac: Optional[str] = None
    mtu: Optional[str] = None
    medium_type: Optional[str] = None
    sn: Optional[str] = None
    create_time: Optional[datetime] = None
    last_modified: Optional[datetime] = None

    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        # RFC 8345 BaseTerminationPoint
        self.tp_id = data.get('res-id')
        self.name = data.get('name')
        self.node_id = data.get('ne-id')
        self.oper_status = data.get('operate-status')
        self.admin_status = data.get('admin-status')
        self.interface_type = data.get('ltp-type-name')
        self.is_physical = data.get('is-physical')
        self.bandwidth = data.get('bandwidth')
        self.ipv4_address = data.get('addrv4')
        self.ipv4_prefix_length = data.get('addrv4-mask')
        self.description = data.get('description')
        self.hardware_port = data.get('native-name')

        # NCE-specific (used by provider for trunk/parent logic)
        self.trunk_ltp_id = data.get('trunk-ltp-id')
        self.parent_tp_id = data.get('parent-ltp-id')
        self.is_sub_interface = data.get('is-sub-ltp')
        self.mac = data.get('mac')
        self.mtu = data.get('mtu')
        self.medium_type = data.get('medium-type')
        self.sn = data.get('sn')
        self.create_time = parse_datetime(data.get('create-time'))
        self.last_modified = parse_datetime(data.get('last-modified'))

        self.vendor_specific_info = {
            'native-name': data.get('native-name'),
            'sc-ltp-type': data.get('sc-ltp-type'),
            'port-type': data.get('port-type'),
            'ltp-role': data.get('ltp-role'),
            'card-id': data.get('card-id'),
            'slot-number': data.get('slot-number'),
            'port-number': data.get('port-number'),
            'frame-number': data.get('frame-number'),
            'port-index': data.get('port-index'),
            'alias': data.get('alias'),
            'user-label': data.get('user-label'),
            'remark': data.get('remark'),
            'work-mode': data.get('work-mode'),
            'layer-rate': data.get('layer-rate'),
            'direction': data.get('direction'),
            'vlan-type': data.get('vlan-type'),
            'addrv6': data.get('addrv6'),
            'is-in-ont': data.get('is-in-ont'),
            'onu-id': data.get('onu-id'),
            'max-reserved-bandwidth': data.get('max-reserved-bandwidth'),
            'available-bandwidth': data.get('available-bandwidth'),
            'load-balance-mode': data.get('load-balance-mode'),
            'lag-type': data.get('lag-type'),
            'max-active-link-number': data.get('max-active-link-number'),
            'optics-bom-code': data.get('optics-bom-code'),
            'signal-type-capability': data.get('signal-type-capability'),
            'level': data.get('level'),
            'transceiver-enabled': data.get('transceiver-enabled'),
        }

    def brief(self) -> str:
        node = self.node_name or self.node_id or 'N/A'
        bw = f"{self.bandwidth:.0f} kbps" if self.bandwidth is not None else 'N/A'
        parts = [self.name or 'N/A', self.interface_type or 'N/A', node, self._status_str(), bw]
        return ' | '.join(parts)

    def details(self) -> str:
        node = f"{self.node_name} ({self.node_id})" if self.node_name else (self.node_id or 'N/A')
        ip = f"{self.ipv4_address}/{self.ipv4_prefix_length}" if self.ipv4_address else 'N/A'
        lines = [
            "=" * 70,
            f"NCE TP: {self.name or 'N/A'}",
            "=" * 70,
            f"  TP ID:            {self.tp_id or 'N/A'}",
            f"  Node:             {node}",
            f"  Type:             {self.interface_type or 'N/A'}",
            f"  Physical:         {self.is_physical}",
            f"  Sub-interface:    {self.is_sub_interface}",
            "-" * 70,
            f"  Oper Status:      {self._status_str()}",
            f"  Admin Status:     {self.admin_status or 'N/A'}",
            f"  Bandwidth:        {f'{self.bandwidth:.0f} kbps' if self.bandwidth is not None else 'N/A'}",
            f"  Medium Type:      {self.medium_type or 'N/A'}",
            f"  MTU:              {self.mtu or 'N/A'}",
            "-" * 70,
            f"  IPv4:             {ip}",
            f"  MAC:              {self.mac or 'N/A'}",
            f"  SN:               {self.sn or 'N/A'}",
            f"  Trunk LTP:        {self.trunk_ltp_id or 'N/A'}",
            f"  Parent TP:        {self.parent_tp_id or 'N/A'}",
            "-" * 70,
            f"  Created:          {_format_dt(self.create_time)}",
            f"  Last Modified:    {_format_dt(self.last_modified)}",
            "=" * 70,
        ]
        return '\n'.join(lines)


# ─── Interface (OpenConfig) ──────────────────────────────────────────


class NceInterface(BaseInterface):
    """
    Huawei NCE L3 interface as OpenConfig Interface.

    Built from NceTerminationPoint data — NCE doesn't have a separate
    "router interface" concept. IP lives directly on ports.

    This class adapts NceTerminationPoint (port with IP) to the
    OpenConfig interface model for unified cross-vendor usage.
    """

    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        """
        Populate from NceTerminationPoint-like dict.

        Expected keys match NCE port API fields:
        name, ne-id, addrv4, addrv4-mask, ltp-type-name, operate-status, etc.
        """
        self.interface_name = data.get('name')
        self.node_id = data.get('ne-id')
        self.hardware_port = data.get('native-name') or data.get('name')
        self.is_lag = (data.get('ltp-type-name') or '').lower() in ('eth-trunk',)
        self.ipv4_address = data.get('addrv4')
        self.ipv4_prefix_length = data.get('addrv4-mask')
        self.oper_status = data.get('operate-status')
        self.admin_status = data.get('admin-status')
        self.mtu = int(data.get('mtu', 0)) if data.get('mtu') else None

        self.vendor_specific_info = {
            'ltp-type-name': data.get('ltp-type-name'),
            'sc-ltp-type': data.get('sc-ltp-type'),
            'bandwidth': data.get('bandwidth'),
            'medium-type': data.get('medium-type'),
            'mac': data.get('mac'),
            'work-mode': data.get('work-mode'),
        }
