"""
This file contains utility functions for parsing Huawei router interface names and converting between short and long interface formats.
"""
import re
from typing import Optional


def copper_pmd_from_bw(trans_bw) -> Optional[str]:
    """Map a Huawei ``trans-bw`` value (in Mbit/s) to an ``EXT_ETH_*BASE_T*`` identity.

    This is invoked ONLY when Huawei explicitly marks the module as copper
    through the ``huawei-pic/optical-module/trans-mode=copper-mode`` leaf,
    so it is not a speed-based heuristic but a direct mapping from bit rate
    to the matching BASE-T identity (IEEE 802.3 §§ 25 / 40 / 55).

    :param trans_bw: ``trans-bw`` value from YANG (string or int, Mbit/s).
    :type trans_bw: str | int | None
    :return: ``"EXT_ETH_100BASE_TX"`` / ``"EXT_ETH_1000BASE_T"`` /
        ``"EXT_ETH_10GBASE_T"``, or ``None`` if the bandwidth is unknown.
    :rtype: Optional[str]
    """
    if trans_bw is None:
        return None
    try:
        bw = int(str(trans_bw).strip())
    except (TypeError, ValueError):
        return None
    return {
        100: 'EXT_ETH_100BASE_TX',
        1000: 'EXT_ETH_1000BASE_T',
        10000: 'EXT_ETH_10GBASE_T',
    }.get(bw)

class HuaweiRouterToolException(Exception):
    def __init__(self, message="Something went wrong!"):
        super().__init__(message)


REGEX_HUAWEI_LONG_IF = "(?#IfNameS)(((Eth-Trunk|LoopBack|Vlanif|Global-VE|NULL|VT)(\d*)|(Aux|GigabitEthernet|Ethernet|Tunnel|Virtual\-Ethernet|XGigabitEthernet|100GE|25GE|50\|100GE|FlexE|FlexE\-50\|100G)(\d*\/\d*\/\d*))(\.\d*)?)(?#IfNameE)"

REGEX_HUAWEI_SHORT_IF = "(?#IfNameS)(((Eth-Trunk|Loop|Vlanif|Global-VE|NULL|VT)(\d*)|(Aux|GE|Eth|Tun|VE|XGE|100GE|MEth|25GE|50\|100GE|FlexE|FlexE\-50\|100G)(\d*\/\d*\/\d*))(\.\d*)?)(?#IfNameE)"


##########################################################################################
# def huawei_split_if_to_type_id_tag(ifname):
def split_if_to_type_id_tag(ifname):
  """ 
  Split Huawei interface name to type, id and tag
  Example: GigabitEthernet7/0/18.2183 -> ('GigabitEthernet', '7/0/18', '.2183')

  param ifname: Interface name to be parsed
  type ifname: str
  return: Dictionary with keys 'if_type', 'if_pos', 'enc', and 'if_port_name'
    """
  regex = "^" + REGEX_HUAWEI_LONG_IF
  parsed_line = re.findall(regex, ifname)
  # print("ifname="+ifname)
  # print(parsed_line)
  if len(parsed_line)==0:
    regex = "^" + REGEX_HUAWEI_SHORT_IF
    parsed_line = re.findall(regex, ifname)
    # print(parsed_line)
    if len(parsed_line)==0:
      raise ValueError('ifname is not ifname. regex return 0')
      pass
    pass
  parsed_line = parsed_line[0]
  part1 = parsed_line[2]+""+parsed_line[4]
  part2 = parsed_line[3]+""+parsed_line[5]
  part3 = parsed_line[6]  
  # return[part1, part2, part3]
  return {'if_type': part1, 'if_pos': part2, 'enc': part3, 'if_port_name': part1 + part2}

# def convert_huawei_short2long_if(short_name):
def convert_short2long_if(short_name):
  """
  Convert short huawei if name to long
  GE7/0/18.2183 - > GigabitEthernet7/0/18.2183
  param short_name: Short interface name to be converted
  type short_name: str
  return: Long interface name as a string
  """
  regex = REGEX_HUAWEI_SHORT_IF
  parsed_line = re.findall(regex, short_name)
  if len(parsed_line)==0:
    raise HuaweiRouterToolException(f'{short_name} is not short interface name')

  parsed_line = parsed_line[0]
  # ('Global-VE3', 'Global-VE', '3', '', '', '.3235')
  # print('C S->L')
  # print(parsed_line)
  part1 = parsed_line[4] +""+parsed_line[2]
  part2 = parsed_line[5]+""+parsed_line[3] +""+parsed_line[6]
  if part1=="Loop":
    part1 = "LoopBack"
  elif part1=="GE":
    part1 = "GigabitEthernet"
  elif part1=="Eth":
    part1 = "Ethernet"
  elif part1=="Tun":
    part1 = "Tunnel"
  elif part1=="VE":
    part1 = "Virtual-Ethernet"
  elif part1=="VT":
    part1 = "Virtual-Template"
  elif part1=="XGE":
    part1 = "XGigabitEthernet"
  return part1+part2+""

# def convert_huawei_long2short_if(long_name):
def convert_long2short_if(long_name):
  """
  Convert long huawei if name to short
  GigabitEthernet7/0/18.2183 - > GE7/0/18.2183
  param long_name: Long interface name to be converted
  type long_name: str
  return: Short interface name as a string
  """
  regex = "^" + REGEX_HUAWEI_LONG_IF
  parsed_line = re.findall(regex, long_name)
  # [('GigabitEthernet7/0/18', '', '', 'GigabitEthernet', '7/0/18', '.2183')]
  # print(long_name, parsed_line)
  if len(parsed_line)==0:
    raise HuaweiRouterToolException(f'{long_name} is not long interface name')

  parsed_line = parsed_line[0]
  part1 = parsed_line[2]+""+parsed_line[4]
  part2 = parsed_line[3]+""+parsed_line[5]+""+parsed_line[6]
  if part1=="LoopBack":
    part1 = "Loop"
  elif part1=="GigabitEthernet":
    part1 = "GE"
  elif part1=="Ethernet":
    part1 = "Eth"
  elif part1=="Tunnel":
    part1 = "Tun"
  elif part1=="Virtual-Ethernet":
    part1 = "VE"
  elif part1=="XGigabitEthernet":
    part1 = "XGE"
  elif part1=="Virtual-Template":
    part1 = "VT"
  # print(part1+part2)
  # exit()
  return part1+part2+""