"""
This module is not used, now. We try to replace it to scrapli library
"""

import platform
import sys
# Определяем операционную систему
os_name = platform.system()

# Импортируем соответствующую библиотеку
if os_name == 'Windows':
	print('Library pexpect not worked on Windows. Use Linux to RUN.')
	# exit()
	if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
		# Если находимся в виртуальном окружении
		# print('virtual')
		import wexpect_venv as pexpect
	else:
		# print('native')
		# Если в системной среде
		import wexpect as pexpect

else:
    import pexpect as pexpect

import re
import logging
from pynetcom.utils.util import bcolors


class cli_caret:
	NOKIA_VIEW = '(A|B)\:\S*#'
	NOKIA_CONF = '(A|B)\:\S*#'
	HUAWEI_VIEW = '\<\S*\>'
	HUAWEI_CONF = '\<\S*\>'

class vendor:
	nokia = 'nokia'
	huawei = 'huawei'

class EquipCLI(object):
	"""Base class for equipment.
	It connect to element by ssh and telnet, check key, fill sysname and other basic info
	Also it have main functions for connecting and executing commands

	This class can be extended by other vendor oriented classes like NokiaEquip and HuaweiEquip
	"""
	host = None
	username = None
	password = None
	is_login = False
	caret_read = None
	caret_write = None
	child = None
	sysname = None
	sys_type = None
	sys_version = None
	sys_uptime = None
	connection_retries = 0
	timeout = -1
	cli_error_messages = '' # Храним ошибки хоста


	debug = 1 # 0 -disable, 1 - error, 2 - info
	# @CARET_READ_READY - что ожидаем когда послали команду
	def __init__(self, HOST, USERNAME, PASSWORD, CARET_READ_READY, CARET_WRITE_READY = "", VENDOR = ""):
		self.logger = logging.getLogger(__name__)
		self.host = HOST
		self.username = USERNAME
		self.password = PASSWORD
		self.caret_read = CARET_READ_READY
		self.caret_write = CARET_WRITE_READY
		self.vendor = VENDOR
		#super(Equip, self).__init__()
		#self.arg = arg

	def after_login_success(self):
		logging.info("Login success")
		out = ""
		out = self.child.before.decode('ASCII')
		print(out)		
		self.disable_more()
		self.get_device_sysinfo()
		self.is_login = True
		pass

	def connect_ssh(self):
		logging.info(""+self.host+": Connect by ssh...")
		self.child = pexpect.spawn('cmd.exe', logfile=open('connect.log', 'wb'))
		print('ZZZ')
		self.child.expect(r'[\$>#]')
		self.child.sendline('ls')
		self.child.expect(r'[\$>#]')
		print(self.child.before)
		print('dddd')
		self.child = pexpect.spawn(f'ssh {self.username}@{self.host}', logfile='connect.log')
		print('qq')
		self.child.setwinsize(400,400)
		if os_name == 'Windows':
			print('windows except')
			i = self.child.expect (["(P|p)assword:", pexpect.TIMEOUT, pexpect.EOF, "Are you sure you want to continue connecting (yes/no/[fingerprint])?", "Invalid key length", "Host key verification failed."] )
		else:
			i = self.child.expect (["(P|p)assword:", pexpect.TIMEOUT, pexpect.EOF, "Are you sure you want to continue connecting (yes/no)?", "Invalid key length", "Host key verification failed."] )
		return self.expect_procedures( i, self.exp_default, self.enter_passwd, self.exp_timeout, self.exp_eof, self.enter_yes_unknown_key, self.connect_telnet, self.exp_reset_ssh_key )


	def connect_telnet(self):
		logging.info(""+self.host+": Connect by telnet...")
		self.child = pexpect.spawn('telnet '+self.host)
		self.child.setwinsize(400,400)
		i = self.child.expect (["(U|u)sername:", pexpect.TIMEOUT, pexpect.EOF] )
		return self.expect_procedures( i, self.exp_default, self.enter_username, self.exp_timeout, self.exp_eof)	


	def expect_procedures(self, i_exp, default_fun, *funs):
		'''
		Execute needed function based on i_exp. Needed to minimize code
		:param i_exp: Index number
		'''
		''' i - принимает на себя порядковый номер функции в *funs и выполняет её
			если i-той функции нет в *funs, то выполянем default_fun
			*funs - переменное число аргументов содержащий функции
		'''
		i = 0
		for fun in funs:
			if i==i_exp:
				return fun()
			i+=1
		return default_fun()

	def enter_passwd(self):
		logging.info(""+self.host+": Enter password")
		self.child.sendline(self.password)

	def enter_username(self):
		logging.info(""+self.host+": Enter username")
		self.child.sendline(self.username)
		i = self.child.expect (["(P|p)assword:", pexpect.TIMEOUT, pexpect.EOF] )
		self.expect_procedures( i, self.exp_default, self.enter_passwd, self.exp_timeout, self.exp_eof)

	def enter_yes_unknown_key(self):
		logging.info("Key is unknown. Contunue (yes/no)? <yes>")
		# Send YES
		self.child.sendline("yes")
		i = self.child.expect (["(P|p)assword:", pexpect.TIMEOUT, pexpect.EOF] )
		self.expect_procedures( i, self.exp_default, self.enter_passwd, self.exp_timeout, self.exp_eof)

	def exp_timeout(self):
		"""
		Handle TIMEOUT error in expect procedure
		return False
		"""
		logging.error("TIMEOUT error "+self.host)
		return False

	def exp_eof(self):
		'''
		Handle EOF error in expect procedure
		return False
		'''
		logging.error("EOF error "+self.host)
		return False

	def exp_default(self):
		logging.error("Can't connect to element: "+self.host)
		out = ""
		out = self.child.before.decode('ASCII')
		self.add_cli_text_errors(out)
		print(out)
		# return False

	def exp_reset_ssh_key(self):
		'''
		Handle "Host key verification failed." error in expect procedure
		When host key is changed, try to reset it with ssh-keygen command
		Then try to connect to the host again
		'''
		logging.info(""+self.host+": Key is changed. Reset ssh key required. Try to reset")
		regex = "(ssh-keygen -f .*)\\r?\\r?\\n?"
		out = self.child.before.decode('ASCII')
		print(["OUT = ", out])
		parsed_line = re.findall(regex, out)
		print(parsed_line)
		parsed_line = parsed_line[0]
		parsed_line=parsed_line.rstrip()
		self.child = pexpect.spawn(parsed_line)
		# out = self.child.before.decode('ASCII')
		i = self.child.expect (["Host .* found: line", pexpect.TIMEOUT, pexpect.EOF] )
		self.expect_procedures(i, self.exp_default, self.connect_ssh, self.exp_timeout, self.exp_eof)
		out = self.child.before.decode('ASCII')


	def exp_key_unknown(self):
		'''
		Handle "Are you sure you want to continue connecting (yes/no)?" in expect procedure
		When host key is unknown, try to enter "yes"
		'''
		logging.info(""+self.host+": Key is unknown (expect)...")
		self.enter_yes_unknown_key()

	def exp_access_denied(self):
		'''
		Handle "Permission denied, please try again." in expect procedure
		'''
		logging.error(""+self.host+"Login failed")
		self.add_cli_text_errors('Login failed')

	def connect(self):
		logging.info(""+self.host+": Connect...")
		if self.connect_ssh() is not False:
			i = self.child.expect ([self.caret_read, pexpect.TIMEOUT, pexpect.EOF,"Permission denied, please try again."] )
			self.expect_procedures(i, self.exp_default, self.after_login_success, self.exp_timeout, self.exp_eof, self.exp_access_denied)
		else:
			self.exp_default()


	def connect2(self):
		# Connect to element by SSH
		self.child = pexpect.spawn('ssh '+self.username+"@"+self.host)
		self.child.setwinsize(400,400)
		# Wiat password: string
		i = self.child.expect (["(P|p)assword:", pexpect.TIMEOUT, pexpect.EOF,"Are you sure you want to continue connecting (yes/no)?", "Invalid key length","Host key verification failed."] )
		# If return that key is unknown
		if i==3:
			logging.info("Key is unknown. Contunue (yes/no)? <yes>")
			# Send YES
			self.child.sendline("yes")
			# Wait password: again
			i = self.child.expect (["(P|p)assword:", pexpect.TIMEOUT, pexpect.EOF,"Are you sure you want to continue connecting (yes/no)?"] )
			# if return password, that enter it
			if i==0:
				logging.info("Connect to "+self.host+" success. Enter password after key is saved")
				self.child.sendline(self.password)
			# Else, say that something wrong
			else:
				logging.error("Can't connect to element: "+self.host+" =")
				out = ""
				out = self.child.before.decode('ASCII')
				print(out)
				return False
		# Try to login throught telnet
		elif i==4:
			self.child = pexpect.spawn('telnet '+self.host)
			self.child.setwinsize(400,400)	
			i = self.child.expect (["(U|u)sername:", pexpect.TIMEOUT, pexpect.EOF] )	
			if i==0:
				self.child.sendline(self.username)
				i = self.child.expect (["(P|p)assword:", pexpect.TIMEOUT, pexpect.EOF] )	
				if i==0:
					self.child.sendline(self.password)
					pass
				else:
					logging.error("Can't connect to element throught telnet (password): "+self.host)
				pass
			else:
				logging.error("Can't connect to element throught telnet (username): "+self.host)


		# If return that wait password, enter it
		elif i==0:
			logging.info("Connect to "+self.host+" success. Enter password")
			self.child.sendline(self.password)
		# Else, say that something wrong. Exit.
		else:
			logging.error("Can't connect to element: "+self.host)
			out = ""
			out = self.child.before.decode('ASCII')
			print(out)
			return False
		# Wait for first view of caret(#). It means that login success
		i = self.child.expect ([self.caret_read, pexpect.TIMEOUT, pexpect.EOF,"Permission denied, please try again."] )
		# If return login failed, that finish
		if i==3:
			logging.error("Login failed")
			return False
		# If return caret, it means that login success
		if i==0:
			self.after_login_success()
		# If return another error, that finish
		else:
			out = ""
			out = self.child.before.decode('ASCII')
			print("out = ")
			print(out)
			logging.error("Can't login to element (caret_read)"+self.host)
			return False
		pass
	def disable_more(self):
		'''
		Disable more function in CLI of router. It is done by one of two commands:
		- For Nokia: "environment no more"
		- For Huawei: "screen-length 0 temporary"
		'''
		if self.vendor == "nokia":
			self.exec_cli("environment no more")
		elif self.vendor == "huawei":
			self.exec_cli("screen-length 0 temporary")
		pass
	def get_device_sysinfo(self):
		'''
		Retrieve device information from CLI. Information includes system name, uptime and software version.
		For Nokia devices, command is "show system information".
		For Huawei devices, command is "display version".
		'''
		if self.vendor == "nokia":
			self.get_device_sysinfo_nokia()
		elif self.vendor == "huawei":
			self.get_device_sysinfo_huawei()

	def get_device_sysinfo_huawei(self):
		'''
		Retrieve device information from CLI. Information includes system name, uptime and software version.
		For Huawei devices, command is "display version".

		- ``sysname``: device's system name
		- ``sys_type``: device's system type
		- ``sys_version``: device's system version
		- ``sys_uptime``: device's system uptime
		'''
		# Временно меняем каретку чтобы распарсить SYSNAME
		old_carretRead = self.caret_read
		self.caret_read = ">"
		out = self.exec_cli("display version")
		# Возвращаем исходную каретку навсякий
		self.caret_read = old_carretRead

		regex_sysname = "^<(.*)"
		regex_type_uptime = "(.*) uptime is (.*)"
		regex_version = "\, Version (.*)$"

		# print(out)

		lines = out.split('\r\n')
		i = 0
		for line in lines:
			i = i+1
			parsed_line_name = re.findall(regex_sysname, line)
			parsed_line_type_uptime = re.findall(regex_type_uptime, line)
			parsed_line_version = re.findall(regex_version, line)


			# пропускаем строку если она пустая
			if len(parsed_line_name)==0 and len(parsed_line_type_uptime)==0 and len(parsed_line_version)==0:
				continue

			# Обрабатываем sysname
			if len(parsed_line_name)!=0:
				parsed_line = parsed_line_name[0]
				self.sysname = parsed_line
				self.caret_read = "<"+self.sysname+">"
			# Обрабатываем type
			if len(parsed_line_type_uptime)!=0 and i<=5:
				# parsed_line = parsed_line_type_uptime[0]
				self.sys_type = parsed_line_type_uptime[0][0]
				self.sys_uptime = parsed_line_type_uptime[0][1]
			# Обрабатываем version
			if len(parsed_line_version)!=0 and i<=5:
				parsed_line = parsed_line_version[0]
				self.sys_version = parsed_line
			# Обрабатываем uptime

		if self.debug>=1:
			print(bcolors.HEADER)
			print ("\r\nsysname = "+self.sysname+" type=\"" + self.sys_type + "\" version=\"" +self.sys_version + "\" uptime=\""+ self.sys_uptime + "\"\r\n")
			print(bcolors.ENDC)


	def get_device_sysinfo_nokia(self):
		"""
		Parses Nokia (Alcatel-Lucent) device's system information
		by executing "show system information" command.

		Attributes set after executing this method:

		- ``sysname``: device's system name
		- ``sys_type``: device's system type
		- ``sys_version``: device's system version
		- ``sys_uptime``: device's system uptime

		"""
		out = self.exec_cli("show system information")


		regex_sysname = "^System Name\s*:\s(.*)$"
		regex_type = "^System Type\s*:\s(.*)$"
		regex_version = "^System Version\s*:\s(.*)$"
		regex_uptime = "^System Up Time\s*:\s(.*)$"

		router_interfaces = {} # Define dict for save parsed interfaces
		lines = out.split('\r\n')
		for line in lines:
			parsed_line_name = re.findall(regex_sysname, line)
			parsed_line_type = re.findall(regex_type, line)
			parsed_line_version = re.findall(regex_version, line)
			parsed_line_uptime = re.findall(regex_uptime, line)

			# пропускаем строку если она пустая
			if len(parsed_line_name)==0 and len(parsed_line_type)==0 and len(parsed_line_version)==0 and len(parsed_line_uptime)==0:
				continue

			# Обрабатываем sysname
			if len(parsed_line_name)!=0:
				parsed_line = parsed_line_name[0]
				self.sysname = parsed_line
				self.caret_read = self.sysname+"#"
			# Обрабатываем type
			if len(parsed_line_type)!=0:
				parsed_line = parsed_line_type[0]
				self.sys_type = parsed_line
			# Обрабатываем version
			if len(parsed_line_version)!=0:
				parsed_line = parsed_line_version[0]
				self.sys_version = parsed_line
			# Обрабатываем uptime
			if len(parsed_line_uptime)!=0:
				parsed_line = parsed_line_uptime[0]
				self.sys_uptime = parsed_line
		if self.debug>=1:
			print ("\r\nsysname = "+self.sysname+" type=\"" + self.sys_type + "\" version=\"" +self.sys_version + "\" uptime=\""+ self.sys_uptime + "\"\r\n")
		pass

	def wait_caret(self, is_recursive_error = False):
		"""Wait for expected caret. If caret is not found, try to get errors and run wait_caret again.

		Args:
			is_recursive_error (bool): If True, then some error exist and function will run itself again.

		Returns:
			None
		"""
		i = self.child.expect ([self.caret_read, pexpect.TIMEOUT, pexpect.EOF,"Error:","MINOR:"], timeout=self.timeout)
		if i==1:
			self.add_cli_text_errors('Timeout')
			self.exp_timeout()

		if i==2:
			self.add_cli_text_errors('EOF')
			self.exp_eof()

		if i!=0:
			out = ""
			out = self.child.before.decode('ASCII')
			print("CARET: "+self.caret_read+"|")
			print(out)		
			self.add_cli_text_errors(out)
			logging.error("Some Error occurs!")
			# run wait_caret again
			self.wait_caret(True)
			pass
		pass
		if i==0:
			if not is_recursive_error:
				if self.debug >=2:
					logging.info("expect: wait caret success")
			else:
				logging.info("expect: wait again caret. Some error exist.")
			pass

	# Run command on router and returt result
	def exec_cli(self, command):
		"""Run command on router and return result
		
		Args:
			command (str): Command to run
		
		Returns:
			str: Result of command
		"""
		if self.child is None:
			print("You must connect first. Use .connect()")
			return False
		self.child.sendline(command)
		self.wait_caret()
		out = ""
		out = self.child.before.decode('ASCII')
		return out


	def add_cli_text_errors(self, msg):
		if self.sysname is None:
			sysname = self.host
		else:
			sysname = self.sysname
		self.cli_error_messages += sysname + ': ' + msg + '\n'




class HuaweiEquipCLI(EquipCLI):
	def cli_display_interface_brief(self):
		return self.exec_cli("display interface brief")
	def cli_display_interface_description(self):
		return self.exec_cli("display interface description")
	def cli_display_ip_vpn_instance(self):
		return self.exec_cli("display ip vpn-instance")
	def cli_display_arp_vpn_instance_X(self, arg):
		if self.sysVersion=="5.160 (NE40E&80E V600R008C10SPC300)":
			return self.exec_cli("display arp vpn-instance "+arg+" all")
		# elif self.sysVersion=="8.220 (NetEngine 8000 V800R022C00SPC600)":
		#	 return self.exec_cli("display arp vpn-instance "+arg+" slot 15")
		elif "(NetEngine 8000 V800R02" in self.sysVersion:
			return self.exec_cli("display arp vpn-instance "+arg+" slot 15")
		elif "NE40E&80E V600R009" in self.sysVersion:
			return self.exec_cli("display arp vpn-instance "+arg+" all")
		elif "NE40E V800R021" in self.sysVersion or " (NE40E V800R022" in self.sysVersion:
			return self.exec_cli("display arp all | in "+arg)
		else:
			return self.exec_cli("display arp vpn-instance "+arg)
	def cli_display_ip_interface_brief(self):
		return self.exec_cli("display ip interface brief")
	def cli_display_mac_address(self):
		return self.exec_cli("display mac-address")
	def cli_display_vsi_services_all(self):
		# IF Switch, then skip
		if "5.110 (S5300 V200R001C00SPC300)" in self.sysVersion:
			return ""
		return self.exec_cli("display vsi services all")
	def cli_display_ve_group(self):
		# IF Switch, then skip
		if "5.110 (S5300 V200R001C00SPC300)" in self.sysVersion:
			return ""
		return self.exec_cli("display virtual-ethernet ve-group")

		
class NokiaEquipCLI(EquipCLI):
	"""docstring for NokiaEquip"""
	# Run show router X interface command and return output
	def cli_show_system_information(self):
		return self.exec_cli("show system information")


	# Run show router X interface command and return output
	def cli_show_router_X_interface(self, service_id = ""):
		out = self.exec_cli("show router "+service_id+" interface")
		return out

	# Run show service service-using command and return output
	def cli_show_service_service_using(self):
		return self.exec_cli("show service service-using | match _tmnx_Internal invert-match")

	# Run show service sap-using command and return output
	def cli_show_service_sap_using(self):
		return self.exec_cli("show service sap-using")

	# Run show service sdp-using command and return output
	def cli_show_service_sdp_using(self):
		return self.exec_cli("show service sdp-using")

	# Run show service fdb-mac command and return output
	def cli_show_service_fdb_mac(self, match=""):
		if match!="":
			match=" | match "+match
		return self.exec_cli("show service fdb-mac" + match)

	# Run show router X arp command and return output
	def cli_show_router_X_arp(self, service_id = ""):
		return self.exec_cli("show router "+service_id+" arp")

	# Run show port command and return output
	def cli_show_port_brief(self):
		return self.exec_cli("show port")

	# Run show port description command and return output
	def cli_show_port_description(self):
		return self.exec_cli("show port description")

	# Run show port X/X/X command and return output
	def cli_show_port_detail(self, portid):
		return self.exec_cli("show port "+portid+' | match exp "avg dBm|Change|Descr"')

	# Run show port command and return output
	def cli_show_lag_description(self):
		return self.exec_cli("show lag description")
# --- END Class Equip ---
		