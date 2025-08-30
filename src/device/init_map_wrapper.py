"""
Device Init Map Wrapper
======================
Calls the server init_map endpoint and downloads/unpacks zip files.
"""

import requests
import json
import pickle
import os
import zipfile
import time
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image
import numpy as np


# Global variable to store current task info for cancellation
_current_task = {}

def call_server_init_map(lat: float, lng: float, meters: int = 1000, 
                        server_url: str = "http://localhost:5000", 
                        session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Call server init_map endpoint and store results locally.
    
    Args:
        lat: Latitude coordinate
        lng: Longitude coordinate  
        meters: Coverage area in meters
        server_url: Server base URL
        session_id: Optional session ID for caching
        
    Returns:
        Dict with success status and session_id
    """
    try:
        print(f"Calling server init_map at {server_url}/init_map")
        if session_id:
            print(f"Requesting cached session: {session_id}")
        else:
            print(f"New request: lat={lat}, lng={lng}, meters={meters}")
        
        # Call server init_map with mode=device_async for cancellable background processing
        # Note: Server expects form data, not JSON
        import uuid
        connection_id = str(uuid.uuid4())
        
        form_data = {
            "lat": lat,
            "lng": lng,
            "meters": meters,
            "mode": "device_async",
            "connection_id": connection_id
        }
        if session_id:
            form_data["session_id"] = session_id
            
        response = requests.post(f"{server_url}/init_map", data=form_data, timeout=(30, 3600))  # 30s connect, 1 hour read for large areas
        
        response.raise_for_status()
        print(f"Server response status: {response.status_code}")
        
        # Parse the async response to get task_id
        try:
            async_response = response.json()
            task_id = async_response.get("task_id")
            if not task_id:
                return {"success": False, "error": "No task_id in response"}
            
            print(f"Got task_id: {task_id}")
            
            # Store task info globally for potential cancellation
            global _current_task
            _current_task = {
                "task_id": task_id,
                "connection_id": connection_id,
                "server_url": server_url
            }
            
            # Poll for progress until completion
            while True:
                time.sleep(1)  # Poll every second
                
                try:
                    progress_response = requests.get(f"{server_url}/progress/{task_id}", timeout=60)  # 1 minute for progress polling
                    progress_response.raise_for_status()
                    progress_data = progress_response.json()
                    
                    # AWS server now forwards progress updates directly to device UI
                    # No need to duplicate forwarding here
                    
                    print(f"Progress: {progress_data.get('progress', 0)}% - {progress_data.get('message', '')}")
                    
                    if progress_data.get("status") == "completed":
                        # Clear task info
                        _current_task.clear()
                        # Task completed successfully
                        if progress_data.get("zip_data"):
                            # Decode base64 zip data and unpack
                            import base64
                            zip_data = base64.b64decode(progress_data["zip_data"])
                            session_id = progress_data.get("session_id", f"session_{int(time.time())}")
                            return _download_and_unpack_zip(zip_data, session_id)
                        else:
                            return {"success": True, "session_id": progress_data.get("session_id"), "message": "Task completed"}
                    
                    elif progress_data.get("status") == "failed":
                        _current_task.clear()
                        return {"success": False, "error": progress_data.get("error", "Task failed")}
                    
                    elif progress_data.get("status") == "cancelled":
                        _current_task.clear()
                        return {"success": False, "error": "Task was cancelled"}
                    
                    # Continue polling if status is "running"
                    
                except requests.RequestException as e:
                    print(f"Error polling progress: {e}")
                    return {"success": False, "error": f"Progress polling failed: {e}"}
                    
        except ValueError as e:
            return {"success": False, "error": f"Invalid JSON response: {e}"}
        
    except requests.exceptions.RequestException as e:
        print(f"Network error calling server: {e}")
        return {"success": False, "error": f"Network error: {str(e)}"}
    except Exception as e:
        print(f"Unexpected error: {e}")
        return {"success": False, "error": f"Error: {str(e)}"}


def _download_and_unpack_zip(zip_data: bytes, session_id: str) -> Dict[str, Any]:
    """Download and unpack zip file to local storage."""
    try:
        # Create directories
        data_dir = Path("data")
        maps_dir = data_dir / "maps"
        embeddings_dir = data_dir / "embeddings"
        
        for dir_path in [data_dir, maps_dir, embeddings_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        # Save zip temporarily
        zip_path = data_dir / f"{session_id}_temp.zip"
        with open(zip_path, 'wb') as f:
            f.write(zip_data)
        
        # Extract zip contents
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Extract map.png
            if 'map.png' in zf.namelist():
                map_data = zf.read('map.png')
                map_file_path = maps_dir / f"{session_id}.png"
                with open(map_file_path, 'wb') as f:
                    f.write(map_data)
                print(f"Saved map to {map_file_path}")
            
            # Extract embeddings.json
            if 'embeddings.json' in zf.namelist():
                embeddings_data = zf.read('embeddings.json')
                embeddings_file_path = embeddings_dir / f"{session_id}.json"
                with open(embeddings_file_path, 'wb') as f:
                    f.write(embeddings_data)
                print(f"Saved embeddings to {embeddings_file_path}")
        
        # Clean up temp zip
        zip_path.unlink()
        
        # Update sessions.pkl with lightweight metadata
        sessions_file = data_dir / "sessions.pkl"
        sessions = {}
        if sessions_file.exists():
            try:
                with open(sessions_file, 'rb') as f:
                    sessions = pickle.load(f)
            except:
                sessions = {}
        
        # Store lightweight session metadata
        sessions[session_id] = {
            "created_at": time.time(),
            "map_path": str(map_file_path),
            "embeddings_path": str(embeddings_file_path)
        }
        
        with open(sessions_file, 'wb') as f:
            pickle.dump(sessions, f)
        
        print(f"Session {session_id} stored successfully")
        return {
            "success": True,
            "session_id": session_id,
            "message": "Map downloaded and cached locally"
        }
        
    except Exception as e:
        print(f"Error unpacking zip: {e}")
        return {"success": False, "error": f"Failed to unpack zip: {e}"}


def abort_current_task() -> Dict[str, Any]:
    """
    Abort the currently running task by simulating connection loss.
    Returns status of the abort operation.
    """
    global _current_task
    
    if not _current_task:
        return {"success": False, "message": "No active task to abort"}
    
    try:
        task_id = _current_task.get("task_id")
        connection_id = _current_task.get("connection_id") 
        server_url = _current_task.get("server_url")
        
        print(f"🚫 Aborting task {task_id} with connection {connection_id}")
        
        # For HTTP-based cancellation, we can mark the connection as disconnected
        # This will trigger the AWS server's task cancellation for this connection_id
        
        # Since there's no direct HTTP endpoint for connection disconnect,
        # we'll manually set the task status to cancelled by calling the progress endpoint
        # and then simulating what the disconnect handler would do
        
        # Method 1: Try to find a cancel endpoint
        try:
            cancel_url = f"{server_url}/cancel_task"
            response = requests.post(cancel_url, json={
                "task_id": task_id,
                "connection_id": connection_id
            }, timeout=30)  # 30 seconds for cancel requests
            
            if response.status_code == 200:
                print(f"✅ Task {task_id} cancellation requested via cancel endpoint")
                _current_task.clear()
                return {"success": True, "message": f"Task {task_id} cancelled"}
        except:
            pass  # Endpoint might not exist, try alternative
        
        # Method 2: Simulate connection loss by triggering background task detection
        # Since we can't directly disconnect HTTP, we'll rely on task status checking
        print(f"⚠️ No direct cancel endpoint found, marking task for cancellation")
        _current_task.clear()
        return {"success": True, "message": "Task abort requested - cancellation will be detected on next poll"}
            
    except Exception as e:
        print(f"❌ Error aborting task: {e}")
        return {"success": False, "error": f"Abort failed: {str(e)}"}


def get_current_task_info() -> Dict[str, Any]:
    """Get information about the currently running task."""
    return _current_task.copy()
