#!/usr/bin/python
from __future__ import annotations

import json
import logging
import threading
from argparse import Namespace
from os import PathLike
from typing import Callable

import apa102_tcp_server.inet_utils as tc
import apa102_tcp_server.tcp_server as Tcp
import apa102_tcp_server.udp_server as Udp
from apa102_tcp_server.apa_led import LedStrip
from apa102_tcp_server.config_loader import ConfigLoader


# General controlling unit, handles and delegates all basic program work-flow
class Controller:

    def __init__(self, config_path: str | PathLike) -> None:
        cl = ConfigLoader(config_path)

        self.new_command_received = threading.Condition()

        # setup and initialize LED Strip
        self.led_strip = LedStrip(cl)

        self.tcp_server = Tcp.TcpServer(cl, self.new_command_received)
        self.udp_server = Udp.UdpServer(cl, server_mode=tc.ServerOperationMode.BC,
                                        stream_data_function=self.led_strip.set_intensity)

        self.command_thread = threading.Thread(target=self.command_worker)
        self.cmd_switch = CmdSwitch(self, self.log)
        self.state: tc.ServerState = tc.ServerState.CLOSED

        self.log = logging.getLogger('CONTROLLER')

    def start(self) -> bool:
        self.log.info('Invoke startup')
        self.tcp_server.start(self)
        # Start the internet server threads
        self.command_thread.start()
        return self.udp_server.start()

    def stop(self) -> None:
        # Invoke tcp server stop
        self.log.info('Invoke stop')
        # Insert dummy termination command to worker queue
        self.tcp_server.stop()
        self.tcp_server.invoke_queue_termination()
        self.command_thread.join()
        self.udp_server.stop()
        self.state = tc.ServerState.CLOSED

    def log_controller_state(self) -> None:
        self.log.debug(f'Server state: {str(self)}')
        self.log.debug(f'Strip: {str(self.led_strip)}')

    def command_worker(self) -> bool:
        while 1:
            c = self.tcp_server.get_next_command()
            if c:
                # Termination command, enqueued artificially by server-stop routine
                if c.command == -1 and c.value == -1:
                    self.log.info('Terminate command-worker thread')
                    return True
                found = False
                for client in self.tcp_server.connected_clients:
                    if client.client_id == c.connection.client_id:
                        found = True
                        break
                if not found:
                    self.log.warning(f'Skip command from unregistered client {client.ip}')
                    continue
                # Execute cmd here
                cmd_type, ret = self.cmd_switch.switch(c)
                if ret is not None and not ret == "":
                    self.tcp_server.send_answer(c.connection, json.dumps({'type': cmd_type, 'message': ret}))
                elif ret is not None and ret == "":
                    self.log.error(f'Could not resolve cmd {c.command} from {client.ip}')
                    self.tcp_server.send_answer(c.connection, 'Unresolved command nr')
                else:
                    self.log.info(f"Closed connection at {client.ip}")
            else:
                return False

    def __str__(self) -> str:
        return f"Mode: {self.state}"


class CmdSwitch:
    def __init__(self, controller: Controller, logger) -> None:
        self.controller = controller
        self.command: Tcp.Command = None

        self.log = logger

    def switch(self, command) -> str | tuple[tc.TcpCommandType, Callable[[CmdSwitch, int], str]]:
        self.command = command
        # Resolve the corresponsing function according to the sent cmmand value (refer to enum TcpCommandType)
        default = "Could not resolve command number " + str(command.command)
        try:
            t = tc.TcpCommandType(command.command).name
            return (t, getattr(self, "_" + t, lambda i: default)(command.value))
        except ValueError:
            return ""

    @property
    def _0(self):
        return

    ### Handler functions for the incomming commands
    ### delegate to the corresponding operation unit

    def _START(self, value: int) -> str:
        if not self.controller.led_strip.start():
            self.log.error("ERROR occured during LED stripe initialization!")
            return json.dumps({'error': 'LED setup failed!'})
        # Return UDP Port
        self.controller.udp_server.change_mode(tc.ServerOperationMode.NORMAL)
        s = self.controller.led_strip.get_status()
        return json.dumps({'port': self.controller.udp_server.PORT, 'state': s[0], 'brightness': s[1], 'color': s[2]})

    def _STOP(self, value: int) -> str:
        self.controller.udp_server.change_mode(tc.ServerOperationMode.OFF)
        self.controller.led_strip.stop()
        return "Strip operation stopped"

    def _SET_COLOR(self, value: int) -> str:
        self.controller.led_strip.set_color(value)
        return "color set to " + str(value)

    def _SET_BRIGHTNESS(self, value: int) -> str:
        self.controller.led_strip.set_brightness(value)
        return "brightness set to " + str(value)

    def _SEND_STATUS(self, value: int) -> str:
        status = self.controller.led_strip.get_strip_info_json()
        return json.dumps({'color': status[0]})

    def _OPERATION_MODE(self, value: int) -> str:
        try:
            mode = tc.ServerOperationMode(value)
        except ValueError:
            return 'Invalid operation mode ' + str(value)
        self.controller.udp_server.change_mode(mode)
        self.controller.led_strip.change_mode(mode)
        return 'Operation mode set to ' + mode.name

    def _DISCONNECT(self, value: int) -> str:
        self.controller.tcp_server.close_client_connection(self.command.connection.client_id)
        return ""

    def _INTENSITY(self, value: int) -> str:
        self.controller.led_strip.set_intensity(value)
        return "Intensity set to " + str(value)


def main(args: Namespace) -> None:
    # Start routine
    controller = Controller(config_path=args.config)
    controller.start()
    while 1:
        key = input('')
        if key == 'i':
            controller.log_controller_state()
        else:
            break
    controller.stop()
