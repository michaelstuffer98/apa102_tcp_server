import socket
import time
import threading
from apa102_tcp_server.inet_utils import TcpCommandType as CMD

cancelled: bool = False

def get_color_from_rgb(r, g, b)->int:
    return int(r) + (int(g) << 8) + (int(b) << 16)

def receiver(con: socket.socket):
    con.setblocking(0)
    while 1:
        try:
            if cancelled:
                return
            con.settimeout(0.1)
            bytes = con.recv(4096)
            if not bytes:
                print('not data')
                return
            a = bytes.decode('utf-8')
            if a == '':
                print('Connection is lost')
                return
            print('Answer: ', a, '\n')
        except socket.timeout as e:
            continue
        except Exception as e:
            print('Terminate receiver thread: ', e)
            return
    print('Exit receiver normally')


try:
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    print('Connect')

    client.connect(('192.168.0.170', 5005))

    rcvThread = threading.Thread(target=receiver, args=(client,))
    rcvThread.start()
    
    if client.fileno() == -1:
        print("fileno failed")
        exit(1)

    input('Press any key to start')
    cmd_nr = CMD.START.value
    cmd_val = 2
    msg = str(cmd_nr) + ':' + str(cmd_val)
    msg = (str(len(msg))).zfill(4) + msg
    print('Send ', msg)
    client.send(msg.encode('utf-8'))
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
    while 1:
        input('Press Enter to send Spectrum')
        MESSAGE = b"100:234:345"
        sock.sendto(MESSAGE, ('192.168.170', 9999))

    cmd_nr = CMD.SET_BRIGHTNESS.value
    cmd_val = 0
    msg = str(cmd_nr) + ':' + str(cmd_val)
    msg = (str(len(msg))).zfill(4) + msg
    print('Send ', msg)
    client.send(msg.encode('utf-8'))

    cmd_nr = CMD.SET_COLOR.value
    cmd_val = get_color_from_rgb(255, 255, 255)
    msg = str(cmd_nr) + ':' + str(cmd_val)
    msg = (str(len(msg))).zfill(4) + msg
    print('Send ', msg)
    client.send(msg.encode('utf-8'))
    
    input('Start...')

    cmd_nr = CMD.INTENSITY.value
    cmd_val = 100
    msg = str(cmd_nr) + ':' + str(cmd_val)
    msg = (str(len(msg))).zfill(4) + msg
    while 1:
        print('Send ', msg)
        client.send(msg.encode('utf-8'))
        time.sleep(0.3)
    input('')
    exit()
    input('White')

    cmd_val = get_color_from_rgb(255, 255, 255)
    msg = str(cmd_nr) + ':' + str(cmd_val)
    msg = (str(len(msg))).zfill(4) + msg
    print('Send ', msg)
    client.send(msg.encode('utf-8'))

    input('Red')

    cmd_val = get_color_from_rgb(255, 0, 0)
    msg = str(cmd_nr) + ':' + str(cmd_val)
    msg = (str(len(msg))).zfill(4) + msg
    print('Send ', msg)
    client.send(msg.encode('utf-8'))

    input('Green')

    cmd_val = get_color_from_rgb(0, 255, 0)
    msg = str(cmd_nr) + ':' + str(cmd_val)
    msg = (str(len(msg))).zfill(4) + msg
    print('Send ', msg)
    client.send(msg.encode('utf-8'))

    input('Blue')

    cmd_val = get_color_from_rgb(0, 0, 255)
    msg = str(cmd_nr) + ':' + str(cmd_val)
    msg = (str(len(msg))).zfill(4) + msg
    print('Send ', msg)
    client.send(msg.encode('utf-8'))

    input('Exit...')

    cancelled = True
    
    #print('Send valid')
    #client.send('000510:04'.encode('utf-8'))
    #time.sleep(1)
    #
    #print('Send invalid pattern')
    #client.send('000555:-1'.encode('utf-8'))
    #time.sleep(1)
    #
    #print('Send invalid pattern')
    #client.send('0005-7:98'.encode('utf-8'))
    #time.sleep(1)
    #
    #print('Send invalid command number')
    #client.send('000534:12'.encode('utf-8'))
    #time.sleep(1)
    #
    #print('Send termination command number')
    #client.send('00039:0'.encode('utf-8'))
    #time.sleep(1)

    rcvThread.join()

    print('Terminate execution properly')

except ConnectionResetError as e:
    print('Connection has been closed by Server')

