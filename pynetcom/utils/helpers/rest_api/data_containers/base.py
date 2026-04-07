"""
Base data container classes for REST API responses.
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
        # Assume milliseconds timestamp
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


class BaseAlarm(ABC):
    """
    Base class for alarm data from network management systems.
    
    Provides common fields and methods for Nokia NSP and Huawei NCE alarms.
    All field names use snake_case convention.
    """
    
    # Common fields (snake_case)
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
        """
        Initialize alarm from raw API data.
        
        Args:
            data: Raw alarm data from API response.
        """
        self.raw_data = data
        self._populate_from_data(data)
    
    @abstractmethod
    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        """Populate fields from raw API data. Must be implemented by subclasses."""
        pass
    
    def brief(self) -> str:
        """
        Get brief one-line representation of the alarm.
        
        Returns:
            String in format: "ne_name | severity | alarm_name | affected_object"
        """
        parts = [
            self.ne_name or 'N/A',
            self.severity or 'N/A',
            self.alarm_name or 'N/A',
            self.affected_object or 'N/A'
        ]
        return ' | '.join(parts)
    
    def details(self) -> str:
        """
        Get detailed multi-line representation of the alarm.
        
        Returns:
            Formatted string with all alarm information.
        """
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
            f"  Time Created:    {self._format_datetime(self.time_created)}",
            f"  Last Changed:    {self._format_datetime(self.last_changed)}",
            f"  Cleared Time:    {self._format_datetime(self.cleared_time)}",
            "-" * 60,
            f"  Additional Text: {self.additional_text or 'N/A'}",
            "=" * 60,
        ]
        return '\n'.join(lines)
    
    def _format_datetime(self, dt: Optional[datetime]) -> str:
        """Format datetime for display."""
        if dt is None:
            return 'N/A'
        return dt.strftime('%Y-%m-%d %H:%M:%S %Z')
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert alarm to dictionary.
        
        Returns:
            Dictionary with all alarm fields (common + vendor_specific_info).
        """
        result = {}
        for attr in dir(self):
            if attr.startswith('_') or callable(getattr(self, attr)):
                continue
            if attr == 'raw_data':
                continue
            value = getattr(self, attr)
            if isinstance(value, datetime):
                value = value.isoformat()
            result[attr] = value
        return result
    
    def to_json(self) -> str:
        """
        Serialize alarm to JSON string.
        
        Returns:
            JSON string representation.
        """
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
    
    def __str__(self) -> str:
        """String representation (alias for brief)."""
        return self.brief()
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(ne_name={self.ne_name!r}, severity={self.severity!r}, alarm_name={self.alarm_name!r})"


class BaseLink(ABC):
    """
    Base class for link/topology data from network management systems.

    Provides common fields and methods for link objects (physical links,
    IGP links, fibers, etc.).

    UUID fields (a_end_ne_id, z_end_ne_id, a_end_ltp_id, z_end_ltp_id) can be
    resolved to human-readable names using NceDataProvider.resolve_link_names()
    or by passing resolve_names=True to get_links()/get_fibers()/get_igp_links().
    When resolved, the corresponding *_name fields are populated.

    Example:
        # Names are None by default (only UUIDs available)
        link.a_end_ne_id    # "d0cc81df-b9f9-11ea-ad74-b008759ca76f"
        link.a_end_ne_name  # None

        # After resolve_link_names() or resolve_names=True:
        link.a_end_ne_name  # "IPBB_Naryn_NE40E-1"
        link.a_end_ltp_name # "GigabitEthernet1/0/0"
    """

    # Common fields — populated from API response
    res_id: Optional[str] = None
    name: Optional[str] = None
    a_end_ne_id: Optional[str] = None
    z_end_ne_id: Optional[str] = None
    a_end_ltp_id: Optional[str] = None
    z_end_ltp_id: Optional[str] = None
    operate_status: Optional[str] = None
    admin_status: Optional[str] = None

    # Resolved name fields — populated by NceDataProvider.resolve_link_names().
    # These are None until explicitly resolved via resolve_names=True or
    # a separate call to resolve_link_names().
    # Source: NE names from /network-elements, port names from /ltps.
    a_end_ne_name: Optional[str] = None
    z_end_ne_name: Optional[str] = None
    a_end_ltp_name: Optional[str] = None
    z_end_ltp_name: Optional[str] = None

    vendor_specific_info: Optional[Dict[str, Any]] = None
    raw_data: Optional[Dict[str, Any]] = None

    def __init__(self, data: Dict[str, Any]):
        """
        Initialize link from raw API data.

        Args:
            data: Raw link data from API response.
        """
        self.raw_data = data
        self._populate_from_data(data)

    @abstractmethod
    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        """Populate fields from raw API data. Must be implemented by subclasses."""
        pass

    def brief(self) -> str:
        """
        Get brief one-line representation of the link.

        Returns:
            String in format: "name | a_end_ne_id -> z_end_ne_id | status"
        """
        parts = [
            self.name or 'N/A',
            f"{self.a_end_ne_id or 'N/A'} -> {self.z_end_ne_id or 'N/A'}",
            self.operate_status or 'N/A'
        ]
        return ' | '.join(parts)

    def details(self) -> str:
        """
        Get detailed multi-line representation of the link.

        Returns:
            Formatted string with all link information.
        """
        lines = [
            "=" * 60,
            f"Link: {self.name or 'N/A'}",
            "=" * 60,
            f"  Resource ID:     {self.res_id or 'N/A'}",
            f"  A-End NE:        {self.a_end_ne_id or 'N/A'}",
            f"  Z-End NE:        {self.z_end_ne_id or 'N/A'}",
            f"  A-End Port:      {self.a_end_ltp_id or 'N/A'}",
            f"  Z-End Port:      {self.z_end_ltp_id or 'N/A'}",
            f"  Operate Status:  {self.operate_status or 'N/A'}",
            f"  Admin Status:    {self.admin_status or 'N/A'}",
            "=" * 60,
        ]
        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Convert link to dictionary."""
        result = {}
        for attr in dir(self):
            if attr.startswith('_') or callable(getattr(self, attr)):
                continue
            if attr == 'raw_data':
                continue
            result[attr] = getattr(self, attr)
        return result

    def to_json(self) -> str:
        """Serialize link to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def __str__(self) -> str:
        """String representation (alias for brief)."""
        return self.brief()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, res_id={self.res_id!r})"


class BasePort(ABC):
    """
    Base class for port/interface (LTP) data from network management systems.

    Provides common fields and methods for port objects (physical ports, logical
    interfaces, subinterfaces, channels, timeslots, etc.).

    Ports represent the termination points on network elements. Each port
    belongs to an NE (ne_id) and may have a parent port (parent_ltp_id) for
    hierarchical relationships (e.g. subinterface -> main interface).

    The ne_name field can be resolved using NceDataProvider.resolve_port_names()
    or by passing resolve_names=True to get_ports().

    Example:
        # Get all physical Ethernet ports on a specific NE
        ports = provider.get_ports(ne_id="...", is_physical=True,
                                   ltp_type_name="Ethernet")

        # After resolve: port.ne_name contains the NE name
        ports = provider.get_ports(ne_id="...", resolve_names=True)
        print(ports[0].ne_name)  # "IPBB_Naryn_NE40E-1"
    """

    # Identification
    res_id: Optional[str] = None
    name: Optional[str] = None
    native_name: Optional[str] = None
    ne_id: Optional[str] = None

    # Classification
    is_physical: Optional[bool] = None
    is_sub_ltp: Optional[bool] = None
    ltp_type_name: Optional[str] = None
    sc_ltp_type: Optional[str] = None
    port_type: Optional[int] = None
    ltp_role: Optional[str] = None

    # Status
    operate_status: Optional[str] = None
    admin_status: Optional[str] = None

    # Network
    bandwidth: Optional[float] = None
    addrv4: Optional[str] = None
    addrv4_mask: Optional[int] = None

    # Hierarchy
    card_id: Optional[str] = None
    slot_number: Optional[str] = None
    port_number: Optional[int] = None
    parent_ltp_id: Optional[str] = None

    # Description
    description: Optional[str] = None
    alias: Optional[str] = None
    user_label: Optional[str] = None
    remark: Optional[str] = None

    # Resolved name — populated by resolve_port_names() or resolve_names=True.
    # Source: NE names from /network-elements endpoint.
    ne_name: Optional[str] = None

    vendor_specific_info: Optional[Dict[str, Any]] = None
    raw_data: Optional[Dict[str, Any]] = None

    def __init__(self, data: Dict[str, Any]):
        """
        Initialize port from raw API data.

        Args:
            data: Raw port data from API response.
        """
        self.raw_data = data
        self._populate_from_data(data)

    @abstractmethod
    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        """Populate fields from raw API data. Must be implemented by subclasses."""
        pass

    def brief(self) -> str:
        """
        Get brief one-line representation of the port.

        Returns:
            String in format: "name | type | ne_id | status"
        """
        status = 'up' if self.operate_status == '0' else 'down' if self.operate_status == '1' else self.operate_status or 'unknown'
        ne = self.ne_name or self.ne_id or 'N/A'
        parts = [
            self.name or 'N/A',
            self.ltp_type_name or 'N/A',
            ne,
            status,
        ]
        return ' | '.join(parts)

    def details(self) -> str:
        """
        Get detailed multi-line representation of the port.

        Returns:
            Formatted string with all port information.
        """
        status = 'up' if self.operate_status == '0' else 'down' if self.operate_status == '1' else self.operate_status or 'unknown'
        ne = self.ne_name or self.ne_id or 'N/A'
        if self.ne_name and self.ne_id:
            ne = f"{self.ne_name} ({self.ne_id})"
        lines = [
            "=" * 60,
            f"Port: {self.name or 'N/A'}",
            "=" * 60,
            f"  Resource ID:     {self.res_id or 'N/A'}",
            f"  NE:              {ne}",
            f"  Type:            {self.ltp_type_name or 'N/A'}",
            f"  Physical:        {self.is_physical}",
            f"  Sub-interface:   {self.is_sub_ltp}",
            f"  Status:          {status}",
            f"  Bandwidth:       {self.bandwidth}",
            "=" * 60,
        ]
        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Convert port to dictionary."""
        result = {}
        for attr in dir(self):
            if attr.startswith('_') or callable(getattr(self, attr)):
                continue
            if attr == 'raw_data':
                continue
            value = getattr(self, attr)
            if isinstance(value, datetime):
                value = value.isoformat()
            result[attr] = value
        return result

    def to_json(self) -> str:
        """Serialize port to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def __str__(self) -> str:
        """String representation (alias for brief)."""
        return self.brief()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, ne_id={self.ne_id!r})"


class BaseNetworkElement(ABC):
    """
    Base class for network element data from management systems.

    Provides common fields and methods for Nokia NSP and Huawei NCE network elements.
    """

    # Common fields
    name: Optional[str] = None
    ip_address: Optional[str] = None
    element_type: Optional[str] = None
    managed_state: Optional[str] = None
    
    raw_data: Optional[Dict[str, Any]] = None
    
    def __init__(self, data: Dict[str, Any]):
        """
        Initialize network element from raw API data.
        
        Args:
            data: Raw network element data from API response.
        """
        self.raw_data = data
        self._populate_from_data(data)
    
    @abstractmethod
    def _populate_from_data(self, data: Dict[str, Any]) -> None:
        """Populate fields from raw API data. Must be implemented by subclasses."""
        pass
    
    def brief(self) -> str:
        """
        Get brief one-line representation of the network element.
        
        Returns:
            String in format: "name | ip_address | type | state"
        """
        parts = [
            self.name or 'N/A',
            self.ip_address or 'N/A',
            self.element_type or 'N/A',
            self.managed_state or 'N/A'
        ]
        return ' | '.join(parts)
    
    def details(self) -> str:
        """
        Get detailed multi-line representation of the network element.
        
        Returns:
            Formatted string with all element information.
        """
        lines = [
            "=" * 60,
            f"Network Element: {self.name or 'N/A'}",
            "=" * 60,
            f"  IP Address:    {self.ip_address or 'N/A'}",
            f"  Type:          {self.element_type or 'N/A'}",
            f"  Managed State: {self.managed_state or 'N/A'}",
            "=" * 60,
        ]
        return '\n'.join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert network element to dictionary."""
        result = {}
        for attr in dir(self):
            if attr.startswith('_') or callable(getattr(self, attr)):
                continue
            if attr == 'raw_data':
                continue
            result[attr] = getattr(self, attr)
        return result
    
    def to_json(self) -> str:
        """Serialize network element to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
    
    def __str__(self) -> str:
        """String representation (alias for brief)."""
        return self.brief()
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, ip_address={self.ip_address!r})"

