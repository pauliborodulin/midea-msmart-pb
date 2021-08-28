# -*- coding: UTF-8 -*-
import asyncio
import logging
import socket
from msmart.cloud import cloud
from msmart.const import BROADCAST_MSG, DEVICE_INFO_MSG, OPEN_MIDEA_APP_ACCOUNT, OPEN_MIDEA_APP_PASSWORD
from msmart.device import air_conditioning_device as ac
from msmart.security import get_udpid, security
try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

VERSION = '0.1.33'

_LOGGER = logging.getLogger(__name__)

Client = None
_security = security()

class scandevice:

    def __init__(self):
        self.type = 'unknown'
        self.support = False
        self.version = 0
        self.ip = None
        self.id = None
        self.port = None
        self.token = None
        self.key = None
        self.ssid = None

    def __str__(self):
        return str(self.__dict__)
    
    async def support_test(self, account=OPEN_MIDEA_APP_ACCOUNT, password=OPEN_MIDEA_APP_PASSWORD):
        if self.version == 3:
            _device = await self.support_testv3(account, password)
        else:
            _device = ac(self.ip, self.id, self.port)
        if self.type == 'ac':
            _device.refresh()
            _LOGGER.debug("{}".format(_device))
            self.support = _device.support
        return self

    async def support_testv3(self, account, password):
        _device = ac(self.ip, self.id, self.port)
        for udpid in [get_udpid(self.id.to_bytes(6, 'little')), get_udpid(self.id.to_bytes(6, 'big'))]:
            token, key = gettoken(udpid, account, password)
            auth = _device.authenticate(key, token)
            if auth:
                self.token, self.key = token, key
                return _device
        return _device

    @staticmethod
    async def load(ip, data):
        if len(data) >= 104 and (data[:2].hex() == '5a5a' or data[8:10].hex() == '5a5a'):
            return scandeviceV2V3(data)
        if data[:6].hex() == '3c3f786d6c20':
            return scandeviceV1(ip, data)

class scandeviceV2V3(scandevice):
    def __init__(self, data):
        super().__init__()
        self.insert(data)
    
    def insert(self, data):
        if data[:2].hex() == '5a5a':
            self.version = 2
        if data[:2].hex() == '8370':
            self.version = 3
        if data[8:10].hex() == '5a5a':
            data = data[8:-16]
        self.id = int.from_bytes(data[20:26], 'little')
        encrypt_data = data[40:-16]
        reply = _security.aes_decrypt(encrypt_data)
        self.ip = '.'.join([str(i) for i in reply[3::-1]])
        _LOGGER.debug("Decrypt Reply: {} {}".format(self.ip, reply.hex()))
        self.port = int.from_bytes(reply[4:8], 'little')
        # ssid like midea_xx_xxxx net_xx_xxxx
        self.ssid = reply[41:41+reply[40]].decode("utf-8")
        self.type = self.ssid.split('_')[1]

class scandeviceV1(scandevice):
    def __init__(self, ip, data):
        super().__init__()
        self.version = 1
        self.ip = ip
        self.insert(data)

    def insert(self, data):
        root = ET.fromstring(data.decode(encoding="utf-8", errors="replace"))
        child = root.find('body/device')
        m = child.attrib
        self.port, self.type = m['port'], str(hex(int(m['apc_type'])))[2:]
        
        self.id = self.get_device_id()

    def get_device_id(self, response):
        response = self.get_device_info()
        if response[64:-16][:6].hex() == '3c3f786d6c20':
            xml = response[64:-16]
            root = ET.fromstring(xml.decode(encoding="utf-8", errors="replace"))
            child = root.find('smartDevice')
            m = child.attrib
            return int.from_bytes(bytearray.fromhex(m['devId']), 'little')
        else:
            return 0

    def get_device_info(self):
        # Create a TCP/IP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(8)

        try:
            # Connect the Device
            device_address = (self.ip, self.port)
            sock.connect(device_address)

            # Send data
            _LOGGER.debug("Sending to {}:{} {}".format(
                self.ip, self.port, DEVICE_INFO_MSG.hex()))
            sock.sendall(DEVICE_INFO_MSG)

            # Received data
            response = sock.recv(512)
        except socket.error:
            _LOGGER.info("Couldn't connect with Device {}:{}".format(
                self.ip, self.port))
            return bytearray(0)
        except socket.timeout:
            _LOGGER.info("Connect the Device {}:{} TimeOut for 8s. don't care about a small amount of this. if many maybe not support".format(
                self.ip, self.port))
            return bytearray(0)
        finally:
            sock.close()
        _LOGGER.debug("Received from {}:{} {}".format(
            self.ip, self.port, response.hex()))
        return response

class MideaDiscovery:
    count = 1
    socket = None

    def __init__(self, account=None, password=None):
        """Init discovery."""
        self.account = account
        self.password = password
        self.socket = _get_socket()

    async def find(self, ip=None):
        if ip is not None:
            return self.get(ip)
        return await self.get_all()

    async def get_all(self):
        await self._broadcast_message(self.count)
        tasks = set()
        while True:
            
            task = await self._get_response()
            if task:
                tasks.add(task)
            else:
                break
        if len(tasks) > 0:
            await asyncio.wait(tasks)
            return [task.result() for task in tasks]
        else:
            return []

    def get(self, ip):
        self._send_message(ip)
        return asyncio.run(self._get_response(), ip)

    async def _get_response(self, ip=None):
        try:
            data, addr = self.socket.recvfrom(512)
            if ip is not None and addr[0] != ip:
                return None
            else:
                ip = addr[0]
            _LOGGER.debug("Midea Local Data {} {}".format(ip, data.hex()))
            device = await scandevice.load(ip, data)
            return asyncio.create_task(device.support_test(self.account, self.password))
        except socket.timeout:
            _LOGGER.info("Socket timeout")
            return None

    async def _broadcast_message(self, amount):
        for i in range(amount):
            self.socket.sendto(
                BROADCAST_MSG, ("255.255.255.255", 6445)
            )
            self.socket.sendto(
                BROADCAST_MSG, ("255.255.255.255", 20086)
            )
            _LOGGER.debug("Broadcast message sent: " + str(i))

    async def _send_message(self, address):
        self.socket.sendto(
            BROADCAST_MSG, (address, 6445)
        )
        self.socket.sendto(
            BROADCAST_MSG, (address, 20086)
        )
        _LOGGER.debug("Message sent")

def gettoken(udpid, account, password):
    global Client
    if Client is None:
        Client = cloud(account, password)
    if Client.session == {}:
        Client.login()
    return Client.gettoken(udpid)
    
def _get_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(5)
    return sock
