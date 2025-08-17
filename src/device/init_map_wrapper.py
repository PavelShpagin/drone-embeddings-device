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
        
        # Call server init_map with mode=device to get zip data
        response = requests.post(f"{server_url}/init_map", json={
            "lat": lat,
            "lng": lng,
            "meters": meters,
            "mode": "device",
            "session_id": session_id
        }, timeout=(15, 120))
        
        response.raise_for_status()
        print(f"Server response status: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
        
        # Check if response is a zip file
        if response.headers.get('content-type') == 'application/zip':
            # Extract session_id from filename header
            content_disposition = response.headers.get('content-disposition', '')
            if 'session_' in content_disposition:
                session_id_from_header = content_disposition.split('session_')[1].split('.')[0]
            else:
                session_id_from_header = f"session_{int(time.time())}"
            
            # Download and unpack zip
            result = _download_and_unpack_zip(response.content, session_id_from_header)
            return result
        else:
            # JSON response (likely error or server mode)
            try:
                result = response.json()
                print(f"JSON response: {str(result)[:200]}...")
                return result
            except Exception as e:
                return {"success": False, "error": f"Failed to parse response: {e}"}
        
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
