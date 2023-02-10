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

    def start(self, controller: Controller) -> None:
        # start listener thread
        self.print_log('Startup')
        self.server_terminated = False
        if not self.thread_tcp.is_alive():
            self.thread_tcp.start()
        self.controller = controller

    def stop(self) -> None:
        # stop the listener thread
        self.server_terminated = True
        n = self.close_all()
        self.print_log('Closed all connections (', n, ')')
        self.print_log('Waiting 5 seconds for TCP thread to stop')
        self.thread_tcp.join(self.stop_timeout)
        if not self.thread_tcp.is_alive():
            self.print_log('TCP thread stopped')
        else:
            self.print_log('Timeout, could not stop tcp thread!')
            return
        self.socket.close()
        self.print_log('TCP server stopped successfully')

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
                    print('Wait for setup...')
                    first = False
                pass
        self.controller.state = ServerState.OPEN
        self.print_log("Server ready on port ", self.PORT)
        while True:
            # Incoming connection
            try:
                if self.server_terminated:
                    return 0
                client_socket, client_address = self.socket.accept()
            except socket.timeout:
                continue
            except OSError as e:
                self.print_log('listener thread: ', e)
                return 1

            self.print_log('New connection request from ' + client_address[0] + ':' + str(client_address[1]))
            # Close connection, if maximum number of clients are already connected
            if len(self.connected_clients) >= self.MAX_CLIENTS:
                client = Client(client_address[0], client_address[1], client_socket)
                client.send_message("REFUSED")
                client_socket.close()
                self.print_log(f'Connection refused: {client_address[0]}: {str(client_address[1])}\
                               because no more clients can connect.')
                continue

            self.controller.state = ServerState.CONNECTED

            # Register Client:
            client = Client(client_address[0], client_address[1], client_socket)
            self.connected_clients.append(client)
            self.print_log(f'Connection accepted ({len(self.connected_clients)} total connections):\
                            {client_address[0]}: {str(client_address[1])}')
            client.send_message(json.dumps({'type': TcpMessageTypes.CONNECTION_ACCEPTED.name, 'message': '0'}))
            # Start the client routine
            try:
                handler_thread = threading.Thread(target=self.client_routine, name=('Client_' + str(client.client_id)),
                                                  args=(client,))
                handler_thread.start()
            except Exception as e:
                self.print_log("Error in Client Thread (", client.client_id, ")")
                self.close_client_connection(client.client_id)
                self.controller.state = ServerState.CLOSED
                self.print_log(str(e))

    def client_routine(self, client: Client) -> bool:
        while 1:
            length_data = self.receive_all(client.client_socket, self.MAX_DIGITS_MESSAGE)
            if not length_data:
                self.print_log('Connection ' + str(client.client_id), 'has been closed by remote device')
                self.close_client_connection(client.client_id)
                return True
            self.print_log('<== Received from client [', client.client_id, '] ', length_data, ' Bytes')
            try:
                data_rec = self.receive_all(client.client_socket, int(length_data))
            except ValueError:
                self.print_log('Failed parsing command length to int')
                self.close_client_connection(client.client_id)
                return False
            if not data_rec:
                self.print_log('Failed to read ', length_data, ' Bytes')
                self.close_client_connection(client.client_id)
                return False
            cmd_nr, cmd_val = self.parse_command(self, data_rec)
            if cmd_nr is None or cmd_val is None:
                self.print_log('Invalid Command Signature (pattern)')
                client.send_message('Invalid Command Pattern')
                continue
            self.print_log("Client [", client.client_id, "]: CMD ", cmd_nr, '(', cmd_val, ')')
            try:
                self.notificator_commands.acquire()
                self.command_queue.put(Command(cmd_nr, cmd_val, client))
                self.notificator_commands.notify_all()
            finally:
                self.notificator_commands.release()

    @staticmethod
    def receive_all(conn: socket.socket, remains) -> str:
        buf = ''
        while remains:
            try:
                data = conn.recv(remains).decode('utf-8')
            except ConnectionResetError:
                print('[Client ', threading.get_ident(), '] Remote connection closed by remote device')
                return
            except ConnectionAbortedError:
                print('[Client ', threading.get_ident(), '] Remote connection aborted')
                return
            except OSError:
                print('[Client ', threading.get_ident(), '] Connection down')
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
                self.print_log('Terminated TCP connection of client [', client_id, ']: ' + c.ip + ':' + str(c.port))
                self.connected_clients.remove(c)
                if len(self.connected_clients) == 0:
                    self.controller.state = ServerState.OPEN
                break
        if len(self.connected_clients) == 0:
            self.controller.udp_server.change_mode(ServerOperationMode.BC)
        return success

    def close_all(self) -> int:
        counter = 0
        for s in self.connected_clients:
            if isinstance(s, Client):
                s.close()
                self.connected_clients.remove(s)
                self.print_log('   Terminated TCP connection of client: ' + s.ip + ':' + str(s.port))
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

    @staticmethod
    def print_log(*args, **kwargs):
        Log.log('[TCP SERVER] ', *args, **kwargs)
