"""
Vendor-agnostic data containers для NETCONF-инициированного traceroute.

Парный к :mod:`ping`. Подход тот же — universal-контракт, vendor-парсинг в
nokia_ping.py / huawei_ping.py. RTT в миллисекундах. Nokia отдаёт UDP-probes
по умолчанию (port 33434), Huawei тоже UDP. ICMP-type/code заполняем когда
вендор отдал (Nokia это делает — type 3 / code 3 = port unreachable от
финального hop'а).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TracerouteRequest:
    """Параметры traceroute-теста.

    :param destination: IPv4 destination address (обязательно).
    :param vrf: Имя VRF / routing-instance. ``"Base"`` — global routing.
        ``None`` = vendor-default.
    :param source_address: Source IP для исходящих probes. ``None`` = vendor
        выбирает.
    :param first_ttl: минимальный TTL (Nokia: ``min-ttl``, Huawei: ``first-ttl``).
    :param max_ttl: максимальный TTL (Nokia: ``ttl``, Huawei: ``max-ttl``).
    :param probes_per_hop: количество probes на каждый hop (Nokia: ``probe-count``,
        Huawei: ``count``).
    :param packet_size: payload-size в байтах. ``None`` = vendor-default
        (Nokia 0 = ``minimum``, Huawei 12).
    :param timeout_ms: ожидание одного probe в **миллисекундах**. Билдер для
        Nokia конвертирует в ``wait`` (Nokia ждёт ``wait`` ms). Huawei ``timeout``
        тоже в ms.
    :param tos: ToS-байт IPv4. ``None`` = vendor-default.
    :param do_not_fragment: установить DF-бит. По умолчанию False.
    """

    destination: str
    vrf: Optional[str] = None
    source_address: Optional[str] = None
    first_ttl: int = 1
    max_ttl: int = 30
    probes_per_hop: int = 3
    packet_size: Optional[int] = None
    timeout_ms: int = 5000
    tos: Optional[int] = None
    do_not_fragment: bool = False


@dataclass
class TracerouteProbe:
    """Один probe внутри hop'а.

    :param probe_index: 1-based индекс probe внутри hop.
    :param success: True если получили reply (ICMP TTL-exceeded для transit
        hop'а или ICMP unreachable от destination, оба считаются success'ом
        с точки зрения "узнали кто там").
    :param rtt_ms: round-trip-time, миллисекунды.
    :param response_address: replier IP. ``None`` если probe не дошёл.
    :param error_kind: нормализованная причина неуспеха (см. PingProbe).
    :param raw_status: vendor-native статус.
    :param icmp_type / icmp_code: для Nokia (3/3 = destination port unreachable
        — финальный hop). Huawei не отдаёт. ``None`` если недоступно.
    """

    probe_index: int
    success: bool
    rtt_ms: Optional[float]
    response_address: Optional[str]
    error_kind: Optional[str]
    raw_status: str
    icmp_type: Optional[int] = None
    icmp_code: Optional[int] = None


@dataclass
class TracerouteHop:
    """Один hop трассы.

    :param hop_index: TTL-номер hop'а (1-based).
    :param probes: список :class:`TracerouteProbe`.
    :param aggregate_address: "лучший" replier (первый успешный probe). Удобно
        для печати таблицы ``hop|replier|rtt``. ``None`` если все probes
        упали в timeout.
    """

    hop_index: int
    probes: List[TracerouteProbe] = field(default_factory=list)
    aggregate_address: Optional[str] = None


@dataclass
class TracerouteResult:
    """Итог traceroute.

    :param hops: упорядоченный список :class:`TracerouteHop`.
    :param status: ``"completed"`` / ``"partial"`` / ``"failed"``.
    :param destination / source_address / vrf: эхо-копия запроса.
    :param vendor: ``"nokia"`` / ``"huawei"``.
    :param duration_ms: длительность теста.
    :param raw_response_xml: полный rpc-reply XML.
    """

    hops: List[TracerouteHop] = field(default_factory=list)
    status: str = "completed"
    destination: str = ""
    source_address: Optional[str] = None
    vrf: Optional[str] = None
    vendor: str = ""
    duration_ms: Optional[int] = None
    raw_response_xml: str = ""
