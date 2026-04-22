"""
Оптимизированная версия генератора топологии DWDM.

Делает ровно то же самое, что ``generate_dwdm_topology.py``, но PM fan-out
по NE выполняется параллельно через ``ThreadPoolExecutor``. Выходной
HTML и структура ``enriched_links`` идентичны оригиналу (с точностью до
realtime input/output power, который естественно дрейфует между
прогонами на секунды).

Цель скрипта — показать максимальное ускорение генератора без изменений
library-кода. Сравнение с оригиналом — через ``compare_topology_generators.py``.

Usage:
    python examples/generate_dwdm_topology_fast.py

Output:
    dwdm_topology_fast.html
"""

import sys
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, '.')

from pynetcom import RestNCE, NceDataProvider
from examples.config import API_NCE_HOST, API_NCE_USER, API_NCE_PASS

# Переиспользуем логику оригинала, которая не должна расходиться между
# версиями. ``collect_optical_config`` НЕ импортируем — делаем свою
# parallel-версию ниже (``collect_optical_config_parallel``).
from examples.generate_dwdm_topology import (
    _parse_fiu_alias,
    _build_pm_entry,
    _build_optical_block,
    _to_float,
    build_enriched_links,
    status_text,
    build_graph_data,
    generate_html,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('urllib3').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------- #
#  Главное отличие от оригинала — PM fan-out параллельный.               #
#  Внутренняя логика обработки одного NE — копия оригинала, только       #
#  вынесена в функцию, чтобы отдать в ThreadPoolExecutor.                #
# ---------------------------------------------------------------------- #

def _process_one_ne(provider, ne, wanted_tps, all_ports):
    """
    Process optical PM for one NE (ports are pre-loaded).

    Повторяет тело цикла оригинала (``collect_optical_pm``, стр. 129-234),
    но принимает уже загруженные ``all_ports`` на вход и возвращает
    результаты локально вместо записи в общий словарь.

    **Почему ports приходят снаружи, а не грузятся здесь:**
    ``NceDataProvider.get_ports`` использует
    ``RestNCE.client.send_request`` с **shared state** (``self.data``
    внутри клиента). Параллельный вызов ``get_ports`` в нескольких
    потоках вызывает race condition: один поток делает ``clear_data``
    в середине другого потока и частично удаляет его накопленные
    страницы. Эмпирически это приводит к потере ~85% PM-данных.
    Поэтому фаза load_ports делается sequential ДО запуска pool'а.

    Returns:
        (ne_name, local_pm_data, local_fiu_unresolved, ports_with_pm_count)
    """
    local_pm: dict = {}
    local_unresolved: list = []

    physical_id = (ne.vendor_specific_info or {}).get('physical-id')
    if not physical_id:
        return ne.name, local_pm, local_unresolved, 0

    link_ports = [p for p in all_ports if p.tp_id in wanted_tps]
    if not link_ports:
        return ne.name, local_pm, local_unresolved, 0

    try:
        port_pm = provider.get_eml_pm_for_ports(link_ports, int(physical_id))
    except Exception as e:
        logger.warning(f"EML PM query failed for {ne.name}: {e}")
        return ne.name, local_pm, local_unresolved, 0

    ports_with_pm = 0
    fiu_ports_needing_mapping = []

    for port in link_ports:
        tp_id = port.tp_id
        has_optical_pm = False
        if tp_id in port_pm:
            entry = _build_pm_entry(port_pm[tp_id], port.name, ne.name, ne.node_id)
            if entry:
                local_pm[tp_id] = entry
                ports_with_pm += 1
                has_optical_pm = True
        if not has_optical_pm:
            vsi = port.vendor_specific_info or {}
            alias = vsi.get('alias', '')
            parsed = _parse_fiu_alias(alias)
            if not parsed and port.parent_tp_id:
                parent = next((p for p in all_ports if p.tp_id == port.parent_tp_id), None)
                if parent:
                    alias = (parent.vendor_specific_info or {}).get('alias', '')
                    parsed = _parse_fiu_alias(alias)
            if parsed:
                fiu_ports_needing_mapping.append((port, parsed))
            elif 'FIU' in (port.name or '') or 'RAU' in (port.name or ''):
                local_unresolved.append((ne.name, port.name, alias))

    if fiu_ports_needing_mapping:
        target_boards: dict = {}
        for port, (shelf, slot, pnum) in fiu_ports_needing_mapping:
            target_boards.setdefault((shelf, slot), []).append((port, pnum))

        for (shelf, slot), port_list in target_boards.items():
            target_pnums = [pn for _, pn in port_list]
            try:
                board_pm = provider.get_eml_pm_for_board(
                    ne_physical_id=int(physical_id),
                    shelf=shelf,
                    slot=slot,
                    ports=target_pnums,
                )
            except Exception:
                continue

            for port, pnum in port_list:
                if pnum in board_pm:
                    entry = _build_pm_entry(
                        board_pm[pnum],
                        f"{port.name} -> 0/{slot}/{pnum}",
                        ne.name,
                        ne.node_id,
                    )
                    if entry:
                        active_port = next(
                            (p for p in all_ports
                             if p.is_physical
                             and int((p.vendor_specific_info or {}).get('slot-number', -1)) == slot
                             and int((p.vendor_specific_info or {}).get('port-number', -1)) == pnum),
                            None,
                        )
                        if active_port:
                            entry['active_tp_id'] = active_port.tp_id
                            entry['active_port_name'] = active_port.name
                        local_pm[port.tp_id] = entry
                        ports_with_pm += 1

    return ne.name, local_pm, local_unresolved, ports_with_pm


def collect_optical_pm_parallel(provider, nes, links, max_workers=8):
    """
    PM fan-out, parallel across NEs (with sequential port preload).

    Вызывается вместо sequential ``collect_optical_pm`` оригинала
    (стр. 102-241). Результат — тот же словарь ``{tp_id: pm_entry}``.

    **Две фазы:**

    1. Sequential предзагрузка портов для всех целевых NE. Это **нельзя**
       делать параллельно из-за race condition в
       ``RestNCE.send_request``/``self.data``. См. docstring
       ``_process_one_ne`` для подробностей.
    2. Параллельный PM fan-out (EML PM endpoint не имеет shared state
       и параллельность там безопасна; semaphore там не нужен, NCE
       выдерживает 8 concurrent на эндпоинте ``querycurdata``).
    """
    ne_to_link_tps: dict = {}
    for link in links:
        if link.source_tp and link.source_node:
            ne_to_link_tps.setdefault(link.source_node, set()).add(link.source_tp)
        if link.dest_tp and link.dest_node:
            ne_to_link_tps.setdefault(link.dest_node, set()).add(link.dest_tp)

    total_tps = sum(len(v) for v in ne_to_link_tps.values())
    targets = [ne for ne in nes if ne.node_id in ne_to_link_tps]
    logger.info(
        f"Link ports to check: {total_tps} across {len(ne_to_link_tps)} NEs"
    )

    # Phase 1: sequential port preload (thread-safe issue in send_request).
    t_ports = time.time()
    ne_to_ports: dict = {}
    for ne in targets:
        try:
            ne_to_ports[ne.node_id] = provider.get_ports(ne_id=ne.node_id)
        except Exception as e:
            logger.warning(f"Failed to get ports for {ne.name}: {e}")
            ne_to_ports[ne.node_id] = []
    logger.info(f"Loaded ports for {len(ne_to_ports)} NEs "
                f"in {time.time()-t_ports:.1f}s (sequential)")

    # Phase 2: parallel PM fan-out (EML PM endpoint is safe at 8 concurrent).
    pm_data: dict = {}
    fiu_unresolved: list = []
    # Per-NE bookkeeping для post-validation — какие NE сколько link_ports
    # имели и сколько PM получили. Это safety net против транзиентных
    # NCE-ошибок (errorCode != 0, пустой response), при которых
    # get_eml_pm_for_board молча пропускал board и мы теряли данные
    # ничего об этом не зная.
    per_ne_stats: dict = {}  # node_id -> (expected_link_ports, got_pm)

    t_pm = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {
            ex.submit(
                _process_one_ne, provider, ne,
                ne_to_link_tps[ne.node_id],
                ne_to_ports.get(ne.node_id, []),
            ): ne
            for ne in targets
        }
        done = 0
        for fut in as_completed(futs):
            done += 1
            ne = futs[fut]
            ne_name, local_pm, local_unresolved, count = fut.result()
            pm_data.update(local_pm)
            fiu_unresolved.extend(local_unresolved)
            link_ports_count = len([
                p for p in ne_to_ports.get(ne.node_id, [])
                if p.tp_id in ne_to_link_tps[ne.node_id]
            ])
            per_ne_stats[ne.node_id] = (link_ports_count, count)
            if count:
                logger.info(f"  [{done}/{len(targets)}] {ne_name}: "
                            f"{count} ports with PM")
    logger.info(f"PM fan-out done in {time.time()-t_pm:.1f}s "
                f"(parallel, max_workers={max_workers})")

    # Phase 3: post-validation. NE с link_ports>0 но 0 PM-данных —
    # подозрительные. Бывают legitimate cases (Virtual NE, switch без
    # оптики), но в общем случае нужно перепроверить sequentially.
    suspicious = [
        ne for ne in targets
        if per_ne_stats.get(ne.node_id, (0, 0)) == (
            per_ne_stats[ne.node_id][0], 0
        ) and per_ne_stats[ne.node_id][0] > 0
    ]
    if suspicious:
        logger.warning(f"Post-validation: {len(suspicious)} NE with "
                       f"link_ports>0 but PM=0 — re-fetching sequentially")
        t_retry = time.time()
        recovered_total = 0
        for ne in suspicious:
            ne_name, local_pm, local_unresolved, count = _process_one_ne(
                provider, ne, ne_to_link_tps[ne.node_id],
                ne_to_ports.get(ne.node_id, []),
            )
            if count:
                pm_data.update(local_pm)
                fiu_unresolved.extend(local_unresolved)
                recovered_total += count
                logger.warning(f"  RECOVERED {count} PM entries for {ne_name}")
            else:
                # Действительно нет PM (Virtual NE, нет активных PM-плат и т.п.).
                # Это нормально — больше не предупреждаем.
                logger.info(f"  {ne_name}: confirmed no PM data "
                            f"(не оптический NE)")
        logger.info(f"Post-validation done in {time.time()-t_retry:.1f}s "
                    f"(recovered {recovered_total} PM entries)")

    if fiu_unresolved:
        logger.warning(f"FIU ports without alias mapping ({len(fiu_unresolved)}):")
        for ne_name, port_name, alias in fiu_unresolved:
            logger.warning(f"  {ne_name} / {port_name} (alias='{alias}')")

    return pm_data


# ---------------------------------------------------------------------- #
#  Reference power — параллельный GET-per-TP                             #
# ---------------------------------------------------------------------- #

def _fetch_one_reference(client, network_id, tp_id, ne_id,
                         max_retries=5):
    """One ACTN GET to fetch input-reference-power. Returns (tp_id, value)
    or (tp_id, None) on miss.

    Копия логики из ``NceDataProvider.get_reference_power`` (внутренний
    цикл), но с retry на 429/5xx. Библиотечный метод
    (``provider.get_reference_power``) использует ``session.get``
    напрямую **без retry**, что при параллельных вызовах ACTN endpoint'а
    приводит к silent data loss на 429. Поэтому здесь retry делаем
    явно — backoff 0.2 → 3.2 с, jitter.

    Принимает ``None``-валидный возврат на 404 (TP без reference
    конфигурации) — статусы 4xx кроме 429 не ретраим.
    """
    import random as _random
    url = (f"{client.API_NCE_HOST}"
           f"/restconf/v2/data/ietf-network:networks"
           f"/network={network_id}"
           f"/node={ne_id}"
           f"/ietf-network-topology:termination-point={tp_id}")
    backoff = 0.2
    for attempt in range(max_retries + 1):
        try:
            r = client.session.get(url, headers=client.header, verify=False)
        except Exception:
            return tp_id, None
        if r.status_code == 200:
            try:
                tps = r.json().get('ietf-network-topology:termination-point', [])
            except Exception:
                return tp_id, None
            if not tps:
                return tp_id, None
            otn = tps[0].get('ietf-te-topology:te', {}).get('otn-specific-info', {})
            ref = otn.get('input-reference-power')
            if ref is None:
                return tp_id, None
            return tp_id, float(ref)
        # retry на транзиентных кодах
        if r.status_code in (429, 502, 503, 504) and attempt < max_retries:
            time.sleep(backoff + _random.random() * 0.1)
            backoff = min(backoff * 2, 8.0)
            continue
        # остальные (404, 500-без-retry, etc) — сдаёмся
        return tp_id, None
    return tp_id, None


def collect_optical_config_parallel(provider, pm_data, ref_workers=6):
    """
    Обогатить pm_data порогами и reference-power.

    Копия ``collect_optical_config`` из оригинала, но reference-фаза
    параллельна (``ref_workers`` одновременных GET). Thresholds-фаза
    остаётся той же (уже параллельна внутри библиотеки через
    ``max_workers=6``).

    Консервативный дефолт ``ref_workers=6`` — тот же уровень, что
    оправдан для ``query-optical-power``. ACTN endpoint отдельно мы не
    замеряли, но патч ``send_request`` с retry на 429 подстрахует.
    """
    if not pm_data:
        return

    # Build query maps (same logic as original).
    query_tp_to_pm_keys: dict = {}
    query_tp_to_ne: dict = {}
    for pm_key, pm in pm_data.items():
        ne_id = pm.get('ne_id')
        if not ne_id:
            continue
        query_tp = pm.get('active_tp_id', pm_key)
        query_tp_to_pm_keys.setdefault(query_tp, []).append(pm_key)
        query_tp_to_ne[query_tp] = ne_id

    all_query_tps = list(query_tp_to_pm_keys.keys())

    # 1. Thresholds via library method (auto-batched, already parallel).
    t_thr = time.time()
    thresholds = provider.get_optical_power_thresholds(all_query_tps)
    threshold_count = 0
    for query_tp, thr in thresholds.items():
        for pm_key in query_tp_to_pm_keys.get(query_tp, []):
            lower = thr.get('input_lower_threshold')
            upper = thr.get('input_upper_threshold')
            if lower is not None:
                pm_data[pm_key]['input_lower_threshold'] = lower
                threshold_count += 1
            if upper is not None:
                pm_data[pm_key]['input_upper_threshold'] = upper
    logger.info(f"  Thresholds: {threshold_count} ports "
                f"(in {time.time()-t_thr:.1f}s)")

    # 2. Reference power — параллельно N workers.
    t_ref = time.time()
    network_id = provider._discover_actn_network_id()
    if not network_id:
        logger.warning("Could not discover ACTN network ID; skipping reference")
        return

    client = provider.client
    # dedup + filter TPs with known ne_id
    seen: set = set()
    tasks = []
    for tp_id in all_query_tps:
        if tp_id in seen:
            continue
        seen.add(tp_id)
        ne_id = query_tp_to_ne.get(tp_id)
        if ne_id:
            tasks.append((tp_id, ne_id))

    refs: dict = {}
    with ThreadPoolExecutor(max_workers=ref_workers) as ex:
        futs = [
            ex.submit(_fetch_one_reference, client, network_id, tp_id, ne_id)
            for tp_id, ne_id in tasks
        ]
        for fut in as_completed(futs):
            tp_id, ref_val = fut.result()
            if ref_val is not None:
                refs[tp_id] = ref_val

    ref_count = 0
    for query_tp, ref_val in refs.items():
        for pm_key in query_tp_to_pm_keys.get(query_tp, []):
            pm_data[pm_key]['input_ref'] = ref_val
            ref_count += 1
    logger.info(f"  Reference power: {ref_count} ports "
                f"(in {time.time()-t_ref:.1f}s, parallel={ref_workers})")


# ---------------------------------------------------------------------- #
#  collect_data — копия оригинала, только PM и reference — parallel      #
# ---------------------------------------------------------------------- #

def collect_data():
    """Collect DWDM topology data from NCE (parallel PM fan-out)."""
    client = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)
    provider = NceDataProvider(client)

    logger.info("Fetching DWDM NEs...")
    subnet = provider.get_subnet_by_name('DWDM')
    nes = provider.get_network_elements(subnet_id=subnet.get('res-id'))
    logger.info(f"NEs: {len(nes)}")

    logger.info("Fetching DWDM links (with name resolution)...")
    links = provider.get_links_by_subnet('DWDM', resolve_names=True)
    logger.info(f"Links: {len(links)}")

    logger.info("Fetching alarms for each NE...")
    ne_alarms = {}
    for ne in nes:
        alarms = provider.get_alarms(name=ne.name, is_cleared=False)
        if alarms:
            sevs = {}
            for a in alarms:
                sevs[a.severity] = sevs.get(a.severity, 0) + 1
            ne_alarms[ne.node_id] = {
                'total': len(alarms),
                'critical': sevs.get('critical', 0),
                'major': sevs.get('major', 0),
                'minor': sevs.get('minor', 0),
                'warning': sevs.get('warning', 0),
                'samples': [{'severity': a.severity, 'name': (a.alarm_name or '')[:50],
                             'object': (a.affected_object or '')[:40]}
                            for a in alarms[:5]]
            }

    logger.info("Fetching optical PM data (parallel)...")
    pm_data = collect_optical_pm_parallel(provider, nes, links)
    logger.info(f"PM data for {len(pm_data)} link ports")

    logger.info("Fetching reference power and thresholds (parallel)...")
    collect_optical_config_parallel(provider, pm_data)

    logger.info("Building enriched link model...")
    enriched_links = build_enriched_links(links, ne_alarms, pm_data, nes)
    logger.info(f"Enriched {len(enriched_links)} links")

    # Не закрываем client здесь — оставляем снаружи, чтобы вызывающий
    # успел прочесть retry_stats. Возвращаем client чтобы можно было
    # закрыть после использования.
    return nes, enriched_links, ne_alarms, client


if __name__ == '__main__':
    start = time.time()

    logger.info("Collecting DWDM topology data from NCE (fast)...")
    nes, enriched_links, ne_alarms, client = collect_data()

    pm_count = sum(1 for el in enriched_links
                   if el['source'].get('optical') or el['source'].get('resolved_optical')
                   or el['dest'].get('optical') or el['dest'].get('resolved_optical'))

    logger.info("Building graph...")
    nodes, edges = build_graph_data(nes, enriched_links, ne_alarms)

    output = 'dwdm_topology_fast.html'
    generate_html(nodes, edges, pm_count, output)

    logger.info(f"Done in {time.time()-start:.1f}s. Open {output} in browser.")
    try:
        logger.info(f"retry_stats: {client.retry_stats}")
    except AttributeError:
        pass
    client.close()
