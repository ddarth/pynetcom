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

from typing import Optional


def _hex_bytes(hex_string) -> list:
    """Parse a ``"AA:BB:CC:..."`` formatted string into a list of integer bytes.

    Returns ``[]`` for empty / None / unparseable input so callers can write
    ``octets = _hex_bytes(s)`` without an extra guard. Invalid tokens cause
    the whole string to be rejected.

    :param hex_string: colon-separated hex dump or None.
    :type hex_string: str | None
    :return: list of ints in the 0..255 range.
    :rtype: list[int]
    """
    if not hex_string or not isinstance(hex_string, str):
        return []
    result = []
    for token in hex_string.split(':'):
        token = token.strip()
        if not token:
            continue
        try:
            result.append(int(token, 16))
        except ValueError:
            # One broken octet must not silently produce a partial result.
            return []
    return result


def derive_ethernet_pmd_from_sff(
    optical_compliance_hex,
    extension_byte,
    wavelength=None,
    port_type=None,
) -> Optional[str]:
    """Decode the exact transceiver PMD identity from a raw Nokia SFF dump.

    Nokia SR OS does not surface a decoded ``ethernet-pmd`` leaf; instead it
    exposes the raw SFF-8472 / 8636 / 8024 EEPROM compliance bytes. We decode
    them on our side. The procedure is two-step:

    * **SFP / SFP+ (1G/10G, byte 0 != 0x80)** — SFF-8472 bytes 3 and 6 carry
      the Ethernet Compliance Codes:

      - byte 3 bit 4 (``0x10``) → ``ETH_10GBASE_SR``
      - byte 3 bit 5 (``0x20``) → ``ETH_10GBASE_LR``
      - byte 3 bit 6 (``0x40``) → ``ETH_10GBASE_LRM`` (or 10G BiDi when
        ``port_type`` marks the port as 10G)
      - byte 3 bit 7 (``0x80``) → ``ETH_10GBASE_ER`` if ``wavelength≈1550``;
        otherwise, on a BiDi-marked port, ``EXT_ETH_10GBASE_BX10/40``
        (decided by ``port_type``); fallback ``ETH_10GBASE_ER``.
      - byte 6 bit 0 (``0x01``) — 1000BASE-SX / LX / LX10 / BX10 depending on
        ``wavelength`` (850 → SX, 1310 → LX10, 1270/1330/1490 → BX10).
      - byte 6 bit 1 (``0x02``) → ``ETH_1000BASE_LX10``
      - byte 6 bit 3 (``0x08``) → ``EXT_ETH_1000BASE_T``
      - byte 6 bit 6 (``0x40``) → ``EXT_ETH_1000BASE_BX10``

    * **QSFP28 / CFP2 (100G)** — two-step decode:

      - if ``byte_0 == 0x80`` → SFF-8024 ``optical-compliance-extension``
        (``0x02=SR4, 0x03=LR4, 0x04=ER4, 0x06=CWDM4, 0x07=PSM4, 0x0B=CR4,
        0x18=DR, 0x24=4WDM-40`` — the last value maps to our
        ``EXT_ETH_100GBASE_4WDM40`` extension).
      - otherwise SFF-8636 byte 5 (Specification Compliance):
        ``0x02=SR4, 0x08=LR4, 0x10=ER4``.

    Edge cases:

    * empty / None compliance string → returns ``None``;
    * unrecognised bit pattern → ``None`` (we never pseudo-detect);
    * ``wavelength`` / ``port_type`` hints are optional — without them the
      function returns the consensus identity (for example
      ``ETH_10GBASE_ER`` when ``wavelength`` is missing).

    :param optical_compliance_hex: colon-separated SFF-8472 / 8636 bytes.
    :type optical_compliance_hex: str | None
    :param extension_byte: SFF-8024 extension byte (int or string in decimal
        or ``0x..`` hex form; typically ``0``).
    :type extension_byte: str | int | None
    :param wavelength: laser wavelength in nm. Optional; disambiguates
        SX/LX/LX10/ER/BX variants.
    :type wavelength: int | float | str | None
    :param port_type: the ``/state/port/type`` leaf (for example
        ``"10/25-gig-ethernet-sfp"`` vs ``"100mb-1/10-gig-ethernet"``). Used
        to tell 1G BiDi and 10G BiDi apart — both share the same SFF
        compliance bytes.
    :type port_type: str | None
    :return: identity name (``ETH_*`` or ``EXT_ETH_*``) or None.
    :rtype: Optional[str]
    """
    octets = _hex_bytes(optical_compliance_hex)
    if not octets:
        return None
    # Pad to the SFF-8472 minimum so byte 6 is always reachable.
    while len(octets) < 8:
        octets.append(0)

    # **Nokia dumps the EEPROM starting from SFF byte 3** — this is confirmed
    # empirically across the collected wire-samples:
    #   * 10G LR (`20:00:..`) — first octet = 0x20 = SFF byte 3 bit 5;
    #   * copper FCLF (`00:00:00:08`) — fourth octet = 0x08 = SFF byte 6
    #     bit 3 (1000BASE-T);
    #   * 1G LX (`00:00:00:02`) — fourth octet = 0x02 = SFF byte 6
    #     bit 1 (1000BASE-LX);
    #   * 1G BiDi (`80:00:00:40`) — first octet = 0x80 (byte 3 bit 7),
    #     fourth octet = 0x40 (byte 6 bit 6 BX10).
    # Therefore:
    #   octets[0] = SFF byte 3 (Transceiver Compliance Codes, Ethernet)
    #   octets[3] = SFF byte 6 (Ethernet Compliance Codes part 2)
    b3 = octets[0]
    b6 = octets[3]
    # 100G modules use the SFF-8024 extension byte (a separate leaf) and/or
    # SFF-8636 byte 5 (Specification Compliance). Empirically Nokia stores
    # 0x08 in ``octets[5]`` for CFP2-LR4 — note that this is not the formal
    # SFF-8636 byte 131 offset, but an observed Nokia layout we rely on.
    b5_8636 = octets[5]
    # ``b0`` kept for diagnostic parity; it points at the same SFF byte 3.
    b0 = octets[0]

    # Normalise ``wavelength`` → int when numeric.
    wl = None
    if wavelength is not None:
        try:
            wl = int(float(str(wavelength).strip()))
        except (TypeError, ValueError):
            wl = None

    # Normalise ``port_type``.
    # NOTE: Nokia ``port-type "100mb-1/10-gig-ethernet"`` denotes a COMBO
    # 1G/10G port that physically accepts both 1G and 10G SFP modules.
    # Treating such a port as 10G-only by ``port_type`` is wrong, so we
    # recognise a 10G port ONLY when ``port-type`` explicitly says 10G or
    # 25G AND is not a combo entry:
    #   * "10/25-gig-ethernet-sfp"  — pure 10G/25G SFP+ MDA
    #   * "10-gig-ethernet-xfp"     — legacy XFP
    # Combo "100mb-1/10-gig-ethernet" → not a 10G-only port.
    pt = (port_type or '').lower() if isinstance(port_type, str) else ''
    is_10g_port = (
        '10/25-gig-ethernet' in pt
        or '10/25-gig-' in pt
        or ('10-gig-ethernet' in pt and '100mb' not in pt)
        or '25-gig-ethernet' in pt
    )
    is_100g_port = ('100-gig' in pt) or ('cfp2' in pt) or ('qsfp28' in pt)

    # ----------------------------- 100G / QSFP28 / CFP2 -----------------
    # 100G is recognised by any of:
    #   * an explicit "100-gig" / "cfp2" / "qsfp28" port-type; OR
    #   * a valid ``extension_byte`` (Nokia fills it only for 100G); OR
    #   * byte 0 == 0x80 with otherwise empty b3/b6 (typical 100G signature).
    ext_int = None
    if extension_byte is not None:
        try:
            text = str(extension_byte).strip()
            ext_int = int(text, 16) if text.lower().startswith('0x') else int(text)
        except (TypeError, ValueError):
            ext_int = None

    # 100G detection:
    #   * explicit port-type (qsfp28 / cfp2 / 100-gig); OR
    #   * non-zero extension byte (Nokia fills SFF-8024 for 100G QSFP28) —
    #     but ONLY when ``b3 == 0x80`` (the SFF "extension valid" marker);
    #     otherwise the extension may be a vendor-specific tag, like the
    #     SPP7041 copper SFP that reports ext=1; OR
    #   * the SFF-8636 specification compliance bytemap in octets[5].
    looks_like_100g = (
        is_100g_port
        or (b3 == 0x80 and ext_int is not None and ext_int != 0)
        or (b3 == 0x01 and b5_8636 != 0)
    )

    if looks_like_100g:
        if b3 == 0x80 and ext_int:
            # SFF-8024 extension table.
            # Confirmed in our fleet:
            #   * 0x24 → 4WDM-40 (Nokia 100G QSFP28 1310 nm)
            # Other entries come from the SFF-8024 spec and are not yet
            # observed on our stand — refresh when a wire-sample appears.
            # See feedback_mark_workarounds_in_code.
            ext_map = {
                0x02: 'ETH_100GBASE_SR4',
                0x03: 'ETH_100GBASE_LR4',
                0x04: 'ETH_100GBASE_ER4',
                0x06: 'ETH_100GBASE_CWDM4',
                0x07: 'ETH_100GBASE_PSM4',
                0x0B: 'ETH_100GBASE_CR4',
                0x18: 'ETH_100GBASE_DR',
                0x24: 'EXT_ETH_100GBASE_4WDM40',
            }
            pmd = ext_map.get(ext_int)
            if pmd:
                return pmd
        # SFF-8636 Specification Compliance — on our stand Nokia stores the
        # SFF-8024 matching byte in ``octets[5]`` for CFP2 / QSFP28 LR4
        # (= 0x08). Confirmed empirically against the CFP2-LR4 samples on
        # 7750 SR-7 ports 3/1/1 and 4/1/1.
        sff8636 = {
            0x02: 'ETH_100GBASE_SR4',
            0x08: 'ETH_100GBASE_LR4',
            0x10: 'ETH_100GBASE_ER4',
        }
        pmd = sff8636.get(b5_8636)
        if pmd:
            return pmd
        return None

    # ----------------------------- 10G branches (SFF-8472 byte 3) -----
    # SR (byte 3 bit 4 = 0x10)
    if b3 & 0x10:
        return 'ETH_10GBASE_SR'
    # LR (byte 3 bit 5 = 0x20)
    if b3 & 0x20:
        return 'ETH_10GBASE_LR'
    # LRM (byte 3 bit 6 = 0x40)
    if b3 & 0x40 and is_10g_port:
        # On a 10G port bit 6 means LRM. On a 1G combo port the same bit may
        # carry 1000BASE-T (observed empirically on Nokia). ``port_type``
        # disambiguates the two.
        return 'ETH_10GBASE_LRM'
    # ER / BX (byte 3 bit 7 = 0x80)
    if b3 & 0x80:
        if is_10g_port:
            # 10G BiDi modules use 1270 / 1330 / 1490 nm. ER is usually
            # 1550 nm.
            if wl in (1270, 1330, 1490, 1310):
                # On our stand all 10G BiDi modules are 40 km (BX40). The
                # SFF bytes do not distinguish BX10 from BX40, so we tag
                # them as BX40 (the dominant variant in our fleet).
                return 'EXT_ETH_10GBASE_BX40'
            return 'ETH_10GBASE_ER'
        # Outside a 10G port bit 7 matches the Nokia 1G BiDi signature
        # (LTF2304-BC+ modules) — handled below via the byte 3 bit pattern.
        if b3 == 0x80 or (b3 & 0x40 and not is_10g_port):
            # 1G BiDi signature: byte 0 = 0x80 plus byte 3 has bit 6/7 set
            # (observed on Nokia). Wavelength 1270/1330/1490 → BX10.
            if wl in (1270, 1330, 1490):
                return 'EXT_ETH_1000BASE_BX10'

    # ----------------------------- 1G branches (SFF-8472 byte 6) -------
    # 1000BASE-T (bit 3 = 0x08) — copper SFP.
    if b6 & 0x08:
        return 'EXT_ETH_1000BASE_T'
    # 1000BASE-LX/LX10 (bit 1 = 0x02).
    if b6 & 0x02:
        return 'ETH_1000BASE_LX10'
    # 1000BASE-BX10 (bit 6 = 0x40) — Nokia-specific signature.
    if b6 & 0x40:
        return 'EXT_ETH_1000BASE_BX10'
    # 1000BASE-SX (bit 0 = 0x01). Some Nokia 1G LX modules report this bit
    # instead of bit 1; ``wavelength`` distinguishes them.
    if b6 & 0x01:
        if wl is not None:
            if wl <= 900:
                return 'ETH_1000BASE_SX'
            if wl in (1270, 1330, 1490):
                return 'EXT_ETH_1000BASE_BX10'
            # 1310 / 1550 → LX10 (no more precise identity is meaningful in
            # our fleet).
            return 'ETH_1000BASE_LX10'
        return 'ETH_1000BASE_SX'

    return None


def transmission_distance_from_sff(link_length_hex) -> Optional[int]:
    """Extract the maximum link distance in metres from an SFF link-length block.

    SFF-8472 lays out six length leaves at EEPROM page A0 bytes 14..19:

    * byte 14 (offset 0): SMF, km units
    * byte 15 (offset 1): SMF, 100 m units (for short single-mode runs)
    * byte 16 (offset 2): OM2 (50/125), 10 m units
    * byte 17 (offset 3): OM1 (62.5/125), 10 m units
    * byte 18 (offset 4): Copper / DAC, metre units
    * byte 19 (offset 5): OM3 (50/125), 10 m units

    The function returns the maximum across all media — that is the
    advertised reach of the module.

    :param link_length_hex: Nokia ``link-length-information`` leaf,
        ``"AA:BB:CC:DD:EE:FF"`` formatted.
    :type link_length_hex: str | None
    :return: distance in metres, or None if all zero or parsing failed.
    :rtype: Optional[int]
    """
    octets = _hex_bytes(link_length_hex)
    if not octets:
        return None
    while len(octets) < 6:
        octets.append(0)

    candidates = [
        octets[0] * 1000,  # SMF km
        octets[1] * 100,   # SMF 100m
        octets[2] * 10,    # OM2
        octets[3] * 10,    # OM1
        octets[4] * 1,     # Copper m
        octets[5] * 10,    # OM3
    ]
    distance = max(candidates)
    return distance if distance > 0 else None


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
