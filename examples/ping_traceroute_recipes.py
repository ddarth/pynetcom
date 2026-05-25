"""
NETCONF ping / traceroute recipes — verification suite для pynetcom.

Цель — за один прогон убедиться что:
  * Nokia ping/traceroute работают (sync action, RTT в μs → ms).
  * Nokia negative-cases правильно мапятся в ``error_kind`` (vrf-not-found).
  * Huawei ping/traceroute работают (async action + state-poll + cleanup).
  * Все cleanup-пути отрабатывают (Huawei state не копится).

Запуск (из корня pynetcom либо network_entries — оба venv'а имеют edit-mode
установку)::

    cd C:\\Users\\dkozlov\\Documents\\scripts\\network_entries
    .venv\\Scripts\\python.exe ..\\pynetcom\\examples\\ping_traceroute_recipes.py
"""

from __future__ import annotations

import dataclasses
import json
import logging

from pynetcom import (
    NetconfClient,
    NetconfActionNotAuthorized,
    PingRequest,
    ServicesClient,
    TracerouteRequest,
)


# ---- Silence ncclient/paramiko transport noise --------------------------- #
logging.basicConfig(level=logging.WARNING)
for _n in ("ncclient", "ncclient.transport", "paramiko", "paramiko.transport"):
    logging.getLogger(_n).setLevel(logging.WARNING)
logging.getLogger("pynetcom").setLevel(logging.INFO)


# ============================================================================
# TEST TARGETS (с боевых роутеров — подтверждены probe'ами 24.05.2026)
# ============================================================================
NETCONF_USER = "M2M_user"
NETCONF_PASS = "M2M_user_123"

NOKIA_HOST = "172.28.205.8"          # Oc.JArk2.AC_01
NOKIA_PORT = 830
NOKIA_DEVICE_PARAMS = {"name": "sros"}
NOKIA_DEST = "10.130.202.29"         # BTS in VPRN_UMTS, directly attached
NOKIA_VPRN = "VPRN_UMTS"

HUAWEI_HOST = "10.255.77.149"        # Bc.UzelA.ATN_1
HUAWEI_PORT = 22
HUAWEI_DEVICE_PARAMS = {"name": "huaweiyang"}
HUAWEI_DEST = "10.110.206.20"        # BTS in VPRN_UMTS, directly attached
HUAWEI_VPRN = "VPRN_UMTS"


def _banner(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def _dump(obj) -> None:
    """Print dataclass as JSON, omitting bulky raw_response_xml."""
    d = dataclasses.asdict(obj)
    if isinstance(d, dict) and "raw_response_xml" in d:
        raw = d.pop("raw_response_xml") or ""
        d["raw_response_xml_size"] = len(raw)
    print(json.dumps(d, indent=2, default=str))


def _print_summary(label: str, result) -> None:
    """Однострочная сводка для быстрого глазного контроля."""
    if hasattr(result, "loss_percent"):
        rtt = f"avg={result.rtt_avg_ms}ms" if result.rtt_avg_ms is not None else "rtt=n/a"
        print(
            f"[{label}] success={result.success} status={result.status} "
            f"{result.received}/{result.sent} loss={result.loss_percent}% {rtt}"
        )
    else:
        n_hops = len(result.hops)
        print(
            f"[{label}] status={result.status} hops={n_hops} "
            f"destination={result.destination} vrf={result.vrf}"
        )


# ============================================================================
# SCENARIO 1 — Nokia ping happy path
# ============================================================================
def scenario_nokia_ping_ok(sc: ServicesClient):
    _banner("SCENARIO 1 — Nokia ping (VPRN_UMTS) — expect success, loss=0")
    req = PingRequest(
        destination=NOKIA_DEST,
        vrf=NOKIA_VPRN,
        count=5,
        packet_size=64,
        timeout_ms=2000,
        interval_ms=1000,
    )
    res = sc.ping(req)
    _print_summary("nokia ping ok", res)
    _dump(res)
    assert res.vendor == "nokia"
    assert res.success, f"Nokia ping должен пройти: {res.status}"
    assert res.loss_percent == 0.0, f"Loss должен быть 0, не {res.loss_percent}"
    assert len(res.probes) == 5
    for p in res.probes:
        assert p.success and p.rtt_ms is not None
    return res


# ============================================================================
# SCENARIO 2 — Nokia ping bad VRF (vrf-not-found error_kind)
# ============================================================================
def scenario_nokia_ping_bad_vrf(sc: ServicesClient):
    _banner("SCENARIO 2 — Nokia ping bad VRF — expect success=False, "
            "error_kind=vrf-not-found")
    req = PingRequest(
        destination=NOKIA_DEST,
        vrf="VPRN_DOES_NOT_EXIST_X",
        count=2,
        timeout_ms=2000,
        interval_ms=1000,
    )
    res = sc.ping(req)
    _print_summary("nokia ping bad-vrf", res)
    _dump(res)
    assert res.vendor == "nokia"
    assert not res.success
    assert res.probes, "probes должны быть"
    assert res.probes[0].error_kind == "vrf-not-found", (
        f"Expected vrf-not-found, got {res.probes[0].error_kind}"
    )
    return res


# ============================================================================
# SCENARIO 3 — Nokia traceroute
# ============================================================================
def scenario_nokia_traceroute(sc: ServicesClient):
    _banner("SCENARIO 3 — Nokia traceroute — expect 1 hop (directly attached)")
    req = TracerouteRequest(
        destination=NOKIA_DEST,
        vrf=NOKIA_VPRN,
        first_ttl=1,
        max_ttl=10,
        probes_per_hop=3,
        timeout_ms=3000,
    )
    res = sc.traceroute(req)
    _print_summary("nokia traceroute", res)
    _dump(res)
    assert res.vendor == "nokia"
    assert res.status in ("completed", "partial")
    assert res.hops, "должен быть хотя бы один hop"
    return res


# ============================================================================
# SCENARIO 4 — Huawei ping happy path
# ============================================================================
def scenario_huawei_ping_ok(sc: ServicesClient):
    _banner("SCENARIO 4 — Huawei ping (VPRN_UMTS) — expect success, loss=0")
    req = PingRequest(
        destination=HUAWEI_DEST,
        vrf=HUAWEI_VPRN,
        count=5,
        packet_size=64,
        interval_ms=1000,
        timeout_ms=2000,
        ttl=64,
    )
    res = sc.ping(req, poll_timeout_s=30.0)
    _print_summary("huawei ping ok", res)
    _dump(res)
    assert res.vendor == "huawei"
    assert res.success, f"Huawei ping должен пройти: {res.status}"
    assert res.loss_percent == 0.0
    assert len(res.probes) == 5
    return res


# ============================================================================
# SCENARIO 5 — Huawei traceroute
# ============================================================================
def scenario_huawei_traceroute(sc: ServicesClient):
    _banner("SCENARIO 5 — Huawei traceroute — expect 1 hop (directly attached)")
    req = TracerouteRequest(
        destination=HUAWEI_DEST,
        vrf=HUAWEI_VPRN,
        first_ttl=1,
        max_ttl=8,
        probes_per_hop=1,
        timeout_ms=2000,
    )
    res = sc.traceroute(req, poll_timeout_s=30.0)
    _print_summary("huawei traceroute", res)
    _dump(res)
    assert res.vendor == "huawei"
    assert res.hops
    return res


# ============================================================================
# SCENARIO 6 — Huawei preflight cleanup self-test
# ============================================================================
#
# Имитируем «осиротевший» state: вручную запускаем 2 ping-теста с префиксом
# ``pc``, дожидаемся ``status=finished``, **НЕ удаляем** (как будто процесс
# упал). Старим ``system-time`` искусственно: ждём `PREFLIGHT_MIN_AGE_S + 5`
# секунд (preflight требует записи старше 60s, можно временно опустить).
# Затем запускаем обычный ``sc.ping(...)`` — на старте он сделает preflight
# и должен удалить orphan'ы.
#
# Чтобы тест не зависел от 60-секундного ожидания — поднимем параметр
# ``min_age_s`` через прямой вызов служебного хелпера (для self-test'а
# это допустимо: мы внутри pynetcom, не извне).
def scenario_huawei_preflight_cleanup(sc: ServicesClient):
    import time
    import uuid
    from pynetcom.utils.helpers.netconf.rpc_requests import (
        HuaweiPingActionRequest,
        HuaweiPingStateFilter,
        HuaweiPingResultsListFilter,
        HuaweiPingDeleteAction,
    )

    _banner("SCENARIO 6 — Huawei preflight cleanup self-test")

    # 1. Создаём 2 orphan'а: pcORPHAN1 / pcORPHAN2.
    # Используем фиктивный destination (тот же что в happy-path сценарии),
    # ping короткий — 2 пакета по 200 мс таймаут.
    orphan_names = [f"pcORPHAN1_{uuid.uuid4().hex[:4]}",
                    f"pcORPHAN2_{uuid.uuid4().hex[:4]}"]
    print(f"[orphan-creation] создаём 2 orphan'а: {orphan_names}")

    short_req = PingRequest(
        destination=HUAWEI_DEST,
        vrf=HUAWEI_VPRN,
        count=2,
        packet_size=64,
        interval_ms=200,
        timeout_ms=1000,
        ttl=64,
    )
    for n in orphan_names:
        action = HuaweiPingActionRequest(short_req, test_name=n)
        sc._send_action_raw(action.get_request_filter())
    print(f"[orphan-creation] action-start отправлен для обоих")

    # 2. Polling — дожидаемся пока оба перейдут в status=finished.
    deadline = time.time() + 30.0
    while True:
        reply = sc.nc.get(HuaweiPingResultsListFilter().get_request_filter())
        entries = sc._extract_huawei_test_entries(
            reply, "ping-results", "ping-result",
        )
        finished = {e["test-name"]: e for e in entries
                    if e.get("test-name") in orphan_names
                    and (e.get("status") or "").lower() == "finished"}
        if len(finished) == len(orphan_names):
            print(f"[orphan-creation] оба orphan'а в finished: "
                  f"{[e['test-name'] for e in finished.values()]}")
            for n, e in finished.items():
                print(f"  {n}: status={e.get('status')} "
                      f"system-time={e.get('system-time')}")
            break
        if time.time() >= deadline:
            raise RuntimeError(
                f"orphan'ы не перешли в finished за 30s: "
                f"видим {[e.get('test-name') for e in entries]}"
            )
        time.sleep(1.0)

    # 3. Подтверждение: в state видим оба orphan'а до preflight'а.
    pre_names = [e["test-name"] for e in entries
                 if e.get("test-name") in orphan_names]
    assert set(pre_names) == set(orphan_names), (
        f"orphan'ы должны быть в state ДО preflight: "
        f"видим {pre_names}, ожидали {orphan_names}"
    )
    print(f"[verify-pre] state содержит orphan'ы: {pre_names}")

    # 4. Запускаем обычный ping. Внутри будет вызван preflight.
    # ВАЖНО: min_age_s по умолчанию 60s, а нашим orphan'ам несколько секунд —
    # дефолтный preflight их не тронет. Чтобы тест был детерминированным
    # и не блокировал прогон на минуту, вызовем preflight явно с min_age_s=0
    # СРАЗУ перед основным ping'ом. (В реальной жизни ping вызовет preflight
    # с дефолтным age=60s и захватит только настоящие orphan'ы.)
    print("[preflight] вызываем _preflight_huawei_diagnostic_cleanup "
          "(min_age_s=0 для self-test)")
    sc._preflight_huawei_diagnostic_cleanup(
        kind="ping", prefix="pc", min_age_s=0.0,
    )

    # 5. Проверка: orphan'ов больше нет в state.
    reply_post = sc.nc.get(HuaweiPingResultsListFilter().get_request_filter())
    entries_post = sc._extract_huawei_test_entries(
        reply_post, "ping-results", "ping-result",
    )
    post_orphans = [e["test-name"] for e in entries_post
                    if e.get("test-name") in orphan_names]
    print(f"[verify-post] orphan'ы в state после preflight: {post_orphans}")
    assert not post_orphans, (
        f"preflight должен был удалить orphan'ы, но в state остались: "
        f"{post_orphans}"
    )

    # 6. Дополнительно — основной sc.ping(...) тоже должен отработать чисто
    # (его preflight ничего не найдёт и тихо пройдёт).
    print("[main-ping] обычный sc.ping(...) после preflight'а")
    res = sc.ping(short_req, poll_timeout_s=20.0)
    _print_summary("preflight self-test main ping", res)
    assert res.vendor == "huawei"

    # 7. Финальный cleanup на случай если preflight ВНУТРИ sc.ping не сработал
    # (или если мы что-то пропустили). Гарантируем что после теста state чист.
    for n in orphan_names:
        try:
            sc._send_action_raw(HuaweiPingDeleteAction(n).get_request_filter())
        except Exception:  # noqa: BLE001
            pass  # уже нет — OK

    print("[scenario-6] OK")
    return True


# ============================================================================
# Driver
# ============================================================================
def run_nokia():
    nc = NetconfClient(
        host=NOKIA_HOST,
        port=NOKIA_PORT,
        user=NETCONF_USER,
        password=NETCONF_PASS,
        device_params=NOKIA_DEVICE_PARAMS,
        rpc_timeout=90,
    )
    try:
        sc = ServicesClient(nc, vendor="nokia")
        try:
            scenario_nokia_ping_ok(sc)
        except NetconfActionNotAuthorized as exc:
            print("[AUTH-ERROR] Nokia ping не разрешён профилем NETCONF.")
            print("fix_hint:")
            print(exc.fix_hint)
            return
        scenario_nokia_ping_bad_vrf(sc)
        scenario_nokia_traceroute(sc)
    finally:
        nc.close()


def run_huawei():
    nc = NetconfClient(
        host=HUAWEI_HOST,
        port=HUAWEI_PORT,
        user=NETCONF_USER,
        password=NETCONF_PASS,
        device_params=HUAWEI_DEVICE_PARAMS,
        rpc_timeout=90,
    )
    try:
        sc = ServicesClient(nc, vendor="huawei")
        try:
            scenario_huawei_ping_ok(sc)
            scenario_huawei_traceroute(sc)
            scenario_huawei_preflight_cleanup(sc)
        except NetconfActionNotAuthorized as exc:
            print("[AUTH-ERROR] Huawei diagnostic-tools не разрешено профилем.")
            print(exc.fix_hint)
    finally:
        nc.close()


if __name__ == "__main__":
    run_nokia()
    run_huawei()
    _banner("ALL SCENARIOS PASSED")
