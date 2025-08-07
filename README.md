# Drone Device Client

Real-time GPS localization client for drone devices.

## Quick Start

### Connect to Remote Server (Default)

```bash
cd device
python localizer.py &
./reader
```

### Connect to Local Server

```bash
cd device
python localizer.py --local &
./reader
```

## Key Features

- **Remote Server Integration**: Uses AWS server by default for map initialization
- **Local Processing**: Fast GPS matching using cached embeddings on device
- **Automatic Path Visualization**: Red dot path images created during GPS processing
- **TCP Communication**: Reliable data transfer between C++ reader and Python localizer
- **Real-time Stream Processing**: Processes drone camera images continuously

## Architecture

```
┌─────────────┐    TCP     ┌─────────────────┐    HTTP    ┌──────────────┐
│ reader.cpp  │────────────│ localizer.py    │────────────│ Remote Server│
│ (C++ client)│ 18001-3    │ (Python adapter)│     5000   │ (AWS/Local)  │
└─────────────┘            └─────────────────┘            └──────────────┘
       │                           │                              │
       │ Image Stream              │ Local Cache                  │ Map Data
       ▼                           ▼                              ▼
┌─────────────┐            ┌─────────────────┐            ┌──────────────┐
│data/stream/ │            │data/sessions.pkl│            │Satellite Maps│
└─────────────┘            └─────────────────┘            └──────────────┘
```

## Data Flow

1. **Init Map**: Remote server call → Download map/embeddings → Store locally
2. **Stream Processing**: reader.cpp reads images → Sends to localizer.py
3. **GPS Processing**: Local fetch_gps → GPS coordinates + Path visualization
4. **Path Updates**: Red dot images saved in `data/server_paths/`

## TCP Ports

- **18001**: init_map requests
- **18002**: fetch_gps requests
- **18003**: visualize_path requests

## Requirements

- Python 3.9+ with torch, numpy, PIL
- C++ compiler (g++)
- Network access to remote server
- CUDA-capable GPU (recommended)

## Build & Run

```bash
# Compile C++ reader
g++ -o reader reader.cpp

# Start localizer (remote server default)
python localizer.py &

# Or use local server
python localizer.py --local &

# Run reader
./reader
```

## Output

- **GPS coordinates**: Written to `data/reader.txt`
- **Path visualizations**: Saved in `data/server_paths/`
- **Session data**: Cached in `data/sessions.pkl`
