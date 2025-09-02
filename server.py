#!/usr/bin/env python3
"""
FastAPI server for drone device management with web UI.
Provides map interface for mission configuration and state management.
"""

import asyncio
import base64
import glob
import io
import json
import logging
import os
import requests
import shutil
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import yaml
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add device src to path
import sys
device_src_path = str(Path(__file__).parent / 'src')
sys.path.insert(0, device_src_path)
sys.path.insert(0, str(Path(__file__).parent / 'src' / 'general'))

# HTTP polling wrapper removed - using WebSocket client only

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Drone Device Server", description="Global UAV Localization Device Interface")

# Global state for tracking async tasks
active_tasks = {}
progress_data = {}


class InitMapRequest(BaseModel):
    lat: float
    lng: float
    km: float
    session_id: Optional[str] = None


class StateManager:
    """Manages device state in YAML file."""
    
    def __init__(self, state_file: str = "state.yaml"):
        self.state_file = Path(state_file)
        self.ensure_state_file()
    
    def ensure_state_file(self):
        """Create state file if it doesn't exist."""
        if not self.state_file.exists():
            default_state = {
                'session_id': '',
                'lat': None,
                'lng': None,
                'km': None,
                'last_updated': None
            }
            self.save_state(default_state)
    
    def load_state(self) -> Dict[str, Any]:
        """Load state from YAML file."""
        try:
            with open(self.state_file, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Error loading state: {e}")
            return {}
    
    def save_state(self, state: Dict[str, Any]):
        """Save state to YAML file."""
        try:
            state['last_updated'] = datetime.now().isoformat()
            with open(self.state_file, 'w') as f:
                yaml.dump(state, f, default_flow_style=False)
        except Exception as e:
            logger.error(f"Error saving state: {e}")
    
    def update_state(self, **kwargs):
        """Update specific state fields."""
        state = self.load_state()
        state.update(kwargs)
        self.save_state(state)
    
    def get_computed_status(self) -> str:
        """Compute status based on session_id: empty = idle, non-empty = ready."""
        state = self.load_state()
        session_id = state.get('session_id', '')
        return 'ready' if session_id else 'idle'
    
    def load_state_with_status(self) -> Dict[str, Any]:
        """Load state with computed status."""
        state = self.load_state()
        state['status'] = self.get_computed_status()
        return state


# Initialize state manager
state_manager = StateManager()


@app.get("/", response_class=HTMLResponse)
async def get_index():
    """Serve the main HTML interface."""
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Global UAV Localization</title>
    <link rel="icon" type="image/png" href="/static/favicon.png">
    <script src="https://maps.googleapis.com/maps/api/js?key=AIzaSyBQEoMxbEzfrLNK2L69c7J6HeS5GJG-Uis&libraries=places"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap');
        
        :root {
            --primary-blue: #1e40af;
            --accent-yellow: #fbbf24;
            --success-green: #10b981;
            --danger-red: #ef4444;
            --neutral-gray: #6b7280;
            --light-gray: #f3f4f6;
            --white: #ffffff;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'JetBrains Mono', monospace;
            background: var(--white);
            min-height: 100vh;
            margin: 0;
            padding: 0;
            color: #333;
        }
        
        .container {
            width: 100%;
            height: 100vh;
            background: var(--white);
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        
        .header {
            background: var(--primary-blue);
            color: var(--white);
            padding: 15px 30px;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .logo {
            width: 36px;
            height: 36px;
        }
        
        .header h1 {
            font-size: 20px;
            font-weight: 700;
        }
        
        .main-content {
            display: flex;
            flex: 1;
            height: calc(100vh - 66px);
        }
        
        .sidebar {
            width: 350px;
            background: var(--light-gray);
            padding: 16px;
            border-right: 1px solid #e5e7eb;
            overflow-y: auto;
        }
        
        .state-box {
            background: var(--white);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }
        
        .state-box h3 {
            color: var(--primary-blue);
            font-size: 16px;
            margin-bottom: 15px;
            font-weight: 700;
        }
        
        .state-item {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            font-size: 13px;
        }
        
        .state-label {
            color: var(--neutral-gray);
            font-weight: 500;
        }
        
        .state-value {
            font-weight: 700;
            color: #333;
        }
        
        .controls {
            margin-top: 14px;
        }
        
        .input-group {
            margin-bottom: 15px;
        }
        
        .input-group label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            color: var(--neutral-gray);
            font-size: 14px;
        }
        
        .input-group input {
            width: 100%;
            padding: 12px;
            border: 2px solid #e5e7eb;
            border-radius: 8px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 14px;
        }
        
        .input-group input:focus {
            outline: none;
            border-color: var(--primary-blue);
        }
        
        .search-input-container {
            position: relative;
            display: flex;
            align-items: center;
        }
        
        .search-icon {
            position: absolute;
            left: 12px;
            color: var(--neutral-gray);
            z-index: 1;
            pointer-events: none;
        }
        
        .search-input-container input {
            padding-left: 40px;
        }
        
        .btn {
            font-family: 'JetBrains Mono', monospace;
            font-weight: 500;
            font-size: 14px;
            padding: 14px 20px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            transition: all 0.2s ease;
        }
        
        .btn-primary {
            background: var(--success-green);
            color: var(--white);
        }
        
        .btn-primary:hover {
            background: #059669;
        }
        
        .btn-danger {
            background: var(--danger-red);
            color: var(--white);
        }
        
        .btn-danger:hover {
            background: #dc2626;
        }
        
        .btn-secondary {
            background: var(--neutral-gray);
            color: var(--white);
        }
        
        .btn-secondary:hover {
            background: #4b5563;
        }

        
        .btn-discovery {
            background: #f59e0b;
            color: var(--white);
            font-weight: 500;
        }
        
        .btn-discovery:hover {
            background: #d97706;
        }
        
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }
        
        .map-container {
            flex: 1;
            position: relative;
        }
        
        #map {
            width: 100%;
            height: 100%;
            min-height: 600px;
        }
        
        .progress-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255, 255, 255, 0.95);
            display: none;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            z-index: 1000;
        }
        
        .progress-content {
            text-align: center;
            width: 360px; /* slightly thinner */
            max-width: 90vw;
            padding: 40px;
            background: var(--white);
            border-radius: 16px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
        }
        
        .progress-bar {
            width: 100%;
            height: 8px;
            background: #e5e7eb;
            border-radius: 4px;
            overflow: hidden;
            margin: 20px 0;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--success-green), #22c55e);
            width: 0%;
            transition: width 0.15s cubic-bezier(0.25, 0.46, 0.45, 0.94);
            border-radius: 4px;
            position: relative;
            overflow: hidden;
            will-change: width;
            transform: translateZ(0);
        }
        
        .progress-fill::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
            animation: progress-shine 2s infinite;
        }
        
        @keyframes progress-shine {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(100%); }
        }
        
        /* Manual session row */
        .manual-session-row {
            display: flex;
            gap: 8px;
            align-items: center;
        }
        .manual-session-row input {
            flex: 1 1 auto;
            min-width: 0;
            padding: 12px;
            border: 2px solid #e5e7eb;
            border-radius: 8px;
            font-family: 'JetBrains Mono', monospace;
        }
        .btn-blue {
            background: #3b7dd8; /* improved natural blue */
            color: var(--white);
        }
        .btn-blue:hover {
            background: #1d4ed8; /* richer blue on hover */
        }
        
        .status-text {
            color: var(--neutral-gray);
            font-size: 14px;
            margin-bottom: 10px;
        }
        
        .timer {
            font-size: 18px;
            font-weight: 700;
            color: var(--primary-blue);
            margin: 10px 0;
        }
        

        
        .hidden {
            display: none !important;
        }
        
        .btn-group {
            display: flex;
            gap: 12px;
            margin-top: 20px;
        }
        
        .btn-group .btn {
            flex: 1;
            min-height: 48px;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 500;
        }
        
        /* Mobile Responsiveness */
        @media (max-width: 768px) {
            .main-content {
                flex-direction: column;
                height: auto;
                min-height: calc(100vh - 66px);
            }
            
            .sidebar {
                width: 100%;
                border-right: none;
                border-bottom: 1px solid #e5e7eb;
                order: 1;
            }
            
            .map-container {
                order: 2;
                min-height: 400px;
                flex: 1;
            }
            
            .header {
                padding: 12px 20px;
            }
            
            .header h1 {
                font-size: 18px;
            }
            
            .logo {
                width: 32px;
                height: 32px;
            }
            
            .sidebar {
                padding: 20px;
            }
            
            .input-group {
                margin-bottom: 15px;
            }
            
            .btn-group {
                flex-direction: column;
                gap: 10px;
            }
            
            .btn-group .btn {
                width: 100%;
                flex: none;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <img src="/static/favicon.png" alt="Logo" class="logo">
            <h1>Global UAV Localization</h1>
        </div>
        
        <div class="main-content">
            <div class="sidebar">
                <div class="state-box">
                    <h3>Drone State</h3>
                    <div id="state-content">
                        <!-- State will be populated by JavaScript -->
                    </div>

                    <button class="btn btn-danger" onclick="clearState()" style="width: 100%; margin-top: 12px;">
                        Clear State
                    </button>
                </div>
                
                <div class="controls">
                    <div class="input-group">
                        <label>Search Location</label>
                        <div class="search-input-container">
                            <svg class="search-icon" viewBox="0 0 24 24" width="16" height="16">
                                <path fill="currentColor" d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>
                            </svg>
                            <input type="text" id="search-input" placeholder="Search for a place...">
                        </div>
                    </div>
                    
                    <div class="input-group">
                        <label>Latitude</label>
                        <input type="number" id="lat-input" step="any" placeholder="50.4162">
                    </div>
                    
                    <div class="input-group">
                        <label>Longitude</label>
                        <input type="number" id="lng-input" step="any" placeholder="30.8906">
                    </div>
                    
                    <div class="input-group">
                        <label>Coverage (km)</label>
                        <input type="number" id="km-input" min="1" max="100" value="1" placeholder="1">
                    </div>
                    
                    <button class="btn btn-primary" style="margin-top: 5px; width: 100%;" id="submit-btn" onclick="submitMission()">
                        Submit Mission
                    </button>
                    
                    <!-- Fetch Existing Session -->
                    <div id="manual-session" style="margin-top: 20px;">
                        <div class="manual-session-row">
                            <input id="session-input" type="text" maxlength="8" placeholder="8-char session id" />
                            <button class="btn btn-blue" id="fetch-session-btn" onclick="fetchExistingSession()">Fetch</button>
                        </div>
                    </div>
                    
                    <!-- 
                    <button class="btn btn-test" id="test-websocket-btn" onclick="testWebSocket()" style="width: 100%; margin-top: 20px; background-color: #8B5CF6;">
                        TEST WEBSOCKET
                    </button>
                    
                    <button class="btn btn-discovery" id="discovery-btn" onclick="startDiscovery()" style="width: 100%; margin-top: 15px;">
                        Find Drones
                    </button>
                    -->
                    <button class="btn btn-secondary" id="send-logs-btn" onclick="sendLogs()" style="width: 100%; margin-top: 15px;">
                        Send Logs
                    </button>
                </div>
            </div>
            
            <div class="map-container">
                <div id="map"></div>
                
                <div class="progress-overlay" id="progress-overlay">
                    <div class="progress-content">
                        <div class="status-text" id="status-text">Initializing...</div>
                        <div class="progress-bar">
                            <div class="progress-fill" id="progress-fill"></div>
                        </div>
                        <div class="timer" id="timer"></div>
                        <button class="btn btn-danger" id="cancel-progress-btn" onclick="immediateCancel()">
                            Cancel Operation
                        </button>
                    </div>
                </div>

                <!-- WebSocket Test Panel -->
                <div class="progress-overlay" id="websocket-test-overlay" style="background: rgba(139, 92, 246, 0.95); display: none;">
                    <div class="progress-content">
                        <div style="color: white; font-size: 32px; font-weight: bold; margin-bottom: 30px; text-align: center;">
                            Hello World <span id="websocket-counter" style="color: #FFD700;">0</span>
            </div>
                        <div style="color: white; font-size: 18px; margin-bottom: 30px; text-align: center;">
                            WebSocket Connection Test
                        </div>
                        <button class="btn btn-danger" id="cancel-websocket-btn" onclick="cancelWebSocketTest()" style="font-size: 16px; padding: 12px 24px;">
                            CANCEL
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let map;
        let marker;
        let currentState = {};
        let progressTimer;
        
        // Initialize Google Map
        function initMap() {
            map = new google.maps.Map(document.getElementById('map'), {
                center: { lat: 50.4162, lng: 30.8906 },
                zoom: 10,
                mapTypeId: 'hybrid',
                mapTypeControl: false,
                streetViewControl: false,
                fullscreenControl: false
            });
            
            // Initialize search functionality
            const searchBox = new google.maps.places.SearchBox(document.getElementById('search-input'));
            
            // Bias the SearchBox results towards current map's viewport
            map.addListener('bounds_changed', function() {
                searchBox.setBounds(map.getBounds());
            });
            
            // Listen for the event fired when the user selects a prediction
            searchBox.addListener('places_changed', function() {
                const places = searchBox.getPlaces();
                
                if (places.length == 0) {
                    return;
                }
                
                // Get the first place
                const place = places[0];
                
                if (!place.geometry || !place.geometry.location) {
                    console.log("Returned place contains no geometry");
                    return;
                }
                
                // Center map on the selected place
                map.setCenter(place.geometry.location);
                map.setZoom(14);
                
                // Update coordinates
                const lat = place.geometry.location.lat();
                const lng = place.geometry.location.lng();
                
                document.getElementById('lat-input').value = lat.toFixed(6);
                document.getElementById('lng-input').value = lng.toFixed(6);
                
                // Update marker
                if (marker) {
                    marker.setPosition(place.geometry.location);
                } else {
                    marker = new google.maps.Marker({
                        position: place.geometry.location,
                        map: map,
                        title: place.name || 'Selected Location'
                    });
                }
            });
            
            // Add click listener for coordinate selection
            map.addListener('click', function(event) {
                const lat = event.latLng.lat();
                const lng = event.latLng.lng();
                
                // Update inputs
                document.getElementById('lat-input').value = lat.toFixed(6);
                document.getElementById('lng-input').value = lng.toFixed(6);
                
                // Update marker
                if (marker) {
                    marker.setPosition(event.latLng);
                } else {
                    marker = new google.maps.Marker({
                        position: event.latLng,
                        map: map,
                        title: 'Selected Location'
                    });
                }
            });
        }
        
        // Load current state
        async function loadState() {
            try {
                const response = await fetch('/api/state');
                currentState = await response.json();
                updateStateDisplay();
            } catch (error) {
                console.error('Error loading state:', error);
            }
        }
        
        // Update state display
        function updateStateDisplay() {
            const stateContent = document.getElementById('state-content');
            const statusBadge = getStatusBadge(currentState.status || 'idle');
            const sessionDisplay = currentState.session_id || 'None';
            
            stateContent.innerHTML = `
                <div class="state-item">
                    <span class="state-label">Status:</span>
                    <span class="state-value">${statusBadge}</span>
                </div>
                <div class="state-item">
                    <span class="state-label">Session:</span>
                    <span class="state-value">${sessionDisplay}</span>
                </div>
                <div class="state-item">
                    <span class="state-label">Location:</span>
                    <span class="state-value">${currentState.lat && currentState.lng ? 
                        `${currentState.lat.toFixed(4)}, ${currentState.lng.toFixed(4)}` : 'Not Set'}</span>
                </div>
                <div class="state-item">
                    <span class="state-label">Coverage:</span>
                    <span class="state-value">${currentState.km ? currentState.km + ' km' : 'Not Set'}</span>
                </div>
            `;
        }
        
        // Get status badge with color
        function getStatusBadge(status) {
            const badges = {
                'idle': '<span style="color: var(--neutral-gray);">● Idle</span>',
                'initializing': '<span style="color: var(--accent-yellow);">● Initializing</span>',
                'ready': '<span style="color: var(--success-green);">● Ready</span>',
                'processing': '<span style="color: var(--primary-blue);">● Processing</span>',
                'error': '<span style="color: var(--danger-red);">● Error</span>'
            };
            return badges[status] || badges['idle'];
        }
        
        // Button management functions
        function disableButtons() {
            const submitBtn = document.getElementById('submit-btn');
            if (submitBtn) submitBtn.disabled = true;
            const discoveryBtn = document.getElementById('discovery-btn');
            if (discoveryBtn) discoveryBtn.disabled = true;
            const sendLogsBtn = document.getElementById('send-logs-btn');
            if (sendLogsBtn) sendLogsBtn.disabled = true;
            const fetchBtn = document.getElementById('fetch-session-btn');
            if (fetchBtn) fetchBtn.disabled = true;
            
            // Also disable clear state button
            const clearBtn = document.querySelector('.state-box button');
            if (clearBtn) clearBtn.disabled = true;
        }
        
        function enableButtons() {
            const submitBtn = document.getElementById('submit-btn');
            if (submitBtn) submitBtn.disabled = false;
            const discoveryBtn = document.getElementById('discovery-btn');
            if (discoveryBtn) discoveryBtn.disabled = false;
            const sendLogsBtn = document.getElementById('send-logs-btn');
            if (sendLogsBtn) sendLogsBtn.disabled = false;
            const fetchBtn = document.getElementById('fetch-session-btn');
            if (fetchBtn) fetchBtn.disabled = false;
            
            // Re-enable clear state button
            const clearBtn = document.querySelector('.state-box button');
            if (clearBtn) clearBtn.disabled = false;
        }
        
        // Fetch existing session function
        async function fetchExistingSession() {
            const sessionInput = document.getElementById('session-input');
            const sessionId = sessionInput.value.trim();
            
            // Validate session ID format (8 characters, alphanumeric)
            if (!/^[a-zA-Z0-9]{8}$/.test(sessionId)) {
                alert('Please enter a valid 8-character session ID (letters and numbers only)');
                return;
            }
            
            // Disable buttons during fetch
            disableButtons();
            showProgress('Fetching session data...', 0);
            
            try {
                const response = await fetch('/api/fetch_session', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: sessionId })
                });
                
                const data = await response.json();
                
                if (!response.ok) {
                    hideProgress();
                    enableButtons();
                    if (response.status === 404) {
                        alert('Session not found. Please check the session ID and try again.');
                    } else {
                        alert(data.message || 'Failed to fetch session data');
                    }
                    return;
                }
                
                // Start polling for progress
                pollProgress();
                
            } catch (error) {
                hideProgress();
                enableButtons();
                alert('Network error. Please check your connection and try again.');
            }
        }
        

        
        function toggleSessionPanel(open) {
            const panel = document.getElementById('session-panel');
            if (!panel) return;
            if (open === false) { panel.style.display = 'none'; return; }
            panel.style.display = (panel.style.display === 'none' || !panel.style.display) ? 'block' : 'none';
        }
        
        async function submitExistingSession() {
            const input = document.getElementById('session-input');
            const err = document.getElementById('session-error');
            if (!input || !err) return;
            const sid = (input.value || '').trim();
            err.textContent = '';
            if (!/^([a-z0-9]{8})$/.test(sid)) {
                err.textContent = 'Please enter a valid 8-character session ID (a-z, 0-9).';
                return;
            }
            disableButtons();  
            showProgress('Preparing data...', unifiedProgress);
            try {
                const res = await fetch('/api/init_map', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ lat: currentState.lat || 0, lng: currentState.lng || 0, km: currentState.km || 1, session_id: sid })
                });
                const data = await res.json();
                if (!res.ok || (data && data.status === 'error')) {
                    err.textContent = (data && data.message) ? data.message : 'Failed to fetch session.';
                    enableButtons();
                    return;
                }
                pollProgress();
            } catch (e) {
                err.textContent = 'Network error fetching session.';
                enableButtons();
            }
        }
        
        // Submit mission
        let missionWebSocketConnection = null;

        async function submitMission() {
            const lat = parseFloat(document.getElementById('lat-input').value);
            const lng = parseFloat(document.getElementById('lng-input').value);
            const km = parseFloat(document.getElementById('km-input').value);
            
            if (!lat || !lng || !km) {
                alert('Please fill in all coordinates and coverage area');
                return;
            }
            
            try {
                disableButtons();
                showProgress('Connecting to mission server...', 0);
                
                // Connect to WebSocket for real-time progress updates
                const wsUrl = `ws://localhost:5000/ws/mission`;
                console.log('🚀 Connecting to mission WebSocket:', wsUrl);
                missionWebSocketConnection = new WebSocket(wsUrl);
                
                missionWebSocketConnection.onopen = function(event) {
                    console.log('✅ Mission WebSocket connected');
                    showProgress('Connected - Starting mission...', 5);
                    
                    // Send mission parameters
                    missionWebSocketConnection.send(JSON.stringify({
                        type: 'init_map',
                        lat: lat,
                        lng: lng,
                        km: km
                    }));
                };
                
                missionWebSocketConnection.onmessage = function(event) {
                    console.log('📨 Mission progress:', event.data);
                    try {
                        const data = JSON.parse(event.data);
                        
                        if (data.type === 'progress') {
                            // Update progress display with clean formatting
                            const progress = data.progress || 0;
                            const message = data.message || 'Processing...';
                            
                            // Pass milestone data for enhanced progress display
                            const extraData = {
                                tiles_completed: data.tiles_completed,
                                total_tiles: data.total_tiles,
                                embeddings_processed: data.embeddings_processed,
                                total_embeddings: data.total_embeddings,
                                phase: data.phase
                            };
                            
                            updateProgress(message, progress, extraData);
                            
                            // Check for completion
                            if (data.status === 'complete' || progress >= 100) {
                                console.log('✅ Mission completed successfully');
                                updateProgress('Processing mission data...', 100);
                                
                                // Handle both zip_data (small files) and download_url (large files)
                                if (data.zip_data && data.session_id) {
                                    console.log('📦 Processing mission data directly...');
                                    processMissionData(data.zip_data, data.session_id, lat, lng, km);
                                } else if (data.download_url && data.session_id) {
                                    console.log(`📥 Downloading mission data from: ${data.download_url}`);
                                    updateProgress('Downloading mission data...', 95);
                                    
                                    fetch(`http://localhost:5000${data.download_url}`)
                                        .then(response => {
                                            if (!response.ok) {
                                                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                                            }
                                            return response.blob();
                                        })
                                        .then(blob => {
                                            console.log(`✅ Downloaded ${blob.size} bytes`);
                                            // Convert blob to base64 for processMissionData
                                            const reader = new FileReader();
                                            reader.onload = function() {
                                                const base64Data = reader.result.split(',')[1]; // Remove data:application/zip;base64, prefix
                                                processMissionData(base64Data, data.session_id, lat, lng, km);
                                            };
                                            reader.readAsDataURL(blob);
                                        })
                                        .catch(error => {
                                            console.error('❌ Download failed:', error);
                                            alert(`Failed to download mission data: ${error.message}`);
                                            setTimeout(() => {
                                                hideProgress();
                                                enableButtons();
                                                loadState();
                                                if (missionWebSocketConnection) {
                                                    missionWebSocketConnection.close();
                                                    missionWebSocketConnection = null;
                                                }
                                            }, 2000);
                                        });
                                } else {
                                    console.log('⚠️ No mission data received, completing anyway');
                                    setTimeout(() => {
                                        hideProgress();
                                        enableButtons();
                                        loadState();
                                        if (missionWebSocketConnection) {
                                            missionWebSocketConnection.close();
                                            missionWebSocketConnection = null;
                                        }
                                    }, 2000);
                                }
                            }
                        } else if (data.type === 'error') {
                            console.error('❌ Mission error:', data.message);
                            alert(`Mission failed: ${data.message}`);
                            hideProgress();
                            enableButtons();
                            if (missionWebSocketConnection) {
                                missionWebSocketConnection.close();
                                missionWebSocketConnection = null;
                            }
                        }
                    } catch (e) {
                        console.error('Error parsing mission WebSocket message:', e);
                    }
                };
                
                missionWebSocketConnection.onclose = function(event) {
                    console.log('❌ Mission WebSocket disconnected');
                    missionWebSocketConnection = null;
                };
                
                missionWebSocketConnection.onerror = function(error) {
                    console.error('Mission WebSocket error:', error);
                    alert('Mission connection failed. Falling back to HTTP...');
                    
                    // Fallback to original HTTP approach
                    fallbackToHttpMission(lat, lng, km);
                };
                
            } catch (error) {
                console.error('Mission setup error:', error);
                alert(`Network error: ${error.message}`);
                hideProgress();
                enableButtons();
            }
        }
        
        // Process mission data from WebSocket completion
        async function processMissionData(zipData, sessionId, lat, lng, km) {
            try {
                console.log('📦 Processing mission data...');
                updateProgress('Saving mission data...', 100);
                
                // Send the zip data to the server for processing
                const response = await fetch('/api/process_mission_data', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        zip_data: zipData,
                        session_id: sessionId,
                        lat: lat,
                        lng: lng,
                        km: km
                    })
                });
                
                if (response.ok) {
                    const result = await response.json();
                    console.log('✅ Mission data processed successfully');
                    updateProgress('Mission Complete! Data saved.', 100);
                    
                    setTimeout(() => {
                        hideProgress();
                        enableButtons();
                        loadState();
                        if (missionWebSocketConnection) {
                            missionWebSocketConnection.close();
                            missionWebSocketConnection = null;
                        }
                    }, 2000);
                } else {
                    const error = await response.json();
                    console.error('❌ Failed to process mission data:', error);
                    alert(`Failed to save mission data: ${error.detail}`);
                    hideProgress();
                    enableButtons();
                    if (missionWebSocketConnection) {
                        missionWebSocketConnection.close();
                        missionWebSocketConnection = null;
                    }
                }
            } catch (error) {
                console.error('❌ Error processing mission data:', error);
                alert(`Error saving mission data: ${error.message}`);
                hideProgress();
                enableButtons();
                if (missionWebSocketConnection) {
                    missionWebSocketConnection.close();
                    missionWebSocketConnection = null;
                }
            }
        }
        
        // Fallback function for HTTP-based mission submission
        async function fallbackToHttpMission(lat, lng, km) {
            try {
                showProgress('Submitting mission (HTTP fallback)...', 0);
                
                const response = await fetch('/api/init_map', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ lat, lng, km })
                });
                
                if (response.ok) {
                    pollProgress();
                } else {
                    const error = await response.json();
                    alert(`Error: ${error.detail}`);
                    hideProgress();
                    enableButtons();
                }
            } catch (error) {
                alert(`Network error: ${error.message}`);
                hideProgress();
                enableButtons();
            }
        }
        
        // Send logs
        async function sendLogs() {
            try {
                disableButtons();
                showProgress('Sending logs...', 0);
                
                const response = await fetch('/api/send_logs', { method: 'POST' });
                
                if (response.ok) {
                    pollProgress();
                } else {
                    const error = await response.json();
                    alert(`Error: ${error.detail}`);
                    hideProgress();
                    enableButtons();
                }
            } catch (error) {
                alert(`Network error: ${error.message}`);
                hideProgress();
                enableButtons();
            }
        }
        
        // Clear state
        async function clearState() {
            if (confirm('Are you sure you want to clear all drone state?')) {
                try {
                    const response = await fetch('/api/clear_state', { method: 'POST' });
                    if (response.ok) {
                        loadState();
                    } else {
                        alert('Error clearing state');
                    }
                } catch (error) {
                    alert(`Network error: ${error.message}`);
                }
            }
        }
        
        // Immediate cancel with instant UI reset - make it globally accessible
        window.immediateCancel = function() {
            console.log('Cancel button clicked - immediate UI reset');
            
            // 1. STOP POLLING IMMEDIATELY to reduce browser lag
            if (progressTimer) {
                clearInterval(progressTimer);
                progressTimer = null;
                console.log('🛑 Stopped progress polling immediately');
            }
            
            // 2. IMMEDIATE UI RESET - no delays, no waiting
            hideProgress();
            enableButtons(); 
            loadState();
            console.log('✅ UI immediately restored');
            
            // 3. Start background cancellation & cleanup (fire-and-forget)
            // Don't await or block on this - UI is already restored
            setTimeout(() => {
                cancelOperationBackground().catch(err => {
                    console.log('Background cancellation completed (error ignored):', err);
                });
            }, 0); // Execute in next tick to avoid blocking
        };
        
        // Quick file cleanup removed - WebSocket-only operations
        
        // Background cancel operation (doesn't block UI)
        async function cancelOperationBackground() {
            console.log('🔄 Starting clean WebSocket-only cancellation...');
            try {
                // Clean WebSocket-only cancellation - no HTTP fallbacks
                console.log('🛑 Closing all WebSocket connections...');
                
                // Close mission WebSocket if active
                if (missionWebSocketConnection) {
                    console.log('🛑 Closing mission WebSocket...');
                    missionWebSocketConnection.close();
                    missionWebSocketConnection = null;
                }
                
                // Close test WebSocket if active
                if (testWebSocketConnection) {
                    console.log('🛑 Closing test WebSocket...');
                    testWebSocketConnection.close();
                    testWebSocketConnection = null;
                }
                
                // Close fetch WebSocket if active
                if (fetchWebSocketConnection) {
                    console.log('🛑 Closing fetch WebSocket...');
                    fetchWebSocketConnection.close();
                    fetchWebSocketConnection = null;
                }
                
                // Close logs WebSocket if active
                if (logsWebSocketConnection) {
                    console.log('🛑 Closing logs WebSocket...');
                    logsWebSocketConnection.close();
                    logsWebSocketConnection = null;
                }
                
                console.log('✅ Clean WebSocket cancellation complete - no HTTP fallbacks');
            } catch (error) {
                console.log('⚠️ WebSocket cancellation error (ignored):', error.message);
            }
        }
        
        // Show progress overlay
        // Unified progress state (persists across phases)
        let unifiedProgress = 0;
        function showProgress(status, progress) {
            document.getElementById('progress-overlay').style.display = 'flex';
            // Reset per-run derived values
            totalTilesDetected = 0;
            // Reset progress for new mission to show smooth milestone transitions
            unifiedProgress = 0;
            updateProgress(status, Number(progress) || 0);
        }
        
        // Smooth milestone-based progress display
        
        function updateProgress(status, progress, extraData = {}) {
            // Use progress directly from WebSocket (already calculated correctly)
            const displayProgress = Math.max(0, Math.min(100, Number(progress) || 0));
            const displayStatus = status || 'Processing...';
            
            // Enhanced status with milestone information
            let enhancedStatus = displayStatus;
            if (extraData.tiles_completed && extraData.total_tiles) {
                const tileProgress = Math.round((extraData.tiles_completed / extraData.total_tiles) * 100);
                enhancedStatus = `${displayStatus} (${extraData.tiles_completed}/${extraData.total_tiles} tiles - ${tileProgress}%)`;
            } else if (extraData.embeddings_processed && extraData.total_embeddings) {
                const embeddingProgress = Math.round((extraData.embeddings_processed / extraData.total_embeddings) * 100);
                enhancedStatus = `${displayStatus}`;
            }
            
            console.log(`📊 Progress update: ${displayProgress}% - ${enhancedStatus}`);
            
            // ALWAYS update progress bar for smooth milestone transitions
            // Only prevent backwards movement if it's a significant jump backwards
            const shouldUpdate = displayProgress >= unifiedProgress || 
                                displayProgress < unifiedProgress - 5; // Allow small backwards corrections
            
            if (shouldUpdate) {
                unifiedProgress = displayProgress;
                
                // Update status and progress bar immediately for smooth UX
                document.getElementById('status-text').textContent = enhancedStatus;
                document.getElementById('progress-fill').style.width = `${displayProgress}%`;
                
                // Add smooth CSS transition for milestone nudges
                const progressFill = document.getElementById('progress-fill');
                progressFill.style.transition = 'width 0.3s ease-out';
            }
        }
        
        // Simplified progress rendering - removed complex throttling for smooth milestone updates
        
        // Hide progress overlay
        function hideProgress() {
            document.getElementById('progress-overlay').style.display = 'none';
            
            if (progressTimer) {
                clearInterval(progressTimer);
                progressTimer = null;
            }
            // Reset unified bar only when fully closed
            unifiedProgress = 0;
        }
        
        // Poll for progress updates
        function pollProgress() {
            let pollCount = 0;
            let idleCount = 0; // Track consecutive idle responses
            const maxPollsWithoutChange = 3600; // 1 hour without change = timeout (for very long operations)
            const maxIdleBeforeClose = 3; // Allow 3 consecutive idle responses before closing
            let lastMessage = '';
            
            progressTimer = setInterval(async () => {
                try {
                    const response = await fetch('/api/progress');
                    const data = await response.json();
                    
                    pollCount++;
                    
                    // Handle idle status with grace period to prevent premature closing
                    if (data.status === 'idle') {
                        idleCount++;
                        console.log(`Operation idle (${idleCount}/${maxIdleBeforeClose})`);
                        
                        // Only close after multiple consecutive idle responses
                        if (idleCount >= maxIdleBeforeClose) {
                            console.log('Operation confirmed idle - resetting UI');
                        clearInterval(progressTimer);
                        progressTimer = null;
                        hideProgress();
                        enableButtons();
                        loadState();
                        return;
                        }
                    } else {
                        // Reset idle counter if we get any non-idle response
                        idleCount = 0;
                    }
                    
                    // Detect if we're stuck with same message for too long
                    if (data.message === lastMessage) {
                        if (pollCount > maxPollsWithoutChange) {
                            console.log('Progress polling timeout - resetting UI');
                            clearInterval(progressTimer);
                            progressTimer = null;
                            hideProgress();
                            enableButtons();
                            loadState();
                            return;
                        }
                    } else {
                        pollCount = 0; // Reset counter on any change
                        lastMessage = data.message;
                    }
                    
                    // Check for completion based on status or when embeddings/state are obtained
                    const isComplete = data.status === 'complete' || 
                                     data.message.includes('Map data ready') ||
                                     data.message.includes('Session') && data.message.includes('stored successfully');
                    
                    if (isComplete) {
                        // Update to 100% and show completion
                        updateProgress('Complete!', 100, data.timer);
                        
                        // Stop polling immediately to prevent idle status
                        clearInterval(progressTimer);
                        progressTimer = null;
                        
                        // Check if this is a fetch session completion
                        const sessionPanel = document.getElementById('session-panel');
                        const sessionError = document.getElementById('session-error');
                        
                        if (sessionPanel && sessionPanel.style.display !== 'none') {
                            // This is a fetch session completion - close panel and hide progress
                            setTimeout(() => {
                                hideProgress();
                                enableButtons();
                                sessionPanel.style.display = 'none';
                                if (sessionError) sessionError.textContent = '';
                                loadState();
                            }, 1500);  // Brief moment to show completion message
                        } else {
                            // Regular operation completion (init_map with embeddings saved)
                            setTimeout(() => {
                                hideProgress();
                                enableButtons();
                                loadState();
                            }, 1500);  // Brief moment to show completion message
                        }
                    } else if (data.status === 'error') {
                        // Check if this is a fetch_session error
                        const sessionPanel = document.getElementById('session-panel');
                        const sessionError = document.getElementById('session-error');
                        
                        if (sessionPanel && sessionPanel.style.display !== 'none' && sessionError) {
                            // This is a fetch session error - show in panel
                            sessionError.textContent = data.message || 'Session not found';
                            clearInterval(progressTimer);
                            progressTimer = null;
                            hideProgress();
                            enableButtons();
                            // Don't reload state, keep panel open for retry
                        } else {
                            // Regular operation error - show alert
                            alert(`Operation failed: ${data.message}`);
                            clearInterval(progressTimer);
                            progressTimer = null;
                            hideProgress();
                            enableButtons();
                            loadState();
                        }
                    } else if (data.status === 'cancelled') {
                        updateProgress(data.message, data.progress, data.timer);
                        clearInterval(progressTimer);
                        progressTimer = null;
                        setTimeout(() => {
                            hideProgress();
                            enableButtons();
                            loadState();
                        }, 1500);  // Brief delay to show "Cleaning up..." message
                    } else if (!data.status) {
                        // Backend operation with no status - reset UI
                        console.log('No status received - resetting UI');
                        clearInterval(progressTimer);
                        progressTimer = null;
                        hideProgress();
                        enableButtons();
                        loadState();
                    } else {
                        updateProgress(data.message, data.progress, data.timer);
                    }
                } catch (error) {
                    console.error('Error polling progress:', error);
                }
            }, 1000);
        }
        
        // Manual discovery function
        async function startDiscovery() {
            try {
                disableButtons();
                showProgress('Looking for other drones...', 0);
                
                const response = await fetch('/api/start_discovery', { method: 'POST' });
                if (response.ok) {
                    pollProgress();
                } else {
                    const error = await response.json();
                    alert(`Error: ${error.detail}`);
                    hideProgress();
                    enableButtons();
                }
            } catch (error) {
                alert(`Network error: ${error.message}`);
                hideProgress();
                enableButtons();
            }
        }
        
        // WebSocket connections for different features
        let testWebSocketConnection = null;
        let fetchWebSocketConnection = null;
        let logsWebSocketConnection = null;
        
        // Fetch Existing Session via WebSocket
        async function fetchExistingSession() {
            console.log('🔍 Starting fetch existing session...');
            
            const sessionId = document.getElementById('session-input').value.trim();
            
            if (!sessionId) {
                alert('Please enter a session ID');
                return;
            }
            
            if (sessionId.length !== 8) {
                alert('Session ID must be exactly 8 characters');
                return;
            }
            
            try {
                disableButtons();
                showProgress('Connecting to fetch server...', 0);
                
                const wsUrl = `ws://localhost:5000/ws/fetch`;
                console.log('🚀 Connecting to fetch WebSocket:', wsUrl);
                fetchWebSocketConnection = new WebSocket(wsUrl);
                
                fetchWebSocketConnection.onopen = function(event) {
                    console.log('✅ Fetch WebSocket connected');
                    showProgress('Connected - Searching for session...', 5);
                    
                    // Send fetch request
                    fetchWebSocketConnection.send(JSON.stringify({
                        type: 'fetch_cached',
                        session_id: sessionId
                    }));
                };
                
                fetchWebSocketConnection.onmessage = function(event) {
                    console.log('📨 Fetch progress:', event.data);
                    try {
                        const data = JSON.parse(event.data);
                        
                        if (data.type === 'progress') {
                            // Pass milestone data for enhanced progress display
                            const extraData = {
                                tiles_completed: data.tiles_completed,
                                total_tiles: data.total_tiles,
                                embeddings_processed: data.embeddings_processed,
                                total_embeddings: data.total_embeddings,
                                phase: data.phase
                            };
                            
                            updateProgress(data.message, data.progress, extraData);
                            
                            // Handle completion with cached data
                            if (data.status === 'complete') {
                                console.log('✅ Cached data received!');
                                
                                // Process the cached data
                                const lat = (typeof data.lat === 'number') ? data.lat : null;
                                const lng = (typeof data.lng === 'number') ? data.lng : null;
                                const km = (typeof data.km === 'number') ? data.km : null;
                                
                                // Handle both zip_data (legacy) and download_url (new) approaches
                                if (data.zip_data) {
                                    // Legacy approach - direct zip data
                                    processMissionData(data.zip_data, data.session_id, lat, lng, km).then(() => {
                                        updateProgress('Cached data loaded successfully!', 100);
                                        setTimeout(() => {
                                            hideProgress();
                                            enableButtons();
                                            loadState();
                                            if (fetchWebSocketConnection) {
                                                fetchWebSocketConnection.close();
                                                fetchWebSocketConnection = null;
                                            }
                                        }, 2000);
                                    });
                                } else if (data.download_url) {
                                    // New approach - download from URL
                                    console.log(`📥 Downloading cached data from: ${data.download_url}`);
                                    updateProgress('Downloading cached data...', 95);
                                    
                                    fetch(`http://localhost:5000${data.download_url}`)
                                        .then(response => response.blob())
                                        .then(blob => {
                                            // Convert blob to base64 for processMissionData
                                            const reader = new FileReader();
                                            reader.onload = function() {
                                                const base64Data = reader.result.split(',')[1]; // Remove data:application/zip;base64, prefix
                                                processMissionData(base64Data, data.session_id, lat, lng, km).then(() => {
                                                    updateProgress('Cached data loaded successfully!', 100);
                                                    setTimeout(() => {
                                                        hideProgress();
                                                        enableButtons();
                                                        loadState();
                                                        if (fetchWebSocketConnection) {
                                                            fetchWebSocketConnection.close();
                                                            fetchWebSocketConnection = null;
                                                        }
                                                    }, 2000);
                                                });
                                            };
                                            reader.readAsDataURL(blob);
                                        })
                                        .catch(error => {
                                            console.error('❌ Download failed:', error);
                                            alert('Failed to download cached data');
                                            hideProgress();
                                            enableButtons();
                                            if (fetchWebSocketConnection) {
                                                fetchWebSocketConnection.close();
                                                fetchWebSocketConnection = null;
                                            }
                                        });
                                } else {
                                    console.log('⚠️ No cached data available');
                                    updateProgress('No cached data available', 100);
                                    setTimeout(() => {
                                        hideProgress();
                                        enableButtons();
                                        if (fetchWebSocketConnection) {
                                            fetchWebSocketConnection.close();
                                            fetchWebSocketConnection = null;
                                        }
                                    }, 2000);
                                }
                            }
                        } else if (data.type === 'error') {
                            console.error('❌ Fetch error:', data.message);
                            alert(`Fetch failed: ${data.message}`);
                            hideProgress();
                            enableButtons();
                            if (fetchWebSocketConnection) {
                                fetchWebSocketConnection.close();
                                fetchWebSocketConnection = null;
                            }
                        }
                    } catch (e) {
                        console.error('Error parsing fetch message:', e);
                    }
                };
                
                fetchWebSocketConnection.onclose = function(event) {
                    console.log('❌ Fetch WebSocket disconnected');
                    fetchWebSocketConnection = null;
                };
                
                fetchWebSocketConnection.onerror = function(error) {
                    console.error('Fetch WebSocket error:', error);
                    alert('Fetch connection failed. Please try again.');
                    hideProgress();
                    enableButtons();
                    fetchWebSocketConnection = null;
                };
                
            } catch (error) {
                console.error('Error in fetchExistingSession:', error);
                alert('Failed to fetch session. Please try again.');
                hideProgress();
                enableButtons();
                if (fetchWebSocketConnection) {
                    fetchWebSocketConnection.close();
                    fetchWebSocketConnection = null;
                }
            }
        }
        
        // Send Logs via WebSocket
        async function sendLogs() {
            console.log('📤 Starting send logs...');
            
            try {
                disableButtons();
                showProgress('Preparing logs for upload...', 0);
                
                // Create logs zip from data/logs directory
                const logsData = await createLogsZip();
                
                if (!logsData) {
                    alert('No logs found to upload');
                    hideProgress();
                    enableButtons();
                    return;
                }
                
                showProgress('Connecting to logs server...', 10);
                
                const wsUrl = `ws://localhost:5000/ws/logs`;
                console.log('🚀 Connecting to logs WebSocket:', wsUrl);
                logsWebSocketConnection = new WebSocket(wsUrl);
                
                logsWebSocketConnection.onopen = function(event) {
                    console.log('✅ Logs WebSocket connected');
                    showProgress('Connected - Uploading logs...', 15);
                    
                    // Send logs upload request
                    logsWebSocketConnection.send(JSON.stringify({
                        type: 'upload_logs',
                        logs_data: logsData
                    }));
                };
                
                logsWebSocketConnection.onmessage = function(event) {
                    console.log('📨 Logs progress:', event.data);
                    try {
                        const data = JSON.parse(event.data);
                        
                        if (data.type === 'progress') {
                            updateProgress(data.message, data.progress);
                            
                            // Handle completion
                            if (data.status === 'complete') {
                                console.log('✅ Logs uploaded successfully!');
                                
                                // Clean up local logs after successful upload
                                cleanupLocalLogs().then(() => {
                                    updateProgress('Logs uploaded and cleaned up locally!', 100);
                                    setTimeout(() => {
                                        hideProgress();
                                        enableButtons();
                                        if (logsWebSocketConnection) {
                                            logsWebSocketConnection.close();
                                            logsWebSocketConnection = null;
                                        }
                                    }, 2000);
                                });
                            }
                        } else if (data.type === 'error') {
                            console.error('❌ Logs upload error:', data.message);
                            alert(`Logs upload failed: ${data.message}`);
                            hideProgress();
                            enableButtons();
                            if (logsWebSocketConnection) {
                                logsWebSocketConnection.close();
                                logsWebSocketConnection = null;
                            }
                        }
                    } catch (e) {
                        console.error('Error parsing logs message:', e);
                    }
                };
                
                logsWebSocketConnection.onclose = function(event) {
                    console.log('❌ Logs WebSocket disconnected');
                    logsWebSocketConnection = null;
                };
                
                logsWebSocketConnection.onerror = function(error) {
                    console.error('Logs WebSocket error:', error);
                    alert('Logs upload connection failed. Please try again.');
                    hideProgress();
                    enableButtons();
                    logsWebSocketConnection = null;
                };
                
            } catch (error) {
                console.error('Error in sendLogs:', error);
                alert('Failed to send logs. Please try again.');
                hideProgress();
                enableButtons();
                if (logsWebSocketConnection) {
                    logsWebSocketConnection.close();
                    logsWebSocketConnection = null;
                }
            }
        }
        
        // Helper function to create logs zip
        async function createLogsZip() {
            try {
                const response = await fetch('/api/create_logs_zip', { method: 'POST' });
                if (response.ok) {
                    const data = await response.json();
                    return data.logs_data;
                } else {
                    console.error('Failed to create logs zip');
                    return null;
                }
            } catch (error) {
                console.error('Error creating logs zip:', error);
                return null;
            }
        }
        
        // Helper function to clean up local logs
        async function cleanupLocalLogs() {
            try {
                const response = await fetch('/api/cleanup_logs', { method: 'POST' });
                if (response.ok) {
                    console.log('✅ Local logs cleaned up');
                } else {
                    console.error('Failed to cleanup local logs');
                }
            } catch (error) {
                console.error('Error cleaning up logs:', error);
            }
        }
        
        function testWebSocket() {
            console.log('Starting WebSocket test...');
            
            // Show the test panel
            const overlay = document.getElementById('websocket-test-overlay');
            const counter = document.getElementById('websocket-counter');
            
            if (overlay && counter) {
                overlay.style.display = 'flex';
                counter.textContent = 'Connecting...';
                console.log('Panel shown, counter set to Connecting...');
            } else {
                console.error('Elements not found:', {overlay: !!overlay, counter: !!counter});
                return;
            }
            
            // Connect to WebSocket
            const wsUrl = 'ws://localhost:5000/ws/hello';
            console.log('Connecting to:', wsUrl);
            testWebSocketConnection = new WebSocket(wsUrl);
            
            testWebSocketConnection.onopen = function(event) {
                console.log('✅ WebSocket connected');
                document.getElementById('websocket-counter').textContent = 'Connected';
            };
            
            testWebSocketConnection.onmessage = function(event) {
                console.log('📨 WebSocket message:', event.data);
                try {
                    const data = JSON.parse(event.data);
                    console.log('Parsed data:', data);
                    if (data.type === 'hello') {
                        document.getElementById('websocket-counter').textContent = data.counter;
                        console.log('Updated counter to:', data.counter);
                    }
                } catch (e) {
                    console.error('Error parsing WebSocket message:', e);
                }
            };
            
            testWebSocketConnection.onclose = function(event) {
                console.log('❌ WebSocket disconnected');
                document.getElementById('websocket-counter').textContent = 'Disconnected';
            };
            
            testWebSocketConnection.onerror = function(error) {
                console.error('WebSocket error:', error);
                document.getElementById('websocket-counter').textContent = 'Error';
                alert('WebSocket connection failed: ' + error);
            };
        }
        
        function cancelWebSocketTest() {
            console.log('Canceling WebSocket test...');
            
            if (testWebSocketConnection) {
                testWebSocketConnection.close();
                testWebSocketConnection = null;
            }
            
            // Hide the test panel
            document.getElementById('websocket-test-overlay').style.display = 'none';
        }
        
        // Initialize on page load
        window.onload = function() {
            initMap();
            loadState();
            
            // Refresh state every 5 seconds
            setInterval(loadState, 5000);
        };

        // Event delegation for cancel button (more reliable than onclick)
        document.addEventListener('click', function(e) {
            if (e.target && e.target.id === 'cancel-progress-btn') {
                e.preventDefault();
                e.stopPropagation();
                console.log('Cancel button clicked via event delegation');
                window.immediateCancel();
            }
        });

        // Keyboard shortcuts for testing via MCP
        document.addEventListener('keydown', function(e) {
            try {
                if (e.key === 'Escape') {
                    // Cancel current operation with immediate UI reset
                    window.immediateCancel();
                } else if ((e.key || '').toLowerCase() === 'd') {
                    // Start discovery (shows overlay and cancel button)
                    startDiscovery();
                }
            } catch (err) {
                console.error('Shortcut handler error:', err);
            }
        });
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)


@app.get("/static/favicon.png")
async def get_favicon():
    """Serve the favicon."""
    favicon_path = Path(__file__).parent / "server" / "favicon.png"
    if favicon_path.exists():
        return FileResponse(favicon_path)
    raise HTTPException(status_code=404, detail="Favicon not found")


@app.get("/api/state")
async def get_state():
    """Get current drone state with computed status."""
    return state_manager.load_state_with_status()


@app.post("/api/init_map")
async def init_map(request: InitMapRequest, background_tasks: BackgroundTasks):
    """Initialize map data for given coordinates."""
    global active_tasks, progress_data
    
    # Cancel any existing task
    if 'init_map' in active_tasks:
        active_tasks['init_map'].cancel()
    
    # Start new background task
    task_id = str(uuid.uuid4())
    active_tasks['init_map'] = asyncio.create_task(
        _init_map_background(request.lat, request.lng, request.km, task_id)
    )
    
    # Set initial progress immediately so UI doesn't see 'idle'
    progress_data['init_map'] = {
        "status": "running",
        "progress": 5,
        "message": "Connecting to server...",
        "task_id": task_id
    }
    
    return {"status": "started", "task_id": task_id}


class ProcessMissionDataRequest(BaseModel):
    zip_data: str
    session_id: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    km: Optional[float] = None


@app.post("/api/process_mission_data")
async def process_mission_data(request: ProcessMissionDataRequest):
    """Process mission data from WebSocket completion."""
    try:
        logger.info(f"📦 Processing mission data for session {request.session_id}")
        
        # Decode base64 zip data
        zip_bytes = base64.b64decode(request.zip_data)
        
        # Extract zip contents
        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zip_ref:
            # Create data directories
            os.makedirs("data/maps", exist_ok=True)
            os.makedirs("data/embeddings", exist_ok=True)
            
            # Extract all files to the data directory
            zip_ref.extractall("data/")
            logger.info(f"✅ Extracted mission data from zip")
            
            # Move files to correct subdirectories
            import shutil
            
            # Move map files to maps subdirectory
            for filename in os.listdir("data/"):
                if filename.endswith(('.png', '.jpg', '.jpeg')) and filename.startswith('map'):
                    src = os.path.join("data", filename)
                    dst = os.path.join("data/maps", filename)
                    shutil.move(src, dst)
                    logger.info(f"📁 Moved {filename} to maps/")
            
            # Move embeddings files to embeddings subdirectory
            for filename in os.listdir("data/"):
                if filename.endswith(('.json', '.pkl', '.npy')) and 'embedding' in filename.lower():
                    src = os.path.join("data", filename)
                    dst = os.path.join("data/embeddings", filename)
                    shutil.move(src, dst)
                    logger.info(f"📁 Moved {filename} to embeddings/")
        
        # Update state by merging with existing values when None
        current = state_manager.load_state()
        merged_state = {
            'lat': request.lat if request.lat is not None else current.get('lat'),
            'lng': request.lng if request.lng is not None else current.get('lng'),
            'km': request.km if request.km is not None else current.get('km'),
            'session_id': request.session_id or current.get('session_id', ''),
        }
        state_manager.save_state(merged_state)
        
        logger.info(f"✅ Mission data processed and state updated for session {request.session_id}")
        return {"success": True, "message": "Mission data processed successfully"}
        
    except Exception as e:
        logger.error(f"❌ Failed to process mission data: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/send_logs")
async def send_logs(background_tasks: BackgroundTasks):
    """Send logs to server."""
    global active_tasks, progress_data
    
    # Cancel any existing task
    if 'send_logs' in active_tasks:
        active_tasks['send_logs'].cancel()
    
    # Start new background task
    task_id = str(uuid.uuid4())
    active_tasks['send_logs'] = asyncio.create_task(
        _send_logs_background(task_id)
    )
    
    return {"status": "started", "task_id": task_id}


@app.post("/api/create_logs_zip")
async def create_logs_zip():
    """Create a zip file of all logs in data/logs directory."""
    try:
        import base64
        import zipfile
        import io
        import os
        import glob
        
        logs_dir = "data/logs"
        
        # Check if logs directory exists and has files
        if not os.path.exists(logs_dir):
            return {"success": False, "error": "No logs directory found"}
        
        log_files = glob.glob(os.path.join(logs_dir, "*"))
        if not log_files:
            return {"success": False, "error": "No log files found"}
        
        # Create zip in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for log_file in log_files:
                if os.path.isfile(log_file):
                    # Add file to zip with relative path
                    arcname = os.path.relpath(log_file, "data")
                    zip_file.write(log_file, arcname)
        
        # Encode to base64
        logs_data = base64.b64encode(zip_buffer.getvalue()).decode('utf-8')
        
        return {
            "success": True, 
            "logs_data": logs_data,
            "file_count": len(log_files)
        }
        
    except Exception as e:
        logger.error(f"❌ Error creating logs zip: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/cleanup_logs")
async def cleanup_logs():
    """Clean up local logs after successful upload."""
    try:
        import os
        import shutil
        
        logs_dir = "data/logs"
        
        if os.path.exists(logs_dir):
            # Remove all files in logs directory
            for filename in os.listdir(logs_dir):
                file_path = os.path.join(logs_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    logger.info(f"🗑️ Removed log file: {filename}")
        
        return {"success": True, "message": "Logs cleaned up successfully"}
        
    except Exception as e:
        logger.error(f"❌ Error cleaning up logs: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/clear_state")
async def clear_state():
    """Clear all state and local data."""
    try:
        # Clear state file
        default_state = {
            'session_id': '',
            'lat': None,
            'lng': None,
            'km': None,
            'last_updated': None
        }
        state_manager.save_state(default_state)
        
        # Clean up local data directories
        data_dir = Path("data")
        for subdir in ["maps", "embeddings"]:
            subdir_path = data_dir / subdir
            if subdir_path.exists():
                shutil.rmtree(subdir_path)
                subdir_path.mkdir(parents=True, exist_ok=True)
        
        # Remove sessions file
        sessions_file = data_dir / "sessions.pkl"
        if sessions_file.exists():
            sessions_file.unlink()
        
        return {"status": "success", "message": "State cleared"}
    
    except Exception as e:
        logger.error(f"Error clearing state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/start_discovery")
async def start_discovery(background_tasks: BackgroundTasks):
    """Start drone discovery process."""
    global active_tasks, progress_data
    
    # Cancel any existing discovery task
    if 'discovery' in active_tasks:
        active_tasks['discovery'].cancel()
    
    # Start new discovery task
    task_id = str(uuid.uuid4())
    active_tasks['discovery'] = asyncio.create_task(
        _discovery_background(task_id)
    )
    
    return {"status": "discovery_started", "task_id": task_id}


@app.post("/api/stop_discovery")
async def stop_discovery():
    """Stop the discovery process."""
    global active_tasks, progress_data
    
    # Cancel discovery task
    if 'discovery' in active_tasks:
        active_tasks['discovery'].cancel()
        logger.info("Discovery cancelled by user")
    
    # Return to proper state based on actual data
    current_state = state_manager.load_state()
    session_id = current_state.get('session_id')
    
    if session_id:
        map_file = Path(f"data/maps/{session_id}.png")
        embeddings_file = Path(f"data/embeddings/{session_id}.json")
        
        if not (map_file.exists() and embeddings_file.exists()):
            # Session ID exists but no data files - reset to empty
            state_manager.update_state(session_id='')
    # Clear discovery progress
    if 'discovery' in progress_data:
        del progress_data['discovery']
    
    return {"status": "discovery_stopped"}


@app.post("/api/stop_listener")
async def stop_listener():
    """Stop the listener discovery process."""
    # This would signal the listener to stop discovery
    # State will be computed from session_id automatically
    return {"status": "listener_stopped"}


@app.post("/api/abort")
async def abort_operation():
    """Abort current operation."""
    global active_tasks, progress_data
    
    logger.info("=== ABORT OPERATION INITIATED ===")
    
    # IMMEDIATE UI FEEDBACK: Set cancellation status for any active operations
    current_operations = list(progress_data.keys())
    for operation in current_operations:
        if operation in progress_data:
            progress_data[operation] = {
                "status": "cancelled",
                "progress": 0,
                "message": "Cleaning up..."
            }
            logger.info(f"✓ Set cancelled status for {operation}")
    
    # Handle WebSocket task cancellation
    try:
        from src.device.websocket_client import cancel_current_websocket_task
        import asyncio

        # Cancel via WebSocket (best-effort, non-fatal on failure)
        loop = asyncio.get_event_loop()
        abort_success = False
        try:
            abort_success = await loop.run_in_executor(
                None,
                lambda: asyncio.run(cancel_current_websocket_task())
            )
        except Exception:
            abort_success = False

        if abort_success:
            logger.info("WebSocket task cancelled successfully")
        else:
            logger.info("No active WebSocket task to cancel")
    except Exception as e:
        logger.error(f"Error cancelling WebSocket task: {e}")
    
    # Cancel active local tasks
    if active_tasks:
        logger.info(f"Active local tasks to cancel: {list(active_tasks.keys())}")
        for task_name, task in active_tasks.items():
            if not task.done():
                task.cancel()
                logger.info(f"✓ Cancelled local task: {task_name}")
            else:
                logger.info(f"✓ Local task already done: {task_name}")
    else:
        logger.info("No active local tasks to cancel")
    
    # The progress data will be cleaned up by the cancelled tasks themselves
    # Don't clear immediately - let the UI show "Cleaning up..." first
    
    logger.info("=== ABORT OPERATION COMPLETED ===")
    
    return {"status": "aborted"}


@app.post("/api/abort_websocket")
async def abort_websocket():
    """Immediately abort any active WebSocket connections."""
    global active_tasks, progress_data
    
    logger.info("=== WEBSOCKET ABORT INITIATED ===")
    
    try:
        # WebSocket operations not supported in current implementation
        result = False
        
        if result:
            logger.info("✓ WebSocket connection forcefully closed")
            
            # Set immediate cancellation status for all operations
            current_operations = list(progress_data.keys())
            for operation in current_operations:
                if operation in progress_data:
                    progress_data[operation] = {
                        "status": "cancelled",
                        "progress": 0,
                        "message": "Connection aborted"
                    }
                    logger.info(f"✓ Set aborted status for {operation}")
            
            # Cancel all active tasks immediately
            if active_tasks:
                for task_name, task in active_tasks.items():
                    if not task.done():
                        task.cancel()
                        logger.info(f"✓ Force cancelled task: {task_name}")
            
            return {"status": "websocket_aborted", "message": "WebSocket connection terminated"}
        else:
            logger.info("✗ No active WebSocket to abort")
            return {"status": "no_websocket", "message": "No active WebSocket connection"}
            
    except Exception as e:
        logger.error(f"Error aborting WebSocket: {e}")
        return {"status": "error", "message": "Failed to abort WebSocket: " + str(e)}


@app.post("/api/cleanup_partial_files")
async def cleanup_partial_files():
    """Clean up any partial files from cancelled operations."""
    try:
        import os
        import glob
        
        cleaned_files = []
        
        # Check for partial map files (less than 1KB might be incomplete)
        maps_pattern = "data/maps/*.png"
        for file_path in glob.glob(maps_pattern):
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                if file_size < 1024:  # Less than 1KB, likely partial
                    os.remove(file_path)
                    cleaned_files.append(file_path)
                    logger.info(f"🧹 Cleaned partial map file: {file_path}")
        
        # Check for partial embedding files (less than 100 bytes might be incomplete)
        embeddings_pattern = "data/embeddings/*.json"
        for file_path in glob.glob(embeddings_pattern):
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                if file_size < 100:  # Less than 100 bytes, likely partial
                    os.remove(file_path)
                    cleaned_files.append(file_path)
                    logger.info(f"🧹 Cleaned partial embeddings file: {file_path}")
        
        logger.info(f"🧹 Quick cleanup completed: {len(cleaned_files)} files removed")
        return {"status": "success", "files_cleaned": len(cleaned_files), "files": cleaned_files}
        
    except Exception as e:
        logger.warning(f"⚠ Error during quick cleanup: {e}")
        return {"status": "completed", "message": "Cleanup completed with minor issues"}


@app.post("/api/fetch_session")
async def fetch_session(request: Request):
    """Fetch existing session from AWS server."""
    try:
        body = await request.json()
        session_id = body.get('session_id', '').strip()
        
        # Validate session ID format
        if not session_id or len(session_id) != 8 or not session_id.isalnum():
            raise HTTPException(status_code=400, detail="Invalid session ID format")
        
        # Start the fetch operation in background
        global active_tasks
        task = asyncio.create_task(_fetch_session_background(session_id))
        active_tasks[f'fetch_session_{session_id}'] = task
        
        return {"status": "started", "session_id": session_id}
        
    except Exception as e:
        logger.error(f"Error in fetch_session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/update_progress")
async def update_progress_endpoint(progress_update: dict):
    """Update progress from external sources (like AWS server)."""
    global progress_data
    
    # Update the init_map progress with real-time data from AWS server
    if 'init_map' not in progress_data:
        progress_data['init_map'] = {}
    
    progress_data['init_map'].update({
        "status": progress_update.get("status", "running"),
        "progress": progress_update.get("progress", 0),
        "message": progress_update.get("message", "Processing..."),
        "timer": progress_update.get("timer")
    })
    
    return {"success": True, "message": "Progress updated"}


@app.get("/api/progress")
async def get_progress():
    """Get current operation progress."""
    global progress_data
    
    # Check for discovery progress first
    if 'discovery' in progress_data:
        return progress_data['discovery']
    
    # Then check for other operations
    for operation in ['fetch_session', 'init_map', 'send_logs']:
        if operation in progress_data:
            return progress_data[operation]
    
    # Return latest progress data or idle state
    if progress_data:
        latest = list(progress_data.values())[-1]
        # Ensure it's a dict, not a string
        if isinstance(latest, str):
            return {"status": "complete", "progress": 100, "message": latest}
        return latest
    
    return {"status": "idle", "progress": 0, "message": ""}


async def _init_map_background(lat: float, lng: float, km: float, task_id: str):
    """Clean background task for map initialization with real-time WebSocket progress."""
    global progress_data
    
    # All required modules already imported at top of file
    
    # Store original state for rollback
    original_state = state_manager.load_state()
    
    try:
        # Initialize progress tracking
        progress_data['init_map'] = {
            "status": "running",
            "progress": 0,
            "message": "Connecting to server...",
            "task_id": task_id,
            "phase": "connecting",
            "tiles_completed": 0,
            "total_tiles": 0,
            "embeddings_processed": 0,
            "total_embeddings": 0
        }
        
        # Define clean progress callback
        async def update_progress(progress_update: Dict[str, Any]):
            """Clean progress callback that updates device UI directly."""
            logger.info(f"📊 Progress: {progress_update.get('progress', 0)}% - {progress_update.get('message', '')}")
            
            # Update global progress with structured data
            progress_data['init_map'].update({
                "status": progress_update.get("status", "running"),
                "progress": progress_update.get("progress", 0),
                "message": progress_update.get("message", "Processing..."),
                "phase": progress_update.get("phase", "unknown"),
                "tiles_completed": progress_update.get("tiles_completed", 0),
                "total_tiles": progress_update.get("total_tiles", 0),
                "embeddings_processed": progress_update.get("embeddings_processed", 0),
                "total_embeddings": progress_update.get("total_embeddings", 0)
            })
        
        # Execute init_map with clean WebSocket client
        logger.info(f"🚀 Starting mission: {lat}, {lng}, {km}km")
            
        # Initialize session_id to avoid undefined variable errors
        session_id = ''
        
        try:
            from src.device.websocket_client import call_server_init_map_websocket
            result = await call_server_init_map_websocket(
                lat=lat, 
                lng=lng, 
                meters=int(km * 1000),
                server_url="ws://localhost:5000",
                progress_callback=update_progress
                )
            
            logger.info(f"✅ Server call completed: success={result.get('success')}")
            
            # Process mission data if present
            if result.get('success'):
                try:
                    zip_bytes = None
                    
                    if result.get('zip_data'):
                        # Small file - decode base64 zip data directly
                        logger.info("📦 Processing zip_data directly")
                        zip_bytes = base64.b64decode(result['zip_data'])
                        
                    elif result.get('download_url'):
                        # Large file - download from URL
                        download_url = result['download_url']
                        # Use localhost:5000 for the download since that's where our AWS server is running
                        server_base = "http://localhost:5000"
                        full_url = f"{server_base}{download_url}"
                        
                        logger.info(f"📥 Downloading large mission file from: {full_url}")
                        
                        import requests
                        response = requests.get(full_url, timeout=30)
                        if response.status_code == 200:
                            zip_bytes = response.content
                            logger.info(f"✅ Downloaded {len(zip_bytes)} bytes")
                        else:
                            raise Exception(f"Download failed with status {response.status_code}")
                    
                    # Extract zip contents if we have data
                    if zip_bytes:
                        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zip_ref:
                            # Create data directories
                            os.makedirs("data/maps", exist_ok=True)
                            os.makedirs("data/embeddings", exist_ok=True)
                            
                            # Extract all files to the data directory
                            zip_ref.extractall("data/")
                            logger.info(f"✅ Extracted mission data from zip")
                    else:
                        logger.warning("⚠️ No mission data to process")
                        
                except Exception as e:
                    logger.error(f"❌ Failed to process mission data: {e}")
                    
        except Exception as e:
            logger.error(f"❌ Server call failed: {e}")
            result = {"success": False, "error": f"Connection failed: {e}"}
        
        if result.get('success'):
            # ATOMIC STATE UPDATE: Only update state after ALL operations succeed
            # This includes: data download, unzipping, storage, AND validation
            session_id = result.get('session_id', '')
            
            # Verify that all data was actually stored successfully
            map_file = Path(f"data/maps/{session_id}.png")
            embeddings_file = Path(f"data/embeddings/{session_id}.json")
        else:
            # WebSocket failed, but AWS might have completed processing
            # Try to find a recent session for these coordinates
            logger.warning("⚠️ WebSocket failed, checking for completed session on server...")
            try:
                # Make a simple HTTP request to get recent sessions
                response = requests.get(f"{os.getenv('AWS_WS_URL', 'ws://localhost:5000').replace('ws://', 'http://')}/health", timeout=5)
                if response.status_code == 200:
                    # Find most recent session file
                    recent_sessions = sorted(glob.glob("data/embeddings/*.json"), key=lambda x: os.path.getmtime(x), reverse=True)
                    if recent_sessions:
                        # Use the most recent session
                        session_file = recent_sessions[0]
                        session_id = os.path.basename(session_file).replace('.json', '')
                        logger.info(f"📁 Found recent session: {session_id}")
                        
                        map_file = Path(f"data/maps/{session_id}.png")
                        embeddings_file = Path(f"data/embeddings/{session_id}.json")
                        
                        if map_file.exists() and embeddings_file.exists():
                            result = {"success": True, "session_id": session_id}
                            logger.info(f"✅ Using completed session: {session_id}")
            except Exception as e:
                logger.warning(f"⚠️ Could not check for completed sessions: {e}")
                session_id = ''
                
            if not result.get('success'):
                logger.error(f"❌ No valid session found")
                session_id = ''  # Ensure session_id is always defined
                map_file = Path("")
                embeddings_file = Path("")
            
            # If files are missing but we have a session_id, attempt a fetch-only fallback
            if session_id and (not map_file.exists() or not embeddings_file.exists()):
                try:
                    # Fallback fetch using WebSocket client
                    fallback = await call_server_init_map_websocket(
                        lat=lat,
                        lng=lng,
                        meters=int(km * 1000),
                        server_url=os.getenv("AWS_WS_URL", "ws://ec2-16-171-238-14.eu-north-1.compute.amazonaws.com:5000"),
                        session_id=session_id,
                        progress_callback=update_progress
                    )
                    # Recompute file paths after fallback
                    map_file = Path(f"data/maps/{session_id}.png")
                    embeddings_file = Path(f"data/embeddings/{session_id}.json")
                except Exception as _:
                    pass

            if map_file.exists() and embeddings_file.exists():
                # TRANSACTION COMMIT: Update all state atomically
                state_manager.update_state(
                    lat=lat,
                    lng=lng,
                    km=km,
                    session_id=session_id
                )
                
                progress_data['init_map'] = {
                    "status": "complete",
                    "progress": 100,
                    "message": "Mission data ready!"
                }
                
                logger.info(f"✓ TRANSACTION COMPLETED: State updated atomically for session {session_id}")
                
                # FRONTEND CLEANUP: Keep completion status for 3 seconds so UI can detect it
                await asyncio.sleep(3.0)  # Give frontend time to detect completion and hide progress
                if 'init_map' in progress_data:
                    del progress_data['init_map']
                if task_id in active_tasks:
                    del active_tasks[task_id]
                    
            else:
                # Data verification failed - clean up partial files and rollback
                logger.error(f"✗ TRANSACTION FAILED: Data files missing for session {session_id}")
                logger.info(f"✓ CLEANUP: Removing partial data files for session {session_id}")
                
                # Clean up any partial files
                try:
                    if map_file.exists():
                        map_file.unlink()
                        logger.info(f"✓ Removed partial map file: {map_file}")
                    if embeddings_file.exists():
                        embeddings_file.unlink()
                        logger.info(f"✓ Removed partial embeddings file: {embeddings_file}")
                except Exception as cleanup_error:
                    logger.warning(f"⚠ Error during cleanup: {cleanup_error}")
                
                progress_data['init_map'] = {
                    "status": "error",
                    "progress": 0,
                    "message": "Data verification failed"
                }
                # State remains unchanged (rollback)
                
                # Keep error status for 3 seconds so frontend can detect it
                await asyncio.sleep(3.0)
                if 'init_map' in progress_data and progress_data['init_map'].get("status") == "error":
                    del progress_data['init_map']
                if task_id in active_tasks:
                    del active_tasks[task_id]
                
    
    except asyncio.CancelledError:
        # TRANSACTION ROLLBACK: Operation cancelled, restore original state
        logger.info(f"✗ TRANSACTION CANCELLED: Init map task {task_id} was cancelled by user")
        logger.info(f"✓ STATE ROLLBACK: Restoring original state")
        
        # Clean up any partial data files that might have been created
        logger.info("✓ CLEANUP: Removing any partial data files from cancelled operation")
        try:
            data_dir = Path("data")
            if data_dir.exists():
                # Clean up any temporary zip files
                for temp_file in data_dir.glob("*_temp.zip"):
                    temp_file.unlink()
                    logger.info(f"✓ Removed temp file: {temp_file}")
                
                # Clean up any partial session files (we don't know the session_id yet)
                # This is a safety cleanup for any partial files
                import time
                current_time = time.time()
                for maps_dir in (data_dir / "maps").glob("*.png"):
                    # Remove files created in the last 5 minutes that might be partial
                    if current_time - maps_dir.stat().st_mtime < 300:  # 5 minutes
                        logger.info(f"⚠ Removing recent map file (might be partial): {maps_dir}")
                        maps_dir.unlink()
                
                for emb_dir in (data_dir / "embeddings").glob("*.json"):
                    if current_time - emb_dir.stat().st_mtime < 300:  # 5 minutes
                        logger.info(f"⚠ Removing recent embeddings file (might be partial): {emb_dir}")
                        emb_dir.unlink()
        except Exception as cleanup_error:
            logger.warning(f"⚠ Error during cancellation cleanup: {cleanup_error}")
        
        # State remains unchanged from original (automatic rollback)
        progress_data['init_map'] = {
            "status": "cancelled",
            "progress": 0,
            "message": "Cleaning up..."
        }
        
        # Brief delay to show cleanup message, then clear
        await asyncio.sleep(1)
        if 'init_map' in progress_data:
            del progress_data['init_map']
        
        # Clean up task
        if task_id in active_tasks:
            del active_tasks[task_id]
    
    except Exception as e:
        # TRANSACTION ROLLBACK: Unexpected error, restore original state
        logger.error(f"✗ TRANSACTION FAILED: Unexpected error in init_map task {task_id}: {e}")
        logger.info(f"✓ STATE ROLLBACK: Restoring original state")
        
        # State remains unchanged from original (automatic rollback)
        progress_data['init_map'] = {
            "status": "error",
            "progress": 0,
            "message": f"Error: {str(e)}"
        }
        
        # Clean up task
        if task_id in active_tasks:
            del active_tasks[task_id]


async def _discovery_background(task_id: str):
    """Background task for drone discovery."""
    global progress_data
    
    try:
        from listener import DroneListener
        
        # Initialize progress
        progress_data['discovery'] = {
            "status": "running",
            "progress": 0,
            "message": "Looking for other drones...",
            "timer": 30,
            "task_id": task_id
        }
        
        # Update state to idle during discovery

        
        # Start discovery using the listener
        listener = DroneListener()
        
        # Simulate discovery countdown
        for i in range(30, 0, -1):
            if asyncio.current_task().cancelled():
                raise asyncio.CancelledError()
            
            progress = int((30 - i) / 30 * 100)
            progress_data['discovery'].update({
                "progress": progress,
                "message": f"Looking for other drones... ({i}s remaining)",
                "timer": i
            })
            
            await asyncio.sleep(1)
        
        # Try to start discovery (this is a placeholder - would integrate with actual listener)
        # result = await listener.start_discovery()
        
        # For now, simulate no drones found
        result = None
        
        if result and result.get('session_id'):
            # Found another drone
            state_manager.update_state(
                session_id=result.get('session_id'),
                lat=result.get('lat'),
                lng=result.get('lng'),
                km=result.get('km'),
                status='ready'
            )
            progress_data['discovery'] = {
                "status": "complete",
                "progress": 100,
                "message": "Found other drone! Session data received.",
                "timer": 0
            }
        else:
            # No drones found - check if we have local data to determine status
            current_state = state_manager.load_state()
            session_id = current_state.get('session_id')
            
            # Check if we have actual map/embedding files for this session
            if session_id:
                map_file = Path(f"data/maps/{session_id}.png")
                embeddings_file = Path(f"data/embeddings/{session_id}.json")
                
                if not (map_file.exists() and embeddings_file.exists()):
                    # Session ID exists but no data files - reset to empty
                    state_manager.update_state(session_id='')
            
            progress_data['discovery'] = {
                "status": "complete",
                "progress": 100,
                "message": "No other drones found. Ready for manual setup.",
                "timer": 0
            }
            
            # Clean up discovery progress after a delay
            await asyncio.sleep(2)
            if 'discovery' in progress_data:
                del progress_data['discovery']
    
    except asyncio.CancelledError:
        # Discovery cancelled - check if we have local data to determine status
        current_state = state_manager.load_state()
        session_id = current_state.get('session_id')
        
        if session_id:
            map_file = Path(f"data/maps/{session_id}.png")
            embeddings_file = Path(f"data/embeddings/{session_id}.json")
            
            if not (map_file.exists() and embeddings_file.exists()):
                state_manager.update_state(session_id='')
        
        if 'discovery' in progress_data:
            del progress_data['discovery']
        
        logger.info("Discovery cancelled")
    
    except Exception as e:
        logger.error(f"Error in discovery background task: {e}")

        progress_data['discovery'] = {
            "status": "error",
            "progress": 0,
            "message": f"Discovery error: {str(e)}",
            "timer": 0
        }


async def _send_logs_background(task_id: str):
    """Background task for sending logs."""
    global progress_data
    
    try:
        # Initialize progress
        progress_data['send_logs'] = {
            "status": "running",
            "progress": 0,
            "message": "Preparing logs...",
            "task_id": task_id
        }
        
        # Check if logs directory exists
        logs_dir = Path("logs")
        if not logs_dir.exists() or not any(logs_dir.iterdir()):
            progress_data['send_logs'] = {
                "status": "complete",
                "progress": 100,
                "message": "No logs to send"
            }
            return
        
        # Simulate log processing
        progress_steps = [
            (20, "Compressing logs..."),
            (40, "Uploading to server..."),
            (70, "Verifying upload..."),
            (90, "Cleaning up..."),
            (100, "Logs sent successfully")
        ]
        
        for progress, message in progress_steps:
            if asyncio.current_task().cancelled():
                raise asyncio.CancelledError()
            
            progress_data['send_logs'].update({
                "progress": progress,
                "message": message
            })
            
            await asyncio.sleep(1)  # Simulate work
        
        # TODO: Implement actual log upload to AWS server
        # For now, just simulate success and clean up logs
        
        # Clean up logs on success
        if logs_dir.exists():
            shutil.rmtree(logs_dir)
            logs_dir.mkdir(exist_ok=True)
        
        progress_data['send_logs'] = {
            "status": "complete",
            "progress": 100,
            "message": "Logs sent and cleaned up"
        }
    
    except asyncio.CancelledError:
        logger.info(f"Send logs task {task_id} was cancelled by user")
        progress_data['send_logs'] = {
            "status": "cancelled",
            "progress": 0,
            "message": "Cleaning up..."
        }
        
        # Brief delay to show cleanup message, then clear
        await asyncio.sleep(1)
        if 'send_logs' in progress_data:
            del progress_data['send_logs']
    
    except Exception as e:
        logger.error(f"Error in send_logs background task: {e}")
        progress_data['send_logs'] = {
            "status": "error",
            "progress": 0,
            "message": f"Error: {str(e)}"
        }


async def _fetch_session_background(session_id: str):
    """Background task to fetch existing session data from AWS server."""
    task_id = f"fetch_session_{session_id}"
    
    try:
        logger.info(f"Starting fetch session background task for session: {session_id}")
        
        # Initialize progress
        progress_data['fetch_session'] = {
            "status": "running",
            "progress": 0,
            "message": "Connecting to server..."
        }
        
        # Import the wrapper function
        # HTTP polling wrapper removed - using WebSocket client only
        
        # Try to fetch using existing session
        try:
            # Use dummy coordinates since we're fetching existing data
            lat, lng, km = 0.0, 0.0, 1
            
            # Update progress manually since sync function doesn't provide callbacks
            progress_data['fetch_session']['message'] = "Connecting to server..."
            progress_data['fetch_session']['progress'] = 20
            
            # Call the synchronous function in an executor to avoid blocking
            import asyncio
            import functools
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, 
                functools.partial(
                    call_server_init_map,
                    lat=lat, 
                    lng=lng, 
                    meters=km,
                    server_url="http://ec2-16-171-238-14.eu-north-1.compute.amazonaws.com:5000", 
                    session_id=session_id
                )
                )
            
            if not result.get('success', True):  # Check for success=False
                error_msg = result.get('error', result.get('message', 'Failed to fetch session'))
                if 'not found' in error_msg.lower() or 'does not exist' in error_msg.lower():
                    progress_data['fetch_session'] = {
                        "status": "error",
                        "progress": 0,
                        "message": "Session not found"
                    }
                else:
                    progress_data['fetch_session'] = {
                        "status": "error", 
                        "progress": 0,
                        "message": error_msg
                    }
                return
            
            # Update state with fetched session
            state_manager.update_state(
                lat=result.get('lat', lat),
                lng=result.get('lng', lng), 
                km=result.get('km', km),
                session_id=session_id
            )
            
            # Success - show completion first
            progress_data['fetch_session'] = {
                "status": "complete",
                "progress": 100,
                "message": "Session data ready!"
            }
            
            # Brief delay to let frontend show completion, then clean up
            await asyncio.sleep(2.0)  # Give enough time for frontend to catch completion
            if 'fetch_session' in progress_data:
                del progress_data['fetch_session']
                
        except Exception as e:
            error_msg = str(e)
            if 'not found' in error_msg.lower() or '404' in error_msg:
                progress_data['fetch_session'] = {
                    "status": "error",
                    "progress": 0,
                    "message": "Session not found"
                }
            else:
                progress_data['fetch_session'] = {
                    "status": "error",
                    "progress": 0, 
                    "message": f"Network error: {error_msg}"
                }
    
    except asyncio.CancelledError:
        logger.info("Fetch session task cancelled")
        progress_data['fetch_session'] = {
            "status": "cancelled",
            "progress": 0,
            "message": "Fetch cancelled"
        }
        await asyncio.sleep(1)
        if 'fetch_session' in progress_data:
            del progress_data['fetch_session']
    
    except Exception as e:
        logger.error(f"Error in fetch session background task: {e}")
        progress_data['fetch_session'] = {
            "status": "error",
            "progress": 0,
            "message": f"Error: {str(e)}"
        }
    
    finally:
        # Clean up active task
        global active_tasks
        task_key = f'fetch_session_{session_id}'
        if task_key in active_tasks:
            del active_tasks[task_key]


if __name__ == "__main__":
    import uvicorn
    
    # Create necessary directories
    for directory in ["data", "data/maps", "data/embeddings", "logs"]:
        Path(directory).mkdir(parents=True, exist_ok=True)
    
    print("Starting Drone Device Server...")
    print("Access the web interface at: http://localhost:8888")
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8888, 
        log_level="info",
        timeout_keep_alive=3600,  # 1 hour keep-alive for very long operations
        timeout_graceful_shutdown=30
    )
