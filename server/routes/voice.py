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
    from intelligence.tts_engine import speak_async, speak_fast

    audio = await speak_fast(body.text)
    if body.mac_speaker:
        asyncio.create_task(speak_async(body.text))

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"X-Text-Length": str(len(body.text))},
    )


@router.post("/voice/transcribe")
async def transcribe_audio(request: Request, _auth: dict = Depends(require_auth)):
    from intelligence.stt_engine import transcribe_async
    audio_bytes = await request.body()
    transcript  = await transcribe_async(audio_bytes, fmt="webm")
    return {"transcript": transcript}


@router.post("/voice/ask")
async def ask(body: AskBody, _auth: dict = Depends(require_auth)):
    from intelligence.conversation_router import route_and_respond
    from intelligence.tts_engine import speak_fast  # noqa: F401

    response = await route_and_respond(body.text, speak=False)
    audio    = await speak_fast(response)

    return {
        "input":     body.text,
        "response":  response,
        "audio_b64": __import__("base64").b64encode(audio).decode() if audio else "",
    }


# ── Full-duplex WebSocket ─────────────────────────────────────────────────────

@router.websocket("/ws/voice")
async def voice_ws(ws: WebSocket):
    await ws.accept()
    log.info("voice_ws_connected")

    async def broadcast(data: dict):
        try:
            await ws.send_text(json.dumps(data))
        except Exception:
            pass

    try:
        while True:
            raw   = await ws.receive_text()
            msg   = json.loads(raw)
            type_ = msg.get("type")

            if type_ == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
                continue

            if type_ == "text":
                content = msg.get("content", "").strip()
                if not content:
                    continue

                await ws.send_text(json.dumps({"type": "thinking"}))

                from intelligence.conversation_router import route_and_respond
                from intelligence.tts_engine import speak_fast  # noqa: F401
                import base64

                response = await route_and_respond(content, broadcast_fn=broadcast, speak=False)
                audio    = await speak_fast(response)

                await ws.send_text(json.dumps({
                    "type":      "response",
                    "text":      response,
                    "audio_b64": base64.b64encode(audio).decode() if audio else "",
                }))

            elif type_ == "audio":
                import base64
                import re as _re
                from intelligence.stt_engine import transcribe_async

                audio_bytes = base64.b64decode(msg.get("data", ""))
                transcript  = await transcribe_async(audio_bytes, fmt="webm")

                if not transcript:
                    await ws.send_text(json.dumps({"type": "transcript_empty"}))
                    continue

                await ws.send_text(json.dumps({"type": "transcript", "text": transcript}))
                await ws.send_text(json.dumps({"type": "thinking"}))

                from intelligence.conversation_router import route_and_respond
                from intelligence.tts_engine import speak_fast  # noqa: F401
                import base64 as _b64

                # Get full response (no Mac speaker — browser handles audio)
                response = await route_and_respond(transcript, broadcast_fn=broadcast, speak=False)

                # ── Sentence streaming — Phase 7 ──────────────────────────────
                # Split into sentences and stream audio chunk-by-chunk so the
                # first sentence plays within ~200ms of the response being ready.
                sentences = [s.strip() for s in _re.split(r"(?<=[.!?])\s+", response.strip()) if s.strip()]
                if not sentences:
                    sentences = [response]

                for idx, sentence in enumerate(sentences):
                    chunk_audio = await speak_fast(sentence)
                    await ws.send_text(json.dumps({
                        "type":      "audio_chunk",
                        "text":      sentence,
                        "audio_b64": _b64.b64encode(chunk_audio).decode() if chunk_audio else "",
                        "index":     idx,
                        "total":     len(sentences),
                        "final":     idx == len(sentences) - 1,
                    }))

                # Also emit the full response text for the live feed
                await ws.send_text(json.dumps({
                    "type": "response",
                    "text": response,
                    "audio_b64": "",   # audio already streamed as chunks
                }))

    except WebSocketDisconnect:
        log.info("voice_ws_disconnected")
    except Exception as e:
        log.warn("voice_ws_error", error=str(e))
