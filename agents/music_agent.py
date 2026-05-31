"""
Music Agent — Apple Music control + mood-based selection.

Uses AppleScript to control Music.app.
Mood engine reads screen monitor + brain state to pick the right vibe.
"""
import asyncio
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from intelligence.mac_controller import run_applescript_async
from observability.logger import log

_MOOD_MAP = {
    "coding":    "focus",
    "writing":   "ambient",
    "meeting":   "calm",
    "reading":   "ambient",
    "planning":  "calm",
    "designing": "creative",
    "break":     "chill",
    "energy":    "hype",
    "late_night":"chill",
}

_PLAYLIST_SEARCH = {
    "focus":    ["Focus", "Deep Work", "Lo-Fi", "Study"],
    "ambient":  ["Ambient", "Instrumental", "Background"],
    "calm":     ["Calm", "Soft", "Jazz", "Piano"],
    "creative": ["Creative", "Indie", "Flow"],
    "chill":    ["Chill", "Evening", "Relax"],
    "hype":     ["Energy", "Workout", "Hype", "Upbeat"],
}


async def _get_playlists() -> list[str]:
    script = 'tell application "Music" to get name of playlists'
    try:
        result = await run_applescript_async(script)
        return [p.strip() for p in result.split(",") if p.strip()]
    except Exception:
        return []


async def _play_playlist(name: str) -> bool:
    script = f'tell application "Music" to play playlist "{name}"'
    try:
        await run_applescript_async(script)
        return True
    except Exception:
        return False


async def _play_by_mood(mood: str) -> str:
    playlists = await _get_playlists()
    keywords  = _PLAYLIST_SEARCH.get(mood, ["music"])
    for kw in keywords:
        for pl in playlists:
            if kw.lower() in pl.lower():
                if await _play_playlist(pl):
                    return pl
    # Fallback: just play the library
    await run_applescript_async('tell application "Music" to play')
    return "library"


async def _current_track() -> dict:
    script = """
tell application "Music"
    if player state is playing then
        set t to current track
        return name of t & " — " & artist of t
    else
        return "nothing playing"
    end if
end tell
"""
    try:
        result = await run_applescript_async(script)
        return {"playing": True, "track": result}
    except Exception:
        return {"playing": False, "track": ""}


async def _infer_mood() -> str:
    """Read screen monitor + brain state to infer best music mood."""
    try:
        from intelligence.brain_state import get_current_state
        state = get_current_state()
        activity = state.get("activity", "").lower()
        for key in _MOOD_MAP:
            if key in activity:
                return _MOOD_MAP[key]
    except Exception:
        pass
    return "focus"   # safe default


class MusicAgent(BaseAgent):
    name = "music"
    capabilities = ["music"]

    async def run(self, task: AgentTask) -> AgentResult:
        action  = task.payload.get("action", "play_mood")
        mood    = task.payload.get("mood", "")
        playlist= task.payload.get("playlist", "")
        query   = task.payload.get("query", "")

        try:
            if action == "status":
                track = await _current_track()
                return self.result_ok(task, track,
                    f"Currently playing: {track['track']}" if track["playing"] else "Nothing is playing, sir.")

            if action == "pause":
                await run_applescript_async('tell application "Music" to pause')
                return self.result_ok(task, {}, "Music paused.")

            if action == "skip":
                await run_applescript_async('tell application "Music" to next track')
                return self.result_ok(task, {}, "Skipped to the next track, sir.")

            if action == "play_playlist" and playlist:
                ok = await _play_playlist(playlist)
                return self.result_ok(task, {"playlist": playlist},
                    f"Playing '{playlist}', sir." if ok else f"Couldn't find '{playlist}'.")

            # Default: mood-based play
            if not mood:
                mood = await _infer_mood()
            played = await _play_by_mood(mood)
            return self.result_ok(task, {"mood": mood, "playlist": played},
                f"Playing {mood} music — '{played}', sir.")

        except Exception as e:
            log.warn("music_agent_error", error=str(e))
            return self.result_err(task, str(e))
