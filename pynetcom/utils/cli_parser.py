"""
Module for parsing CLI output.

Example:

# Parse show port brief to dict and return dict
def parse_show_port_brief(out):
    logging.debug('SHOW PORT')
    regex = "^(?#port_id)(\d*\/\d*\/\d*)\s*(?#adm_status)(Up|Down)\s*(?#Link)(Yes|No)\s*(?#port_state)(Down|Up)\s*(?#cfg_mtu)(\d*)\s*(?#opr_mtu)(\d*)\s*(?#LAG)(\d*|\-)\s*(?#mode)(netw|accs|hybr)\s*(?#enc)(null|dotq|qinq)\s*(?#type)(\S*)\s*(?#sfp)(.*$|$)"
    ports = cli_parser.parse(
        regex=regex,
        text=out, 
        col_names={
            'id' : 0,
            'adm_status' : 1,
            'link_status' : 2,
            'op_status' : 3,
            'cfg_mtu' : 4,
            'op_mtu' : 5,
            'lag_id' : 6,
            'mode' : 7,
            'enc' : 8,
            'type' : 9,
            'sfp' : 10,
            'description' : "",
            'optical' : "",
            'optical_high' : "",
            'optical_low' : "",
            'last_state' : "",
        },
        key_name='id'
    )
    logging.debug('END')

    return ports
"""

import re
import logging

class CLIParser:
    def __init__(self):
        """
        Class for parsing CLI output.

        :param regex: Regular expression for parsing lines.
        :param debug_level: Debug level.
        """



    def parse(self, regex, text, col_names, key_name = None):
        """
        Parsing input data into a dictionary.

        :param regex: Regular expression for parsing lines.
        :param text: Input string data for parsing.
        :param col_names: Dictionary with column names.
        :param key_name: Name of the key to use as a key in the dictionary.
        :return: Dictionary with parsing results.
        """
        
        parsed_data = {}
        lines = text.split('\r\n')
        i = 0
        for line in lines:
            parsed_line = re.findall(regex, line)
            if len(parsed_line) == 0:
                continue
            i+=1
            parsed_line = parsed_line[0]

            data = self._create_dict(parsed_line, col_names)
            # If the key is not assigned, then use i
            if key_name is None:
                item_id = i
            else:
                item_id = data.get(key_name)

            parsed_data[item_id] = data
            logging.debug(data)
        
        return parsed_data

    def parse_multiline(self, regex, text, col_names, key_name = None):
        """
        Parsing input data into a dictionary.

        :param regex: Regular expression for parsing lines.
        :param text: Input string data for parsing.
        :param col_names: Dictionary with column names.
        :param key_name: Name of the key to use as a key in the dictionary.
        :return: Dictionary with parsing results.
        """
        print(text)
        parsed_data = {}
        parsed_text = re.findall(regex, text, re.S | re.M  | re.VERBOSE)
        print(parsed_text)
        i = 0
        for parsed_line in parsed_text:
            i+=1

            data = self._create_dict(parsed_line, col_names)
            # If the key is not assigned, then use i
            if key_name is None:
                item_id = i
            else:
                item_id = data.get(key_name)

            parsed_data[item_id] = data
            logging.debug(data)

        return parsed_data

    def _create_dict(self, parsed_line, col_names):
        """
        Creates a dictionary for the input format.

        :param parsed_line: Parsed line.
        :param col_names: Required format.
        :return: Dictionary with data.
        """
        data = dict()

        for key in col_names:
            val = col_names[key]
            """
            This is needed to not use a key in some cases, that is, ""
            col_names={
                'id' = 0
                'adm_status' = 1
                'link_status' = 2
                'description' = "" # Here
                'last_state' = ""  # and here
            },
            """
            if isinstance(val, int):
                data[key] = parsed_line[val]
            else:
                data[key] = val

        return data
