#!/bin/bash
# start_voice.sh — Start LocusAI with Voice AI support
# Runs both the Flask web server and the WebSocket server for Retell

cd "$(dirname "$0")"

echo "=========================================="
echo "  LocusAI Voice Server Startup"
echo "=========================================="
echo ""

# Check if ports are available
check_port() {
    if lsof -i :$1 > /dev/null 2>&1; then
        echo "Warning: Port $1 is already in use"
        return 1
    fi
    return 0
}

check_port 5050
check_port 8080

echo "Starting Flask web server on port 5050..."
python3 -m flask --app dashboard run --host=0.0.0.0 --port=5050 &
FLASK_PID=$!

sleep 2

echo "Starting Voice WebSocket server on port 8080..."
python3 voice_ws.py &
WS_PID=$!

echo ""
echo "=========================================="
echo "  Servers Running"
echo "=========================================="
echo ""
echo "  Web Dashboard: http://localhost:5050"
echo "  Voice WebSocket: ws://localhost:8080"
echo ""
echo "  Flask PID: $FLASK_PID"
echo "  WebSocket PID: $WS_PID"
echo ""
echo "=========================================="
echo ""
echo "To expose for Retell (development):"
echo "  ngrok http 8080    # For WebSocket"
echo ""
echo "Then update your Retell agent with the ngrok URL."
echo ""
echo "Press Ctrl+C to stop both servers"
echo ""

# Handle cleanup
cleanup() {
    echo ""
    echo "Shutting down servers..."
    kill $FLASK_PID 2>/dev/null
    kill $WS_PID 2>/dev/null
    echo "Done."
    exit 0
}

trap cleanup SIGINT SIGTERM

# Wait for either process to exit
wait
