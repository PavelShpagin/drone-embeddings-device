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
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image
import numpy as np


async def call_server_init_map(lat: float, lng: float, meters: int = 1000, 
                               server_url: str = "http://localhost:5000", 
                               session_id: Optional[str] = None,
                               progress_callback: Optional[callable] = None) -> Dict[str, Any]:
    """
    Call server init_map endpoint and store results locally with progress polling.
    
    Args:
        lat: Latitude coordinate
        lng: Longitude coordinate  
        meters: Coverage area in meters
        server_url: Server base URL
        session_id: Optional session ID for caching
        progress_callback: Callback function for progress updates
        
    Returns:
        Dict with success status and session_id
    """
    try:
        if progress_callback:
            progress_callback("Initializing connection...", 5)
        
        print(f"Calling server init_map at {server_url}/init_map")
        if session_id:
            print(f"Requesting cached session: {session_id}")
        else:
            print(f"New request: lat={lat}, lng={lng}, meters={meters}")
        
        if progress_callback:
            progress_callback("Requesting satellite data...", 10)
        
        # Try async mode first (new server)
        try:
            response = requests.post(f"{server_url}/init_map", json={
                "lat": lat,
                "lng": lng,
                "meters": meters,
                "mode": "device_async",  # Request async mode for progress tracking
                "session_id": session_id
            }, timeout=(30, 120))  # 30s connection, 120s read for large areas
            
            response.raise_for_status()
            result = response.json()
            
            # Check if we got a task_id for polling
            if result.get("task_id"):
                # Async mode supported - poll for progress
                task_id = result["task_id"]
                print(f"Server supports async mode. Got task_id: {task_id}, polling for progress...")
                
                # Poll for progress updates
                final_result = await _poll_server_progress(server_url, task_id, progress_callback)
                return final_result
                
        except (requests.exceptions.RequestException, KeyError) as e:
            print(f"Async mode failed ({e}), falling back to device mode...")
            # Fallback to regular device mode
            
        # Fallback to regular device mode (old server or error)
        if progress_callback:
            progress_callback("Connecting to data server...", 15)
        

            
        response = requests.post(f"{server_url}/init_map", json={
            "lat": lat,
            "lng": lng,
            "meters": meters,
            "mode": "device",  # Fallback to regular device mode
            "session_id": session_id
        }, timeout=(30, 180))  # 30s connection, 180s read for fallback mode
        
        response.raise_for_status()
        
        # Check if response is a zip file (old server style)
        if response.headers.get('content-type') == 'application/zip':
            if progress_callback:
                progress_callback("Downloading map data...", 40)
            
            # Extract session_id from filename header
            content_disposition = response.headers.get('content-disposition', '')
            if 'session_' in content_disposition:
                session_id_from_header = content_disposition.split('session_')[1].split('.')[0]
            else:
                session_id_from_header = f"session_{int(time.time())}"
            
            # Download and unpack zip
            final_result = _download_and_unpack_zip(response.content, session_id_from_header, progress_callback)
            return final_result
            
        else:
            # JSON response
            result = response.json()
            
            if result.get("zip_data"):
                # Base64 encoded zip data response
                if progress_callback:
                    progress_callback("Processing satellite data...", 40)
                
                import base64
                zip_data = base64.b64decode(result["zip_data"])
                session_id_received = result.get("session_id", f"session_{int(time.time())}")
                
                # Download and unpack zip
                final_result = _download_and_unpack_zip(zip_data, session_id_received, progress_callback)
                return final_result
                
            else:
                # Error or other response
                return result
        
    except requests.exceptions.RequestException as e:
        print(f"Network error calling server: {e}")
        return {"success": False, "error": f"Network error: {str(e)}"}
    except Exception as e:
        print(f"Unexpected error: {e}")
        return {"success": False, "error": f"Error: {str(e)}"}


async def _poll_server_progress(server_url: str, task_id: str, progress_callback: Optional[callable] = None) -> Dict[str, Any]:
    """
    Poll the server for progress updates on a long-running task.
    
    Args:
        server_url: Base server URL
        task_id: Task ID to poll for
        progress_callback: Callback for progress updates
        
    Returns:
        Final result when task completes
    """
    try:
        max_polls = 120  # 2 minutes max polling
        poll_interval = 1  # Poll every second
        
        for poll_count in range(max_polls):
            await asyncio.sleep(poll_interval)
            
            try:
                # Poll progress endpoint
                response = requests.get(f"{server_url}/progress/{task_id}", timeout=60)  # 60s timeout for progress polls
                response.raise_for_status()
                progress_data = response.json()
                
                status = progress_data.get("status", "unknown")
                progress = progress_data.get("progress", 0)
                message = progress_data.get("message", "Processing...")
                
                # Update progress
                if progress_callback and message and progress:
                    progress_callback(message, progress)
                
                print(f"Poll {poll_count + 1}: {status} - {progress}% - {message}")
                
                if status == "completed":
                    # Task completed successfully
                    if progress_data.get("zip_data"):
                        # Got zip data, process it
                        import base64
                        zip_data = base64.b64decode(progress_data["zip_data"])
                        session_id = progress_data.get("session_id", f"session_{int(time.time())}")
                        
                        if progress_callback:
                            progress_callback("Compressing map data...", 85)
                        
                        return _download_and_unpack_zip(zip_data, session_id, progress_callback)
                    else:
                        return {
                            "success": True,
                            "session_id": progress_data.get("session_id"),
                            "message": "Task completed successfully"
                        }
                        
                elif status == "failed" or status == "error":
                    # Task failed
                    error_msg = progress_data.get("error", "Unknown error")
                    return {"success": False, "error": error_msg}
                    
                # Continue polling for in_progress, queued, etc.
                
            except requests.exceptions.RequestException as e:
                print(f"Error polling progress: {e}")
                # Continue polling unless it's a persistent error
                if poll_count > 5:  # Give it a few retries
                    return {"success": False, "error": f"Progress polling failed: {e}"}
        
        # Polling timeout
        return {"success": False, "error": "Timeout waiting for server response"}
        
    except Exception as e:
        print(f"Error in progress polling: {e}")
        return {"success": False, "error": f"Progress polling error: {e}"}


def _download_and_unpack_zip(zip_data: bytes, session_id: str, progress_callback: Optional[callable] = None) -> Dict[str, Any]:
    """Download and unpack zip file to local storage."""
    try:
        if progress_callback:
            progress_callback("Preparing storage...", 50)
        
        # Create directories
        data_dir = Path("data")
        maps_dir = data_dir / "maps"
        embeddings_dir = data_dir / "embeddings"
        
        for dir_path in [data_dir, maps_dir, embeddings_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        if progress_callback:
            progress_callback("Saving data package...", 60)
        
        # Save zip temporarily
        zip_path = data_dir / f"{session_id}_temp.zip"
        with open(zip_path, 'wb') as f:
            f.write(zip_data)
        
        if progress_callback:
            progress_callback("Extracting satellite images...", 70)
        
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
        
        if progress_callback:
            progress_callback("Finalizing installation...", 90)
        
        # Clean up temp zip
        zip_path.unlink()
        
        if progress_callback:
            progress_callback("Completing setup...", 95)
        
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
        
        if progress_callback:
            progress_callback("Mission data ready!", 100)
        
        print(f"Session {session_id} stored successfully")
        return {
            "success": True,
            "session_id": session_id,
            "message": "Map downloaded and cached locally"
        }
        
    except Exception as e:
        print(f"Error unpacking zip: {e}")
        return {"success": False, "error": f"Failed to unpack zip: {e}"}
