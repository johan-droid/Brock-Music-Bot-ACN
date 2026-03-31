"""
FFmpeg constants and configuration.
(Subprocess management removed in favor of NTgCalls internal pipeline) 💀🎻
"""

import logging

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
