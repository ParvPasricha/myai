"""
Voice routes — Jarvis speaks and listens.

POST /voice/speak        — text → Jarvis speaks on Mac + returns MP3 bytes
POST /voice/transcribe   — audio bytes → Whisper transcript (local faster-whisper)
POST /voice/ask          — full pipeline: audio in → Jarvis thinks → speaks + returns text
WS   /ws/voice           — full-duplex: send audio frames, receive spoken responses
"""
import asyncio
import json

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

from server.auth import require_auth
from observability.logger import log

router = APIRouter()


class SpeakBody(BaseModel):
    text: str
    mac_speaker: bool = True   # also play through Mac speakers


class AskBody(BaseModel):
    text: str                  # use this OR transcribe from audio


@router.post("/voice/speak")
async def speak(body: SpeakBody, _auth: dict = Depends(require_auth)):
    from intelligence.tts_engine import speak_async, speak_to_bytes_async

    audio = await speak_to_bytes_async(body.text)
    if body.mac_speaker:
        asyncio.create_task(speak_async(body.text))

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"X-Text-Length": str(len(body.text))},
    )


@router.post("/voice/transcribe")
async def transcribe_audio(request: Request, _auth: dict = Depends(require_auth)):
    from fastapi import Request
    from intelligence.stt_engine import transcribe_async
    audio_bytes = await request.body()
    transcript  = await transcribe_async(audio_bytes, fmt="wav")
    return {"transcript": transcript}


@router.post("/voice/ask")
async def ask(body: AskBody, _auth: dict = Depends(require_auth)):
    from intelligence.jarvis_core import think
    from intelligence.tts_engine import speak_to_bytes_async

    response = await think(body.text, speak=True)
    audio    = await speak_to_bytes_async(response)

    return {
        "input":    body.text,
        "response": response,
        "audio_b64": __import__("base64").b64encode(audio).decode() if audio else "",
    }


# ── Full-duplex WebSocket ─────────────────────────────────────────────────────

@router.websocket("/ws/voice")
async def voice_ws(ws: WebSocket):
    await ws.accept()
    log.info("voice_ws_connected")

    try:
        while True:
            # Expect JSON: {"type": "text", "content": "..."} or {"type": "audio", "data": "<b64>"}
            raw  = await ws.receive_text()
            msg  = json.loads(raw)
            type_ = msg.get("type")

            if type_ == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
                continue

            if type_ == "text":
                content = msg.get("content", "").strip()
                if not content:
                    continue

                await ws.send_text(json.dumps({"type": "thinking"}))

                from agents.head_agent import handle as jarvis_handle
                from intelligence.tts_engine import speak_to_bytes_async
                import base64

                async def broadcast(data: dict):
                    try:
                        await ws.send_text(json.dumps(data))
                    except Exception:
                        pass

                response = await jarvis_handle(content, broadcast_fn=broadcast, speak=True)
                audio    = await speak_to_bytes_async(response)

                await ws.send_text(json.dumps({
                    "type":     "response",
                    "text":     response,
                    "audio_b64": base64.b64encode(audio).decode() if audio else "",
                }))

            elif type_ == "audio":
                import base64
                from intelligence.stt_engine import transcribe_async

                audio_bytes = base64.b64decode(msg.get("data", ""))
                transcript  = await transcribe_async(audio_bytes, fmt="wav")

                if not transcript:
                    await ws.send_text(json.dumps({"type": "transcript_empty"}))
                    continue

                await ws.send_text(json.dumps({"type": "transcript", "text": transcript}))

                from agents.head_agent import handle as jarvis_handle
                from intelligence.tts_engine import speak_to_bytes_async
                import base64 as _b64

                async def broadcast(data: dict):
                    try:
                        await ws.send_text(json.dumps(data))
                    except Exception:
                        pass

                response = await jarvis_handle(transcript, broadcast_fn=broadcast, speak=True)
                audio_out = await speak_to_bytes_async(response)

                await ws.send_text(json.dumps({
                    "type":     "response",
                    "text":     response,
                    "audio_b64": _b64.b64encode(audio_out).decode() if audio_out else "",
                }))

    except WebSocketDisconnect:
        log.info("voice_ws_disconnected")
    except Exception as e:
        log.warn("voice_ws_error", error=str(e))
