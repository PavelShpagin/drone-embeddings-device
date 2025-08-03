# Device Submodule

Local device-side satellite embedding processing with UDP communication.

## Architecture

The device submodule provides real-time GPS localization by processing camera stream images against pre-computed satellite embeddings. It consists of two main components:

### Components

**1. localizer.py** - Python UDP server
- Serves as adapter between UDP sockets and server library functions
- Handles three endpoints: init_map, fetch_gps, visualize_path
- Reuses code from `../server/src` via Python path manipulation
- Runs on ports 8001, 8002, 8003

**2. reader.cpp** - C++ UDP client  
- Processes image stream from `data/stream/`
- Non-blocking socket communication with localizer
- Logs GPS results to `data/reader.log`
- 1ms loop cycle for real-time performance

### Data Flow

```
Stream Images → reader.cpp → UDP → localizer.py → Server Functions → GPS Results
```

1. **Initialization**: reader.cpp sends init_map request to localizer.py
2. **Processing Loop**: For each stream image:
   - reader.cpp sends fetch_gps request with image path
   - localizer.py processes via server functions
   - GPS coordinates returned and logged
3. **Non-blocking**: reader.cpp checks sockets every 1ms iteration

## Directory Structure

```
device/
├── localizer.py          # UDP server adapter
├── reader.cpp           # C++ stream processor
├── src/                 # Empty (imports from ../server/src)
├── data/
│   ├── stream/          # Input image stream
│   ├── maps/            # Cached satellite maps
│   ├── embeddings/      # Cached patch embeddings
│   ├── server_paths/    # Path visualizations
│   └── reader.log       # GPS output log
└── README.md           # This documentation
```

## Code Reuse Strategy

The device reuses server code via Python path manipulation:
```python
sys.path.append('../server/src')
from server_core import SatelliteEmbeddingServer
```

This approach is:
- Git-friendly (no symlink issues)
- Cross-platform compatible
- Maintains single source of truth

## Usage

### 1. Start Localizer
```bash
cd device
python localizer.py
```

### 2. Compile and Run Reader
```bash
cd device
g++ -std=c++17 reader.cpp -o reader
./reader
```

### 3. Monitor Results
```bash
tail -f data/reader.log
```

## UDP Protocol

### Ports
- **8001**: init_map endpoint
- **8002**: fetch_gps endpoint  
- **8003**: visualize_path endpoint

### Message Format
JSON strings over UDP:

**init_map request:**
```json
{
    "lat": 50.4162,
    "lng": 30.8906, 
    "meters": 1000,
    "mode": "device"
}
```

**fetch_gps request:**
```json
{
    "session_id": "abc123",
    "image_path": "data/stream/frame001.jpg"
}
```

**Response format:**
```json
{
    "success": true,
    "session_id": "abc123",
    "gps": {"lat": 50.416, "lng": 30.891}
}
```

## Dependencies

### Python (localizer.py)
- Standard library only
- Imports from ../server/src

### C++ (reader.cpp)
- C++17 filesystem support
- POSIX sockets (Linux/macOS)
- Standard library threading

## Compilation

```bash
# Linux/macOS
g++ -std=c++17 reader.cpp -o reader

# With debugging
g++ -std=c++17 -g -O0 reader.cpp -o reader
```

## Performance

- **Loop cycle**: 1ms as specified
- **Non-blocking**: reader.cpp never blocks on socket operations
- **Concurrent**: localizer.py handles multiple endpoints simultaneously
- **Memory efficient**: Images passed by file path, not raw data

## Logging

All GPS results logged to `data/reader.log`:
```
DeviceReader started at Mon Jan 1 12:00:00 2024
Session initialized: abc123
Frame 0: {"success": true, "gps": {"lat": 50.416, "lng": 30.891}}
Frame 1: {"success": true, "gps": {"lat": 50.417, "lng": 30.892}}
```

## Testing

1. Place test images in `data/stream/`
2. Start localizer: `python localizer.py`
3. Run reader: `./reader` 
4. Check log: `cat data/reader.log`

## Notes

- reader.cpp expects localizer.py to be running first
- Stream images processed in alphabetical order
- Session persists until reader.cpp restarts
- UDP provides fast, lightweight communication
- All paths relative to device/ directory