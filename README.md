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

1. Run the daemon process first (flamosd.py)
2. Run the Flask process second (flamos.py)
3. Configure your favorite webserver to proxy requests (default listening on 0.0.0.0/5002)
4. Use db/add-user.py script to add an admin user for r/w control


# Development

Coming soon
