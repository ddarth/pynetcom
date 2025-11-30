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
        try:
            response = self.session.get(("subtree", request_filter))
            return xmltodict.parse(response.data_xml)
        except Exception as e:
            # ncclient/lxml can't parse multi-root XML fragments for subtree filters.
            # Fall back to a raw <get> that embeds the fragment as-is under <filter>.
            self.logger.warning(f'Standard NETCONF get() failed, falling back to raw get(): {e}')
            raw_xml = self.get_raw(request_filter)
            if not raw_xml:
                raise
            raw_dict = xmltodict.parse(raw_xml)
            # Normalize to { 'data': ... } like xmltodict.parse(response.data_xml)
            rpc_key = None
            if isinstance(raw_dict, dict):
                if 'rpc-reply' in raw_dict:
                    rpc_key = 'rpc-reply'
                else:
                    # try to find key that ends with 'rpc-reply' (namespaced)
                    for k in raw_dict.keys():
                        if k.endswith('rpc-reply') or k.endswith(':rpc-reply'):
                            rpc_key = k
                            break
            data_payload = None
            data_key_found = False
            if rpc_key and isinstance(raw_dict.get(rpc_key), dict):
                rpc_section = raw_dict[rpc_key]
                # Find 'data' key with optional namespace prefix
                for k in rpc_section.keys():
                    if k.split(':')[-1] == 'data':
                        data_key_found = True
                        data_payload = rpc_section[k]
                        break
                # If no data, check for rpc-error and raise with details
                if data_payload is None:
                    rpc_error = None
                    for k in rpc_section.keys():
                        if k.split(':')[-1] == 'rpc-error':
                            rpc_error = rpc_section[k]
                            break
                    if rpc_error is not None:
                        # Extract common fields if present
                        etype = rpc_error.get('error-type') if isinstance(rpc_error, dict) else None
                        etag = rpc_error.get('error-tag') if isinstance(rpc_error, dict) else None
                        eseve = rpc_error.get('error-severity') if isinstance(rpc_error, dict) else None
                        emsg = rpc_error.get('error-message') if isinstance(rpc_error, dict) else None
                        einfo = rpc_error.get('error-info') if isinstance(rpc_error, dict) else None
                        self.logger.error(f'NETCONF rpc-error: type={etype}, tag={etag}, severity={eseve}, msg={emsg}, info={einfo}')
                        raise RuntimeError(f"NETCONF rpc-error: tag={etag}, severity={eseve}, message={emsg}")
                    # Some servers may return <ok/> (unusual for <get>); treat as empty data
                    for k in rpc_section.keys():
                        if k.split(':')[-1] == 'ok':
                            return {'data': {}}
                    # If <data> key exists but empty/null, return empty data
                    if data_key_found:
                        self.logger.warning('NETCONF <get> returned empty <data>; returning empty object.')
                        return {'data': {}}
                    # Otherwise, no <data> and no explicit error → return empty with warning
                    snippet = raw_xml[:400] if isinstance(raw_xml, str) else ''
                    self.logger.warning(f'NETCONF <get> reply contained no <data> and no <rpc-error>. Returning empty object. Reply snippet: {snippet}')
                    return {'data': {}}
            return {'data': data_payload}

    def get_raw(self, request_filter):
        """
        Build a minimal <get> RPC with a subtree <filter> that can include
        multiple top-level elements, and send it via ncclient.dispatch.
        Returns raw <rpc-reply> XML as string.
        """
        base_ns = "urn:ietf:params:xml:ns:netconf:base:1.0"
        # Build NETCONF <get> and <filter> using lxml directly with Clark notation
        get_el = etree.Element(f"{{{base_ns}}}get")
        filter_el = etree.SubElement(get_el, f"{{{base_ns}}}filter")
        filter_el.set("type", "subtree")

        # Normalize request_filter to string and parse. If multi-root, wrap then append children.
        if isinstance(request_filter, bytes):
            rf_str = request_filter.decode('utf-8', 'ignore')
        else:
            rf_str = str(request_filter)

        try:
            # Try as a single well-formed element
            one = etree.fromstring(rf_str)
            filter_el.append(one)
        except Exception:
            # Fallback: wrap to allow multiple top-level elements, then append each child
            wrapped = etree.fromstring(f"<root>{rf_str}</root>")
            for child in list(wrapped):
                # Detach from wrapper before appending
                wrapped.remove(child)
                filter_el.append(child)

        # Send via ncclient (manager) and robustly convert reply to raw XML string
        reply = self.session.rpc(get_el)
        # Prefer common attributes first
        if hasattr(reply, 'xml') and isinstance(getattr(reply, 'xml'), str):
            return reply.xml
        if hasattr(reply, 'data_xml') and isinstance(getattr(reply, 'data_xml'), str):
            return reply.data_xml
        # Fallback to ncclient xml helper or lxml serialization
        try:
            return to_xml(reply)  # ncclient.xml_ helper
        except Exception:
            try:
                return etree.tostring(reply, encoding='unicode')
            except Exception:
                return str(reply)
    
    def rpc(self, rpc_command):
        self.logger.debug(f'Send request with filter: {rpc_command}')
        rpc_request = etree.fromstring(rpc_command)
        result = self.session.rpc(rpc_request).xml
        return xmltodict.parse(result)


    def close(self):
        self.session.close_session()