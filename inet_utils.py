from log import Log
import socket
from enum import Enum
import inet_utils as utils
### Port declarations ###

#   broadcast of rpi ip address and streaming data
UDP_PORT = 9999
#   tcp commands
TCP_PORT    = 5005

# build the message:
#   4 digits to specify legth of following message in bytes
#   message in bytes: cmd_nr:cmd_val
def make_message(cmd_nr: int, cmd_val: int) -> str:
    msg = str(cmd_nr) + ':' + str(cmd_val)
    msg = (str(len(msg))).zfill(4) + msg
    return msg

def make_message(msg: str) -> str:
    if type(msg) != str:
        msg = str(msg)
    msg = (str(len(msg))).zfill(4) + msg
    return msg

class Client:
    id_static: int = 0

    def __init__(self, ip: str, port: int, client_socket: socket.socket):
        self.ip = ip
        self.port = port
        self.client_id = self.id_static
        self.id_static = self.id_static + 1
        self.client_socket = client_socket

    def send_message(self, server_socket, msg: str):
        msg = utils.make_message(msg)
        try:
            self.client_socket.send(msg.encode('utf-8'))
            self.print_log('==>SEND: \'', msg[4:len(msg):1], '\' to ', self.ip, ':', str(self.port))
        except OSError as e:
            self.print_log('Can\'t send message to ' + self.ip + ':' + str(self.port), ' -> ', e)

    def close(self):
        try:
            self.client_socket.shutdown(socket.SHUT_RDWR)
            self.client_socket.close()
        except OSError as e:
            self.print_log('Error while closing client socket: ', e)

    def print_log(self, *args, **kwargs):
        Log.log('[Client ' + str(self.client_id) + '] ', *args, **kwargs)

# TCP command container with the client, who sent the command
class Command:
    def __init__(self, cmd, val, connection: Client):
        self.command = cmd
        self.value = val
        self.connection = connection

# Available commands that can be send via TCP 
# with the specified integer-key
class TcpCommandType(Enum):
    START = 1
    STOP = 2
    SET_COLOR = 3
    SET_BRIGHTNESS = 4
    INTENSITY = 5
    SEND_STATUS = 6
    OPERATION_MODE = 7
    CONNECT = 8
    DISCONNECT = 9
    MODE = 10
    MESSAGE = 11

class TcpMessageTypes(Enum):
    CONNECTION_ACCEPTED = 1
    CONNECTION_DENIED = 2

class ServerOperationMode(Enum):
    OFF = 0
    NORMAL = 1
    SOUND = 2
    BC = 3

class BroadcastMessages(Enum):
    WHERE_IS_PI = 1

class Spectrum():
    bass: int
    mid: int
    treb: int

    def __getitem__(self, item):
        if item == 0:
            return self.bass
        if item == 1:
            return self.mid
        if item == 2:
            return self.treb
        raise IndexError

    def __init__(self, bass: int = 0, mid: int = 0, treb: int = 0) -> None:
        self.bass = bass
        self.mid = mid
        self.treb = treb

class ServerState(Enum):
    CONNECTED = 1,
    OPEN = 2,
    CLOSED = 3