"""
This file contains utility functions for parsing Nokia SR OS SAP identifiers
into their component parts (physical port and VLAN tag).

Background
----------
Nokia's NETCONF/YANG state model for VPLS / EPIPE services exposes each SAP
under ``/state/service/{vpls,epipe}/sap[sap-id]`` keyed by a composite
``sap-id`` leaf that bakes the port name and the encapsulation value into a
single string (e.g. ``"1/1/4:1342"``). There are NO separate ``port`` /
``vlan`` leaves on the SAP — this was verified by a live YANG probe (Phase 0
of the SAP-fields refactor). Extending the subtree filter with candidate
leaves only triggers ``MGMT_CORE #2201 Unknown element``. So we split the
identifier client-side.

Format reference (Nokia SR OS guides)
-------------------------------------
    "<port>:<encap>"     dot1q / single-tag         e.g. "1/1/4:1342"
    "lag-N:<encap>"      LAG with single tag        e.g. "lag-15:333"
    "<port>:*"           default-encap catch-all    e.g. "1/1/4:*"
    "<port>"             null-encap (port-based)    e.g. "1/1/11"

QinQ (``"<port>:<outer>.<inner>"``) is explicitly NOT supported here — we
have no QinQ in the network. If a caller passes one in, the vlan field stays
the raw string (e.g. ``"1342.10"``); add proper QinQ handling only when it
becomes a real requirement.
"""


def split_sap_id(sap_id):
    """
    Split a Nokia SAP id into its physical port and VLAN tag components.

    Examples:
        '1/1/4:1342'   -> {'port': '1/1/4',   'vlan': '1342'}     # dot1q
        'lag-1:1342'   -> {'port': 'lag-1',   'vlan': '1342'}     # LAG dot1q
        '1/1/4:*'      -> {'port': '1/1/4',   'vlan': '*'}        # default encap
        '1/1/4'        -> {'port': '1/1/4',   'vlan': None}       # null encap

    The ``vlan`` field stays a ``str`` (callers convert to int as needed) —
    consistent with :func:`pynetcom.utils.huawei_router_tools.split_if_to_type_id_tag`
    which also returns its encap (``enc``) as a string.

    :param sap_id: Nokia SAP id, e.g. ``"1/1/4:1342"`` / ``"lag-1:1342"`` /
        ``"1/1/4"``.
    :type sap_id: str
    :return: Dictionary with keys ``'port'`` (str) and ``'vlan'`` (str or None).
    :raises ValueError: If ``sap_id`` is empty / None / not a string.
    """
    if sap_id is None:
        raise ValueError("sap_id is None")
    if not isinstance(sap_id, str):
        raise ValueError(f"sap_id must be str, got {type(sap_id).__name__}")
    s = sap_id.strip()
    if not s:
        raise ValueError("sap_id is empty")

    if ":" in s:
        port, vlan = s.split(":", 1)
        port = port.strip()
        vlan = vlan.strip()
        if not port:
            raise ValueError(f"sap_id {sap_id!r} has empty port part")
        # Keep vlan as str even if it contains a dot (QinQ form);
        # caller can decide how to interpret. Empty after ':' → None.
        return {"port": port, "vlan": vlan if vlan else None}

    return {"port": s, "vlan": None}
