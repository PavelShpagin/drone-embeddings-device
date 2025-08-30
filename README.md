# Drone Device System

A comprehensive drone device management system with web UI for Global UAV Localization. This system provides a complete infrastructure for drone coordination, map data management, and real-time processing.

## Features

- **Web-based Control Interface**: Modern UI with Google Maps integration
- **Drone Network Discovery**: Automatic discovery and coordination between drones
- **Session Management**: Share map data between drones to avoid redundant downloads
- **Real-time Processing**: Stream-based image processing with GPS localization
- **Progress Tracking**: Live progress updates for all operations
- **Log Management**: Automatic log collection and transmission

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Web Browser   │    │   Other Drones  │    │   AWS Server    │
│   (Port 8000)   │    │   (UDP 19001)   │    │   (HTTP API)    │
└─────────┬───────┘    └─────────┬───────┘    └─────────┬───────┘
          │                      │                      │
          │ HTTP                 │ UDP                  │ HTTP
          │                      │                      │
┌─────────▼──────────────────────▼──────────────────────▼───────┐
│                     Drone Device System                       │
├─────────────────┬─────────────────┬─────────────────┬─────────┤
│   FastAPI       │   Listener      │   Localizer     │ Reader  │
│   Server        │   (Discovery)   │   (Processing)  │ (Stream)│
│   (Port 8000)   │   (UDP 19001)   │   (TCP 18001)   │ (C++)   │
└─────────────────┴─────────────────┴─────────────────┴─────────┘
          │                      │                      │
          ▼                      ▼                      ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   state.yaml    │    │   Local Cache   │    │   Stream Data   │
│   (Device State)│    │   (Maps/Embed)  │    │   (Images)      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Quick Start

### Prerequisites

- Ubuntu/Debian Linux system
- Python 3.8+
- tmux
- g++ compiler
- Internet connection

### Installation

1. **Install dependencies:**

   ```bash
   cd /home/pavel/dev/drone-embeddings/device
   pip install -r requirements.txt
   ```

2. **Compile reader:**

   ```bash
   g++ -std=c++17 -o reader reader.cpp
   ```

3. **Run system test:**
   ```bash
   python3 test_system.py
   ```

### Usage

1. **Start the complete system:**

   ```bash
   ./run.sh
   ```

2. **Access the web interface:**

   - Local: http://localhost:8000
   - LAN: http://YOUR_IP:8000

3. **Control the system:**

   - Use the web UI to select coordinates and start missions
   - Press ENTER in the reader window to start image processing
   - Monitor logs in the tmux session

4. **Shutdown:**
   - Press Ctrl+C in the main terminal
   - Or: `tmux kill-session -t drone_device`

## Components

### 1. Web Interface (`server.py`)

**Features:**

- Interactive Google Maps for coordinate selection
- Real-time progress tracking
- Drone state monitoring
- Log management
- Session coordination

**API Endpoints:**

- `GET /` - Main web interface
- `GET /api/state` - Get current drone state
- `POST /api/init_map` - Initialize map for coordinates
- `POST /api/send_logs` - Send logs to server
- `POST /api/clear_state` - Clear all state
- `POST /api/abort` - Abort current operation

### 2. Network Listener (`listener.py`)

**Features:**

- UDP broadcast discovery of other drones
- Session sharing between drones
- Automatic map data retrieval from cache
- Background listening for new drone requests

**Modes:**

- **Discovery Mode**: Broadcasts for 30 seconds looking for other drones
- **Listen Mode**: Responds to discovery requests from other drones

### 3. Localizer (`localizer.py`)

**Features:**

- TCP-based communication with reader
- GPS processing using embeddings
- Session management
- Real-time image localization

**Ports:**

- 18001: init_map requests
- 18002: fetch_gps requests
- 18003: visualize_path requests

### 4. Reader (`reader.cpp`)

**Features:**

- Key-press activation
- Stream-based image processing
- TCP communication with localizer
- Real-time GPS coordinate output

### 5. State Management (`state.yaml`)

**Structure:**

```yaml
session_id: "session_1234567890"
lat: 50.4162
lng: 30.8906
km: 5
status: "ready"
last_updated: "2024-01-01T12:00:00"
```

## Operation Flow

### Mission Initialization

1. **Drone Startup:**

   ```bash
   ./run.sh
   ```

2. **Discovery Phase:**

   - Listener broadcasts to LAN looking for other drones
   - If found: Downloads shared session data
   - If not found: Continues to manual setup

3. **Manual Setup (if no other drones):**

   - Open web interface
   - Select coordinates on map
   - Set coverage area (km)
   - Click "Submit Mission"

4. **Processing Phase:**
   - Press ENTER in reader window
   - System processes stream images
   - Real-time GPS coordinates displayed

### Multi-Drone Coordination

1. **First Drone:**

   - Runs discovery (finds nothing)
   - User configures mission via web UI
   - System downloads and caches map data

2. **Additional Drones:**
   - Run discovery (finds first drone)
   - Automatically receive shared session
   - Download cached map data
   - Ready for processing

## File Structure

```
device/
├── run.sh                 # Main startup script
├── server.py              # Web interface server
├── listener.py            # Network discovery
├── localizer.py           # GPS processing
├── reader.cpp             # Stream processor
├── state.yaml             # Device state
├── requirements.txt       # Python dependencies
├── test_system.py         # System tests
├── README.md              # This file
├── server/
│   └── favicon.png        # Web UI logo
├── data/
│   ├── maps/              # Cached map tiles
│   ├── embeddings/        # Cached embeddings
│   ├── stream/            # Input images
│   └── sessions.pkl       # Session metadata
└── logs/                  # System logs
    ├── server.log
    ├── listener.log
    ├── localizer.log
    └── reader.log
```

## Configuration

### Network Ports

- **Web Server**: 8000 (HTTP)
- **Localizer**: 18001-18003 (TCP)
- **Listener**: 19001-19002 (UDP)

### Environment Variables

None required - all configuration is automatic.

### Server Configuration

Default AWS server: `http://ec2-16-171-238-14.eu-north-1.compute.amazonaws.com:5000`

To use local server:

```bash
python3 localizer.py --local
```

## Troubleshooting

### Common Issues

1. **"tmux not found"**

   ```bash
   sudo apt-get install tmux
   ```

2. **"g++ not found"**

   ```bash
   sudo apt-get install build-essential
   ```

3. **"Permission denied on ./run.sh"**

   ```bash
   chmod +x run.sh
   ```

4. **"Port already in use"**

   ```bash
   tmux kill-session -t drone_device
   # Wait a few seconds, then restart
   ```

5. **"Cannot connect to server"**
   - Check internet connection
   - Verify server URL in localizer.py
   - Try local server mode

### Log Analysis

Monitor real-time logs:

```bash
tmux attach -t drone_device
# Use Ctrl+B + 4 to switch to logs window
```

Individual log files:

```bash
tail -f logs/server.log     # Web server
tail -f logs/listener.log   # Network discovery
tail -f logs/localizer.log  # GPS processing
tail -f logs/reader.log     # Stream processing
```

### Network Issues

1. **Discovery not working:**

   - Check firewall settings
   - Ensure UDP ports 19001-19002 are open
   - Verify all drones are on same LAN

2. **Web UI not accessible:**
   - Check if port 8000 is blocked
   - Try: `netstat -tlnp | grep 8000`

## Development

### Testing

Run comprehensive tests:

```bash
python3 test_system.py
```

### Adding Features

1. **New API Endpoints**: Add to `server.py`
2. **Network Protocols**: Modify `listener.py`
3. **Processing Logic**: Update `localizer.py`
4. **Stream Handling**: Modify `reader.cpp`

### Debugging

Enable verbose logging:

```bash
export PYTHONPATH=/home/pavel/dev/drone-embeddings/device/src
python3 -u server.py  # or other components
```

## Security Notes

- System runs on local network only
- No authentication implemented (suitable for isolated drone networks)
- Logs may contain sensitive location data
- Use VPN or isolated networks for sensitive operations

## Performance

- **Concurrent Drones**: Up to 10 recommended per LAN
- **Processing Rate**: ~1 FPS per drone
- **Memory Usage**: ~2GB per drone (with embeddings)
- **Network Bandwidth**: ~1MB/s during initial download

## Support

For issues or questions:

1. Check troubleshooting section
2. Review log files
3. Run system tests
4. Check tmux session status: `tmux list-sessions`
