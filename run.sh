#!/bin/bash
"""
Drone Device Boot Script
========================
Orchestrates the complete drone system startup with tmux session management.
Runs localizer, listener, server, and reader in coordinated fashion.
"""

# Configuration
SESSION_NAME="drone_device"
DEVICE_DIR="/home/pavel/dev/drone-embeddings/device"
LOG_DIR="$DEVICE_DIR/logs"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"
}

success() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS:${NC} $1"
}

warn() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

# Cleanup function
cleanup() {
    log "Shutting down drone device system..."
    
    # Kill tmux session
    if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        tmux kill-session -t "$SESSION_NAME"
        success "Tmux session '$SESSION_NAME' terminated"
    fi
    
    # Kill any remaining processes
    pkill -f "python3.*localizer.py" 2>/dev/null
    pkill -f "python3.*listener.py" 2>/dev/null
    pkill -f "python3.*server.py" 2>/dev/null
    pkill -f "./reader" 2>/dev/null
    
    success "Drone device system shutdown complete"
    exit 0
}

# Setup signal handlers
trap cleanup SIGINT SIGTERM

# Check dependencies
check_dependencies() {
    log "Checking dependencies..."
    
    # Check tmux
    if ! command -v tmux &> /dev/null; then
        error "tmux is not installed. Please install tmux first."
        exit 1
    fi
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        error "python3 is not installed."
        exit 1
    fi
    
    # Check if reader binary exists
    if [ ! -f "$DEVICE_DIR/reader" ]; then
        log "Reader binary not found. Attempting to compile..."
        cd "$DEVICE_DIR"
        if ! g++ -std=c++17 -o reader reader.cpp; then
            error "Failed to compile reader.cpp"
            exit 1
        fi
        success "Reader compiled successfully"
    fi
    
    success "All dependencies satisfied"
}

# Setup environment
setup_environment() {
    log "Setting up environment..."
    
    cd "$DEVICE_DIR"
    
    # Create necessary directories
    mkdir -p "$LOG_DIR"
    mkdir -p "data/maps"
    mkdir -p "data/embeddings"
    mkdir -p "data/stream"
    
    # Initialize state file if it doesn't exist
    if [ ! -f "state.yaml" ]; then
        cat > state.yaml << EOF
session_id: ""
lat: null
lng: null
km: null
status: "idle"
last_updated: null
EOF
        log "Created initial state.yaml"
    fi
    
    success "Environment setup complete"
}

# Start tmux session
start_tmux_session() {
    log "Starting tmux session '$SESSION_NAME'..."
    
    # Kill existing session if it exists
    if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        warn "Existing session found. Terminating..."
        tmux kill-session -t "$SESSION_NAME"
    fi
    
    # Create new session
    tmux new-session -d -s "$SESSION_NAME" -c "$DEVICE_DIR"
    
    # Set up panes
    # Main window for reader (will wait for key press)
    tmux rename-window -t "$SESSION_NAME:0" "reader"
    
    # Create additional windows
    tmux new-window -t "$SESSION_NAME" -n "localizer" -c "$DEVICE_DIR"
    tmux new-window -t "$SESSION_NAME" -n "listener" -c "$DEVICE_DIR"
    tmux new-window -t "$SESSION_NAME" -n "server" -c "$DEVICE_DIR"
    tmux new-window -t "$SESSION_NAME" -n "logs" -c "$LOG_DIR"
    
    success "Tmux session created with 5 windows"
}

# Start services
start_services() {
    log "Starting drone services..."
    
    # 1. Start listener in listen mode (for responding to other drones)
    log "Starting listener in background listen mode..."
    tmux send-keys -t "$SESSION_NAME:listener" "python3 listener.py --listen 2>&1 | tee $LOG_DIR/listener.log" Enter
    sleep 2
    
    # 2. Start localizer
    log "Starting localizer..."
    tmux send-keys -t "$SESSION_NAME:localizer" "python3 localizer.py --local 2>&1 | tee $LOG_DIR/localizer.log" Enter
    sleep 2
    
    # 3. Start web server FIRST so UI is available during discovery
    log "Starting web server..."
    tmux send-keys -t "$SESSION_NAME:server" "python3 server.py 2>&1 | tee $LOG_DIR/server.log" Enter
    sleep 3
    
    # 4. Start discovery process through the web server API
    log "Initiating drone discovery through web interface..."
    # The discovery will be triggered via the web UI or API
    
    # 5. Show reader window and start reader (will wait for key press)
    log "Starting reader (will wait for key press)..."
    tmux send-keys -t "$SESSION_NAME:reader" "./reader 2>&1 | tee $LOG_DIR/reader.log" Enter
    
    # 6. Setup log monitoring
    tmux send-keys -t "$SESSION_NAME:logs" "tail -f $LOG_DIR/*.log" Enter
    
    success "All services started"
}

# Display status
show_status() {
    log "Drone Device System Status:"
    echo ""
    echo -e "${GREEN}Services Running:${NC}"
    echo "  - Localizer: TCP ports 18001-18003"
    echo "  - Listener: UDP ports 19001-19002"
    echo "  - Web Server: HTTP port 8888"
    echo "  - Reader: Waiting for key press"
    echo ""
    echo -e "${BLUE}Access Points:${NC}"
    echo "  - Web UI: http://localhost:8888"
    echo "  - Web UI (LAN): http://$(hostname -I | awk '{print $1}'):8888"
    echo ""
    echo -e "${YELLOW}Tmux Session: $SESSION_NAME${NC}"
    echo "  - reader: Main reader interface"
    echo "  - localizer: GPS processing service"
    echo "  - listener: Drone network communication"
    echo "  - server: Web interface server"
    echo "  - logs: Real-time log monitoring"
    echo ""
    echo -e "${GREEN}Commands:${NC}"
    echo "  - Attach to session: tmux attach -t $SESSION_NAME"
    echo "  - Switch windows: Ctrl+B + [0-4]"
    echo "  - Shutdown system: Ctrl+C (in this terminal)"
    echo ""
}

# Main execution
main() {
    echo -e "${BLUE}"
    echo "=================================================="
    echo "         Drone Device System Boot"
    echo "         Global UAV Localization"
    echo "=================================================="
    echo -e "${NC}"
    
    check_dependencies
    setup_environment
    start_tmux_session
    start_services
    
    show_status
    
    # Switch to reader window for manual control
    tmux select-window -t "$SESSION_NAME:reader"
    
    log "System ready. Press ENTER in the reader window to start processing."
    log "Use 'tmux attach -t $SESSION_NAME' to access the system."
    log "Press Ctrl+C here to shutdown the entire system."
    
    # Keep script running and monitor
    while true; do
        if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            warn "Tmux session lost. System may have crashed."
            break
        fi
        sleep 5
    done
}

# Check if running as source or executed
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
