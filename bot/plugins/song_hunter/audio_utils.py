import aiohttp
import asyncio
import os
import logging
import random
from typing import Optional

try:
    from pydub import AudioSegment
except ImportError:  # pragma: no cover - depends on deployment image
    AudioSegment = None

logger = logging.getLogger(__name__)


def _audio_runtime_available() -> bool:
    return AudioSegment is not None

CACHE_DIR = "data/hunter_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

async def download_and_trim_audio(url: str, track_id: str, duration_sec: int = 15) -> Optional[str]:
    if not _audio_runtime_available():
        logger.warning("Song Hunter audio trimming is unavailable because pydub is not installed")
        return None

    file_path = os.path.join(CACHE_DIR, f"{track_id}_full.mp3")
    trimmed_path = os.path.join(CACHE_DIR, f"{track_id}_trimmed.mp3")

    if os.path.exists(trimmed_path):
        return trimmed_path

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=20) as response:
                if response.status != 200:
                    logger.error(f"Failed to download audio: HTTP {response.status}")
                    return None

                content = await response.read()
                with open(file_path, 'wb') as f:
                    f.write(content)

        def _trim():
            audio = AudioSegment.from_file(file_path)
            total_duration_ms = len(audio)

            segment_ms = random.randint(5000, 8000)

            if total_duration_ms <= segment_ms:
                audio.export(trimmed_path, format="mp3", bitrate="128k")
                return

            max_start = total_duration_ms - segment_ms
            if max_start > 30000:
                start_ms = random.randint(10000, max_start - 10000)
            else:
                start_ms = random.randint(0, max_start)

            end_ms = start_ms + segment_ms

            segment = audio[start_ms:end_ms]
            segment = segment.fade_in(500).fade_out(500)
            segment.export(trimmed_path, format="mp3", bitrate="128k")

        await asyncio.to_thread(_trim)

        if os.path.exists(file_path):
            os.remove(file_path)

        return trimmed_path
    except Exception as e:
        logger.error(f"Error trimming audio {track_id}: {e}")
        return None

def clear_cache():
    try:
        for f in os.listdir(CACHE_DIR):
            os.remove(os.path.join(CACHE_DIR, f))
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
