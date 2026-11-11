"""Shared wire constants, independent of codec and transport implementations."""

MAGIC = b"hd"
PK_TYPE = b"pk"
DK_TYPE = b"dk"
DEFAULT_KEY = b"khggd54865SNJHGF"
HEADER_LENGTH = 42
SESSION_LENGTH = 32
MAX_PACKET_LENGTH = 0xFFFF

UDP_PORT = 10000
TCP_PORT = 8088
UDP_BROADCAST = "255.255.255.255"
SOFTWARE_VER = "5.1.3.309"
SOFTWARE_NAME = "ZhiJia365"
SOFTWARE_VERSION = "50103309"
SYS_VERSION = "Android14_34"
HARDWARE_VERSION = "Google Pixel 8"
LANGUAGE = "zh"
PHONE_NAME = "Pixel 8"
DEBUG_INFO = "Android_ZhiJia365_34_5.1.3.309"
# Control commands were captured from a newer app build than the session
# handshake above. Both are kept as captured; the connection only fills in
# SOFTWARE_VER/DEBUG_INFO for requests that do not set their own.
CONTROL_SOFTWARE_VER = "5.1.5.302"
CONTROL_DEBUG_INFO = "Android_ZhiJia365_34_5.1.5.302"
SIGN_KEY = "nQ45RjPtOws96jmH"
HTTPS_HOST = "homemate.orvibo.com"

# Command constants
CMD_HELLO = 0
CMD_LOGIN = 2
CMD_CONTROL = 15
CMD_STATE_UPDATE = 42
CMD_HEARTBEAT = 32

ID_UNSET = b"\x20" * 32
