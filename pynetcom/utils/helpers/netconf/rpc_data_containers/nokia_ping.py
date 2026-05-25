"""
Nokia SR OS адаптеры для парсинга rpc-reply от
``urn:nokia.com:sros:ns:yang:sr:oper-global`` (ping / traceroute).

Lifecycle на Nokia синхронный: один RPC ``<action>`` → один ``<rpc-reply>`` с
полным результатом. Никакого polling'а.

Важные детали wire-формата (зафиксированы probe'ом 24 мая 2026, артефакты
``network_entries/examples/probe_artifacts/nokia_v2_20260524_103350/``):

* ``round-trip-time`` приходит в **МИКРОСЕКУНДАХ**. Здесь делим на 1000.0
  чтобы получить миллисекунды в universal-контракте.
* Negative case (bad VRF, unreachable) **не** даёт ``rpc-error``: вендор
  возвращает успешный rpc-reply, а провал ICMP кодируется в
  ``<probe>/<status>`` и ``<summary>/<loss>=100.0``. Это нормальный путь
  и мы маппим ``<status>`` в ``error_kind``.
* ``start-time`` и ``end-time`` в ISO-8601 с точностью 0.1с — отдают
  длительность через простую разность.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import List, Optional, Tuple

from pynetcom.utils.helpers.netconf.rpc_data_containers.ping import (
    PingProbe,
    PingRequest,
    PingResult,
)
from pynetcom.utils.helpers.netconf.rpc_data_containers.traceroute import (
    TracerouteHop,
    TracerouteProbe,
    TracerouteRequest,
    TracerouteResult,
)

logger = logging.getLogger("pynetcom")


# ---- helpers -------------------------------------------------------------- #
def _as_list(value):
    """xmltodict для YANG-list с одной записью отдаёт dict, для нескольких — list.
    Нормализуем в list чтобы парсер был branch-free."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _strip_ns(tag: str) -> str:
    """``{ns}localname`` -> ``localname``, ``prefix:localname`` -> ``localname``.
    Используется чтобы не зависеть от того как xmltodict нанёс namespace-префиксы.
    """
    if not isinstance(tag, str):
        return tag
    if "}" in tag:
        tag = tag.split("}", 1)[1]
    if ":" in tag:
        tag = tag.split(":", 1)[1]
    return tag


def _clean_keys(node):
    """Рекурсивно убирает namespace-префиксы из ключей dict, чтобы парсер не
    зависел от того, выдал ли xmltodict ключ как ``destination`` или
    ``nokia:destination``. Не трогает значения (только ключи)."""
    if isinstance(node, dict):
        return {_strip_ns(k): _clean_keys(v) for k, v in node.items()
                if not (isinstance(k, str) and k.startswith("@xmlns"))}
    if isinstance(node, list):
        return [_clean_keys(item) for item in node]
    return node


def _find_first(node, name: str):
    """DFS-поиск первого ключа ``name`` (после _strip_ns) в произвольно вложенной
    dict/list структуре. Возвращает значение или None.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            if _strip_ns(k) == name:
                return v
        for v in node.values():
            found = _find_first(v, name)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_first(item, name)
            if found is not None:
                return found
    return None


def _to_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _us_to_ms(value) -> Optional[float]:
    """Nokia отдаёт round-trip-time в микросекундах. Конвертация в миллисекунды
    с округлением до 3 знаков (микросекундная точность сохраняется)."""
    n = _to_int(value)
    if n is None:
        return None
    return round(n / 1000.0, 3)


# Маппинг Nokia `<status>` → universal error_kind. См. probe artifacts.
_NOKIA_STATUS_OK = "response-received"
_NOKIA_STATUS_TO_ERROR_KIND = {
    "no-route-to-dest": "unreachable",
    "send-fail-undefined-service-id": "vrf-not-found",
    "request-timeout": "timeout",
    "request-timed-out": "timeout",       # ARP-таймаут в VPRN (сосед без хоста), probe 24.05.2026
    "timeout": "timeout",
    "source-ip-is-not-local": "bad-source",  # передан source_address не с интерфейса роутера, probe 24.05.2026
}


def _classify_status(raw_status: Optional[str]) -> Tuple[bool, Optional[str]]:
    """status → (success, error_kind)."""
    if raw_status is None:
        return False, "other"
    s = str(raw_status).strip().lower()
    if s == _NOKIA_STATUS_OK:
        return True, None
    mapped = _NOKIA_STATUS_TO_ERROR_KIND.get(s)
    if mapped:
        return False, mapped
    # неизвестный → other, raw_status сохраняется в PingProbe для отладки
    return False, "other"


def _duration_ms(start_iso: Optional[str], end_iso: Optional[str]) -> Optional[int]:
    """Считает миллисекунды между ISO-8601 строками типа ``2026-05-24T04:34:13.0Z``.
    Возвращает None если хоть один из аргументов невалиден.
    """
    if not start_iso or not end_iso:
        return None
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
    try:
        s = datetime.strptime(start_iso, fmt)
        e = datetime.strptime(end_iso, fmt)
    except ValueError:
        # Попытка без долей секунды (``2026-05-24T04:34:13Z``)
        try:
            fmt2 = "%Y-%m-%dT%H:%M:%SZ"
            s = datetime.strptime(start_iso, fmt2)
            e = datetime.strptime(end_iso, fmt2)
        except ValueError:
            return None
    delta = e - s
    return int(delta.total_seconds() * 1000)


# ---- PING ---------------------------------------------------------------- #
def parse_nokia_ping_response(
    rpc_reply_xml: str,
    request: PingRequest,
) -> PingResult:
    """Парсит один ``<rpc-reply>`` от Nokia ping action в :class:`PingResult`.

    :param rpc_reply_xml: сырой XML rpc-reply (как строка).
    :param request: исходный :class:`PingRequest` — нужен чтобы заполнить
        destination/source/vrf в result когда rpc-reply их не возвращает явно
        (Nokia в test-parameters возвращает все, но защищаемся на случай
        обрезанных ответов).
    :return: :class:`PingResult` с заполненными probe'ами и summary.

    Принимает XML строку (как отдаёт ncclient ``reply.xml``). xmltodict внутри.
    """
    import xmltodict  # локальный импорт — модуль грузится только когда нужно

    raw_xml = rpc_reply_xml or ""
    if not raw_xml:
        return _empty_ping_result(request, raw_xml, status="failed")

    try:
        parsed = xmltodict.parse(raw_xml)
    except Exception as exc:  # noqa: BLE001
        logger.error("Nokia ping: не удалось распарсить rpc-reply: %s", exc)
        return _empty_ping_result(request, raw_xml, status="failed")

    parsed = _clean_keys(parsed)

    # Корень обычно "rpc-reply"; берём содержимое
    rpc_reply = parsed.get("rpc-reply", parsed)
    status = rpc_reply.get("status", "completed")
    start_time = rpc_reply.get("start-time")
    end_time = rpc_reply.get("end-time")
    results = rpc_reply.get("results") or {}

    # test-parameters → восстановим destination/source/router-instance
    tp = results.get("test-parameters") or {}
    destination = tp.get("destination") or request.destination
    vrf = tp.get("router-instance") or request.vrf
    source_address = tp.get("source-address") or request.source_address

    # per-probe
    probes: List[PingProbe] = []
    for probe in _as_list(results.get("probe")):
        sequence = _to_int(probe.get("probe-index")) or len(probes) + 1
        raw_status = probe.get("status") or ""
        success, error_kind = _classify_status(raw_status)
        rtt_ms = _us_to_ms(probe.get("round-trip-time")) if success else None

        response_packet = probe.get("response-packet") or {}
        ttl = _to_int(response_packet.get("ttl")) if success else None
        response_address = response_packet.get("source-address") if success else None

        probes.append(PingProbe(
            sequence=sequence,
            success=success,
            rtt_ms=rtt_ms,
            ttl=ttl,
            response_address=response_address,
            error_kind=error_kind,
            raw_status=str(raw_status),
            timestamp=None,  # Nokia per-probe не отдаёт
        ))

    # summary / statistics
    summary = results.get("summary") or {}
    statistics = summary.get("statistics") or {}
    packets = statistics.get("packets") or {}
    sent = _to_int(packets.get("sent")) or 0
    received = _to_int(packets.get("received")) or 0
    loss_pct = _to_float(packets.get("loss"))
    if loss_pct is None and sent:
        loss_pct = round((sent - received) * 100.0 / sent, 1)
    elif loss_pct is None:
        loss_pct = 0.0
    lost = sent - received if sent and received is not None else \
        sum(1 for p in probes if not p.success)

    rtt_section = statistics.get("round-trip-time") or {}
    rtt_min = _us_to_ms(rtt_section.get("minimum"))
    rtt_avg = _us_to_ms(rtt_section.get("average"))
    rtt_max = _us_to_ms(rtt_section.get("maximum"))
    rtt_std = _us_to_ms(rtt_section.get("standard-deviation"))

    # На негативе Nokia ставит min/avg/max = 0; делаем None для чистоты
    if rtt_min == 0.0 and received == 0:
        rtt_min = rtt_avg = rtt_max = None
        rtt_std = None

    result_success = received > 0
    result_status = "completed" if status == "completed" else "partial"

    return PingResult(
        success=result_success,
        status=result_status,
        sent=sent,
        received=received,
        lost=max(lost, 0),
        loss_percent=float(loss_pct or 0.0),
        rtt_min_ms=rtt_min,
        rtt_avg_ms=rtt_avg,
        rtt_max_ms=rtt_max,
        rtt_stddev_ms=rtt_std,
        probes=probes,
        destination=destination or "",
        source_address=source_address,
        vrf=vrf,
        vendor="nokia",
        duration_ms=_duration_ms(start_time, end_time),
        raw_response_xml=raw_xml,
    )


def _empty_ping_result(request: PingRequest, raw_xml: str, status: str) -> PingResult:
    return PingResult(
        success=False,
        status=status,
        sent=0,
        received=0,
        lost=0,
        loss_percent=0.0,
        rtt_min_ms=None,
        rtt_avg_ms=None,
        rtt_max_ms=None,
        rtt_stddev_ms=None,
        probes=[],
        destination=request.destination,
        source_address=request.source_address,
        vrf=request.vrf,
        vendor="nokia",
        duration_ms=None,
        raw_response_xml=raw_xml,
    )


# ---- TRACEROUTE ---------------------------------------------------------- #
def parse_nokia_traceroute_response(
    rpc_reply_xml: str,
    request: TracerouteRequest,
) -> TracerouteResult:
    """Парсит rpc-reply от Nokia traceroute action.

    XML структура (см. probe ``03_traceroute_minimal_response.xml``):
      results/hop[]/probe[]/{probe-index, status, round-trip-time, size,
                              response-packet/{icmp-type, icmp-code, source-address}}
    """
    import xmltodict

    raw_xml = rpc_reply_xml or ""
    if not raw_xml:
        return _empty_traceroute_result(request, raw_xml, status="failed")

    try:
        parsed = xmltodict.parse(raw_xml)
    except Exception as exc:  # noqa: BLE001
        logger.error("Nokia traceroute: не удалось распарсить rpc-reply: %s", exc)
        return _empty_traceroute_result(request, raw_xml, status="failed")

    parsed = _clean_keys(parsed)
    rpc_reply = parsed.get("rpc-reply", parsed)
    status = rpc_reply.get("status", "completed")
    start_time = rpc_reply.get("start-time")
    end_time = rpc_reply.get("end-time")
    results = rpc_reply.get("results") or {}

    tp = results.get("test-parameters") or {}
    destination = tp.get("destination") or request.destination
    vrf = tp.get("router-instance") or request.vrf
    source_address = tp.get("source-address") or request.source_address

    hops: List[TracerouteHop] = []
    for hop in _as_list(results.get("hop")):
        hop_index = _to_int(hop.get("hop-index")) or len(hops) + 1
        probes: List[TracerouteProbe] = []
        for probe in _as_list(hop.get("probe")):
            p_idx = _to_int(probe.get("probe-index")) or len(probes) + 1
            raw_status = probe.get("status") or ""
            success, error_kind = _classify_status(raw_status)
            rtt_ms = _us_to_ms(probe.get("round-trip-time")) if success else None
            rp = probe.get("response-packet") or {}
            response_address = rp.get("source-address") if success else None
            icmp_type = _to_int(rp.get("icmp-type")) if success else None
            icmp_code = _to_int(rp.get("icmp-code")) if success else None

            probes.append(TracerouteProbe(
                probe_index=p_idx,
                success=success,
                rtt_ms=rtt_ms,
                response_address=response_address,
                error_kind=error_kind,
                raw_status=str(raw_status),
                icmp_type=icmp_type,
                icmp_code=icmp_code,
            ))

        # aggregate_address = первый успешный probe или None
        agg = next((p.response_address for p in probes if p.success), None)
        hops.append(TracerouteHop(
            hop_index=hop_index,
            probes=probes,
            aggregate_address=agg,
        ))

    result_status = "completed" if status == "completed" else "partial"

    return TracerouteResult(
        hops=hops,
        status=result_status,
        destination=destination or "",
        source_address=source_address,
        vrf=vrf,
        vendor="nokia",
        duration_ms=_duration_ms(start_time, end_time),
        raw_response_xml=raw_xml,
    )


def _empty_traceroute_result(
    request: TracerouteRequest, raw_xml: str, status: str,
) -> TracerouteResult:
    return TracerouteResult(
        hops=[],
        status=status,
        destination=request.destination,
        source_address=request.source_address,
        vrf=request.vrf,
        vendor="nokia",
        duration_ms=None,
        raw_response_xml=raw_xml,
    )
