"""
Base data container classes for REST API responses.

Models are aligned with open standards:
- RFC 8345 (ietf-network + ietf-network-topology): Node, Link, TerminationPoint
- RFC 8346 (ietf-l3-unicast-topology): L3 augmentations
- OpenConfig interfaces + if-ip: Interface with IPv4 addressing
- OpenConfig network-instance: routing protocols

Vendor-specific fields go into vendor_specific_info dict.
Standard fields follow IETF/OpenConfig naming where possible.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from abc import ABC, abstractmethod
import json


def parse_datetime(value: Any) -> Optional[datetime]:
    """
    Parse various datetime formats to datetime object.

    Supports:
    - datetime objects (returned as-is)
    - Unix timestamps in milliseconds (int/float)
    - ISO 8601 strings with 'Z' suffix or timezone
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    if isinstance(value, str):
        text = value.strip()
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    return None


def _format_dt(dt: Optional[datetime]) -> str:
    """Format datetime for display."""
    if dt is None:
        return 'N/A'
    return dt.strftime('%Y-%m-%d %H:%M:%S %Z')


def _to_dict_helper(obj) -> Dict[str, Any]:
    """Convert object fields to dictionary, excluding raw_data and callables."""
    result = {}
    for attr in dir(obj):
        if attr.startswith('_') or callable(getattr(obj, attr)):
            continue
        if attr == 'raw_data':
            continue
        value = getattr(obj, attr)
        if isinstance(value, datetime):
            value = value.isoformat()
        result[attr] = value
    return result


# ─── RFC 8345: Network Node ───────────────────────────────────────────


class BaseNode(ABC):
    """
    RFC 8345 network node — a device in the network topology.

    Based on ietf-network:network/node, augmented with OpenConfig platform
    attributes for device identification and status.

    Standard references:
    - RFC 8345 Section 6.1: node-id, supporting-node
    - OpenConfig openconfig-platform: platform type, vendor, version
    - OpenConfig openconfig-system: hostname, management address

    Example:
        node = provider.get_nodes(name="Router-01")[0]
        print(node.name)                # "Router-01"
        print(node.management_address)  # "172.28.205.9"
        print(node.platform_type)       # "7250 IXR-e"
    """

    # RFC 8345: node identity
    node_id: Optional[str] = None
    name: Optional[str] = None

    # OpenConfig platform
    platform_type: Optional[str] = None
    platform_vendor: Optional[str] = None
    software_version: Optional[str] = None

    # Operational status
    oper_status: Optional[str] = None
    admin_status: Optional[str] = None

    # Network context
    management_address: Optional[str] = None
    topology_group: Optional[str] = None

    vendor_specific_info: Optional[Dict[str, Any]] = None
    raw_data: Optional[Dict[str, Any]] = None

    def __init__(self, data: Dict[str, Any]):
        self.raw_data = data
        self._populate_from_data(data)

    @abstractmethod
    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        pass

    def brief(self) -> str:
        return ' | '.join([
            self.name or 'N/A',
            self.management_address or 'N/A',
            self.platform_type or 'N/A',
            self.oper_status or 'N/A',
        ])

    def details(self) -> str:
        lines = [
            "=" * 60,
            f"Node: {self.name or 'N/A'}",
            "=" * 60,
            f"  Node ID:           {self.node_id or 'N/A'}",
            f"  Management Address:{self.management_address or 'N/A'}",
            f"  Platform Type:     {self.platform_type or 'N/A'}",
            f"  Platform Vendor:   {self.platform_vendor or 'N/A'}",
            f"  Software Version:  {self.software_version or 'N/A'}",
            f"  Oper Status:       {self.oper_status or 'N/A'}",
            f"  Admin Status:      {self.admin_status or 'N/A'}",
            f"  Topology Group:    {self.topology_group or 'N/A'}",
            "=" * 60,
        ]
        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict_helper(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def __str__(self) -> str:
        return self.brief()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, node_id={self.node_id!r})"


# ─── RFC 8345: Network Link ──────────────────────────────────────────


class BaseLink(ABC):
    """
    RFC 8345 network link — a connection between two termination points.

    Based on ietf-network-topology:link with source/destination nodes
    and termination points. Augmented with RFC 8346 L3 attributes.

    Links are point-to-point and unidirectional in IETF model.
    To represent a bidirectional connection, two links are used
    (or a single link with direction="bidirectional" as vendor extension).

    Standard references:
    - RFC 8345 Section 6.2: link-id, source, destination
    - RFC 8346: L3 topology augmentations (metric, bandwidth)

    Field naming follows IETF:
    - source_node / dest_node (not a_end / z_end)
    - source_tp / dest_tp (termination points)

    Example:
        link = provider.get_links(resolve_names=True)[0]
        print(link.source_node_name)  # "Router-01"
        print(link.dest_node_name)    # "Router-02"
        print(link.source_tp_name)    # "GigabitEthernet1/0/7"
    """

    # RFC 8345: link identity
    link_id: Optional[str] = None
    name: Optional[str] = None

    # RFC 8345: source (Section 6.2)
    source_node: Optional[str] = None
    source_tp: Optional[str] = None

    # RFC 8345: destination (Section 6.2)
    dest_node: Optional[str] = None
    dest_tp: Optional[str] = None

    # Resolved names (pynetcom extension for human-readable display)
    source_node_name: Optional[str] = None
    dest_node_name: Optional[str] = None
    source_tp_name: Optional[str] = None
    dest_tp_name: Optional[str] = None

    # RFC 8346 L3 / operational attributes
    oper_status: Optional[str] = None
    admin_status: Optional[str] = None

    vendor_specific_info: Optional[Dict[str, Any]] = None
    raw_data: Optional[Dict[str, Any]] = None

    def __init__(self, data: Dict[str, Any]):
        self.raw_data = data
        self._populate_from_data(data)

    @abstractmethod
    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        pass

    def brief(self) -> str:
        src = self.source_node_name or self.source_node or 'N/A'
        dst = self.dest_node_name or self.dest_node or 'N/A'
        return ' | '.join([
            self.name or 'N/A',
            f"{src} -> {dst}",
            self.oper_status or 'N/A',
        ])

    def details(self) -> str:
        src_n = f"{self.source_node_name} ({self.source_node})" if self.source_node_name else (self.source_node or 'N/A')
        dst_n = f"{self.dest_node_name} ({self.dest_node})" if self.dest_node_name else (self.dest_node or 'N/A')
        src_tp = f"{self.source_tp_name} ({self.source_tp})" if self.source_tp_name else (self.source_tp or 'N/A')
        dst_tp = f"{self.dest_tp_name} ({self.dest_tp})" if self.dest_tp_name else (self.dest_tp or 'N/A')
        lines = [
            "=" * 60,
            f"Link: {self.name or 'N/A'}",
            "=" * 60,
            f"  Link ID:         {self.link_id or 'N/A'}",
            f"  Source Node:     {src_n}",
            f"  Source TP:       {src_tp}",
            f"  Dest Node:       {dst_n}",
            f"  Dest TP:         {dst_tp}",
            f"  Oper Status:     {self.oper_status or 'N/A'}",
            f"  Admin Status:    {self.admin_status or 'N/A'}",
            "=" * 60,
        ]
        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict_helper(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def __str__(self) -> str:
        return self.brief()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, link_id={self.link_id!r})"


# ─── RFC 8345: Termination Point ─────────────────────────────────────


class BaseTerminationPoint(ABC):
    """
    RFC 8345 termination point — a port or interface on a node.

    Based on ietf-network-topology:termination-point, augmented with
    OpenConfig interfaces attributes for type, status, and IP addressing.

    Termination points anchor links to nodes. They represent physical
    ports, logical interfaces, LAG groups, subinterfaces, etc.

    Standard references:
    - RFC 8345 Section 6.3: tp-id
    - OpenConfig openconfig-interfaces: type, oper-status, admin-status
    - OpenConfig openconfig-if-ip: ipv4 address, prefix-length

    Example:
        tp = provider.get_termination_points(node_id="...")[0]
        print(tp.name)           # "GigabitEthernet1/0/0"
        print(tp.ipv4_address)   # "172.28.206.133"
        print(tp.interface_type) # "ethernetCsmacd"
    """

    # RFC 8345: identity
    tp_id: Optional[str] = None
    name: Optional[str] = None

    # Parent node
    node_id: Optional[str] = None
    node_name: Optional[str] = None

    # OpenConfig interfaces: state
    oper_status: Optional[str] = None
    admin_status: Optional[str] = None

    # OpenConfig interfaces: type classification
    interface_type: Optional[str] = None
    is_physical: Optional[bool] = None

    # OpenConfig interfaces: hardware binding
    hardware_port: Optional[str] = None
    bandwidth: Optional[float] = None

    # OpenConfig if-ip: ipv4 (if assigned)
    ipv4_address: Optional[str] = None
    ipv4_prefix_length: Optional[int] = None

    # Description
    description: Optional[str] = None

    vendor_specific_info: Optional[Dict[str, Any]] = None
    raw_data: Optional[Dict[str, Any]] = None

    def __init__(self, data: Dict[str, Any]):
        self.raw_data = data
        self._populate_from_data(data)

    @abstractmethod
    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        pass

    def _status_str(self) -> str:
        if self.oper_status == '0' or self.oper_status == 'up' or self.oper_status == 'enabled':
            return 'up'
        if self.oper_status == '1' or self.oper_status == 'down' or self.oper_status == 'disabled':
            return 'down'
        return self.oper_status or 'unknown'

    def brief(self) -> str:
        node = self.node_name or self.node_id or 'N/A'
        bw = f"{self.bandwidth:.0f} kbps" if self.bandwidth is not None else ''
        parts = [self.name or 'N/A', self.interface_type or 'N/A', node, self._status_str()]
        if bw:
            parts.append(bw)
        return ' | '.join(parts)

    def details(self) -> str:
        node = f"{self.node_name} ({self.node_id})" if self.node_name else (self.node_id or 'N/A')
        ip = f"{self.ipv4_address}/{self.ipv4_prefix_length}" if self.ipv4_address else 'N/A'
        lines = [
            "=" * 60,
            f"Termination Point: {self.name or 'N/A'}",
            "=" * 60,
            f"  TP ID:           {self.tp_id or 'N/A'}",
            f"  Node:            {node}",
            f"  Type:            {self.interface_type or 'N/A'}",
            f"  Physical:        {self.is_physical}",
            f"  Status:          {self._status_str()}",
            f"  Bandwidth:       {self.bandwidth}",
            f"  IPv4:            {ip}",
            f"  Description:     {self.description or 'N/A'}",
            "=" * 60,
        ]
        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict_helper(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def __str__(self) -> str:
        return self.brief()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, tp_id={self.tp_id!r})"


# ─── OpenConfig: L3 Interface ────────────────────────────────────────


class BaseInterface(ABC):
    """
    OpenConfig L3 router interface with IPv4 addressing.

    Combines data from:
    - openconfig-interfaces: name, oper-status, admin-status, mtu, hardware-port
    - openconfig-if-ip: ipv4 address/prefix-length, neighbor
    - openconfig-network-instance: associated routing protocols

    This represents a configured L3 interface (not just a physical port).
    An interface has an IP address and is bound to a physical port or LAG.

    Standard references:
    - OpenConfig openconfig-interfaces (2022-10-25)
    - OpenConfig openconfig-if-ip (2022-11-09)
    - OpenConfig openconfig-network-instance (2022-07-04)

    Example:
        iface = provider.get_interfaces("Router-01")[0]
        print(iface.interface_name)    # "Router-01-Router-02"
        print(iface.hardware_port)     # "1/1/23" or "lag-2"
        print(iface.ipv4_address)      # "172.28.206.133"
        print(iface.protocols)         # ["ospfv2", "mpls", "ldp"]
    """

    # openconfig-interfaces: identity
    interface_name: Optional[str] = None

    # Parent node
    node_name: Optional[str] = None
    node_id: Optional[str] = None

    # openconfig-interfaces: state
    oper_status: Optional[str] = None
    admin_status: Optional[str] = None
    mtu: Optional[int] = None

    # openconfig-interfaces: hardware binding
    hardware_port: Optional[str] = None
    is_lag: Optional[bool] = None

    # openconfig-if-ip: ipv4 addressing
    ipv4_address: Optional[str] = None
    ipv4_prefix_length: Optional[int] = None

    # openconfig-if-ip: neighbor discovery
    neighbor_address: Optional[str] = None
    neighbor_mac: Optional[str] = None

    # openconfig-network-instance: protocols
    protocols: Optional[List[str]] = None

    vendor_specific_info: Optional[Dict[str, Any]] = None
    raw_data: Optional[Dict[str, Any]] = None

    def __init__(self, data: Dict[str, Any]):
        self.raw_data = data
        self._populate_from_data(data)

    @abstractmethod
    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        pass

    def brief(self) -> str:
        ip = f"{self.ipv4_address}/{self.ipv4_prefix_length}" if self.ipv4_address else 'N/A'
        port = self.hardware_port or 'N/A'
        node = self.node_name or self.node_id or 'N/A'
        return ' | '.join([
            self.interface_name or 'N/A',
            port,
            ip,
            node,
            self.oper_status or 'N/A',
        ])

    def details(self) -> str:
        ip = f"{self.ipv4_address}/{self.ipv4_prefix_length}" if self.ipv4_address else 'N/A'
        node = f"{self.node_name} ({self.node_id})" if self.node_name else (self.node_id or 'N/A')
        proto = ', '.join(self.protocols) if self.protocols else 'N/A'
        nbr = f"{self.neighbor_address} ({self.neighbor_mac})" if self.neighbor_address else 'N/A'
        lines = [
            "=" * 60,
            f"Interface: {self.interface_name or 'N/A'}",
            "=" * 60,
            f"  Node:            {node}",
            f"  Hardware Port:   {self.hardware_port or 'N/A'}",
            f"  Is LAG:          {self.is_lag}",
            "-" * 60,
            f"  IPv4:            {ip}",
            f"  Neighbor:        {nbr}",
            f"  Protocols:       {proto}",
            "-" * 60,
            f"  Oper Status:     {self.oper_status or 'N/A'}",
            f"  Admin Status:    {self.admin_status or 'N/A'}",
            f"  MTU:             {self.mtu}",
            "=" * 60,
        ]
        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict_helper(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def __str__(self) -> str:
        return self.brief()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(interface_name={self.interface_name!r}, ipv4_address={self.ipv4_address!r})"


# ─── Alarm (vendor-neutral, not strictly IETF/OC) ───────────────────


class BaseAlarm(ABC):
    """
    Base class for alarm data from network management systems.

    Alarm models are not standardized in OpenConfig/IETF the same way
    as topology, but we follow similar naming conventions.
    """

    severity: Optional[str] = None
    alarm_name: Optional[str] = None
    alarm_type: Optional[str] = None
    probable_cause: Optional[str] = None
    additional_description: Optional[str] = None

    ne_name: Optional[str] = None
    ne_id: Optional[str] = None
    affected_object: Optional[str] = None

    acknowledged: Optional[bool] = None
    is_cleared: Optional[bool] = None
    root_cause: Optional[bool] = None

    time_created: Optional[datetime] = None
    last_changed: Optional[datetime] = None
    cleared_time: Optional[datetime] = None

    additional_text: Optional[str] = None
    alarm_serial_number: Optional[str] = None
    other_info: Optional[str] = None

    vendor_specific_info: Optional[Dict[str, Any]] = None
    raw_data: Optional[Dict[str, Any]] = None

    def __init__(self, data: Dict[str, Any]):
        self.raw_data = data
        self._populate_from_data(data)

    @abstractmethod
    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        pass

    def brief(self) -> str:
        return ' | '.join([
            self.ne_name or 'N/A',
            self.severity or 'N/A',
            self.alarm_name or 'N/A',
            self.affected_object or 'N/A',
        ])

    def details(self) -> str:
        lines = [
            "=" * 60,
            f"Alarm: {self.alarm_name or 'N/A'}",
            "=" * 60,
            f"  Severity:        {self.severity or 'N/A'}",
            f"  Alarm Type:      {self.alarm_type or 'N/A'}",
            f"  Probable Cause:  {self.probable_cause or 'N/A'}",
            "-" * 60,
            f"  NE Name:         {self.ne_name or 'N/A'}",
            f"  NE ID:           {self.ne_id or 'N/A'}",
            f"  Affected Object: {self.affected_object or 'N/A'}",
            "-" * 60,
            f"  Acknowledged:    {self.acknowledged}",
            f"  Cleared:         {self.is_cleared}",
            f"  Root Cause:      {self.root_cause}",
            "-" * 60,
            f"  Time Created:    {_format_dt(self.time_created)}",
            f"  Last Changed:    {_format_dt(self.last_changed)}",
            f"  Cleared Time:    {_format_dt(self.cleared_time)}",
            "-" * 60,
            f"  Additional Text: {self.additional_text or 'N/A'}",
            "=" * 60,
        ]
        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict_helper(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def __str__(self) -> str:
        return self.brief()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(ne_name={self.ne_name!r}, severity={self.severity!r}, alarm_name={self.alarm_name!r})"
