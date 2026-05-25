"""
Vendor-agnostic data containers для NETCONF-инициированного ping.

OpenConfig / IETF не стандартизировали "operational ping" YANG-модель в виде,
который поддерживают наши вендоры (Nokia ``nokia-oper-global``, Huawei
``huawei-diagnostic-tools`` — оба private augmentations). Поэтому собственный
universal-контракт: AI-боту, REST-клиенту, CLI-консоли важно видеть
**нормализованные** поля без vendor-парсинга.

Единицы измерения — миллисекунды. Vendor-парсеры обязаны привести RTT к ms:
  * Nokia state — round-trip-time в **микросекундах**, делим на 1000.0
  * Huawei state — round-trip-time в **миллисекундах** как есть.

PingRequest и PingResult совместимы с :func:`dataclasses.asdict` для лёгкой
JSON-сериализации в bts_api/telerobot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PingRequest:
    """Параметры одного ICMP echo-теста с роутера.

    :param destination: IPv4 destination address (обязательно).
    :param vrf: Имя VRF / routing-instance. ``"Base"`` — global routing на обоих
        вендорах. ``None`` = не передавать (vendor возьмёт умолчание, обычно Base).
    :param source_address: source IP для исходящих ICMP echo. ``None`` = vendor
        выбирает сам (как правило, primary IP исходящего интерфейса).
    :param count: количество echo-запросов (Nokia: ``count``, Huawei: ``packet-count``).
    :param packet_size: payload-size в байтах (Nokia: ``size``, Huawei: ``packet-size``).
    :param interval_ms: пауза между пингами в **миллисекундах**. Билдер для
        Nokia делит на 1000 (там секунды, **минимум 1с** — Nokia YANG не
        принимает sub-second интервалы; значение ``<1000`` округлится до 1с).
        Huawei принимает мс как-есть (минимум 1мс).
    :param timeout_ms: ожидание одного echo-reply в **миллисекундах**.
        Аналогично Nokia: минимум 1с, Huawei: как есть.
    :param ttl: начальный TTL IP-заголовка.
    :param do_not_fragment: установить DF-бит. По умолчанию False.
    :param tos: ToS-байт IPv4 (0..255). ``None`` = vendor-default.
    """

    destination: str
    vrf: Optional[str] = None
    source_address: Optional[str] = None
    count: int = 5
    packet_size: int = 64
    interval_ms: int = 1000
    timeout_ms: int = 2000
    ttl: int = 64
    do_not_fragment: bool = False
    tos: Optional[int] = None


@dataclass
class PingProbe:
    """Один echo-probe внутри :class:`PingResult`.

    :param sequence: 1-based порядковый номер probe'а внутри теста.
    :param success: True если получили ICMP echo reply.
    :param rtt_ms: round-trip-time, миллисекунды. ``None`` если probe не дошёл.
    :param ttl: TTL принятого IP-пакета (с ответом). ``None`` если ответа нет.
    :param response_address: IP-адрес отправителя echo reply. ``None`` если не дошло.
    :param error_kind: нормализованная причина неуспеха:
        ``timeout`` | ``unreachable`` | ``vrf-not-found`` |
        ``bad-source`` (source_address не с интерфейса роутера) |
        ``admin-prohibited`` | ``other`` | ``None`` (success).
    :param raw_status: то что прислал вендор (``response-received`` /
        ``no-route-to-dest`` / Huawei ``result-type=success`` и т.п.) — для
        отладки и трассировки экзотики.
    :param timestamp: ISO-8601 строка вендора (Huawei ``system-time``) или
        ``None`` (Nokia на per-probe не отдаёт).
    """

    sequence: int
    success: bool
    rtt_ms: Optional[float]
    ttl: Optional[int]
    response_address: Optional[str]
    error_kind: Optional[str]
    raw_status: str
    timestamp: Optional[str] = None


@dataclass
class PingResult:
    """Итог выполнения :class:`PingRequest` на устройстве.

    :param success: True если ≥1 probe.success. Удобно для быстрой проверки
        "хоть один пакет дошёл".
    :param status: ``"completed"`` (получили финальный summary) /
        ``"partial"`` (polling timeout на Huawei, отдаём что есть) /
        ``"failed"`` (state ``error`` от вендора).
    :param sent: количество отправленных echo (из summary).
    :param received: количество полученных echo reply.
    :param lost: ``sent - received`` если оба известны, иначе ``len([p for p in probes if not p.success])``.
    :param loss_percent: 0.0..100.0.
    :param rtt_min_ms / rtt_avg_ms / rtt_max_ms: агрегированные RTT в ms.
    :param rtt_stddev_ms: только Nokia (отдаёт standard-deviation в µs). На
        Huawei всегда ``None``.
    :param probes: список :class:`PingProbe`. Может быть пустым если вендор
        не отдал per-probe детализацию (особенно partial state).
    :param destination / source_address / vrf: эхо-копия из :class:`PingRequest`
        — удобно когда result сериализуется отдельно от request.
    :param vendor: ``"nokia"`` / ``"huawei"``.
    :param duration_ms: длительность выполнения теста (end-time minus start-time
        для Nokia, ``None`` если не разобрали).
    :param raw_response_xml: полный rpc-reply XML (для отладки / телерасследования
        AI-агентом). Не сериализовать в публичный API без редактирования.
    """

    success: bool
    status: str
    sent: int
    received: int
    lost: int
    loss_percent: float
    rtt_min_ms: Optional[float]
    rtt_avg_ms: Optional[float]
    rtt_max_ms: Optional[float]
    rtt_stddev_ms: Optional[float]
    probes: List[PingProbe] = field(default_factory=list)
    destination: str = ""
    source_address: Optional[str] = None
    vrf: Optional[str] = None
    vendor: str = ""
    duration_ms: Optional[int] = None
    raw_response_xml: str = ""
