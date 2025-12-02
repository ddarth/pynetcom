"""
Base classes for REST API data filtering.
"""

from typing import List, Dict, Any, Tuple, TypeVar, Optional, Callable
from datetime import datetime
from copy import deepcopy

T = TypeVar('T')


class RestNMSDataFilter:
    """
    Universal data filter with builder pattern.
    
    Supports filtering by field values (exclude/include) and time ranges.
    All field names use snake_case convention.
    
    Example:
        filter = DataFilter()
        filter.exclude(severity=['cleared', 'warning'], alarm_name=['LinkDown'])
        filter.include(source_type=['nfmp'])
        filter.time_range(last_time_detected=(start_date, end_date))
        
        filtered_data = filter.apply(alarms)
    """
    
    def __init__(self):
        self._exclude_rules: Dict[str, List[Any]] = {}
        self._include_rules: Dict[str, List[Any]] = {}
        self._time_ranges: Dict[str, Tuple[Optional[datetime], Optional[datetime]]] = {}
    
    def exclude(self, **kwargs) -> 'RestNMSDataFilter':
        """
        Exclude records where field values match any of the specified values.
        
        Args:
            **kwargs: Field names and lists of values to exclude.
                      Example: severity=['cleared', 'warning'], alarm_name=['LinkDown']
        
        Returns:
            Self for method chaining.
        """
        for field, values in kwargs.items():
            if not isinstance(values, (list, tuple)):
                values = [values]
            if field not in self._exclude_rules:
                self._exclude_rules[field] = []
            self._exclude_rules[field].extend(values)
        return self
    
    def include(self, **kwargs) -> 'RestNMSDataFilter':
        """
        Include only records where field values match any of the specified values.
        
        Args:
            **kwargs: Field names and lists of values to include.
                      Example: severity=['major', 'critical']
        
        Returns:
            Self for method chaining.
        """
        for field, values in kwargs.items():
            if not isinstance(values, (list, tuple)):
                values = [values]
            if field not in self._include_rules:
                self._include_rules[field] = []
            self._include_rules[field].extend(values)
        return self
    
    def time_range(self, **kwargs) -> 'RestNMSDataFilter':
        """
        Filter records by time range for datetime fields.
        
        Args:
            **kwargs: Field names and tuples of (start, end) datetime.
                      Either start or end can be None for open-ended ranges.
                      Example: last_time_detected=(start_date, end_date)
                               time_created=(start_date, None)  # from start onwards
        
        Returns:
            Self for method chaining.
        """
        for field, time_tuple in kwargs.items():
            if isinstance(time_tuple, tuple) and len(time_tuple) == 2:
                start, end = time_tuple
                self._time_ranges[field] = (start, end)
            else:
                raise ValueError(f"time_range expects tuple (start, end), got {type(time_tuple)}")
        return self
    
    def _get_field_value(self, item: Any, field: str) -> Any:
        """Get field value from item (supports both dict and object attributes)."""
        if isinstance(item, dict):
            return item.get(field)
        return getattr(item, field, None)
    
    def _normalize_value(self, value: Any) -> Any:
        """Normalize value for comparison (lowercase strings)."""
        if isinstance(value, str):
            return value.lower()
        return value
    
    def _check_exclude(self, item: Any) -> bool:
        """Check if item should be excluded. Returns True if item passes (not excluded)."""
        for field, values in self._exclude_rules.items():
            item_value = self._get_field_value(item, field)
            normalized_item_value = self._normalize_value(item_value)
            normalized_values = [self._normalize_value(v) for v in values]
            if normalized_item_value in normalized_values:
                return False
        return True
    
    def _check_include(self, item: Any) -> bool:
        """Check if item should be included. Returns True if item passes."""
        if not self._include_rules:
            return True
        
        for field, values in self._include_rules.items():
            item_value = self._get_field_value(item, field)
            normalized_item_value = self._normalize_value(item_value)
            normalized_values = [self._normalize_value(v) for v in values]
            if normalized_item_value in normalized_values:
                return True
        return False
    
    def _make_naive(self, dt: datetime) -> datetime:
        """Convert datetime to naive (strip timezone, keeping UTC time)."""
        if dt is None:
            return None
        if dt.tzinfo is not None:
            from datetime import timezone
            # Convert to UTC first, then strip timezone
            dt_utc = dt.astimezone(timezone.utc)
            return dt_utc.replace(tzinfo=None)
        return dt
    
    def _check_time_range(self, item: Any) -> bool:
        """Check if item falls within time ranges. Returns True if item passes."""
        for field, (start, end) in self._time_ranges.items():
            item_value = self._get_field_value(item, field)
            
            if item_value is None:
                return False
            
            # Convert to datetime if needed
            if isinstance(item_value, (int, float)):
                # Assume milliseconds timestamp (convert to naive UTC)
                item_value = datetime.utcfromtimestamp(item_value / 1000)
            elif isinstance(item_value, str):
                try:
                    parsed = datetime.fromisoformat(item_value.replace('Z', '+00:00'))
                    # Convert to naive for comparison
                    item_value = self._make_naive(parsed)
                except ValueError:
                    return False
            elif isinstance(item_value, datetime):
                # Convert to naive for comparison
                item_value = self._make_naive(item_value)
            
            # Normalize filter values to naive as well
            start_naive = self._make_naive(start) if start else None
            end_naive = self._make_naive(end) if end else None
            
            if start_naive is not None and item_value < start_naive:
                return False
            if end_naive is not None and item_value > end_naive:
                return False
        
        return True
    
    def apply(self, data: List[T]) -> List[T]:
        """
        Apply all filters to the data.
        
        Args:
            data: List of items to filter (dicts or objects with attributes).
        
        Returns:
            Filtered list of items.
        """
        result = []
        for item in data:
            if self._check_exclude(item) and self._check_include(item) and self._check_time_range(item):
                result.append(item)
        return result
    
    def reset(self) -> 'RestNMSDataFilter':
        """Reset all filter rules."""
        self._exclude_rules.clear()
        self._include_rules.clear()
        self._time_ranges.clear()
        return self
    
    def copy(self) -> 'RestNMSDataFilter':
        """Create a copy of this filter."""
        new_filter = DataFilter()
        new_filter._exclude_rules = deepcopy(self._exclude_rules)
        new_filter._include_rules = deepcopy(self._include_rules)
        new_filter._time_ranges = deepcopy(self._time_ranges)
        return new_filter
    
    def __repr__(self) -> str:
        parts = []
        if self._exclude_rules:
            parts.append(f"exclude={self._exclude_rules}")
        if self._include_rules:
            parts.append(f"include={self._include_rules}")
        if self._time_ranges:
            parts.append(f"time_range={self._time_ranges}")
        return f"DataFilter({', '.join(parts)})"

