#!/usr/bin/env python3

# Written by Thomas York

# Imports

import zmq

context = zmq.Context()
socket = context.socket(zmq.SUB)

print("Testing ZeroMQ datafeed of terminal information...")
socket.connect('tcp://127.0.0.1:5556')
socket.setsockopt(zmq.SUBSCRIBE, b'')

while True:
    message = socket.recv_string()
    print(message)
