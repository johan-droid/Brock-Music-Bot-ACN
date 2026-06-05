"""
FFmpeg constants and configuration.
(Subprocess management removed in favor of NTgCalls internal pipeline) 💀🎻
Includes stream validation routine before playback.
"""

import asyncio
import json
import logging
import os
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# FFmpeg PCM output settings for reference or external tools
PCM_FLAGS = [
    "-vn",                         # Audio only
    "-f", "s16le",                 # PCM signed 16-bit little-endian
    "-ar", "48000",                # 48kHz sample rate
    "-ac", "2",                    # Stereo
]

# Standard loudness normalization filter
LOUDNORM_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"


def get_ffmpeg_cmd(input_url: str, seek: int = 0, volume: int = 100) -> list:
    """
    Generates a basic FFmpeg command for reference.
    Note: The bot now uses NTgCalls for direct streaming.
    """
    cmd = ["ffmpeg", "-i", input_url]
    if seek > 0:
        cmd.insert(1, "-ss")
        cmd.insert(2, str(seek))

    af = LOUDNORM_FILTER
    if volume != 100:
        af = f"volume={volume / 100:.2f},{af}"

    cmd.extend(["-af", af])
    cmd.extend(PCM_FLAGS)
    cmd.append("pipe:1")
    return cmd


def _validation_mode() -> str:
    """
    STREAM_VALIDATION_MODE:
      strict   -> ffprobe must pass
      warn     -> log ffprobe failures but allow PyTgCalls to attempt playback
      disabled -> skip ffprobe entirely
    """
    return os.getenv("STREAM_VALIDATION_MODE", "warn").strip().lower()


async def validate_stream_ffprobe(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 5) -> bool:
    """
    Validate stream via ffprobe in a non-blocking way before playback.

    Many provider URLs are short-lived, redirect-heavy, header-sensitive, or only
    accepted by FFmpeg/NTgCalls at playback time. Treat ffprobe as a guardrail,
    not as a process-killing truth source, unless STREAM_VALIDATION_MODE=strict.
    """
    mode = _validation_mode()
    if mode in {"off", "false", "0", "disabled", "disable"}:
        logger.debug("ffprobe validation skipped by STREAM_VALIDATION_MODE=%s", mode)
        return True

    timeout = max(2, int(os.getenv("STREAM_VALIDATION_TIMEOUT", str(timeout)) or timeout))

    cmd = [
        "ffprobe",
        "-v", "error",
        "-hide_banner",
        "-show_entries", "stream=codec_type",
        "-of", "json",
    ]

    if headers:
        header_str = ""
        for k, v in headers.items():
            if not v:
                continue
            if k.lower() == "user-agent":
                cmd.extend(["-user_agent", str(v)])
            elif k.lower() == "referer":
                cmd.extend(["-referer", str(v)])
            else:
                header_str += f"{k}: {v}\r\n"
        if header_str:
            cmd.extend(["-headers", header_str])

    cmd.append(url)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            logger.warning("ffprobe stream validation timed out after %ss", timeout)
            return mode != "strict"

        if process.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            logger.warning("ffprobe validation failed: %s", err[:500])
            return mode != "strict"

        raw = stdout.decode(errors="replace").strip()
        if not raw:
            logger.warning("ffprobe returned empty output")
            return mode != "strict"

        data = json.loads(raw)
        streams = data.get("streams", [])
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        if not has_audio:
            logger.warning("ffprobe found no audio stream")
            return mode != "strict"

        return True

    except FileNotFoundError:
        logger.warning("ffprobe binary is not installed; allowing playback attempt")
        return mode != "strict"
    except json.JSONDecodeError as exc:
        logger.warning("ffprobe returned invalid JSON: %s", exc)
        return mode != "strict"
    except Exception as exc:
        logger.warning("Error during stream validation: %s", exc)
        return mode != "strict"
