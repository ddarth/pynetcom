"""
Pls not use this example now
This example used cli_client, but cli_client is depricated in future because scrapli have same functional
"""

# from pynetcom import EquipCLI
# from pynetcom.cli_client import cli_caret
# from config import CLI_HOST, CLI_USER, CLI_PASSWORD
import logging

import wexpect

logger = logging.getLogger('wexpect')
logger.setLevel(logging.DEBUG)

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Set needed logging level
# logging.getLogger().setLevel(logging.INFO)


print('SPAWN')
child = wexpect.spawn('powershell.exe', logfile=open('connect.log', 'wb'))
print('END SPAWN')
child.expect(r'[\$>#]')

# router_cli = EquipCLI(CLI_HOST, CLI_USER, CLI_PASSWORD, cli_caret.NOKIA_VIEW, cli_caret.NOKIA_CONF, "nokia")
# router_cli.connect()
# cli_result = router_cli.exec_cli("show port description")
# print(cli_result)