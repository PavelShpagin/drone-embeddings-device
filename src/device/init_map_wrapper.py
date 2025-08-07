"""
Device Init Map Wrapper
======================
Calls the server init_map endpoint and stores results locally.
"""

import requests
import json
import pickle
import os
from typing import Dict, Any, Optional
from models import SessionData, PatchData
import numpy as np
import uuid


def call_server_init_map(lat: float, lng: float, meters: int = 1000, 
                        server_url: str = "http://localhost:5000") -> Dict[str, Any]:
    """
    Call server init_map endpoint and store results locally.
    
    Args:
        lat: Latitude coordinate
        lng: Longitude coordinate  
        meters: Coverage area in meters
        server_url: Server base URL
        
    Returns:
        Dict with success status and session_id
    """
    try:
        # Call server init_map with mode=device to get full data
        response = requests.post(f"{server_url}/init_map", json={
            "lat": lat,
            "lng": lng,
            "meters": meters,
            "mode": "device"
        }, timeout=120)
        
        response.raise_for_status()
        result = response.json()
        
        if not result.get("success", False):
            return {"success": False, "error": result.get("error", "Unknown error")}
            
        # Extract session data
        session_id = result.get("session_id")
        if not session_id:
            return {"success": False, "error": "No session_id received"}
        
        # Extract map_data from result (for mode=device)
        map_data = result.get("map_data", {})
        if not map_data:
            return {"success": False, "error": "No map_data received from server"}
            
        # Store session data locally
        _store_session_data(session_id, map_data)
        
        return {
            "success": True,
            "session_id": session_id,
            "message": "Map initialized and cached locally"
        }
        
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"Network error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Error: {str(e)}"}


def _store_session_data(session_id: str, map_data: Dict[str, Any]) -> None:
    """Store session data received from server locally."""
    
    # Create directories
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/maps", exist_ok=True)
    os.makedirs("data/embeddings", exist_ok=True)
    os.makedirs("data/server_paths", exist_ok=True)
    
    # Save full map
    if "full_map" in map_data:
        map_path = f"data/maps/{session_id}.pkl"
        with open(map_path, 'wb') as f:
            pickle.dump(map_data["full_map"], f)
    
    # Save patches with embeddings (this is what we need for GPS matching!)
    if "patches" in map_data:
        embeddings_path = f"data/embeddings/{session_id}.json"
        with open(embeddings_path, 'w') as f:
            json.dump(map_data["patches"], f)
    
    # Load or create sessions.pkl
    sessions_file = "data/sessions.pkl"
    sessions = {}
    if os.path.exists(sessions_file):
        try:
            with open(sessions_file, 'rb') as f:
                sessions = pickle.load(f)
        except:
            sessions = {}
    
    # Convert patches from server format to PatchData objects
    patch_objects = []
    for patch_dict in map_data.get("patches", []):
        patch_obj = PatchData(
            embedding=np.array(patch_dict["embedding"]),
            lat=patch_dict["lat"],
            lng=patch_dict["lng"],
            patch_coords=tuple(patch_dict["coords"])
        )
        patch_objects.append(patch_obj)
    
    # Create SessionData object from map_data
    session_data = SessionData(
        session_id=session_id,
        created_at=0.0,  # Set current time
        meters_coverage=map_data.get("meters_coverage", 0),
        patches=patch_objects,  # Now properly formatted PatchData objects!
        full_map=np.array(map_data.get("full_map", [])) if map_data.get("full_map") else None,
        map_bounds=map_data.get("map_bounds", {}),
        patch_size=10,  # Default patch size
        path_data=[],
        path_image_file=None
    )
    
    # Store in sessions
    sessions[session_id] = session_data
    
    # Save sessions.pkl
    with open(sessions_file, 'wb') as f:
        pickle.dump(sessions, f)
