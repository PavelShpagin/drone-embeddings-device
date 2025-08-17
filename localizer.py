#!/usr/bin/env python3
"""
TCP-based localizer for device-side satellite embedding processing.
Serves as adapter between TCP sockets and server library functions.
"""

import sys
import os
import json
import socket
import threading
import base64
import argparse
import uuid
from pathlib import Path

# Add device src to path for code reuse
device_src_path = str(Path(__file__).parent / 'src')
sys.path.insert(0, device_src_path)
sys.path.insert(0, str(Path(__file__).parent / 'src' / 'general'))

from general.fetch_gps import process_fetch_gps_request
from models import InitMapRequest, FetchGpsRequest, VisualizePathRequest, SessionData
from device.init_map_wrapper import call_server_init_map
import pickle
import time

class DeviceLocalizer:
    def __init__(self, server_url="http://ec2-16-171-238-14.eu-north-1.compute.amazonaws.com:5000"):
        self.server_url = server_url
        self.sessions = {}
        self.logger_id = str(uuid.uuid4())  # Generate logger_id for this localizer session
        self._load_sessions()
        self.running = True
        print(f"Device localizer starting with logger_id: {self.logger_id}")
        
        # Import embedder from server path (only needed for fetch_gps processing) 
        sys.path.append('/home/pavel/dev/drone-embeddings/server/src')
        sys.path.append('/home/pavel/dev/drone-embeddings/server/src/server')
        from embedder import TinyDINOEmbedder
        self.embedder = TinyDINOEmbedder()
        
        # TCP ports for each endpoint (high numbers to avoid conflicts)
        self.ports = {
            'init_map': 18001,
            'fetch_gps': 18002, 
            'visualize_path': 18003
        }
        
        # Create TCP sockets for reliable large data transfer
        self.sockets = {}
        for endpoint, port in self.ports.items():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('localhost', port))
            sock.listen(5)
            self.sockets[endpoint] = sock
            print(f"Localizer bound to TCP port {port} for {endpoint}")

    def _load_sessions(self):
        """Load sessions from local storage."""
        sessions_file = "data/sessions.pkl"
        if os.path.exists(sessions_file):
            try:
                with open(sessions_file, 'rb') as f:
                    self.sessions = pickle.load(f)
                print(f"Loaded {len(self.sessions)} sessions")
            except Exception as e:
                print(f"Error loading sessions: {e}")
                self.sessions = {}
        else:
            self.sessions = {}

    def handle_init_map(self):
        """Handle init_map TCP requests."""
        sock = self.sockets['init_map']
        
        while self.running:
            try:
                conn, addr = sock.accept()
                print(f"init_map connection from {addr}")
                
                # Receive request
                data = conn.recv(4096).decode(errors='ignore')
                request = json.loads(data)
                print(f"Received init_map request: {request}")
                
                # Call server via HTTP and store locally
                result = call_server_init_map(
                    lat=request['lat'],
                    lng=request['lng'], 
                    meters=request['meters'],
                    server_url=self.server_url
                )
                
                # Reload sessions after storing
                self._load_sessions()
                
                # Send MINIMAL response to the reader to avoid huge TCP payloads
                # Only session_id and success are needed by the reader
                minimal = {
                    'success': bool(result.get('success', False)),
                    'session_id': result.get('session_id')
                }
                response = json.dumps(minimal)
                conn.send(response.encode())
                conn.close()
                print(f"Sent init_map response to {addr}")
                
            except Exception as e:
                print(f"Error in init_map handler: {e}")

    def handle_fetch_gps(self):
        """Handle fetch_gps TCP requests."""
        sock = self.sockets['fetch_gps']
        
        while self.running:
            try:
                conn, addr = sock.accept()
                print(f"fetch_gps connection from {addr}")
                
                # Receive request size first
                size_data = conn.recv(4).decode()
                if not size_data:
                    conn.close()
                    continue
                    
                request_size = int(size_data)
                
                # Receive full request
                data = b''
                while len(data) < request_size:
                    chunk = conn.recv(min(request_size - len(data), 4096))
                    if not chunk:
                        break
                    data += chunk
                
                request = json.loads(data.decode())
                print(f"Received fetch_gps request for session: {request['session_id']}")
                
                # Read image file
                image_path = request['image_path']
                with open(image_path, 'rb') as f:
                    image_data = f.read()
                
                # Extract parameters
                session_id = request['session_id']
                logging_id = request.get('logging_id')
                visualization = request.get('visualization', False)
                
                # Process request using new file-based system with localizer's logger_id
                result = process_fetch_gps_request(
                    image_data,
                    session_id,
                    self.embedder,
                    logging_id=self.logger_id,  # Use localizer's logger_id
                    visualization=True  # Always enable visualization for enhanced logging
                )
                
                # Send response
                response = json.dumps(result, default=str)
                conn.send(response.encode())
                conn.close()
                print(f"Sent fetch_gps response to {addr}")
                
            except Exception as e:
                print(f"Error in fetch_gps handler: {e}")

    def handle_visualize_path(self):
        """Handle visualize_path TCP requests (unused in server mode)."""
        sock = self.sockets['visualize_path']
        
        while self.running:
            try:
                conn, addr = sock.accept()
                print(f"visualize_path connection from {addr} (not used in server mode)")
                
                # Just close the connection since we don't use visualize_path in server mode
                conn.close()
                
            except Exception as e:
                print(f"Error in visualize_path handler: {e}")

    def start(self):
        """Start all TCP handlers in separate threads."""
        handlers = [
            threading.Thread(target=self.handle_init_map, daemon=True),
            threading.Thread(target=self.handle_fetch_gps, daemon=True),
            threading.Thread(target=self.handle_visualize_path, daemon=True)
        ]
        
        for handler in handlers:
            handler.start()
        
        print("Device localizer started. Press Ctrl+C to stop.")
        
        try:
            while self.running:
                pass
        except KeyboardInterrupt:
            print("Stopping localizer...")
            self.running = False

    def stop(self):
        """Stop the localizer and close sockets."""
        self.running = False
        for sock in self.sockets.values():
            sock.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Device Localizer')
    parser.add_argument('--local', action='store_true', 
                       help='Use local server (localhost:5000) instead of remote AWS server')
    
    args = parser.parse_args()
    
    if args.local:
        server_url = "http://localhost:5000"
        print("Using local server: localhost:5000")
    else:
        server_url = "http://ec2-16-171-238-14.eu-north-1.compute.amazonaws.com:5000"
        print(f"Using remote server: {server_url}")
    
    localizer = DeviceLocalizer(server_url)
    localizer.start()