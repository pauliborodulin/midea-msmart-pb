
from abc import ABC, abstractmethod
import asyncio
import logging
import time
from typing import Union

from msmart.lan import LAN, ProtocolError
from msmart.types import Token, Key

_LOGGER = logging.getLogger(__name__)


class device(ABC):

    def __init__(self, *, ip: str, port: int, id: int, **kwargs):
        self._ip = ip
        self._port = port

        self._id = id
        self._sn = kwargs.get("sn", None)
        self._name = kwargs.get("name", None)
        self._type = kwargs.get("type", None)

        self._lan = LAN(ip, port, id)
        self._support = False
        self._online = False

    @abstractmethod
    async def refresh(self):
        raise NotImplementedError()

    @abstractmethod
    async def apply(self):
        raise NotImplementedError()

    async def authenticate(self, token: Token, key: Key):
        return await self._lan.authenticate(token, key)

    async def send_command(self, command: bytes):

        data = command.pack()
        _LOGGER.debug("Sending command to %s:%d: %s.",
                      self.ip, self.port, data.hex())

        start = time.time()
        responses = None
        try:
            responses = await self._lan.send(data)
        except (ProtocolError, TimeoutError, asyncio.TimeoutError) as e:
            _LOGGER.error("Network error: %s", e)
        finally:
            response_time = round(time.time() - start, 2)

        if responses is None:
            _LOGGER.warning("No response from %s:%d in %f seconds. ",
                            self.ip, self.port, response_time)
            return None

        _LOGGER.debug("Response from %s:%d in %f seconds.",
                      self.ip, self.port, response_time)

        return responses

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def port(self) -> int:
        return self._port

    @property
    def id(self) -> int:
        return self._id

    @property
    def type(self) -> Union[str, None]:
        return self._type

    @property
    def name(self) -> Union[str, None]:
        return self._name

    @property
    def sn(self) -> Union[str, None]:
        return self._sn

    @property
    def online(self) -> bool:
        return self._online

    def __str__(self) -> str:
        return f"{self.ip}:{self.port} Type: {self.type} ID: {self.id}"
