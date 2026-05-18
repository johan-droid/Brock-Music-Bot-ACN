import os
import math
import hashlib
import aiohttp
import asyncio
import logging
from typing import Optional, Dict

from pydub import AudioSegment
from pedalboard import Pedalboard, Reverb, Chorus, HighpassFilter, LowpassFilter, PeakFilter, LowShelfFilter, HighShelfFilter
from pedalboard.io import AudioFile

logger = logging.getLogger(__name__)

# Memory store for active effects per chat
# Map of chat_id (int) -> effect name (str)
ACTIVE_EFFECTS: Dict[int, str] = {}

def get_active_effect(chat_id: int) -> Optional[str]:
    """Get the active effect for a chat. Returns None if 'none' or not set."""
    effect = ACTIVE_EFFECTS.get(chat_id)
    if effect == "Remove Effects" or effect == "none" or effect is None:
        return None
    return effect

def set_active_effect(chat_id: int, effect: str) -> None:
    """Set the active effect for a chat."""
    ACTIVE_EFFECTS[chat_id] = effect
    logger.info(f"Set effect '{effect}' for chat {chat_id}")


CACHE_DIR = "cache/effects"
os.makedirs(CACHE_DIR, exist_ok=True)

async def _download_audio(url: str, dest_path: str) -> bool:
    """Download audio from URL to dest_path."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.error(f"Failed to download audio: HTTP {response.status}")
                    return False
                with open(dest_path, "wb") as f:
                    while True:
                        chunk = await response.content.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
        return True
    except Exception as e:
        logger.error(f"Error downloading audio: {e}")
        return False

def apply_effect(input_path: str, output_path: str, effect: str) -> bool:
    """Apply the chosen effect using pedalboard and pydub."""
    try:
        if effect == "Slowed+Reverb" or effect == "Nightcore":
            # Pydub speed modifications
            audio = AudioSegment.from_file(input_path)

            if effect == "Slowed+Reverb":
                # Reduce speed by 20%
                new_sample_rate = int(audio.frame_rate * 0.8)
                audio = audio._spawn(audio.raw_data, overrides={'frame_rate': new_sample_rate})
                audio = audio.set_frame_rate(44100)
            elif effect == "Nightcore":
                # Increase speed by 25% and pitch shift
                new_sample_rate = int(audio.frame_rate * 1.25)
                audio = audio._spawn(audio.raw_data, overrides={'frame_rate': new_sample_rate})
                audio = audio.set_frame_rate(44100)

            temp_path = f"{output_path}.temp.wav"
            audio.export(temp_path, format="wav")

            # Apply Pedalboard effects
            with AudioFile(temp_path) as f:
                audio_data = f.read(f.frames)
                samplerate = f.samplerate

            board = Pedalboard()
            if effect == "Slowed+Reverb":
                board.append(Reverb(room_size=0.8, damping=0.5, wet_level=0.4))

            effected = board(audio_data, samplerate)
            with AudioFile(output_path, 'w', samplerate, effected.shape[0]) as f:
                f.write(effected)

            if os.path.exists(temp_path):
                os.remove(temp_path)

        elif effect == "8D Audio":
            # Pedalboard has no simple auto-panner yet, so we simulate 8D by applying a simple chorus or reverb for spatialization
            # then using pydub for actual panning oscillation
            audio = AudioSegment.from_file(input_path)
            # Create oscillating pan effect
            # Simple approach: split into small chunks and pan each
            chunk_length = 50 # ms
            chunks = []
            for i in range(0, len(audio), chunk_length):
                chunk = audio[i:i+chunk_length]
                # Pan oscillates from -1 to 1 every 2 seconds (0.5 Hz)
                t = i / 1000.0
                pan_val = math.sin(2 * math.pi * 0.5 * t)
                chunks.append(chunk.pan(pan_val))

            effected_audio = sum(chunks)
            effected_audio.export(output_path, format="wav")

        else:
            # For Pure Pedalboard effects like Bass Boost and Vocal Isolation
            # Must read via pydub first to handle arbitrary audio containers (e.g. mp3)
            audio = AudioSegment.from_file(input_path)
            temp_path = f"{output_path}.temp.wav"
            audio.export(temp_path, format="wav")

            with AudioFile(temp_path) as f:
                audio_data = f.read(f.frames)
                samplerate = f.samplerate

            board = Pedalboard()

            if effect == "Bass Boost":
                board.append(LowShelfFilter(cutoff_frequency_hz=100.0, gain_db=6.0))
            elif effect == "Vocal Isolation":
                # Crude isolation: remove low bass and extreme highs
                board.append(HighpassFilter(cutoff_frequency_hz=300.0))
                board.append(LowpassFilter(cutoff_frequency_hz=3000.0))

            effected = board(audio_data, samplerate)
            with AudioFile(output_path, 'w', samplerate, effected.shape[0]) as f:
                f.write(effected)

            if os.path.exists(temp_path):
                os.remove(temp_path)

        return True
    except Exception as e:
        logger.error(f"Error applying effect {effect}: {e}")
        return False

async def process_track(track_id: str, audio_url: str, effect: str) -> str:
    """
    Process track with effect.
    Returns the path to the cached processed file, or original audio_url if processing fails/no effect.
    """
    if effect is None or effect == "Remove Effects" or effect == "none":
        return audio_url

    track_id_safe = str(track_id).replace("/", "_").replace("\\", "_")
    effect_safe = effect.replace(" ", "_").replace("+", "_")

    # Create hash for cache filename
    hash_str = hashlib.md5(f"{track_id_safe}_{effect_safe}".encode()).hexdigest()[:10]
    cached_file = os.path.join(CACHE_DIR, f"{track_id_safe}_{effect_safe}_{hash_str}.wav")

    if os.path.exists(cached_file):
        logger.info(f"Using cached effect file for {track_id} - {effect}")
        return cached_file

    # Not cached, process it
    temp_input = os.path.join(CACHE_DIR, f"temp_in_{hash_str}.mp3")

    try:
        logger.info(f"Downloading track {track_id} for effect {effect}...")
        success = await _download_audio(audio_url, temp_input)
        if not success:
            raise RuntimeError("Failed to download audio")

        logger.info(f"Applying effect {effect}...")
        # Run CPU bound audio processing in thread pool
        success = await asyncio.to_thread(apply_effect, temp_input, cached_file, effect)

        if success and os.path.exists(cached_file):
            logger.info(f"Successfully processed effect {effect} for track {track_id}")
            return cached_file
        else:
            raise RuntimeError("Effect application failed")

    except Exception as e:
        logger.error(f"Failed to process track for effects: {e}")
        # Return error flag or exception
        raise

    finally:
        if os.path.exists(temp_input):
            try:
                os.remove(temp_input)
            except:
                pass

    return audio_url
