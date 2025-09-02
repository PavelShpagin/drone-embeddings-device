#!/usr/bin/env python3
"""Clean WebSocket client for real-time communication with AWS server."""

import asyncio
import json
import uuid
import websockets
from typing import Dict, Any, Optional, Callable
import logging

logger = logging.getLogger(__name__)

class CleanWebSocketClient:
    """Simplified WebSocket client with clean architecture."""
    
    def __init__(self, server_url: str, progress_callback: Optional[Callable] = None):
        """
        Initialize WebSocket client.
        
        Args:
            server_url: AWS WebSocket server URL
            progress_callback: Function to call with progress updates
        """
        self.server_url = server_url.replace("http://", "ws://").replace("https://", "wss://")
        self.connection_id = str(uuid.uuid4())
        self.websocket = None
        self.task_id = None
        self.progress_callback = progress_callback
        
    async def connect(self) -> bool:
        """Establish WebSocket connection to AWS server."""
        ws_url = f"{self.server_url}/ws/{self.connection_id}"
        logger.info(f"🔌 Connecting to WebSocket: {ws_url}")
        
        try:
            self.websocket = await websockets.connect(ws_url)
            logger.info(f"✅ WebSocket connected with ID: {self.connection_id}")
            return True
        except Exception as e:
            logger.error(f"❌ WebSocket connection failed: {e}")
            return False
    
    async def init_map(self, lat: float, lng: float, meters: int = 1000, 
                      session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute init_map with real-time progress updates.
        
        Args:
            lat: Latitude
            lng: Longitude
            meters: Coverage radius in meters
            session_id: Optional session ID for cached results
            
        Returns:
            Dict with success status and result data
        """
        if not self.websocket:
            return {"success": False, "error": "Not connected"}
        
        try:
            # Send init_map request
            request = {
                "type": "init_map",
                "lat": lat,
                "lng": lng,
                "meters": meters,
                "fetch_only": False
            }
            
            if session_id:
                request["session_id"] = session_id
            
            logger.info(f"📤 Sending init_map request: {request}")
            await self.websocket.send(json.dumps(request))
            
            # Listen for responses
            return await self._listen_for_completion()
            
        except Exception as e:
            logger.error(f"❌ Error in init_map: {e}")
            return {"success": False, "error": str(e)}
    
    async def _listen_for_completion(self) -> Dict[str, Any]:
        """Listen for progress updates and completion."""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    message_type = data.get("type")
                    logger.debug(f"📨 Received message type: {message_type}, status: {data.get('status')}")
                    
                    if message_type == "task_started":
                        self.task_id = data.get("task_id")
                        logger.info(f"✅ Task started: {self.task_id}")
                        continue
                        
                    elif message_type == "progress_update":
                        # Send progress update via callback (structured format)
                        if self.progress_callback:
                            progress_data = {
                                "status": data.get("status", "running"),
                                "progress": data.get("progress", 0),
                                "message": data.get("message", "Processing..."),
                                "phase": data.get("phase", "unknown"),
                                "tiles_completed": data.get("tiles_completed", 0),
                                "total_tiles": data.get("total_tiles", 0),
                                "embeddings_processed": data.get("embeddings_processed", 0),
                                "total_embeddings": data.get("total_embeddings", 0)
                            }
                            
                            # Call callback with structured data
                            if asyncio.iscoroutinefunction(self.progress_callback):
                                await self.progress_callback(progress_data)
                            else:
                                self.progress_callback(progress_data)
                    
                    # Check for completion status (can be in any message type)
                    status = data.get("status")
                    if status == "completed" or status == "complete":
                        logger.info(f"🎉 Task completed! Session: {data.get('session_id')}")
                        result = {
                            "success": True,
                            "session_id": data.get("session_id"),
                            "message": data.get("message", "Mission completed successfully")
                        }
                        
                        # Handle both zip_data (small files) and download_url (large files)
                        if data.get("zip_data"):
                            result["zip_data"] = data.get("zip_data")
                            logger.info("✅ Received zip_data directly")
                        elif data.get("download_url"):
                            result["download_url"] = data.get("download_url")
                            result["zip_size"] = data.get("zip_size")
                            logger.info(f"✅ Received download_url: {data.get('download_url')}")
                        
                        return result
                    elif status == "error":
                        logger.error(f"❌ Task failed: {data.get('message')}")
                        return {
                            "success": False,
                            "error": data.get("message", "Unknown error")
                        }
                    elif status and status != "running":
                        logger.warning(f"⚠️ Unexpected status: {status}")
                    
                    elif message_type == "connection_confirmed":
                        logger.info("✅ Connection confirmed")
                        continue
                    
                except json.JSONDecodeError:
                    logger.warning(f"⚠️ Invalid JSON received: {message}")
                    continue
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("🔌 WebSocket connection closed - checking for completion...")
            # Connection closed - this might be normal after completion
            # For now, return failure so device server handles this properly
            logger.error("❌ Connection closed - treating as failure for proper handling")
            return {"success": False, "error": "Connection closed during processing"}
        except Exception as e:
            logger.error(f"❌ Error listening for completion: {e}")
            return {"success": False, "error": str(e)}
    
    async def cancel_task(self) -> bool:
        """Cancel the current task."""
        if not self.websocket or not self.task_id:
            return False
        
        try:
            cancel_message = {
                "type": "cancel_task", 
                "task_id": self.task_id
            }
            await self.websocket.send(json.dumps(cancel_message))
            logger.info(f"🚫 Cancellation sent for task: {self.task_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to send cancellation: {e}")
            return False
    
    async def disconnect(self):
        """Close WebSocket connection."""
        if self.websocket:
            await self.websocket.close()
            logger.info("🔌 WebSocket disconnected")

# Global task management
_current_client: Optional[CleanWebSocketClient] = None

async def call_server_init_map_websocket(lat: float, lng: float, meters: int = 1000, 
                                       server_url: str = "ws://ec2-16-171-238-14.eu-north-1.compute.amazonaws.com:5000", 
                                       session_id: Optional[str] = None,
                                       progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """
    Execute init_map via WebSocket with clean architecture.
    
    Args:
        lat: Latitude
        lng: Longitude
        meters: Coverage radius in meters
        server_url: WebSocket server URL
        session_id: Optional session ID for cached results
        progress_callback: Function to call with structured progress updates
    
    Returns:
        Dict with success status and result data
    """
    global _current_client
    
    try:
        # Create and connect client
        _current_client = CleanWebSocketClient(server_url, progress_callback)
        
        if not await _current_client.connect():
            return {"success": False, "error": "Failed to connect to WebSocket"}
        
        # Verify client is properly initialized
        if _current_client is None:
            return {"success": False, "error": "Client initialization failed"}
        
        # Execute init_map with real-time progress
        result = await _current_client.init_map(lat, lng, meters, session_id)
        return result
        
    except Exception as e:
        logger.error(f"❌ WebSocket call failed: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        if _current_client:
            await _current_client.disconnect()
            _current_client = None

async def cancel_current_websocket_task() -> bool:
    """Cancel the currently running WebSocket task."""
    global _current_client
    if _current_client:
        return await _current_client.cancel_task()
    return False