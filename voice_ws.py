# voice_ws.py — WebSocket server for Retell Custom LLM Integration
# This allows Retell to use LocusAI as the AI backend for voice calls,
# giving full access to our KB, booking system, customer data, and sentiment analysis.

import asyncio
import json
import logging
import os
import sys
from typing import Optional, Dict, Any

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import websockets
from websockets.server import WebSocketServerProtocol

from core.db import get_conn, log_message, get_business_by_id
from core.ai import process_message_for_voice
from core.voice import (
    get_voice_call,
    update_voice_call,
    extract_voice_booking,
    detect_booking_response,
    confirm_voice_booking,
    cancel_voice_booking,
    get_voice_pending_booking,
)
try:
    from core.kb import search_kb as kb_search
except ImportError:
    kb_search = None
from core.sentiment import analyze_sentiment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
WS_HOST = os.getenv("VOICE_WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("VOICE_WS_PORT", "8080"))
DEFAULT_BUSINESS_ID = int(os.getenv("DEFAULT_BUSINESS_ID", "9"))  # StyleCuts Hair Studio


class RetellLLMWebSocket:
    """Handles WebSocket connections from Retell for custom LLM responses."""

    def __init__(self):
        self.active_calls: Dict[str, Dict[str, Any]] = {}

    async def handle_connection(self, websocket: WebSocketServerProtocol):
        """Handle a new WebSocket connection from Retell."""
        call_id = None

        try:
            async for message in websocket:
                data = json.loads(message)
                response = await self.process_message(data, websocket)

                if response:
                    await websocket.send(json.dumps(response))

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Connection closed for call {call_id}")
        except Exception as e:
            logger.error(f"Error handling connection: {e}", exc_info=True)
        finally:
            if call_id and call_id in self.active_calls:
                del self.active_calls[call_id]

    async def process_message(self, data: Dict, websocket: WebSocketServerProtocol) -> Optional[Dict]:
        """Process incoming message from Retell."""

        interaction_type = data.get("interaction_type")

        if interaction_type == "call_details":
            # Initial call setup
            return await self.handle_call_details(data)

        elif interaction_type == "ping_pong":
            # Keep-alive
            return {"response_type": "ping_pong", "timestamp": data.get("timestamp")}

        elif interaction_type == "update_only":
            # Transcript update without needing response
            await self.handle_transcript_update(data)
            return None

        elif interaction_type == "response_required":
            # Retell needs an AI response
            return await self.handle_response_required(data, websocket)

        elif interaction_type == "reminder_required":
            # User hasn't spoken, need a reminder/prompt
            return await self.handle_reminder(data)

        else:
            logger.warning(f"Unknown interaction type: {interaction_type}")
            return None

    async def handle_call_details(self, data: Dict) -> Dict:
        """Handle initial call setup with call details."""
        call_id = data.get("call_id") or data.get("call", {}).get("call_id")

        logger.info(f"New call started: {call_id}")

        # Initialize call state
        self.active_calls[call_id] = {
            "call_id": call_id,
            "transcript": [],
            "business_id": None,
            "session_id": None,
            "state": {},
        }

        # Try to get call info from database
        voice_call = get_voice_call(call_id)
        if voice_call:
            self.active_calls[call_id]["business_id"] = voice_call.get("business_id")
            self.active_calls[call_id]["session_id"] = voice_call.get("session_id")

        # Return acknowledgment (Retell may not need a response here)
        return {
            "response_type": "config",
            "config": {
                "auto_reconnect": True,
                "call_details_received": True
            }
        }

    async def handle_transcript_update(self, data: Dict):
        """Handle transcript update (no response needed)."""
        call_id = data.get("call_id")
        transcript = data.get("transcript", [])

        if call_id in self.active_calls:
            self.active_calls[call_id]["transcript"] = transcript

    async def handle_response_required(self, data: Dict, websocket: WebSocketServerProtocol) -> Dict:
        """Handle request for AI response - this is where the magic happens."""
        call_id = data.get("call_id")
        transcript = data.get("transcript", [])

        # Get or initialize call state
        call_state = self.active_calls.get(call_id, {
            "call_id": call_id,
            "transcript": transcript,
            "business_id": None,
            "session_id": None,
            "state": {},
        })
        call_state["transcript"] = transcript
        self.active_calls[call_id] = call_state

        # Get the last user utterance
        last_user_message = None
        for item in reversed(transcript):
            if item.get("role") == "user":
                last_user_message = item.get("content", "")
                break

        if not last_user_message:
            return {
                "response_type": "response",
                "response_id": data.get("response_id", 0),
                "content": "",
                "content_complete": True
            }

        # Get business info
        business_id = call_state.get("business_id")
        session_id = call_state.get("session_id")

        # Try to get from voice_calls table if not in state
        if not business_id:
            voice_call = get_voice_call(call_id) if call_id else None
            if voice_call:
                business_id = voice_call.get("business_id")
                session_id = voice_call.get("session_id")
                call_state["business_id"] = business_id
                call_state["session_id"] = session_id
            else:
                # Use default business for test calls
                business_id = DEFAULT_BUSINESS_ID
                call_state["business_id"] = business_id
                logger.info(f"Using default business {business_id} for test call")

        # Check for pending booking confirmation
        pending = get_voice_pending_booking(call_id) if call_id else None
        if pending:
            response_type = detect_booking_response(last_user_message)
            if response_type == "confirm":
                success, message, appt_id = confirm_voice_booking(call_id, business_id, session_id)
                if success:
                    response_text = "Brilliant, your booking is confirmed! You'll receive a confirmation text shortly. Is there anything else I can help you with?"
                else:
                    response_text = f"I'm sorry, I couldn't complete that booking: {message}. Would you like to try a different time?"

                return self._create_response(data, response_text)

            elif response_type == "cancel":
                cancel_voice_booking(call_id)
                response_text = "No problem, I've cancelled that. Would you like to look at a different time, or is there something else I can help with?"
                return self._create_response(data, response_text)

        # Get business data for AI processing
        business_data = None
        if business_id:
            business_data = get_business_by_id(business_id)

        if not business_data:
            # Fallback response if no business context
            response_text = "I'm sorry, I'm having trouble accessing the system right now. Could you please call back in a moment?"
            return self._create_response(data, response_text)

        # Process through LocusAI with full KB, sentiment, booking support
        try:
            state = call_state.get("state", {})
            state["session_id"] = session_id
            state["channel"] = "voice"
            state["call_id"] = call_id

            # Add conversation history from transcript (OpenAI format)
            history = []
            for item in transcript[:-1]:  # Exclude last message (current)
                role = "user" if item.get("role") == "user" else "assistant"
                content = item.get("content", "")
                if content:
                    history.append({"role": role, "content": content})
            state["history"] = history

            # Get AI response using our full system
            ai_response = process_message_for_voice(
                user_input=last_user_message,
                business_data=business_data,
                state=state
            )

            # Check for booking in response
            cleaned_response, booking_data = extract_voice_booking(ai_response, call_id)

            if booking_data:
                update_voice_call(call_id, booking_discussed=1)

            # Log messages
            if session_id:
                log_message(session_id, "user", last_user_message)
                log_message(session_id, "bot", cleaned_response)

            # Update state
            call_state["state"] = state

            # Stream the response back
            return await self._stream_response(data, cleaned_response, websocket)

        except Exception as e:
            logger.error(f"Error processing voice message: {e}", exc_info=True)
            return self._create_response(
                data,
                "I'm sorry, I'm having a bit of trouble right now. Could you repeat that?"
            )

    async def handle_reminder(self, data: Dict) -> Dict:
        """Handle reminder when user hasn't spoken."""
        return self._create_response(
            data,
            "Are you still there? Is there anything I can help you with?"
        )

    def _create_response(self, data: Dict, content: str) -> Dict:
        """Create a simple response object."""
        return {
            "response_type": "response",
            "response_id": data.get("response_id", 0),
            "content": content,
            "content_complete": True
        }

    async def _stream_response(self, data: Dict, content: str, websocket: WebSocketServerProtocol) -> Dict:
        """Stream response word by word for more natural speech.

        Retell can start speaking before the full response is received,
        making the conversation feel more natural.
        """
        response_id = data.get("response_id", 0)

        # Split into chunks (phrases/sentences for natural pacing)
        # Split on punctuation to maintain natural pauses
        import re
        chunks = re.split(r'(?<=[.!?,])\s+', content)
        chunks = [c for c in chunks if c.strip()]

        if len(chunks) <= 1:
            # Short response, send all at once
            return {
                "response_type": "response",
                "response_id": response_id,
                "content": content,
                "content_complete": True
            }

        # Stream chunks
        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)

            response = {
                "response_type": "response",
                "response_id": response_id,
                "content": chunk + (" " if not is_last else ""),
                "content_complete": is_last
            }

            await websocket.send(json.dumps(response))

            if not is_last:
                # Small delay between chunks for natural pacing
                await asyncio.sleep(0.05)

        # Return None since we already sent everything
        return None


async def main():
    """Start the WebSocket server."""
    handler = RetellLLMWebSocket()

    logger.info(f"Starting Retell LLM WebSocket server on ws://{WS_HOST}:{WS_PORT}")

    async with websockets.serve(
        handler.handle_connection,
        WS_HOST,
        WS_PORT,
        ping_interval=20,
        ping_timeout=20,
    ):
        logger.info(f"WebSocket server running on ws://{WS_HOST}:{WS_PORT}")
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped")
