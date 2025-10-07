from ncclient import manager
# from ncclient.xml_ import to_ele
from ncclient.xml_ import *
import xmltodict
import xml.dom.minidom
import logging
from  typing import Type, Optional
from lxml import etree

class NetconfClient:
    def __init__(self, host, port, user, password, device_params=None, hostkey_verify=False):
        """
        When instantiating a connection to a known type of NETCONF server:

            Alcatel Lucent: device_params={'name':'alu'}
            Ciena: device_params={'name':'ciena'}
            Cisco:
                CSR: device_params={'name':'csr'}
                Nexus: device_params={'name':'nexus'}
                IOS XR: device_params={'name':'iosxr'}
                IOS XE: device_params={'name':'iosxe'}
            H3C: device_params={'name':'h3c'}
            HP Comware: device_params={'name':'hpcomware'}
            Huawei:
                device_params={'name':'huawei'}
                device_params={'name':'huaweiyang'}
            Juniper: device_params={'name':'junos'}
            Server or anything not in above: device_params={'name':'default'}
        """
        self.logger = logging.getLogger('pynetcom')
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.device_params = device_params
        self.hostkey_verify = hostkey_verify
        self.session : Optional[manager.Manager] = None
        self.__connect()

    def __connect(self):
        self.logger.debug(f'Connecting to {self.host}, {self.port}')
        self.session = manager.connect(
            host=self.host,
            port=self.port,
            username=self.user,
            password=self.password,
            device_params=self.device_params,
            hostkey_verify=self.hostkey_verify,
            timeout=120
        )
        

    def get_config(self):
        self.logger.debug(f'Get config')
        config = self.session.get_config(source="running")
        # config = self.session.get_configuration()
        # print('########################################')
        # print(config)
        return xmltodict.parse(config.xml)
    
    def get(self, request_filter):
        self.logger.debug(f'Get request with filter: {request_filter}')
        response = self.session.get(("subtree", request_filter))
        # print(response)
        return xmltodict.parse(response.data_xml)

    def get_raw(self, request_filter):
        """
        Used for debug, if some parse error occurs
        
        Send a raw NETCONF <rpc><get> with subtree filter and capture the raw
        <rpc-reply> using a temporary SessionListener to avoid any XML parsing.
        """
        # Localized imports and helpers to keep debug-only logic out of module scope
        import re
        import threading
        from ncclient.transport import SessionListener
        import ncclient.xml_ as nc_xml
        from ncclient.operations import rpc as nc_rpc

        invalid_xml10 = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\u0080-\u0084\u0086-\u009F]")

        # Temporarily monkeypatch to sanitize invalid chars and avoid parse crashes
        orig_to_ele = nc_xml.to_ele
        def to_ele_sanitized(x, huge_tree=False):
            if isinstance(x, (str, bytes)):
                if isinstance(x, bytes):
                    x = x.decode('utf-8', 'ignore')
                x = invalid_xml10.sub("", x)
            return orig_to_ele(x, huge_tree=huge_tree)

        orig_parse = nc_rpc.RPCReply.parse
        def safe_parse(self):
            try:
                return orig_parse(self)
            except Exception as e:
                # Record parse error but keep raw available
                self._parse_error = e
                self._root = None
                return

        nc_xml.to_ele = to_ele_sanitized
        nc_rpc.RPCReply.parse = safe_parse
        message_id = "pynetcom-raw-1"
        rpc_envelope = (
            f'<rpc message-id="{message_id}" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">'
            '<get>'
            '<filter type="subtree">'
            f"{request_filter}"
            '</filter>'
            '</get>'
            '</rpc>'
        )

        class _RawListener(SessionListener):
            def __init__(self, mid: str):
                self.mid = mid
                self.event = threading.Event()
                self.raw = None
            def callback(self, root, raw):
                # Match by message-id in raw; works even if root is None
                if raw and f'message-id="{self.mid}"' in raw:
                    self.raw = raw
                    self.event.set()

        listener = _RawListener(message_id)
        sess = self.session._session
        try:
            sess.add_listener(listener)
            sess.send(rpc_envelope)
            # wait up to manager timeout (default 120s)
            timeout = getattr(self.session, 'timeout', 120)
            listener.event.wait(timeout)
            return listener.raw
        finally:
            try:
                sess.remove_listener(listener)
            except Exception:
                pass
            # Restore monkeypatches
            try:
                nc_xml.to_ele = orig_to_ele
                nc_rpc.RPCReply.parse = orig_parse
            except Exception:
                pass
    
    def rpc(self, rpc_command):
        self.logger.debug(f'Send request with filter: {rpc_command}')
        rpc_request = etree.fromstring(rpc_command)
        result = self.session.rpc(rpc_request).xml
        return xmltodict.parse(result)


    def close(self):
        self.session.close()