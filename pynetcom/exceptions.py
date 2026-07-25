"""
Кастомные исключения pynetcom для границы устройство ↔ протокол.

Эти классы используются, когда обычная NETCONF / REST ошибка имеет специальный
смысл и должна **не теряться** в стеке вызовов. Самый яркий пример — Nokia SR OS
отказывает в RPC ``<action>`` потому что профиль безопасности (``base-op-authorization``)
не содержит ключевого слова ``action``. С точки зрения NETCONF транспорт жив, но
с точки зрения оператора NOC: "пинг не пошёл — причём не из-за сети, а из-за конфига
самого роутера". Бот должен сказать пользователю не "сеть упала", а "попросите NOC
расширить профиль на устройстве" с готовым сниппетом.
"""

from __future__ import annotations

from typing import Optional


class NetconfActionNotAuthorized(RuntimeError):
    """RPC ``<action>`` запрещён политикой безопасности роутера.

    Поднимается из :mod:`pynetcom.services_client`, когда устройство ответило
    ``rpc-error`` с тэгом ``operation-not-supported`` (Nokia) либо иной
    vendor-специфичной формой "action не разрешён в данном NETCONF профиле".

    Это **не** сетевой / транспортный сбой и **не** обычный ICMP-fail. Это
    конфиг устройства: NOC должен добавить ``action`` в профиль безопасности.
    Поэтому исключение несёт готовый ``fix_hint`` — вендор-специфичный
    конфиг-сниппет для копи-пасты в CLI.

    :param vendor: ``"nokia"`` / ``"huawei"`` / иное. Влияет на содержимое
        :attr:`fix_hint`.
    :type vendor: str
    :param router_hint: Опциональный человекочитаемый идентификатор роутера
        (host или name). Только для сообщения. ``None`` если неизвестно.
    :type router_hint: Optional[str]
    :param underlying_error: Исходное исключение от ncclient/lxml. Сохраняем
        в ``__cause__`` ради ``raise ... from ...`` диагностики.
    :type underlying_error: Optional[BaseException]
    """

    _NOKIA_FIX = (
        "/configure system security profile \"default\" netconf base-op-authorization\n"
        "    action\n"
        "    get\n"
        "    get-config\n"
        "    get-data\n"
        "exit"
    )

    _HUAWEI_FIX = (
        "system-view\n"
        "aaa\n"
        "  task-group <your-group> task-id system enable\n"
        "  ! либо обогатите user-template / netconf-permission-list согласно политике\n"
        "quit"
    )

    def __init__(
        self,
        vendor: str,
        router_hint: Optional[str] = None,
        underlying_error: Optional[BaseException] = None,
    ):
        self.vendor = (vendor or "").strip().lower()
        self.router_hint = router_hint
        self.underlying_error = underlying_error

        # fix_hint собирается по vendor
        if self.vendor == "nokia":
            self.fix_hint = self._NOKIA_FIX
        elif self.vendor == "huawei":
            self.fix_hint = self._HUAWEI_FIX
        else:
            self.fix_hint = (
                "Расширьте NETCONF security/authorization профиль так чтобы "
                "RPC <action> был разрешён для данного пользователя."
            )

        who = router_hint or "router"
        vendor_label = self.vendor or "unknown vendor"
        message = (
            f"Router {who} ({vendor_label}) doesn't permit NETCONF <action> "
            f"under the active security profile. Ask NOC to add `action` to "
            f"the NETCONF base-op-authorization list."
        )
        super().__init__(message)


class HuaweiLldpNotSupported(RuntimeError):
    """Per-port RPC hit a Huawei port/interface that does not support LLDP.

    The vendor-agnostic per-port subtree filter
    (:class:`~pynetcom.utils.helpers.netconf.rpc_requests.HuaweiInterfaceRPCRequest`)
    bundles an OpenConfig ``<lldp>`` subtree together with the port state,
    transceiver and ``devm``/``ifm`` blocks. On interfaces that carry no
    LLDP agent — software loopbacks (``LoopBack*``), and other logical
    interfaces — Huawei VRP rejects the **whole** ``<get>`` with::

        RPCError: LLDP is not supported on this port.

    losing the port/transceiver data that WOULD have come back. This is not
    a transport failure and not a permission problem: the fix is simply to
    re-issue the request without the LLDP subtree
    (``HuaweiInterfaceRPCRequest(port, include_lldp=False)``).

    The caller catches ``RPCError``, tests :meth:`matches`, and on a match
    rebuilds the filter with ``include_lldp=False`` and retries — never
    swallowing any other RPCError. LAG (``Eth-Trunk*``) interfaces already
    use an LLDP-free filter and never hit this.

    :param port: interface name the RPC targeted (for the message). ``None``
        if unknown.
    :type port: Optional[str]
    :param underlying_error: original ncclient ``RPCError`` — preserved in
        ``__cause__`` for ``raise ... from ...`` diagnostics.
    :type underlying_error: Optional[BaseException]
    """

    # Substrings that identify the Huawei "LLDP not supported" rpc-error.
    # Matched case-insensitively; both must be present so unrelated errors
    # that merely mention "LLDP" are never mistaken for this one.
    _SIGNATURE = ("lldp", "not supported")

    def __init__(
        self,
        port: Optional[str] = None,
        underlying_error: Optional[BaseException] = None,
    ):
        self.port = port
        self.underlying_error = underlying_error
        self.fix_hint = (
            "Re-issue the per-port filter without the LLDP subtree: "
            "HuaweiInterfaceRPCRequest(port, include_lldp=False)."
        )
        where = f" on {port}" if port else ""
        super().__init__(
            f"Huawei rejected the per-port <get>{where}: LLDP is not "
            f"supported on this interface. Retry with include_lldp=False."
        )

    @classmethod
    def matches(cls, error: BaseException) -> bool:
        """Return True iff ``error`` is the Huawei "LLDP not supported" rpc-error.

        Deliberately narrow: requires BOTH ``lldp`` and ``not supported`` in
        the error text so that other ``RPCError`` values (auth, unknown
        element, timeouts) are never absorbed. Safe to call on any
        exception type.

        :param error: the exception to classify (typically an ncclient
            ``RPCError``).
        :type error: BaseException
        :rtype: bool
        """
        text = str(getattr(error, "message", None) or error).lower()
        return all(token in text for token in cls._SIGNATURE)
