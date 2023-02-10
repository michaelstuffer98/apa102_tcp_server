import queue
import socket
import threading
import re
import json
from typing import Callable
import apa102_tcp_server.inet_utils as tc
from apa102_tcp_server.log import Log
from apa102_tcp_server.config_laoder import ConfigLoader


class UdpServer:
    # Constants
    BUFFER_SIZE: int
    MAX_CLIENTS: int = 1
    # Internet Socket
    udp_socket: socket.socket
    connected_clients = []
    # Incomming commands
    message_queue = queue.Queue()
    # Threading helper
    condition_queue = threading.Condition()
    condition_worker = threading.Condition()
    condition_server = threading.Condition()

    # How long the main thread will wait until the called thread notified on its startup in seconds
    timeout_thread_start = 3.0

    server_cancelled: bool = False
    waiting_for_notification = False

    def __init__(self, cl: ConfigLoader, server_mode: tc.ServerOperationMode,
                 stream_data_function, buffer_size: int = 256) -> None:
        self.PORT: int = cl['udp.port'],
        self.BUFFER_SIZE: int = buffer_size
        self.mode: tc.ServerOperationMode = server_mode
        # Listener Thread
        self.thread_udp: threading.Thread = None
        self.command_worker_thread: threading.Thread = None
        self.ident: str = cl['udp.server_ident'],
        self.tcp_info: int = cl['tcp.port'],
        self.processor = ProcessorBc(self.server_ident, self.tcp_info)
        self.stream_data_function: Callable[[int], None] = stream_data_function
        self.timeout_start: float = cl['udp.thread_start_timeout_s']
        self.timeout_close: float = cl['udp.thread_close_timeout_s']

    def start(self) -> bool:
        # Start server listener Thread
        self.server_cancelled = False
        timeout = False
        # Start udp listener thread
        if self.thread_udp is None:
            self.thread_udp = threading.Thread(target=self.udp_server_thread,
                                               name=f'UDP_{self.mode.name}_LISTENER_THREAD')
        if not self.thread_udp.is_alive():
            self.thread_udp.start()
            with self.condition_server:
                self.waiting_for_notification = True
                timeout = not self.condition_server.wait(self.timeout_thread_start)
                self.waiting_for_notification = False
        # Received no notification:
        if timeout:
            self.server_cancelled = True
            return False
        # Start command worker thread
        if self.command_worker_thread is None:
            self.command_worker_thread = threading.Thread(target=self.command_worker,
                                                          name=f'udp_{self.mode.name}_worker_thread')
        if not self.command_worker_thread.is_alive():
            self.command_worker_thread.start()
            with self.condition_worker:
                self.waiting_for_notification = True
                timeout = not self.condition_worker.wait(self.timeout_thread_start)
                self.waiting_for_notification = False
        if timeout:     # Recevied no notification
            self.server_cancelled = True
            return False
        status = self.status()
        return status[0] and status[1]

    def stop(self) -> None:
        self.server_cancelled = True
        if self.thread_udp is not None:
            self.print_log('Waiting for server thread to end')
            self.thread_udp.join(3.0)
            if self.thread_udp.is_alive():
                self.print_log('Could not stop udp server thread properly!')
        if self.command_worker_thread is not None:
            self.print_log('Waiting for command thread to end')
            # self.message_queue.clear()
            # insert dummy to notify command worker thread
            self.message_queue.put(-1, block=True)
            self.command_worker_thread.join(3.0)
            if self.command_worker_thread.is_alive():
                print(self.message_queue.empty())
                self.print_log('Could not stop udp command thread properly!')

    # Tuple with status of the worker thread and server thread
    # False means not running
    def status(self) -> tuple[bool, bool]:
        try:
            return (self.command_worker_thread.is_alive(), self.thread_udp.is_alive())
        except AttributeError:
            return (self.command_worker_thread is not None, self.thread_udp is not None)

    def change_mode(self, mode: tc.ServerOperationMode) -> None:
        if mode == tc.ServerOperationMode.BC:
            self.processor = ProcessorBc(self.ident, self.tcp_info)
        elif mode == tc.ServerOperationMode.SOUND:
            self.processor = ProcessorStream(self.stream_data_function)
        elif mode == tc.ServerOperationMode.OFF:
            self.processor = None
        elif mode == tc.ServerOperationMode.NORMAL:
            self.processor = None
        else:
            self.processor = None
        self.print_log('Mode changed to ', mode.name)

    def udp_server_thread(self) -> bool:
        while not self.waiting_for_notification:
            if self.server_cancelled:
                return
        with self.condition_server:
            self.condition_server.notify()
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.settimeout(0.5)
        self.udp_socket.bind(('', self.PORT))
        self.print_log("Server ready on port ", self.PORT)
        while 1:
            try:
                bytes, address = self.udp_socket.recvfrom(self.BUFFER_SIZE)
            except socket.timeout:
                if self.server_cancelled:
                    self.print_log('Return normally from cancelled thread ', threading.current_thread().name)
                    return True
                continue
            if bytes is not None:
                msg = bytes.decode('utf-8')
            # with self.condition_queue:
            self.message_queue.put((msg, address))
            #    self.condition_queue.notify()

    def command_worker(self) -> bool:
        while not self.waiting_for_notification:
            if self.server_cancelled:
                return True
        with self.condition_worker:
            self.condition_worker.notify()
        while 1:
            try:
                # with self.condition_queue:
                # self.condition_queue.wait_for(self.queue_is_not_empty)
                message = self.message_queue.get(block=True)
                if self.server_cancelled:
                    self.message_queue.queue.clear()
                    return True
                msg, address = message      # self.message_queue.pop()
            except IndexError as e:
                self.print_log(f'[UDP worker] Error when accessing the command queue: \
                               {threading.current_thread().ident}: {e}')
                continue
            ret = None
            if self.processor is not None:
                ret = self.processor.process_message(msg)
            if ret is not None and ret != "":
                n_bytes = self.udp_socket.sendto(ret.encode('utf-8'), address)
                self.print_log('[UDP worker] Send ', n_bytes, ' bytes to ', address)

    def print_log(self, *args, **kwargs):
        Log.log('[UPD SERVER ' + self.mode.name + '] ', *args, **kwargs)

    @staticmethod
    def recvall(conn, remains):
        buf = ""
        while remains:
            data = conn.recv(remains).decode()
            if not data:
                break
            buf += data
            remains -= len(data)
        return buf


class ProcessorBc():
    def __init__(self, ident: str, tcp_info: str) -> None:
        self.my_info = json.dumps({'ident': ident, 'port': tcp_info})

    def process_message(self, msg: str) -> str:
        try:
            m = tc.BroadcastMessages[msg]
        except KeyError:
            return None
        default = "No handler for " + str(m.name)
        return getattr(self, "_" + m.name + '_handler', lambda i: default)()

    # String to be sent back, return None if nothing should be send
    def _WHERE_IS_PI_handler(self) -> str:
        return self.my_info


class ProcessorStream():
    PATTER_COMMAND = re.compile(r'[0-9]{1,3}:[0-9]{1,3}:[0-9]{1,3}')

    def __init__(self, func_interface: Callable[[int], None]) -> None:
        self.strip_interface = func_interface

    def process_message(self, msg: str) -> str:
        if not self.PATTER_COMMAND.match(msg):
            return None
        spec = self.parse_spec(msg)
        if spec is None:
            self.strip_interface(int(spec[0]))
        return None

    def parse_spec(self, s: str) -> tc.Spectrum:
        values = s.split(':')
        try:
            return tc.Spectrum(values[0], values[1], values[2])
        except (IndexError, ValueError):
            return None
