# start-server.sh - startup script for the server

hypercorn "app:create_app()" --bind 127.0.0.1:5000