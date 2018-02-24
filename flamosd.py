#!/usr/bin/env python3

# Written by Thomas York

# Imports

import os
import time
import zmq
import logging
from queue import Queue
from threading import Thread
from logging.handlers import RotatingFileHandler
from flashforge import FlashForge, FlashForgeError
from nut2 import PyNUTClient
import flamosdconfig
import requests
from requests.auth import HTTPBasicAuth
import socket

# Thread definitions
## Stream Queue Exporter
class StreamQueueExporter(Thread):
    _instance = None

    def __init__(self):
        Thread.__init__(self)
        self.context = zmq.Context()

    def run(self):
        logger.info('[StreamQueueExporter] started')
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind('tcp://127.0.0.1:5556')
        while True:
            message = StreamQueue.get()
            logger.debug('[StreamQueueExporter] Processing queue item')
            self.socket.send_string(str(message))
            StreamQueue.task_done()


## Command Queue Importer
class CommandQueueImporter(Thread):
    _instance = None

    def __init__(self):
        Thread.__init__(self)
        self.context = zmq.Context()
        self.connectionstring = "tcp://*:%s" % "5557"

    def run(self):
        logger.info('[CommandQueueExporter] started')
        self.socket = self.context.socket(zmq.SUB)
        self.socket.bind(self.connectionstring)
        self.socket.setsockopt(zmq.SUBSCRIBE, b'')
        while True:
            command = self.socket.recv_string()
            logger.debug('[CommandQueueExporter] Processing incoming queue item')
            CommandQueue.put(command)


## Supervisor
class Supervisor(Thread):
    _instance = None

    def __init__(self):
        Thread.__init__(self)
        self.context = zmq.Context()
        self.connectionstring = "tcp://127.0.0.1:%s" % "5556"

    def run(self):
        logger.info('[Supervisor] started')
        self.socket = self.context.socket(zmq.SUB)
        self.socket.connect(self.connectionstring)
        self.socket.setsockopt(zmq.SUBSCRIBE, b'')
        while True:
            command = self.socket.recv_string()
            logger.debug('[Supervisor] Reading ZeroMQ data stream')
            # Ignore errors
            if "ERROR" in command:
                logger.debug('[Supervisor] Ignored error command')
                pass

            # Executed data only
            if "< CMD" in command:
                # CO Status
                if "FLAMOSCOSTATUS" in command:
                    # Bad statuses
                        if "WARNING" in command or "EMERGENCY" in command:
                            # CO ALARM!
                            logger.warning('[Supervisor] CO Alarm triggered! Issuing shutdown!')
                            CommandQueue.put('FLAMOSEMERGENCYPOWEROFF')
                        else:
                            logger.debug('[Supervisor] CO status good')
                elif "FLAMOSSMOKESTATUS" in command:
                    # Bad statuses
                        if "WARNING" in command or "EMERGENCY" in command:
                            # CO ALARM!
                            logger.warning('[Supervisor] Smoke Alarm triggered! Issuing shutdown!')
                            CommandQueue.put('FLAMOSEMERGENCYPOWEROFF')
                        else:
                            logger.debug('[Supervisor] Smoke status good')


## Periodic Command Scheduler
class PeriodicCommandScheduler(Thread):
    _instance = None

    def __init__(self):
        Thread.__init__(self)

    def run(self):
        logger.info('[PeriodicCommandScheduler500ms] started')
        global RemoteCommandLockout
        global CommandQueueLockout
        while True:
            if CommandQueueLockout is False and RemoteCommandLockout is False:
                logger.info('[PeriodicCommandScheduler500ms] Adding Dreamer status codes to queue')
                CommandQueue.put('M115')
                CommandQueue.put('M119')
                CommandQueue.put('M105')
                CommandQueue.put('M27')
            time.sleep(.5)


## Periodic Command Scheduler 5000ms
class PeriodicCommandScheduler5000ms(Thread):
    _instance = None

    def __init__(self):
        Thread.__init__(self)

    def run(self):
        logger.info('[PeriodicCommandScheduler5000ms] started')
        while True:
            if CommandQueueLockout is False:
                logger.info('[PeriodicCommandScheduler5000ms] Adding FLAMOS Ping code to queue')
                CommandQueue.put('FLAMOSPING')
                logger.info('[PeriodicCommandScheduler5000ms] Adding UPS status code to queue')
                CommandQueue.put('FLAMOSUPSSTATUS')
                logger.info('[PeriodicCommandScheduler5000ms] Adding Smoke status code to queue')
                CommandQueue.put('FLAMOSSMOKESTATUS')
                logger.info('[PeriodicCommandScheduler5000ms] Adding CO status code to queue')
                CommandQueue.put('FLAMOSCOSTATUS')
                logger.info('[PeriodicCommandScheduler5000ms] Adding Power status code to queue')
                CommandQueue.put('FLAMOSPOWERSTATUS')


            time.sleep(5)


## Remote Serial Injector
class RemoteSerialInjector(Thread):
    _instance = None

    def __init__(self):
        Thread.__init__(self)
        self.port = 9999
        self.TCPSocket = socket.socket()

    def readasciicommand(self, conn):
        # read data from TCP socket until new line signals end
        data = ''
        cmd_done = False
        while not cmd_done:
            newdata = None
            try:
                newdata = conn.recv(1024).decode()
            except:
                continue
            if newdata is None:
                next
            elif newdata.endswith('\n'):
                cmd_done = True
            data += newdata
        return data

    def readuploaddata(self, conn):
        # read data from TCP socket, exactly 4112 bytes
        MSGLEN = 4112
        chunks = []
        bytes_recd = 0
        while bytes_recd < MSGLEN:
            chunk = conn.recv(min(MSGLEN - bytes_recd, 2048))
            if chunk == b'':
                raise RuntimeError("socket connection broken")
            chunks.append(chunk)
            bytes_recd = bytes_recd + len(chunk)
        return b''.join(chunks)

    def run(self):
        logger.info('[RemoteSerialInjector] started')
        global ff
        while True:
            self.TCPSocket.bind(('', self.port))
            self.TCPSocket.listen(1)

            while True:
                global RemoteCommandLockout
                RemoteCommandLockout = False
                conn, addr = self.TCPSocket.accept()
                logger.info("[RemoteSerialInjector] Connection from: " + str(addr))
                print("RemoteSerialInjector] Connection from: " + str(addr))
                global jobinfo
                RemoteCommandLockout = True
                
                run_loop = True
                binary_mode = False

                while run_loop is True:
                    try:
                        if ff is None:
                            try:
                                ff = FlashForge()
                            except:
                                logger.error('[RemoteSerialInjector] Error connecting to FlashForge Dreamer via USB')
                                print("USB Error")
                                continue
                        if binary_mode is False:
                            command = self.readasciicommand(conn)
                            try:
                                if "M28 " in command.strip():
                                    binary_mode = True
                                    jobinfo['file'] = command.strip().split()[3].split('/')[-1]
                                    # We round down here using int because the file is padded to 4096 boundaries
                                    jobinfo['segments'] = int(float(command.strip().split()[2])/4096)
                                    jobinfo['status'] = 'Uploading ' + jobinfo['file'] + ': ' + jobinfo['percentage']
                            except:
                                continue
                            StreamQueue.put('> ' + command)
                            print('> ' + command)
                            data = ff.gcodecmd(command)
                            if not data.endswith('\n'):
                                data += '\n'
                            StreamQueue.put('< ' + data)
                            print('< ' + data)
                            conn.send(data.encode())
                        else:
                            command = self.readuploaddata(conn)
                            data = ff.asciicommand(command)
                            chunknumber_search = re.search('N(\d+).+ok.+', data)
                            if chunknumber_search:
                                jobinfo['percentage'] = str(int(int(chunknumber_search.group(1))/int(jobinfo['segments'])) * 100) + "%"
                                jobinfo['status'] = 'Uploading ' + jobinfo['file'] + ': ' + jobinfo['percentage']
                                if int(jobinfo['segments']) == int(chunknumber_search.group(1)):
                                    binary_mode = False
                                    jobinfo['status'] = 'Uploaded ' + jobinfo['file']
                            StreamQueue.put('< ' + data)
                            print('< ' + data)
                            conn.send(data.encode())
                    except:
                        conn.close()
                        RemoteCommandLockout = False
                        break


## Command Processor
class CommandProcessor(Thread):
    _instance = None

    def __init__(self, reconnect_timeout=5, vendorid=0x2b71, deviceid=0x0001):
        Thread.__init__(self)

    def run(self):
        logger.info('[CommandProcessor] started')
        global RemoteCommandLockout
        global ff
        ff = None
        self.postheaders = {
            'Content-Type': 'text/plain',
            'Accept': 'application/json',
        }
        self.getheaders = {
            'Content-Type': 'text/plain',
        }
        self.openhabianuser = flamosdconfig.openhab_username
        self.openhabianpass = flamosdconfig.openhab_password
        self.openhab_power_url = flamosdconfig.openhab_power_url
        self.openhab_smoke_url = flamosdconfig.openhab_smoke_url
        self.openhab_co_url = flamosdconfig.openhab_co_url


        if flamosdconfig.enable_nut == "yes":
            self.upsclient = PyNUTClient()
            logger.info('[CommandProcessor] NUT support enabled')
        if flamosdconfig.enable_openhab == "yes":
            logger.info('[CommandProcessor] OpenHAB support enabled')

        while True:
            command = CommandQueue.get()
            global CommandQueueLockout
            global logging
            if not command.endswith('\n'):
                command += '\n'
            StreamQueue.put('> ' + command)
            logger.info('[CommandProcessor] Executing command: {0}'.format(command))
            if "FLAMOS" not in command:
                if CommandQueueLockout is True:
                    StreamQueue.put('< CMD ' + command.rstrip() + ' ERROR\nCommandQueue lockout enabled\nok\n')
                    CommandQueue.task_done()
                elif RemoteCommandLockout is True:
                    StreamQueue.put('< CMD ' + command.rstrip() + ' ERROR\nRemote command lockout enabled\nok\n')
                    CommandQueue.task_done()
                else:
                    if ff is None:
                        try:
                            ff = FlashForge()
                        except:
                            logger.error('[CommandProcessor] Error connecting to FlashForge Dreamer via USB')
                            StreamQueue.put('< CMD ' + command.rstrip() + ' ERROR\nok\n')
                            CommandQueue.task_done()
                            continue
                    try:
                        data = ff.gcodecmd(command)
                        if not data.endswith('\n'):
                            data += '\n'
                        StreamQueue.put('< ' + data)
                        CommandQueue.task_done()
                    except FlashForgeError as error:
                        ff = None
                        logger.error(error.message)
                        StreamQueue.put('CommandProcessor ERROR: {0}'.format(error.message))
                        CommandQueue.task_done()
            else:
                if command == "FLAMOSPING\n":
                    data = "CMD FLAMOSPING Received.\n"
                    data += "CommandProcessor Pong\n"
                    data += "ok\n"
                    StreamQueue.put('<' + data)
                    CommandQueue.task_done()
                elif command == "FLAMOSUPSSTATUS\n":
                    if CommandQueueLockout is True:
                        StreamQueue.put('< CMD ' + command.rstrip() + ' ERROR\nCommandQueue lockout enabled\nok\n')
                        CommandQueue.task_done()
                        continue
                    try:
                        upsdata = self.upsclient.list_vars(flamosdconfig.nut_ups_name)
                        data = "CMD FLAMOSUPSSTATUS Received.\n"
                        data += "Charge: " + upsdata['battery.charge'] + "\n"
                        data += "Model: " + upsdata['device.model'] + "\n"
                        data += "InputVoltage: " + upsdata['input.voltage'] + "\n"
                        data += "Load: " + upsdata['ups.load'] + "%\n"
                        if upsdata['ups.status'] == "OL":
                            data += "Status: Utility\n"
                        elif upsdata['ups.status'] == "OB DISCHRG":
                            data += "Status: Battery\n"
                        else:
                            data += "Status: Unknown\n"
                        data += "ok\n"
                        StreamQueue.put('< ' + data)
                        CommandQueue.task_done()
                    except:
                        logger.error('[CommandProcessor] Error communicating with NUT')
                        StreamQueue.put('CommandProcessor UPS ERROR: Error communicating with NUT')
                        CommandQueue.task_done()
                elif command == "FLAMOSCOMMANDQUEUELOCKOUTENABLE\n":
                    data = "CMD FLAMOSCOMMANDQUEUELOCKOUTENABLE Received.\nCommandQueue lockout enabled\nok\n"
                    StreamQueue.put('< ' + data)
                    CommandQueueLockout = True
                    CommandQueue.task_done()
                elif command == "FLAMOSCOMMANDQUEUELOCKOUTDISABLE\n":
                    data = "CMD FLAMOSCOMMANDQUEUELOCKOUTENABLE Received.\nCommandQueue lockout disabled\nok\n"
                    StreamQueue.put('< ' + data)
                    CommandQueueLockout = False
                    CommandQueue.task_done()
                elif command == "FLAMOSCOMMANDQUEUELOCKOUTSTATUS\n":
                    data = "CMD FLAMOSCOMMANDQUEUELOCKOUTENABLE Received.\nCommandQueueLockout: " + str(CommandQueueLockout) + "\nok\n"
                    StreamQueue.put('< ' + data)
                    CommandQueue.task_done()
                elif command == "FLAMOSPOWERON\n":
                    r = requests.post(self.openhab_power_url, headers=self.postheaders, data='ON', auth=(self.openhabianuser, self.openhabianpass))
                    if r.status_code == requests.codes.ok:
                        data = "CMD FLAMOSPOWERON Received.\nDevice powered on\nok\n"
                    else:
                        data = "CMD FLAMOSPOWERON Received.\nRestAPI call failed\nok\n"
                    StreamQueue.put('< ' + data)
                    CommandQueue.task_done()
                elif command == "FLAMOSPOWERONPROPER\n":
                    r = requests.post(self.openhab_power_url, headers=self.postheaders, data='ON', auth=(self.openhabianuser, self.openhabianpass))
                    if r.status_code == requests.codes.ok:
                        data = "CMD FLAMOSPOWERONPROPER Received.\nDevice powered on\nok\n"
                    else:
                        data = "CMD FLAMOSPOWERONPROPER Received.\nRestAPI call failed\nok\n"
                    ff = None
                    time.sleep(30)
                    StreamQueue.put('< ' + data)
                    CommandQueueLockout = False
                    CommandQueue.task_done()
                elif command == "FLAMOSPOWEROFF\n":
                    r = requests.post(self.openhab_power_url, headers=self.postheaders, data='OFF', auth=(self.openhabianuser, self.openhabianpass))
                    if r.status_code == requests.codes.ok:
                        data = "CMD FLAMOSPOWEROFF Received.\nDevice powered off\nok\n"
                    else:
                        data = "CMD FLAMOSPOWEROFF Received.\nRestAPI call failed\nok\n"
                    StreamQueue.put('< ' + data)
                    CommandQueue.task_done()
                elif command == "FLAMOSPOWEROFFPROPER\n":
                    CommandQueueLockout = True
                    ff = None
                    r = requests.post(self.openhab_power_url, headers=self.postheaders, data='OFF', auth=(self.openhabianuser, self.openhabianpass))
                    if r.status_code == requests.codes.ok:
                        data = "CMD FLAMOSPOWEROFFPROPER Received.\nDevice powered off\nok\n"
                    else:
                        data = "CMD FLAMOSPOWEROFFPROPER Received.\nRestAPI call failed\nok\n"
                    time.sleep(15)
                    CommandQueueLockout = False
                    StreamQueue.put('< ' + data)
                    CommandQueue.task_done()
                elif command == "FLAMOSPOWERSTATUS\n":
                    r = requests.get(self.openhab_power_url + "/state", headers=self.getheaders, auth=(self.openhabianuser, self.openhabianpass))
                    if r.status_code == requests.codes.ok:
                        data = "CMD FLAMOSPOWERSTATUS Received.\nPowerStatus: " + r.text + "\nok\n"
                    else:
                        data = "CMD FLAMOSPOWERSTATUS Received.\nRestAPI call failed\nok\n"
                    StreamQueue.put('< ' + data)
                    CommandQueue.task_done()
                elif command == "FLAMOSSMOKESTATUS\n":
                    r = requests.get(self.openhab_smoke_url + "/state", headers=self.getheaders, auth=(self.openhabianuser, self.openhabianpass))
                    if r.status_code == requests.codes.ok:
                        data = "CMD FLAMOSSMOKESTATUS Received.\nSmokeStatus: " + r.text + "\nok\n"
                    else:
                        data = "CMD FLAMOSSMOKESTATUS Received.\nRestAPI call failed\nok\n"
                    StreamQueue.put('< ' + data)
                    CommandQueue.task_done()
                elif command == "FLAMOSCOSTATUS\n":
                    r = requests.get(self.openhab_co_url + "/state", headers=self.getheaders, auth=(self.openhabianuser, self.openhabianpass))
                    if r.status_code == requests.codes.ok:
                        data = "CMD FLAMOSCOSTATUS Received.\nCOStatus: " + r.text + "\nok\n"
                    else:
                        data = "CMD FLAMOSCOSTATUS Received.\nRestAPI call failed\nok\n"
                    StreamQueue.put('< ' + data)
                    CommandQueue.task_done()
                elif command == "FLAMOSFIREDRILL\n":
                    r = requests.get(self.openhab_smoke_url + "/state", headers=self.getheaders, auth=(self.openhabianuser, self.openhabianpass))
                    smokedata = None
                    if r.status_code == requests.codes.ok:
                        smokedata = r.text
                    else:
                        smokedata = "Error"

                    r = requests.get(self.openhab_co_url + "/state", headers=self.getheaders, auth=(self.openhabianuser, self.openhabianpass))
                    codata = None
                    if r.status_code == requests.codes.ok:
                        codata = r.text
                    else:
                        codata = "Error"

                    CommandQueueLockout = True
                    time.sleep(5)

                    r = requests.post(self.openhab_power_url, headers=self.postheaders, data='OFF', auth=(self.openhabianuser, self.openhabianpass))
                    poweroff = None
                    if r.status_code == requests.codes.ok:
                        poweroff = str(True)
                    else:
                        poweroff = str(False)

                    data = "CMD FLAMOSFIREDRILL Received.\n"
                    data += "SmokeStatus: " + smokedata + "\n"
                    data += "COStatus: " + codata + "\n"
                    data += "CommandQueue lockout enabled\n"
                    data += "PowerStatus: " + poweroff + "\n"
                    data += "ok\n"
                    StreamQueue.put('< ' + data)
                    CommandQueue.task_done()
                elif command == "FLAMOSEMERGENCYPOWEROFF\n":
                    CommandQueueLockout = True

                    r = requests.post(self.openhab_power_url, headers=self.postheaders, data='OFF', auth=(self.openhabianuser, self.openhabianpass))
                    poweroff = None
                    if r.status_code == requests.codes.ok:
                        poweroff = str(True)
                    else:
                        poweroff = str(False)

                    r = requests.get(self.openhab_smoke_url + "/state", headers=self.getheaders, auth=(self.openhabianuser, self.openhabianpass))
                    smokedata = None
                    if r.status_code == requests.codes.ok:
                        smokedata = r.text
                    else:
                        smokedata = "Error"

                    r = requests.get(self.openhab_co_url + "/state", headers=self.getheaders, auth=(self.openhabianuser, self.openhabianpass))
                    codata = None
                    if r.status_code == requests.codes.ok:
                        codata = r.text
                    else:
                        codata = "Error"

                    data = "CMD FLAMOSEMERGENCYPOWEROFF Received.\n"
                    data += "CommandQueue lockout enabled\n"
                    data += "PowerStatus: " + poweroff + "\n"
                    data += "SmokeStatus: " + smokedata + "\n"
                    data += "COStatus: " + codata + "\n"
                    data += "ok\n"
                    StreamQueue.put('< ' + data)
                    CommandQueue.task_done()
                else:
                    logger.info('[CommandProcessor] Invalid command: ' + command)



# Main Thread Code
def main():
    # Starting logger
    global logger
    handler = RotatingFileHandler('flamosd.log', maxBytes=10000, backupCount=1)
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger('flamosd')
    logger.addHandler(handler)

    # Starting global command queue priority override
    global CommandQueueLockout
    CommandQueueLockout = False

    # Starting remote command priority override
    global RemoteCommandLockout
    RemoteCommandLockout = False

    # Starting Queues
    global CommandQueue
    CommandQueue = Queue()
    global StreamQueue
    StreamQueue = Queue()

    # FlashForge object
    global ff
    ff = None

    # Job information and sane defaults
    global jobinfo
    jobinfo = {}
    jobinfo['status'] = 'No job'
    jobinfo['percentage'] = '0%'
    jobinfo['segments'] = 0
    jobinfo['file'] = 'None'
    jobinfo['sleep'] = False
    jobinfo['link'] = 'javascript:void(0);'

    # Start child threads

    ## Logging/Printer broadcast messages
    StreamQueueExporter._instance = StreamQueueExporter()
    StreamQueueExporter._instance.start()

    ## Command Queue
    CommandQueueImporter._instance = CommandQueueImporter()
    CommandQueueImporter._instance.start()

    ## Supervisor Thread
    Supervisor._instance = Supervisor()
    Supervisor._instance.start()

    ## Period Command Scheduler
    PeriodicCommandScheduler._instance = PeriodicCommandScheduler()
    PeriodicCommandScheduler._instance.start()

    ## Period Command Scheduler5000ms
    PeriodicCommandScheduler5000ms._instance = PeriodicCommandScheduler5000ms()
    PeriodicCommandScheduler5000ms._instance.start()

    ## Command Processor
    CommandProcessor._instance = CommandProcessor()
    CommandProcessor._instance.start()

    ## Remote Serial Injector
    RemoteSerialInjector._instance = RemoteSerialInjector()
    RemoteSerialInjector._instance.start()

    while True:
        logger.debug('[Main] Checking thread health...')
        if StreamQueueExporter._instance is None:
            StreamQueueExporter._instance = StreamQueueExporter()
            StreamQueueExporter._instance.start()
            logger.warning('[Main] StreamQueueExporter was found dead and restarted')

        if CommandQueueImporter._instance is None:
            CommandQueueImporter._instance = CommandQueueImporter()
            CommandQueueImporter._instance.start()
            logger.warning('[Main] CommandQueueImporter was found dead and restarted')

        if Supervisor._instance is None:
            Supervisor._instance = Supervisor()
            Supervisor._instance.start()
            logger.warning('[Main] Supervisor was found dead and restarted')

        if PeriodicCommandScheduler._instance is None:
            PeriodicCommandScheduler._instance = PeriodicCommandScheduler()
            PeriodicCommandScheduler._instance.start()
            logger.warning('[Main] PeriodicCommandScheduler was found dead and restarted')

        if PeriodicCommandScheduler5000ms._instance is None:
            PeriodicCommandScheduler5000ms._instance = PeriodicCommandScheduler5000ms()
            PeriodicCommandScheduler5000ms._instance.start()
            logger.warning('[Main] PeriodicCommandScheduler5000ms was found dead and restarted')

        if CommandProcessor._instance is None:
            CommandProcessor._instance = CommandProcessor()
            CommandProcessor._instance.start()
            logger.warning('[Main] CommandProcessor was found dead and restarted')

        time.sleep(15)


# Main thread
if __name__ == '__main__':
    main()
