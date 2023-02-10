#!/usr/bin/python

import threading
from apa102_tcp_server.apa_led import LedStrip
import apa102_tcp_server.tcp_server as Tcp
import apa102_tcp_server.udp_server as Udp
from apa102_tcp_server.log import Log
import apa102_tcp_server.inet_utils as tc
import json
from apa102_tcp_server.config_laoder import ConfigLoader
from os import path


# General controlling unit, handles and delegates all basic program work-flow
class Controller:

    def __init__(self, config_name):
        cl = ConfigLoader(path.join('./data', config_name))

        self.new_command_received = threading.Condition()

        # setup and initialize LED Strip
        self.led_strip = LedStrip(cl)

        self.tcp_server = Tcp.TcpServer(cl, self.new_command_received)
        self.udp_server = Udp.UdpServer(cl, server_mode=tc.ServerOperationMode.BC,
                                        stream_data_function=self.led_strip.set_intensity)

        self.command_thread = threading.Thread(target=self.command_worker)
        self.cmd_switch = CmdSwitch(self)
        self.state: tc.ServerState = tc.ServerState.CLOSED

    def start(self):
        self.print_log('Invoke controler start')
        self.tcp_server.start(self)
        # Start the internet server threads
        self.command_thread.start()
        self.udp_server.start()

    def stop(self):
        # Invoke tcp server stop
        self.print_log('Invoke controler stop')
        # Insert dummy termination command to worker queue
        self.tcp_server.stop()
        self.tcp_server.terminate_queue()
        self.command_thread.join()
        self.udp_server.stop()
        self.state = tc.ServerState.CLOSED

    def print_server_state(self):
        self.print_log('SERVER STATE: ', self.state)

    def command_worker(self):
        while 1:
            c = self.tcp_server.get_next_command()
            if c:
                # Termination command, enqueued artificially by server-stop routine
                if c.command == -1 and c.value == -1:
                    self.print_log('Terminate CMD-Worker Thread')
                    return
                found = False
                for client in self.tcp_server.connected_clients:
                    if client.client_id == c.connection.client_id:
                        found = True
                        break
                if not found:
                    self.print_log('Command from unregistered client. Skip command...')
                    continue
                # Execute cmd here
                cmd_type, ret = self.cmd_switch.switch(c)
                if ret is not None and not ret == "":
                    self.tcp_server.send_answer(c.connection, json.dumps({'type': cmd_type, 'message': ret}))
                elif ret is not None and ret == "":
                    self.tcp_server.send_answer(c.connection, 'Unresolved command nr')
                else:
                    self.print_log("Closed connection....")
            else:
                return

    @staticmethod
    def print_log(*args, **kwargs):
        Log.log('[CONTROLLER] ', *args, **kwargs)


class CmdSwitch:
    def __init__(self, controller: Controller) -> None:
        self.controller = controller
        self.command: Tcp.Command = None

    def switch(self, command):
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

    def _START(self, value: int):
        if not self.controller.led_strip.start():
            self.print_log("ERROR occured during LED stripe initialization!")
            return json.dumps({'error': 'LED setup failed!'})
        # Return UDP Port
        self.controller.udp_server.change_mode(tc.ServerOperationMode.NORMAL)
        s = self.controller.led_strip.get_status()
        return json.dumps({'port': self.controller.udp_server.PORT, 'state': s[0], 'brightness': s[1], 'color': s[2]})

    def _STOP(self, value: int):
        self.controller.udp_server.change_mode(tc.ServerOperationMode.OFF)
        self.controller.led_strip.stop()
        return "Strip operation stopped"

    def _SET_COLOR(self, value: int):
        self.controller.led_strip.set_color(value)
        return "color set to " + str(value)

    def _SET_BRIGHTNESS(self, value: int):
        self.controller.led_strip.set_brightness(value)
        return "brightness set to " + str(value)

    def _SEND_STATUS(self, value: int):
        status = self.controller.led_strip.get_strip_info_json()
        return json.dumps({'color': status[0]})

    def _OPERATION_MODE(self, value: int):
        try:
            mode = tc.ServerOperationMode(value)
        except ValueError:
            return 'Invalid operation mode ' + str(value)
        self.controller.udp_server.change_mode(mode)
        self.controller.led_strip.change_mode(mode)
        return 'Operation mode set to ' + mode.name

    def _DISCONNECT(self, value: int):
        self.controller.tcp_server.close_client_connection(self.command.connection.client_id)
        return None

    def _INTENSITY(self, value: int):
        self.controller.led_strip.set_intensity(value)
        return "Intensity set to " + str(value)

    @staticmethod
    def print_log(*args, **kwargs):
        Log.log('[CONTROLLER] ', *args, **kwargs)


if __name__ == '__main__':
    # Start routine
    controller = Controller(config_name='config.yaml')
    controller.start()
    while 1:
        key = input('')
        if key == 'i':
            controller.led_strip.print_status()
        else:
            break
    controller.stop()
