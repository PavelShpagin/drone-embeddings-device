# Device Submodule

Real-time GPS localization system with server integration and local processing.

## Architecture

The device submodule enables real-time GPS localization by integrating with the main server for initialization and performing local processing for GPS matching.

### Components

**1. localizer.py** - Python TCP server

- Acts as adapter between TCP sockets and server library functions
- Calls main server HTTP API for `init_map`, processes `fetch_gps` locally
- Handles three endpoints: init_map (18001), fetch_gps (18002), visualize_path (18003)
- Reuses code from `../server/src` via copied modules in `src/`
- Caches map data and embeddings locally for fast processing

**2. reader.cpp** - C++ TCP client

- Processes image stream from `data/stream/`
- Non-blocking socket communication with localizer
- Logs GPS results to `data/reader.txt`
- 1ms loop cycle for real-time performance

**3. init_map_wrapper.py** - HTTP client

- Calls server `init_map` endpoint to get session data
- Stores full map and embeddings locally in device data folders
- Enables device to work offline after initialization

### Code Reuse Strategy

The device reuses server code through copied modules:

```
device/src/
├── general/          # Copy of server/src/general (shared modules)
└── device/           # Device-specific modules
    └── init_map_wrapper.py
```

This approach enables easy push/pull synchronization while maintaining modularity.

### Data Flow

#### Initialization (Server Integration)

```
reader.cpp → localizer.py → HTTP → server:5000 → cached locally
```

#### GPS Processing (Local)

```
Stream Images → reader.cpp → TCP → localizer.py → local embeddings → GPS Results
```

## Protocol Details

### TCP Communication

**Ports:**

- 18001: init_map endpoint
- 18002: fetch_gps endpoint
- 18003: visualize_path endpoint (unused in server mode)

**Message Format:**

- Size-prefixed messages for reliable large data transfer
- JSON serialization for structured data
- Base64 encoding for binary image data

### init_map Flow

1. reader.cpp sends: `{"lat": 50.4162, "lng": 30.8906, "meters": 1000, "mode": "server"}`
2. localizer.py calls server HTTP API with `mode=device` to get full data
3. localizer.py caches map in `data/maps/`, embeddings in `data/embeddings/`
4. localizer.py returns: `{"success": true, "session_id": "..."}`
5. reader.cpp receives session_id and starts processing

### fetch_gps Flow

1. reader.cpp sends: `{"session_id": "...", "image_path": "data/stream/1000.jpg"}`
2. localizer.py loads cached embeddings and processes image locally
3. localizer.py returns: `{"success": true, "gps": {"lat": ..., "lng": ...}, ...}`
4. reader.cpp logs GPS coordinates to `data/reader.txt`

## Local Storage

Device maintains same data structure as server:

```
device/data/
├── maps/            # Full satellite maps (session_id.pkl)
├── embeddings/      # Patch embeddings (session_id.json)
├── server_paths/    # Path visualizations (session_id.jpg)
├── sessions.pkl     # Session metadata
├── reader.txt       # GPS coordinate log
└── stream/          # Input images (1000.jpg, 1001.jpg, ...)
```

## Performance Benefits

- **Offline Operation**: Once initialized, device works without server connection
- **Fast Processing**: Local embeddings enable ~50ms GPS matching
- **Reliability**: TCP ensures large data transfers complete successfully
- **Real-time**: C++ reader processes images as fast as they arrive

## Setup and Testing

### Prerequisites

- Python 3.8+ with same dependencies as server
- C++ compiler (g++)
- Compiled reader executable

### Quick Start

```bash
# Terminal 1: Start main server (from project root)
python server/app.py --port 5000

# Terminal 2: Start device localizer
cd device
python localizer.py

# Terminal 3: Start reader
cd device
./reader
```

### Compilation

```bash
cd device
g++ -o reader reader.cpp -std=c++17
```

### Monitoring

```bash
# Watch GPS coordinates in real-time
tail -f data/reader.txt

# Monitor system status
tmux capture-pane -t localizer -p
tmux capture-pane -t reader -p
```

## Configuration

### Server Integration

- Default server URL: `http://localhost:5000`
- Configurable in `init_map_wrapper.py`
- Uses `mode=device` to get full data, `mode=server` for reader requests

### TCP Settings

- High port numbers (18001-18003) avoid conflicts
- Size-prefixed messages handle large transfers
- Non-blocking reads in reader.cpp prevent blocking

### Performance Tuning

- Stream processing: processes all images in `data/stream/`
- Loop delay: 1ms for real-time responsiveness
- Memory efficiency: file-based storage, not in-memory caching

## Troubleshooting

### Port Conflicts

```bash
# Kill all tmux sessions
tmux kill-server

# Check port usage
ss -tuln | grep -E "18001|18002|18003"
```

### Import Errors

- Ensure all server modules copied to `device/src/`
- Check Python path setup in localizer.py

### Connection Issues

- Verify server running on port 5000
- Check TCP connectivity between reader and localizer
- Monitor tmux session outputs for error messages

### Data Issues

- Verify stream images exist in `data/stream/`
- Check session data cached in `data/sessions.pkl`
- Ensure proper permissions on data directories

## Integration with Main System

The device submodule integrates seamlessly with the main drone embeddings system:

1. **Initialization**: Uses server infrastructure for map generation
2. **Processing**: Leverages cached embeddings for fast local GPS matching
3. **Storage**: Maintains compatible data formats for interoperability
4. **Monitoring**: GPS logs compatible with visualization tools

This design enables scalable deployment where multiple devices can initialize from a central server and then operate independently for real-time localization.
