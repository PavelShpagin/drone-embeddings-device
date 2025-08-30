#!/bin/bash

# Local AWS Server Test Script
# Starts the AWS server locally for testing device connectivity

set -e  # Exit on any error

AWS_PORT=5000
SERVER_DIR="../server"

# Cleanup function
cleanup() {
    echo ""
    echo "🛑 Stopping local AWS server..."
    
    if [ ! -z "$AWS_SERVER_PID" ]; then
        echo "  ☁️  Stopping AWS server (PID: $AWS_SERVER_PID)"
        kill $AWS_SERVER_PID 2>/dev/null || true
    fi
    
    # Kill any python processes in server directory
    pkill -f "python.*server.py" 2>/dev/null || true
    
    echo "✅ Local AWS server stopped"
    exit 0
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

echo "🧪 Starting Local AWS Server for Testing"
echo "📍 Port: $AWS_PORT"
echo "📁 Directory: $SERVER_DIR"
echo ""

# Check if server directory exists
if [ ! -d "$SERVER_DIR" ]; then
    echo "❌ Server directory not found: $SERVER_DIR"
    echo "   Make sure you're running this from the device/ directory"
    exit 1
fi

# Check if server.py exists
if [ ! -f "$SERVER_DIR/server.py" ]; then
    echo "❌ server.py not found in $SERVER_DIR"
    exit 1
fi

# Create logs directory if it doesn't exist
mkdir -p ../logs

# Function to wait for server to be ready
wait_for_aws_server() {
    local max_attempts=30
    local attempt=1
    
    echo "⏳ Waiting for AWS server to start..."
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s --connect-timeout 1 "http://localhost:$AWS_PORT/health" >/dev/null 2>&1; then
            echo "✅ AWS server is ready!"
            return 0
        fi
        
        echo "   Attempt $attempt/$max_attempts - waiting..."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo "❌ AWS server failed to start after $max_attempts attempts"
    return 1
}

# Start AWS server
echo "☁️  Starting AWS server..."
cd "$SERVER_DIR"
python server.py > ../logs/aws_server.log 2>&1 &
AWS_SERVER_PID=$!
cd - > /dev/null

# Wait for AWS server to be ready
if wait_for_aws_server; then
    echo ""
    echo "📋 AWS Server Status:"
    echo "   ☁️  AWS Server: http://localhost:$AWS_PORT    - PID: $AWS_SERVER_PID"
    echo "   🔌 WebSocket: ws://localhost:$AWS_PORT"
    echo "   📊 Health Check: http://localhost:$AWS_PORT/health"
    echo ""
    echo "🧪 Testing Server Health:"
    
    # Test health endpoint
    HEALTH_RESPONSE=$(curl -s "http://localhost:$AWS_PORT/health" 2>/dev/null || echo "ERROR")
    if [[ "$HEALTH_RESPONSE" == *"healthy"* ]]; then
        echo "   ✅ Health check: PASSED"
        echo "   📊 Response: $HEALTH_RESPONSE"
    else
        echo "   ❌ Health check: FAILED"
        echo "   📊 Response: $HEALTH_RESPONSE"
    fi
    
    echo ""
    echo "🎯 Ready for Device Testing:"
    echo "   • Start device server: ../run.sh --local"
    echo "   • Test WebSocket: Use browser at http://localhost:8888"
    echo "   • Manual API test: curl http://localhost:$AWS_PORT/health"
    echo ""
    echo "📝 Logs:"
    echo "   • AWS server: ../logs/aws_server.log"
    echo "   • Device server: ../logs/device_server.log"
    echo ""
    echo "🛑 Press Ctrl+C to stop AWS server"
    echo ""
    
    # Keep script running and wait for interruption
    wait $AWS_SERVER_PID
else
    echo "❌ Failed to start AWS server"
    echo "📝 Check logs: ../logs/aws_server.log"
    cleanup
    exit 1
fi
