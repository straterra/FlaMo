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
from app.config import Config

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


## Periodic Command Scheduler
class PeriodicCommandScheduler(Thread):
    _instance = None

    def __init__(self):
        Thread.__init__(self)

    def run(self):
        logger.info('[PeriodicCommandScheduler500ms] started')
        while True:
            logger.info('[PeriodicCommandScheduler500ms] Adding Dreamer status codes to queue')
            CommandQueue.put('M115')
            CommandQueue.put('M119')
            CommandQueue.put('M105')
            CommandQueue.put('M27')
            # CommandQueue.put('FLAMOSPING')
            time.sleep(.5)


## Periodic Command Scheduler 5000ms
class PeriodicCommandScheduler5000ms(Thread):
    _instance = None

    def __init__(self):
        Thread.__init__(self)

    def run(self):
        logger.info('[PeriodicCommandScheduler5000ms] started')
        while True:
            logger.info('[PeriodicCommandScheduler5000ms] Adding UPS status code to queue')
            CommandQueue.put('FLAMOSUPSSTATUS')
            logger.info('[PeriodicCommandScheduler5000ms] Adding FLAMOS Ping code to queue')
            CommandQueue.put('FLAMOSPING')
            time.sleep(5)


## Command Processor
class CommandProcessor(Thread):
    _instance = None

    def __init__(self, reconnect_timeout=5, vendorid=0x2b71, deviceid=0x0001):
        Thread.__init__(self)

    def run(self):
        logger.info('[CommandProcessor] started')
        self.ff = FlashForge()
        if Config('enable_nut') == "yes":
            self.upsclient = PyNUTClient()
            logger.info('[CommandProcessor] NUT support enabled')
        if Config('enable_openhab') == "yes":
            logger.info('[CommandProcessor] OpenHAB support enabled')

        while True:
            command = CommandQueue.get()
            if not command.endswith('\n'):
                command += '\n'
            StreamQueue.put('> ' + command)
            logger.info('[CommandProcessor] Executing command: {0}'.format(command))
            if "FLAMOS" not in command:
                try:
                    data = self.ff.gcodecmd(command)
                    # data = 'CMD OK ' + command
                    if not data.endswith('\n'):
                        data += '\n'
                    StreamQueue.put('< ' + data)
                    CommandQueue.task_done()
                except Error as error:
                    logger.error(error.message)
                    StreamQueue.put('CommandProcessor ERROR: {0}'.format(error.message))
                    CommandQueue.task_done()

            else:
                if command == "FLAMOSPING\n":
                    StreamQueue.put("< PONG\n")
                elif command == "FLAMOSUPSSTATUS":
                    try:
                        upsdata = self.upsclient.list_vars("850va")
                        data = "CMD FLAMOSUPSSTATUS Received.\n"
                        data += "Charge: " + upsdata['battery.charge'] + "\n"
                        data += "Model: " + upsdata['device.model'] + "\n"
                        data += "InputVoltage: " + upsdata['input.voltage'] + "\n"
                        data += "Load: " + upsdata['ups.load'] + "\n"
                        if upsdata['ups.status'] == "OL":
                            data += "Status: Utility\n"
                        elif upsdata['ups.status'] == "OB DISCHRG":
                            data += "Status: Battery\n"
                        else:
                            data += "Status: Unknown\n"
                        data += "ok\n"
                        StreamQueue.put('< ' + data)
                        CommandQueue.task_done()
                    except Error as error:
                        logger.error(error.message)
                        StreamQueue.put('CommandProcessor UPS ERROR: {0}'.format(error.message))
                        CommandQueue.task_done()


# Main Thread Code
def main():
    # Starting logger
    global logger
    handler = RotatingFileHandler('flamosd.log', maxBytes=10000, backupCount=1)
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger('flamosd')
    logger.addHandler(handler)

    # Starting Queues
    global CommandQueue
    CommandQueue = Queue()
    global StreamQueue
    StreamQueue = Queue()

    # Start child threads

    ## Logging/Printer broadcast messages
    StreamQueueExporter._instance = StreamQueueExporter()
    StreamQueueExporter._instance.start()

    ## Command Queue
    CommandQueueImporter._instance = CommandQueueImporter()
    CommandQueueImporter._instance.start()

    ## Period Command Scheduler
    PeriodicCommandScheduler._instance = PeriodicCommandScheduler()
    PeriodicCommandScheduler._instance.start()

    ## Period Command Scheduler5000ms
    PeriodicCommandScheduler5000ms._instance = PeriodicCommandScheduler5000ms()
    PeriodicCommandScheduler5000ms._instance.start()

    ## Command Processor
    CommandProcessor._instance = CommandProcessor()
    CommandProcessor._instance.start()

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
