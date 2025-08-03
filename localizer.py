#!/usr/bin/env python3
"""
UDP-based localizer for device-side satellite embedding processing.
Serves as adapter between UDP sockets and server library functions.
"""

import sys
import os
import json
import socket
import threading
import base64
from pathlib import Path

# Add server src to path for code reuse
sys.path.append(str(Path(__file__).parent / '../server/src'))

from server_core import SatelliteEmbeddingServer
from models import InitMapRequest, FetchGpsRequest, VisualizePathRequest

class DeviceLocalizer:
    def __init__(self):
        self.server = SatelliteEmbeddingServer()
        self.running = True
        
        # UDP ports for each endpoint
        self.ports = {
            'init_map': 8001,
            'fetch_gps': 8002, 
            'visualize_path': 8003
        }
        
        # Create UDP sockets
        self.sockets = {}
        for endpoint, port in self.ports.items():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('localhost', port))
            self.sockets[endpoint] = sock
            print(f"Localizer bound to port {port} for {endpoint}")

    def handle_init_map(self):
        """Handle init_map UDP requests."""
        sock = self.sockets['init_map']
        
        while self.running:
            try:
                data, addr = sock.recvfrom(4096)
                request = json.loads(data.decode())
                print(f"Received init_map request: {request}")
                
                # Process request
                result = self.server.init_map(
                    lat=request['lat'],
                    lng=request['lng'], 
                    meters=request['meters'],
                    mode=request['mode']
                )
                
                # Send response
                response = json.dumps(result).encode()
                sock.sendto(response, addr)
                print(f"Sent init_map response to {addr}")
                
            except Exception as e:
                print(f"Error in init_map handler: {e}")

    def handle_fetch_gps(self):
        """Handle fetch_gps UDP requests."""
        sock = self.sockets['fetch_gps']
        
        while self.running:
            try:
                data, addr = sock.recvfrom(8192)
                request = json.loads(data.decode())
                print(f"Received fetch_gps request for session: {request['session_id']}")
                
                # Read image file
                image_path = request['image_path']
                with open(image_path, 'rb') as f:
                    image_data = f.read()
                
                # Process request
                result = self.server.fetch_gps(
                    image_data=image_data,
                    session_id=request['session_id']
                )
                
                # Send response
                response = json.dumps(result, default=str).encode()
                sock.sendto(response, addr)
                print(f"Sent fetch_gps response to {addr}")
                
            except Exception as e:
                print(f"Error in fetch_gps handler: {e}")

    def handle_visualize_path(self):
        """Handle visualize_path UDP requests."""
        sock = self.sockets['visualize_path']
        
        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                request = json.loads(data.decode())
                print(f"Received visualize_path request for session: {request['session_id']}")
                
                # Process request
                result = self.server.visualize_path(session_id=request['session_id'])
                
                # Send response
                response = json.dumps(result, default=str).encode()
                sock.sendto(response, addr)
                print(f"Sent visualize_path response to {addr}")
                
            except Exception as e:
                print(f"Error in visualize_path handler: {e}")

    def start(self):
        """Start all UDP handlers in separate threads."""
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
    localizer = DeviceLocalizer()
    localizer.start()
