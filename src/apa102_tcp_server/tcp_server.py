import json
import queue
import socket
import threading
import re
from typing import List
from apa102_tcp_server.log import Log
from apa102_tcp_server.led_audio_controller import Controller
from apa102_tcp_server.inet_utils import Client, ServerOperationMode, Command, ServerState, TcpMessageTypes
from apa102_tcp_server.config_laoder import ConfigLoader
import logging


class TcpServer:
    # Constants
    PORT: int
    BUFFER_SIZE: int
    MAX_CLIENTS: int
    MAX_DIGITS_MESSAGE = 4
    PATTER_COMMAND = re.compile(r'[0-9]+:(-)*[0-9]+')
    controller: Controller
    server_terminated: bool = True

    # thread_tcp: threading.Thread

    connected_clients = []
    # Incomming commands

    def __init__(self, cl: ConfigLoader, condition_var: threading.Condition,
                 buffer_size: int = 1024, max_clients: int = 1) -> None:
        self.PORT = cl['tcp.port']
        self.BUFFER_SIZE = buffer_size
        # Internet Socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Listener Thread
        self.thread_tcp = threading.Thread(target=self.listener)
        self.MAX_CLIENTS = max_clients
        # Condition variable
        self.notificator_commands = condition_var
        self.command_queue = queue.Queue()
        self.thread_locker = threading.Lock()
        self.stop_timeout = cl['tcp.thread_close_timeout_s']

        self.log = logging.getLogger('TCP SERVER')

    def start(self, controller: Controller) -> None:
        # start listener thread
        self.log.info('Invoke Tcp Server startup')
        self.server_terminated = False
        if not self.thread_tcp.is_alive():
            self.thread_tcp.start()
        self.controller = controller

    def stop(self) -> None:
        # stop the listener thread
        self.server_terminated = True
        n = self.close_all()
        self.log.info(f'Closed all connections ({n})')
        self.log.info(f'Waiting {self.stop_timeout} seconds for TCP thread to stop')
        self.thread_tcp.join(self.stop_timeout)
        if not self.thread_tcp.is_alive():
            self.log.info('TCP thread stopped normally')
        else:
            self.log.error('Could not stop tcp thread within given timeout!')
            return
        self.socket.close()
        self.log.info('TCP server stopped successfully')

    def listener(self) -> int:
        # Wait for Client to connect
        self.socket.bind(('0.0.0.0', self.PORT))
        self.socket.listen()
        self.socket.settimeout(0.5)
        # Avoids occassionally crash when controller was not ready set up
        first = True
        while 1:
            try:
                self.controller
                break
            except AttributeError:
                if first:
                    self.log.info('Wait for setup...')
                    first = False
                pass
        self.controller.state = ServerState.OPEN
        self.log.info(f"Server ready on port {self.PORT}")
        while True:
            # Incoming connection
            try:
                if self.server_terminated:
                    self.log.info(f'Incomming connection listener stops because server has been terminated')
                    return 0
                client_socket, client_address = self.socket.accept()
            except socket.timeout:
                continue
            except OSError as e:
                self.log.exception(f'Listener thread received an error while accepting incomming connection!')
                return 2

            self.log.info(f'New connection request from {client_address[0]}: {client_address[1]}')
            # Close connection, if maximum number of clients are already connected
            if len(self.connected_clients) >= self.MAX_CLIENTS:
                client = Client(client_address[0], client_address[1], client_socket)
                client.send_message("REFUSED")
                client_socket.close()
                self.log.warning(f'Connection refused: {client_address[0]}: {str(client_address[1])}\
                               because no more clients can connect.')
                continue

            self.controller.state = ServerState.CONNECTED

            # Register Client:
            client = Client(client_address[0], client_address[1], client_socket)
            self.connected_clients.append(client)
            self.log.info(f'Connection accepted ({len(self.connected_clients)} total connections):\
                            {client_address[0]}: {str(client_address[1])}')
            client.send_message(json.dumps({'type': TcpMessageTypes.CONNECTION_ACCEPTED.name, 'message': '0'}))
            # Start the client routine
            try:
                handler_thread = threading.Thread(target=self.client_routine, name=('Client_' + str(client.client_id)),
                                                  args=(client,))
                handler_thread.start()
            except Exception as e:
                self.log.exception(f"Error in Client Thread ({client.client_id})")
                self.close_client_connection(client.client_id)
                self.controller.state = ServerState.CLOSED

    def client_routine(self, client: Client) -> bool:
        while 1:
            length_data = self.receive_all(client.client_socket, self.MAX_DIGITS_MESSAGE, self.log)
            if not length_data:
                self.log.info(f'Connection {client.client_id} has been closed by remote device')
                self.close_client_connection(client.client_id)
                return True
            self.log.info(f'<== Received from client {client.ip} {length_data}B')
            try:
                data_rec = self.receive_all(client.client_socket, int(length_data), self.log)
            except ValueError:
                self.log.exception(f'Failed parsing command length to int, close connection at {client.ip}')
                self.close_client_connection(client.client_id)
                return False
            if not data_rec:
                self.log.error(f'Failed to read {length_data}B from {client.ip}, close connection')
                self.close_client_connection(client.client_id)
                return False
            cmd_nr, cmd_val = self.parse_command(self, data_rec)
            if cmd_nr is None or cmd_val is None:
                self.log.error(f'Invalid Command Signature (pattern), got {data_rec}')
                client.send_message('Invalid Command Pattern')
                continue
            self.log.info(f"Client {client.ip}: CMD n:{cmd_nr} v:{cmd_val}")
            try:
                self.notificator_commands.acquire()
                self.command_queue.put(Command(cmd_nr, cmd_val, client))
                self.notificator_commands.notify_all()
            finally:
                self.notificator_commands.release()

    @staticmethod
    def receive_all(conn: socket.socket, remains, log) -> str:
        buf = ''
        while remains:
            try:
                data = conn.recv(remains).decode('utf-8')
            except ConnectionResetError:
                log.exception(f'Client {threading.get_ident()}: Remote connection closed by remote device')
                return
            except ConnectionAbortedError:
                log.exception(f'Client {threading.get_ident()}: Remote connection aborted')
                return
            except OSError:
                log.exception(f'Client {threading.get_ident()}: Connection down')
                return
            if not data:
                break
            buf += data
            remains -= len(data)
        return buf

    @staticmethod
    def parse_command(self, cmd: str) -> List[int, int]:
        if not self.PATTER_COMMAND.match(cmd):
            return [None, None]
        cmd = cmd.split(sep=":")
        return [int(cmd[0]), int(cmd[1])]

    def send_answer(self, client: Client, msg: str) -> bool:
        return client.send_message(str(msg))

    def close_client_connection(self, client_id: int) -> bool:
        for c in self.connected_clients:
            if isinstance(c, Client) and c.client_id == client_id:
                success = c.close()
                self.log.info(f'Closed TCP connection at {c.ip}')
                self.connected_clients.remove(c)
                if len(self.connected_clients) == 0:
                    self.controller.state = ServerState.OPEN
                break
        if len(self.connected_clients) == 0:
            self.controller.udp_server.change_mode(ServerOperationMode.BC)
        return success

    def close_all(self) -> int:
        counter = 0
        for c in self.connected_clients:
            if isinstance(c, Client):
                c.close()
                self.connected_clients.remove(s)
                self.log.info(f'   Terminated TCP connection at {c.ip}')
                counter = counter + 1
        return counter

    def get_next_command(self) -> Command:
        # Wait for queue input without timeout
        c = self.command_queue.get(block=True)
        return c

    def invoke_queue_termination(self) -> None:
        # Enqueue termination process
        while not self.command_queue.empty():
            self.command_queue.get(block=False)
        self.command_queue.queue.clear()
        self.command_queue.put(Command(-1, -1, None))
