#!/usr/bin/env python3
"""
Drone Network Listener
======================
Handles drone discovery via UDP broadcast and session sharing.
Manages communication between drones in the same LAN.
"""

import asyncio
import json
import logging
import socket
import time
import yaml
from pathlib import Path
from typing import Dict, Any, Optional

# Add device src to path
import sys
device_src_path = str(Path(__file__).parent / 'src')
sys.path.insert(0, device_src_path)
sys.path.insert(0, str(Path(__file__).parent / 'src' / 'general'))

from device.init_map_wrapper import call_server_init_map

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Network configuration
BROADCAST_PORT = 19001
LISTEN_PORT = 19002
BROADCAST_INTERVAL = 5  # seconds
DISCOVERY_TIMEOUT = 30  # seconds


class DroneListener:
    """Manages drone discovery and session sharing."""
    
    def __init__(self, state_file: str = "state.yaml"):
        self.state_file = Path(state_file)
        self.running = False
        self.discovery_active = False
        self.broadcast_socket = None
        self.listen_socket = None
        self.discovery_future = None
        
        # Ensure state file exists
        self._ensure_state_file()
    
    def _ensure_state_file(self):
        """Create state file if it doesn't exist."""
        if not self.state_file.exists():
            default_state = {
                'session_id': '',
                'lat': None,
                'lng': None,
                'km': None,
                'status': 'idle',
                'last_updated': None
            }
            self._save_state(default_state)
    
    def _load_state(self) -> Dict[str, Any]:
        """Load state from YAML file."""
        try:
            with open(self.state_file, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Error loading state: {e}")
            return {}
    
    def _save_state(self, state: Dict[str, Any]):
        """Save state to YAML file."""
        try:
            from datetime import datetime
            state['last_updated'] = datetime.now().isoformat()
            with open(self.state_file, 'w') as f:
                yaml.dump(state, f, default_flow_style=False)
        except Exception as e:
            logger.error(f"Error saving state: {e}")
    
    def _update_state(self, **kwargs):
        """Update specific state fields."""
        state = self._load_state()
        state.update(kwargs)
        self._save_state(state)
    
    async def setup_sockets(self):
        """Setup UDP sockets for broadcasting and listening."""
        try:
            # Setup broadcast socket
            self.broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Setup listen socket
            self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.listen_socket.bind(('', LISTEN_PORT))
            self.listen_socket.setblocking(False)
            
            logger.info(f"UDP sockets setup - broadcast port: {BROADCAST_PORT}, listen port: {LISTEN_PORT}")
            
        except Exception as e:
            logger.error(f"Error setting up sockets: {e}")
            raise
    
    async def broadcast_discovery(self) -> Optional[Dict[str, Any]]:
        """Broadcast discovery request and wait for responses."""
        logger.info("Starting drone discovery broadcast...")
        
        self.discovery_active = True
        self._update_state(status='discovering')
        
        # Update server progress
        await self._update_server_progress("Looking for other drones...", 0, 30)
        
        discovery_message = {
            "type": "discovery_request",
            "timestamp": time.time()
        }
        
        message_data = json.dumps(discovery_message).encode()
        
        # Broadcast for 30 seconds
        start_time = time.time()
        while time.time() - start_time < DISCOVERY_TIMEOUT and self.discovery_active:
            try:
                # Send broadcast
                self.broadcast_socket.sendto(message_data, ('<broadcast>', BROADCAST_PORT))
                
                # Listen for responses with timeout
                try:
                    await asyncio.wait_for(self._check_for_responses(), timeout=1.0)
                    # If we got a response, break the loop
                    if not self.discovery_active:
                        break
                except asyncio.TimeoutError:
                    pass  # Continue broadcasting
                
                # Update progress
                elapsed = time.time() - start_time
                remaining = max(0, DISCOVERY_TIMEOUT - elapsed)
                progress = int((elapsed / DISCOVERY_TIMEOUT) * 100)
                await self._update_server_progress(
                    f"Looking for other drones... ({int(remaining)}s remaining)", 
                    progress, 
                    int(remaining)
                )
                
                await asyncio.sleep(BROADCAST_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error during broadcast: {e}")
        
        self.discovery_active = False
        
        if self._load_state().get('session_id'):
            logger.info("Discovery complete - session found")
            await self._update_server_progress("Session found from other drone", 100)
            return self._load_state()
        else:
            logger.info("Discovery complete - no other drones found")
            await self._update_server_progress("No other drones found", 100)
            return None
    
    async def _check_for_responses(self):
        """Check for incoming discovery responses."""
        loop = asyncio.get_event_loop()
        
        while self.discovery_active:
            try:
                data, addr = await loop.sock_recvfrom(self.listen_socket, 1024)
                message = json.loads(data.decode())
                
                if message.get('type') == 'discovery_response':
                    session_data = message.get('session_data', {})
                    session_id = session_data.get('session_id', '')
                    
                    if session_id:
                        logger.info(f"Received session from {addr}: {session_id}")
                        
                        # Store the received session data
                        self._update_state(
                            session_id=session_id,
                            lat=session_data.get('lat'),
                            lng=session_data.get('lng'),
                            km=session_data.get('km'),
                            status='received_session'
                        )
                        
                        # Request map data for this session
                        await self._request_map_data(session_id)
                        
                        self.discovery_active = False
                        return
                        
            except socket.error:
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error checking responses: {e}")
                await asyncio.sleep(0.1)
    
    async def _request_map_data(self, session_id: str):
        """Request map data from server using session ID."""
        try:
            logger.info(f"Requesting map data for session: {session_id}")
            await self._update_server_progress("Requesting cached map data...", 50)
            
            # Call init_map_wrapper with the session_id to get cached data
            result = call_server_init_map(
                lat=0, lng=0, meters=0,  # These will be ignored with session_id
                session_id=session_id
            )
            
            if result.get('success'):
                self._update_state(status='ready')
                await self._update_server_progress("Map data received from cache", 100)
                logger.info("Map data successfully retrieved from cache")
            else:
                self._update_state(status='error')
                await self._update_server_progress("Failed to retrieve cached map data", 0)
                logger.error(f"Failed to retrieve map data: {result.get('error')}")
                
        except Exception as e:
            logger.error(f"Error requesting map data: {e}")
            self._update_state(status='error')
            await self._update_server_progress(f"Error: {str(e)}", 0)
    
    async def listen_for_requests(self):
        """Listen for discovery requests from other drones."""
        logger.info("Starting listener for discovery requests...")
        
        loop = asyncio.get_event_loop()
        
        while self.running:
            try:
                data, addr = await loop.sock_recvfrom(self.listen_socket, 1024)
                message = json.loads(data.decode())
                
                if message.get('type') == 'discovery_request':
                    await self._handle_discovery_request(addr)
                    
            except socket.error:
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error in listen loop: {e}")
                await asyncio.sleep(1)
    
    async def _handle_discovery_request(self, requester_addr):
        """Handle incoming discovery request."""
        state = self._load_state()
        session_id = state.get('session_id', '')
        
        # Only respond if we have a valid session
        if session_id:
            logger.info(f"Responding to discovery request from {requester_addr} with session: {session_id}")
            
            response = {
                "type": "discovery_response",
                "session_data": {
                    "session_id": session_id,
                    "lat": state.get('lat'),
                    "lng": state.get('lng'),
                    "km": state.get('km')
                },
                "timestamp": time.time()
            }
            
            response_data = json.dumps(response).encode()
            
            # Send response to the broadcast port of the requester
            try:
                response_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                response_socket.sendto(response_data, (requester_addr[0], BROADCAST_PORT))
                response_socket.close()
                logger.info(f"Sent session data to {requester_addr}")
            except Exception as e:
                logger.error(f"Error sending response to {requester_addr}: {e}")
        else:
            logger.debug(f"No session to share with {requester_addr}")
    
    async def _update_server_progress(self, message: str, progress: int, timer: Optional[int] = None):
        """Update server progress via HTTP request."""
        try:
            import aiohttp
            progress_data = {
                "status": "running",
                "progress": progress,
                "message": message
            }
            if timer is not None:
                progress_data["timer"] = timer
            
            # This would normally update the server, but for simplicity 
            # we'll just log it since the server manages its own progress
            logger.info(f"Progress: {message} ({progress}%)")
            
        except Exception as e:
            logger.debug(f"Could not update server progress: {e}")
    
    async def start_discovery(self) -> Optional[Dict[str, Any]]:
        """Start the discovery process."""
        try:
            await self.setup_sockets()
            return await self.broadcast_discovery()
        finally:
            await self.cleanup()
    
    async def start_listener(self):
        """Start listening for other drones (long-running)."""
        try:
            await self.setup_sockets()
            self.running = True
            await self.listen_for_requests()
        finally:
            await self.cleanup()
    
    def stop_discovery(self):
        """Stop the discovery process."""
        self.discovery_active = False
        logger.info("Discovery stopped by user")
    
    async def cleanup(self):
        """Clean up sockets and resources."""
        self.running = False
        self.discovery_active = False
        
        if self.broadcast_socket:
            self.broadcast_socket.close()
            self.broadcast_socket = None
        
        if self.listen_socket:
            self.listen_socket.close()
            self.listen_socket = None
        
        logger.info("Listener cleanup complete")


async def main():
    """Main function for standalone testing."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Drone Network Listener')
    parser.add_argument('--discover', action='store_true', 
                       help='Run discovery mode (search for other drones)')
    parser.add_argument('--listen', action='store_true', 
                       help='Run listener mode (respond to other drones)')
    
    args = parser.parse_args()
    
    listener = DroneListener()
    
    if args.discover:
        logger.info("Starting discovery mode...")
        result = await listener.start_discovery()
        if result:
            logger.info(f"Discovery successful: {result}")
        else:
            logger.info("No other drones found")
    
    elif args.listen:
        logger.info("Starting listener mode...")
        await listener.start_listener()
    
    else:
        logger.info("No mode specified. Use --discover or --listen")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Listener stopped by user")
    except Exception as e:
        logger.error(f"Error in listener: {e}")
