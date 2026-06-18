"""
Huawei VRP адаптеры для парсинга state-XML от
``urn:huawei:yang:huawei-diagnostic-tools`` (ping / traceroute).

Lifecycle async: action возвращает ``<ok/>``, далее polling ``<get>`` по
state-пути ``/diagnostic-tools/ipv4/ping-results/ping-result``. Этот модуль
парсит state-ответ (один polled snapshot), не сам action и не действие
удаления.

Wire-формат (probe 24 мая 2026 на боевом Huawei-роутере):

* ``rtt`` / ``rtt-min`` / ``rtt-max`` / ``average-rtt`` приходят в
  **миллисекундах** как целые. Возвращаем как есть (без деления).
* ``status``: ``processing`` / ``finished`` / ``error`` / прочее.
* ``error-type``: ``success`` / ``timeout`` / прочее — даёт нам базовый
  hint для error_kind когда per-detail success==False.
* Per-detail ``result-type``: ``success`` / ``timeout`` / unreachable варианты.
* ``system-time`` в ISO-8601 — берём как timestamp probe'а.
* Для traceroute использовать ``<hops>/<hop>/<probes>/<probe>``, а **не**
  ``<details>`` (там агрегат по hop'у без per-probe детализации).
"""

from __future__ import annotations

import logging
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


# ---- helpers (идентичны nokia_ping для самодостаточности модуля) -------- #
def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _strip_ns(tag: str) -> str:
    if not isinstance(tag, str):
        return tag
    if "}" in tag:
        tag = tag.split("}", 1)[1]
    if ":" in tag:
        tag = tag.split(":", 1)[1]
    return tag


def _clean_keys(node):
    if isinstance(node, dict):
        return {_strip_ns(k): _clean_keys(v) for k, v in node.items()
                if not (isinstance(k, str) and k.startswith("@xmlns"))}
    if isinstance(node, list):
        return [_clean_keys(item) for item in node]
    return node


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


# Маппинг Huawei result-type → universal error_kind.
_HUAWEI_RESULT_OK = "success"
_HUAWEI_RESULT_TO_ERROR_KIND = {
    "timeout": "timeout",
    "no-route": "unreachable",
    "host-unreachable": "unreachable",
    "net-unreachable": "unreachable",
    "protocol-unreachable": "unreachable",
    "port-unreachable": "unreachable",
    "destination-unreachable": "unreachable",
    "admin-prohibit": "admin-prohibited",
    "ttl-exceeded": "ttl-exceeded",
}


def _classify_result_type(result_type: Optional[str]) -> Tuple[bool, Optional[str]]:
    if result_type is None:
        return False, "other"
    rt = str(result_type).strip().lower()
    if rt == _HUAWEI_RESULT_OK:
        return True, None
    mapped = _HUAWEI_RESULT_TO_ERROR_KIND.get(rt)
    if mapped:
        return False, mapped
    return False, "other"


def _huawei_global_error_kind(error_type: Optional[str]) -> Optional[str]:
    """Маппинг top-level ``error-type`` Huawei → universal kind."""
    if not error_type:
        return None
    et = str(error_type).strip().lower()
    if et == "success":
        return None
    return _HUAWEI_RESULT_TO_ERROR_KIND.get(et, "other")


# ---- PING ---------------------------------------------------------------- #
def parse_huawei_ping_state(
    state_xml: str,
    request: PingRequest,
    test_name: str,
) -> PingResult:
    """Парсит один polled snapshot Huawei ping-result state.

    :param state_xml: сырой XML rpc-reply от ``<get>`` с фильтром по test-name.
    :param request: исходный запрос (для destination/vrf/source).
    :param test_name: имя теста (для логирования при ошибках).
    :return: :class:`PingResult` со статусом ``completed`` если ``status=finished``,
        иначе ``partial`` (state ещё пуст / processing).
    """
    import xmltodict

    raw_xml = state_xml or ""
    if not raw_xml:
        return _empty_ping_result(request, raw_xml, status="partial")

    try:
        parsed = xmltodict.parse(raw_xml)
    except Exception as exc:  # noqa: BLE001
        logger.error("Huawei ping(%s): не удалось распарсить state: %s", test_name, exc)
        return _empty_ping_result(request, raw_xml, status="failed")

    parsed = _clean_keys(parsed)

    # rpc-reply/data/diagnostic-tools/ipv4/ping-results/ping-result
    rpc_reply = parsed.get("rpc-reply", parsed)
    data = rpc_reply.get("data") if isinstance(rpc_reply, dict) else None
    if data is None:
        data = rpc_reply  # на случай если ncclient уже снял rpc-reply envelope
    if not isinstance(data, dict):
        return _empty_ping_result(request, raw_xml, status="partial")

    diag = data.get("diagnostic-tools") or {}
    ipv4 = diag.get("ipv4") or {}
    ping_results = ipv4.get("ping-results") or {}
    entries = _as_list(ping_results.get("ping-result"))

    # Найдём свой test-name (на случай если фильтр почему-то не сработал)
    entry = None
    for e in entries:
        if e and e.get("test-name") == test_name:
            entry = e
            break
    if entry is None and entries:
        entry = entries[0]

    if entry is None:
        # state ещё не появился — это нормально для первой пары polling-итераций
        return _empty_ping_result(request, raw_xml, status="partial")

    huawei_status = (entry.get("status") or "").strip().lower()
    huawei_error_type = entry.get("error-type")
    completed = huawei_status == "finished"

    sent = _to_int(entry.get("packet-send")) or 0
    received = _to_int(entry.get("packet-recv")) or 0
    lost = max(sent - received, 0)
    loss_pct = 0.0 if sent == 0 else round(lost * 100.0 / sent, 1)

    rtt_min = _to_float(entry.get("rtt-min"))
    rtt_avg = _to_float(entry.get("average-rtt"))
    rtt_max = _to_float(entry.get("rtt-max"))
    if received == 0:
        # Huawei ставит rtt-min/max/avg в 0 на негативе — убираем шум
        if rtt_min == 0.0:
            rtt_min = None
        if rtt_avg == 0.0:
            rtt_avg = None
        if rtt_max == 0.0:
            rtt_max = None

    # per-detail probes
    details = (entry.get("details") or {}).get("detail") or []
    probes: List[PingProbe] = []
    global_err = _huawei_global_error_kind(huawei_error_type)
    for d in _as_list(details):
        if not isinstance(d, dict):
            continue
        idx = _to_int(d.get("index")) or len(probes) + 1
        raw_status = d.get("result-type") or huawei_error_type or ""
        success, error_kind = _classify_result_type(d.get("result-type") or huawei_error_type)
        rtt_ms = _to_float(d.get("rtt")) if success else None
        ttl = _to_int(d.get("ttl")) if success else None
        response_address = d.get("ip-addr") if success else None
        if not success and error_kind is None:
            error_kind = global_err or "other"
        probes.append(PingProbe(
            sequence=idx,
            success=success,
            rtt_ms=rtt_ms,
            ttl=ttl,
            response_address=response_address,
            error_kind=error_kind,
            raw_status=str(raw_status),
            timestamp=d.get("system-time"),
        ))

    # duration
    duration_ms = None
    if probes and probes[0].timestamp and probes[-1].timestamp:
        duration_ms = _huawei_duration_ms(
            probes[0].timestamp, probes[-1].timestamp
        )

    success = received > 0
    if completed:
        result_status = "completed"
    elif huawei_status in ("error",):
        result_status = "failed"
    else:
        result_status = "partial"

    return PingResult(
        success=success,
        status=result_status,
        sent=sent,
        received=received,
        lost=lost,
        loss_percent=loss_pct,
        rtt_min_ms=rtt_min,
        rtt_avg_ms=rtt_avg,
        rtt_max_ms=rtt_max,
        rtt_stddev_ms=None,  # Huawei не отдаёт
        probes=probes,
        destination=request.destination,
        source_address=request.source_address,
        vrf=request.vrf,
        vendor="huawei",
        duration_ms=duration_ms,
        raw_response_xml=raw_xml,
    )


def _huawei_duration_ms(start_iso: str, end_iso: str) -> Optional[int]:
    """Считает миллисекунды между ISO-8601 ``2026-05-24T04:27:10Z``."""
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    try:
        s = datetime.strptime(start_iso, fmt)
        e = datetime.strptime(end_iso, fmt)
    except ValueError:
        return None
    delta = e - s
    return int(delta.total_seconds() * 1000)


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
        vendor="huawei",
        duration_ms=None,
        raw_response_xml=raw_xml,
    )


# ---- TRACEROUTE ---------------------------------------------------------- #
def parse_huawei_traceroute_state(
    state_xml: str,
    request: TracerouteRequest,
    test_name: str,
) -> TracerouteResult:
    """Парсит state-ответ Huawei trace-result.

    Использует ``<hops>/<hop>/<probes>/<probe>`` (per-probe), а не ``<details>``
    (агрегат по hop'у — там нет per-probe).
    """
    import xmltodict

    raw_xml = state_xml or ""
    if not raw_xml:
        return _empty_traceroute_result(request, raw_xml, status="partial")

    try:
        parsed = xmltodict.parse(raw_xml)
    except Exception as exc:  # noqa: BLE001
        logger.error("Huawei traceroute(%s): не удалось распарсить state: %s",
                     test_name, exc)
        return _empty_traceroute_result(request, raw_xml, status="failed")

    parsed = _clean_keys(parsed)
    rpc_reply = parsed.get("rpc-reply", parsed)
    data = rpc_reply.get("data") if isinstance(rpc_reply, dict) else None
    if data is None:
        data = rpc_reply
    if not isinstance(data, dict):
        return _empty_traceroute_result(request, raw_xml, status="partial")

    diag = data.get("diagnostic-tools") or {}
    ipv4 = diag.get("ipv4") or {}
    trace_results = ipv4.get("trace-results") or {}
    entries = _as_list(trace_results.get("trace-result"))

    entry = None
    for e in entries:
        if e and e.get("test-name") == test_name:
            entry = e
            break
    if entry is None and entries:
        entry = entries[0]

    if entry is None:
        return _empty_traceroute_result(request, raw_xml, status="partial")

    huawei_status = (entry.get("status") or "").strip().lower()
    completed = huawei_status == "finished"

    hops_section = entry.get("hops") or {}
    hop_entries = _as_list(hops_section.get("hop"))

    hops: List[TracerouteHop] = []
    for h in hop_entries:
        if not isinstance(h, dict):
            continue
        hop_index = _to_int(h.get("hop-index")) or len(hops) + 1
        probes_section = h.get("probes") or {}
        probe_entries = _as_list(probes_section.get("probe"))
        probes: List[TracerouteProbe] = []
        for p in probe_entries:
            if not isinstance(p, dict):
                continue
            p_idx = _to_int(p.get("probe-index")) or len(probes) + 1
            raw_status = p.get("result-type") or ""
            success, error_kind = _classify_result_type(raw_status)
            rtt_ms = _to_float(p.get("rtt")) if success else None
            response_address = p.get("replier") if success else None
            probes.append(TracerouteProbe(
                probe_index=p_idx,
                success=success,
                rtt_ms=rtt_ms,
                response_address=response_address,
                error_kind=error_kind,
                raw_status=str(raw_status),
                icmp_type=None,  # Huawei не отдаёт
                icmp_code=None,
            ))

        agg = next((pr.response_address for pr in probes if pr.success), None)
        hops.append(TracerouteHop(
            hop_index=hop_index,
            probes=probes,
            aggregate_address=agg,
        ))

    if completed:
        result_status = "completed"
    elif huawei_status == "error":
        result_status = "failed"
    else:
        result_status = "partial"

    return TracerouteResult(
        hops=hops,
        status=result_status,
        destination=request.destination,
        source_address=request.source_address,
        vrf=request.vrf,
        vendor="huawei",
        duration_ms=None,
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
        vendor="huawei",
        duration_ms=None,
        raw_response_xml=raw_xml,
    )
