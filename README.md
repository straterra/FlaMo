# FlaMoS

Working features at the moment:
 - Access control with password
 - Display webcam stream
 - GCode Terminal
 - Set and monitor temperatures
 - Only Flashforge Dreamer printer supported by USB vendorid and deviceid
 - Move to scalable model using daemon + ZeroMQ
 - Seperate admin and read-only interfaces

Forked feature goals
 - Embedded HTML5 player for RMTP
 - Play real Dreamer audio files when corresponding event happens
 - Upload job file via HTTP
 - Move USBID to config files
 - Better deployment strategy (and instructions!)

# Installation

1. Configure your favorite webserver to proxy requests (default listening on 0.0.0.0/5002)
2. sudo adduser flamos
3. sudo passwd -l flamos
4. sudo apt-get install -y python3-venv
5. sudo su - flamos
6. git clone https://github.com/straterra/FlaMoS.git
7. pyvenv-3.5 venv
8. source venv/bin/activate
9. pip3 install -r FlaMoS/requirements.txt
10. cp FlaMoS/app/config.py.dist FlaMoS/app/config.py
11. vim FlaMoS/app/config.py
12. cd FlaMoS
13. mkdir db
14. python3 add-user.py
15. exit
16. sudo cp FlaMoS/systemd/*.service /lib/systemd/system/
17. sudo chmod 644 /lib/systemd/system/flamos*.service
18. sudo systemctl daemon-reload
19. sudo systemctl start flamos
20. sudo systemctl status flamos
21. sudo systemctl start flamos-http
22. sudo systemctl status flamos-http


# Development

Coming soon
