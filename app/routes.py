#!/usr/bin/env python3

# Written by Thomas York

# Imports
import eventlet

eventlet.monkey_patch()
from app import app
from app import hashing
from flask import Flask
from flask import Flask, flash, redirect, render_template, request, session, abort
from flask import copy_current_request_context
from sqlalchemy.orm import sessionmaker
from flask_hashing import Hashing
import os
import time
from queue import Queue
from threading import Thread
import flask
from flask import Flask, render_template, request
from app.tabledef import *
from time import sleep
import zmq
import git

# Setup ZMQ sockets
contextCommand = zmq.Context()
socketCommand = contextCommand.socket(zmq.PUB)
socketCommand.connect('tcp://127.0.0.1:5557')

# Detect version
repo = git.Repo(search_parent_directories=True)
sha = repo.head.object.hexsha
version = "FlaMoS " + str(next((tag for tag in repo.tags if tag.commit == repo.head.commit), "git"))  + "-" + str(repo.head.object.hexsha)
print(version)

# Thread for processing ZeroMQ messages
def StreamQueueImporter():
    print('Thread started')
    context = zmq.Context()

    socket = context.socket(zmq.SUB)
    socket.connect('tcp://127.0.0.1:5556')
    socket.setsockopt(zmq.SUBSCRIBE, b'')
    while True:
        try:
            stream = socket.recv_string(flags=zmq.NOBLOCK)
            socketio.emit('terminal', stream, broadcast=True)
        except zmq.Again as e:
            time.sleep(.1)
            pass
        eventlet.sleep(0)


# SocketIO
@socketio.on('gcodecmd')
def socketio_machine_state(cmd):
    if not cmd == "M105":
        if session.get('logged_in'):
            print('Command Received from SocketIO: {0}'.format(cmd))
            socketCommand.send_string(str(cmd))


# Routes
@app.route('/', methods=['GET'])
def flamos():
    return render_template('index.html', video_type=app.config['VIDEO_TYPE'], streamurl=app.config['VIDEO_URL'], version=version)


@app.route('/admin', methods=['GET'])
def admin():
    if not session.get('logged_in'):
        return redirect('/login')
    else:
        return render_template('admin.html', video_type=app.config['VIDEO_TYPE'], streamurl=app.config['VIDEO_URL'], version=version)


@app.route('/login', methods=["GET", "POST"])
def login():
    if request.method == "POST":

        POST_USERNAME = str(request.form['username'])
        POST_PASSWORD = str(request.form['password'])

        Session = sessionmaker(bind=engine)
        s = Session()
        query = s.query(User).filter(User.username.in_([POST_USERNAME]))
        result = query.first()
        passwd = result.password

        if hashing.check_value(passwd, POST_PASSWORD, salt=app.config['SECRET_KEY']):
            session['logged_in'] = True
            return redirect('/admin')
        else:
            flash('wrong password!')
            return redirect('/login')
    else:
        return render_template('login.html')


@app.route("/logout")
def logout():
    session['logged_in'] = False
    return redirect('/')


eventlet.spawn(StreamQueueImporter)
