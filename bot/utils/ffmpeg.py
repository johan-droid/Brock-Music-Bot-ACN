"""
FFmpeg constants and configuration.
(Subprocess management removed in favor of NTgCalls internal pipeline) 💀🎻
Includes stream validation routine before playback.
"""

import logging
import asyncio
import json
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
        af = f"volume={volume/100:.2f},{af}"
    
    cmd.extend(["-af", af])
    cmd.extend(PCM_FLAGS)
    cmd.append("pipe:1")
    return cmd

async def validate_stream_ffprobe(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 5) -> bool:
    """
    Validate stream via ffprobe in a non-blocking way before playback.
    """
    cmd = ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json"]

    if headers:
        header_str = ""
        for k, v in headers.items():
            if k.lower() == "user-agent":
                cmd.extend(["-user_agent", v])
            elif k.lower() == "referer":
                cmd.extend(["-referer", v])
            else:
                header_str += f"{k}: {v}\r\n"
        if header_str:
            cmd.extend(["-headers", header_str])

    cmd.append(url)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            logger.warning("ffprobe stream validation timed out")
            return False

        if process.returncode != 0:
            logger.warning(f"ffprobe validation failed: {stderr.decode().strip()}")
            return False

        data = json.loads(stdout.decode())
        streams = data.get("streams", [])
        if any(s.get("codec_type") == "audio" for s in streams):
            return True
        return False

    except Exception as e:
        logger.error(f"Error during stream validation: {e}")
        return False
