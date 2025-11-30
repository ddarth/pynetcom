from string import Template
from pynetcom.utils.huawei_router_tools import split_if_to_type_id_tag
import re
from typing import Tuple


class OpenconfigInterfaceRPCRequest():
    """Base class for Openconfig interface RPC request"""
    template : Template = None
    interface : str= """
    <interfaces xmlns="http://openconfig.net/yang/interfaces">
        <interface>
            <name>$port</name>
        </interface>
    </interfaces>"""
    transceiver : str = """
    <components xmlns="http://openconfig.net/yang/platform">
        <component>
            <name>$transceiver_prefix$port</name>
            <transceiver xmlns="http://openconfig.net/yang/platform/transceiver">
            </transceiver>
        </component>
    </components>
    """
    # lldp : str = """
    # <lldp xmlns="http://openconfig.net/yang/lldp">
    #     <interfaces>
    #         <interface>
    #             <name>$port</name>
    #         </interface>
    #     </interfaces>
    # </lldp>
    # """
    lldp : str = """
    <lldp xmlns="http://openconfig.net/yang/lldp">
        <interfaces>
            <interface>
                <name>$port</name>
                <state>
                    <enabled/>
                </state>
                <neighbors>
                    <neighbor>
                        <id/>
                        <state/>
                    </neighbor>
                </neighbors>
            </interface>
        </interfaces>
    </lldp>
    """

    def __init__(self, port: str, transceiver_prefix: str):
        self.port = port
        self.transceiver_prefix = transceiver_prefix
        self.request_filter = self.get_template().substitute(port=self.port, transceiver_prefix=self.transceiver_prefix)

    def get_template(self) -> Template:
        return Template(self.interface + self.transceiver + self.lldp)
    
    def get_request_filter(self):
        return self.request_filter

class HuaweiInterfaceRPCRequest(OpenconfigInterfaceRPCRequest):
    """Class for Huawei interface RPC request"""
    huawei_interface: str = """
        <devm xmlns="urn:huawei:yang:huawei-devm">
            <ports>
                <port>
                    <position>$position</position>
                    <last-up-time/>
                    <last-down-time/>
                    <optical-module xmlns="urn:huawei:yang:huawei-pic">
                    </optical-module>
                    <!-- Request Ethernet state (speed/duplex/negotiation) from Huawei PIC model -->
                    <ethernet xmlns="urn:huawei:yang:huawei-pic">
                        <speed/>
                        <duplex-status/>
                        <negotiation/>
                        <negotiation-mode/>
                    </ethernet>
                    <physical-bandwidth/>
                </port>
            </ports>
        </devm>
        <ifm xmlns="urn:huawei:yang:huawei-ifm">
            <interfaces>
                <interface>
                    <name>$port</name>
                    <qos xmlns="urn:huawei:yang:huawei-qos">
                        <port-shapings/>
                    </qos>
                </interface>
            </interfaces>
        </ifm>
    """
    # OpenConfig-only filter for Eth-Trunk (LAG) interfaces
    eth_trunk_interface: str = """
<interfaces xmlns="http://openconfig.net/yang/interfaces">
  <interface>
    <name>$port</name>
    <state>
    </state>
    <aggregation xmlns="http://openconfig.net/yang/interfaces/aggregate">
    </aggregation>
  </interface>
</interfaces>
"""

    def __init__(self, port: str):
        # Eth-Trunk interfaces: use simplified OpenConfig filter with aggregation info only
        if isinstance(port, str) and port.lower().startswith('eth-trunk'):
            self.port = port
            self.transceiver_prefix = 'TRANSCEIVER:'
            self.request_filter = Template(self.eth_trunk_interface.strip()).substitute(port=self.port)
            return

        self.port = port
        self.transceiver_prefix = 'TRANSCEIVER:'
        self.request_filter = self.get_template().substitute(
            port=self.port,
            transceiver_prefix=self.transceiver_prefix,
            position=self.get_position(),
        )

    def get_template(self) -> Template:
        return Template(self.interface + self.transceiver + self.lldp + self.huawei_interface)

    def get_position(self) -> str:
        """Get position of the interface"""
        return split_if_to_type_id_tag(self.port)['if_pos']


class NokiaInterfaceRPCRequest(OpenconfigInterfaceRPCRequest):
    """Class for Nokia interface RPC request"""
    nokia_interface : str = """
    <state xmlns="urn:nokia.com:sros:ns:yang:sr:state">
        <port>
            <port-id>$connector_port</port-id>
            <transceiver/>
        </port>
        <port>
            <port-id>$breakout_port</port-id>
            <oper-state-last-changed/>
            <ethernet>
                <oper-egress-rate/>
                <lldp>
                    <dest-mac>
                        <mac-type>nearest-bridge</mac-type>
                        <remote-system/>
                    </dest-mac>
                </lldp>
            </ethernet>
        </port>
    </state>
    """
    lag_interface : str = """
<interfaces xmlns="http://openconfig.net/yang/interfaces">
  <interface>
    <name>$port</name>
    <state>
    </state>
    <aggregation  xmlns="http://openconfig.net/yang/interfaces/aggregate">
    </aggregation>
  </interface>
</interfaces>
"""

    def get_connector_port(self) -> str:
        # First check format with /c
        m = re.match(r"^(.+?/c\d+)(?:/(\d+))?$", self.port)
        if m:
            connector = m.group(1)
            breakout_index = m.group(2) or "1"
            breakout = f"{connector}/{breakout_index}"
            return connector, breakout
        # If not match with /c, then assume this is already L/M/P format
        m2 = re.match(r"^(\d+/\d+/\d+)$", self.port)
        if m2:
            connector = self.port
            breakout = self.port
            return connector, breakout
        raise ValueError(f"Unexpected port format: {self.port}")

    def __init__(self, port: str):
        # LAG interfaces: use simplified OpenConfig filter with aggregation info only
        if re.match(r"^lag-\d+$", port, re.IGNORECASE):
            self.port = port
            self.transceiver_prefix = 'transceiver '
            self.request_filter = Template(self.lag_interface).substitute(port=self.port)
            return

        self.port = port
        self.transceiver_prefix = 'transceiver '

        connector_port, breakout_port = self.get_connector_port()
        self.transceiver = self.transceiver.replace('$port', '$connector_port')

        self.request_filter = self.get_template().substitute(
            port=breakout_port, 
            transceiver_prefix=self.transceiver_prefix, 
            connector_port=connector_port,
            breakout_port=breakout_port
        )
        # print(self.request_filter)

    def get_template(self) -> Template:
        return Template(self.interface + self.transceiver + self.lldp + self.nokia_interface)


class OpenconfigInterfacesBriefListRPCRequest:
    """Builds RPC filter to fetch all interface names and descriptions using OpenConfig (state-only)."""
    template: Template = Template(
        """
<interfaces xmlns="http://openconfig.net/yang/interfaces">
  <interface>
    <name/>
    <state>
      <name/>
      <description/>
      <oper-status/>
      <admin-status/>
    </state>
  </interface>
</interfaces>
""".strip()
    )

    def __init__(self):
        self.request_filter = self.get_template().substitute()

    def get_template(self) -> Template:
        return self.template

    def get_request_filter(self):
        return self.request_filter