"""High-quality audio configuration and FFmpeg optimization for Telegram Video Chats.

Telegram 2025 Audio Specifications:
- Preferred codec: Opus
- Sample rate: 48000 Hz (48 kHz)
- Channels: Stereo (2ch)
- Bitrate: 128-256 kbps for high quality
- Frame duration: 60ms (network optimized)

This module provides optimized FFmpeg pipelines for maximum audio quality.
"""

import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class AudioQuality(Enum):
    """Audio quality presets for different bandwidth scenarios."""
    STANDARD = "standard"      # 128kbps - Balanced
    HIGH = "high"              # 192kbps - Recommended
    PREMIUM = "premium"        # 256kbps - Best quality
    LOSSLESS = "lossless"      # 320kbps+ - Studio quality
    AUTO = "auto"              # Adaptive based on network


@dataclass
class AudioConfig:
    """Audio configuration for Telegram Video Chat streaming."""
    quality: AudioQuality = AudioQuality.HIGH
    sample_rate: int = 48000  # Telegram requires 48kHz
    channels: int = 2  # Stereo
    bitrate: int = 192  # kbps
    frame_duration: int = 60  # ms - 60ms recommended for network stability
    
    # Advanced FFmpeg options
    use_loudnorm: bool = True  # EBU R128 loudness normalization
    loudnorm_target: int = -14  # LUFS target for consistent Telegram playback
    
    # Network optimization
    buffer_size: int = 1024 * 1024  # 1MB buffer
    max_bitrate: int = 256
    min_bitrate: int = 128
    
    def __post_init__(self):
        """Validate configuration."""
        if self.sample_rate != 48000:
            logger.warning("Telegram requires 48000 Hz sample rate. Adjusting...")
            self.sample_rate = 48000
        
        if self.channels not in [1, 2]:
            logger.warning("Only mono (1) or stereo (2) supported. Using stereo.")
            self.channels = 2

        # Detect environment limits
        if os.getenv("DYNO") or os.getenv("RENDER"):
            # Heroku/Render memory limits -> Cap to standard quality
            self.max_bitrate = min(self.max_bitrate, 128)
            self.bitrate = min(self.bitrate, 128)
            self.quality = AudioQuality.STANDARD


class AudioOptimizer:
    """Optimized audio processing for Telegram Video Chats."""
    
    # Quality presets
    QUALITY_PRESETS = {
        AudioQuality.STANDARD: {
            "bitrate": 128,
            "compression_level": 10,
            "application": "audio",  # Opus application mode
        },
        AudioQuality.HIGH: {
            "bitrate": 192,
            "compression_level": 10,
            "application": "audio",
        },
        AudioQuality.PREMIUM: {
            "bitrate": 256,
            "compression_level": 10,
            "application": "audio",
        },
        AudioQuality.LOSSLESS: {
            "bitrate": 320,
            "compression_level": 10,
            "application": "audio",
        },
        AudioQuality.AUTO: {
            "bitrate": 192,
            "compression_level": 10,
            "application": "audio",
        }
    }
    
    def __init__(self, config: Optional[AudioConfig] = None):
        self.config = config or AudioConfig()
        self.preset = self.QUALITY_PRESETS.get(self.config.quality, self.QUALITY_PRESETS[AudioQuality.HIGH])

        # Override bitrate for environment constraints
        if self.config.bitrate > self.config.max_bitrate:
            self.config.bitrate = self.config.max_bitrate
    
    def get_ffmpeg_params(self, input_url: str, seek: Optional[int] = None, source: str = "auto") -> Dict[str, Any]:
        """Generate optimized FFmpeg parameters for high-quality audio streaming.
        
        Returns parameters compatible with the py-tgcalls streaming pipeline.
        """
        # Base FFmpeg command optimized for Opus -> PCM s16le 48kHz
        ffmpeg_params = {
            "ffmpeg_parameters": {
                "ss": str(seek) if seek else None,
                "acodec": "pcm_s16le",
                "ar": str(self.config.sample_rate),
                "ac": str(self.config.channels),
                "af": self._build_audio_filter(),
                "f": "s16le",
                "thread_queue_size": "4096",
                "threads": "4",
                "vn": None,
                "reconnect": "1",
                "reconnect_streamed": "1",
                "reconnect_delay_max": "5",
                "err_detect": "ignore_err",
            },
            "audio_parameters": {
                "bitrate": self.config.bitrate * 1000,
                "channels": self.config.channels,
            }
        }
        
        # Source-specific adaptations
        if source == "youtube":
            ffmpeg_params["ffmpeg_parameters"].update({
                "reconnect_on_network_error": "1",
                "reconnect_on_http_error": "4xx,5xx",
                "multiple_requests": "1",
                "bufsize": "2M",
            })
        elif source == "direct":
            ffmpeg_params["ffmpeg_parameters"].update({
                "reconnect_delay_max": "10",
                "bufsize": "4M",
            })

        return ffmpeg_params
    
    def _build_audio_filter(self) -> str:
        """Build FFmpeg audio filter chain for optimal quality."""
        filters = []
        filters.append("aresample=resampler=soxr:precision=28")
        filters.append("acompressor=threshold=-18dB:ratio=3:attack=10:release=100")
        if self.config.use_loudnorm:
            filters.append(
                f"loudnorm=I={self.config.loudnorm_target}:"
                f"TP=-1.5:LRA=11:"
                f"measured_I=0:measured_TP=0:"
                f"measured_LRA=0:measured_thresh=0"
            )
        filters.append("highpass=f=20")
        filters.append("alimiter=level_in=1:level_out=1:limit=0.95:attack=5:release=50")
        filters.append("volume=1.0")
        return ",".join(filters)
    def get_ntgcalls_params(self) -> Dict[str, Any]:
        """Get NTgCalls (low-level) parameters for py-tgcalls 2.x."""
        return {
            "sample_rate": self.config.sample_rate,
            "bits_per_sample": 16,
            "channel_count": self.config.channels,
            "buffer_duration": self.config.frame_duration,
        }

_audio_optimizer: Optional[AudioOptimizer] = None

def get_audio_optimizer() -> AudioOptimizer:
    global _audio_optimizer
    if _audio_optimizer is None:
        try:
            from config import config
            quality_str = getattr(config, 'AUDIO_QUALITY', 'high').lower()
            quality = AudioQuality(quality_str) if quality_str in [q.value for q in AudioQuality] else AudioQuality.HIGH

            audio_config = AudioConfig(
                quality=quality,
                bitrate=getattr(config, 'AUDIO_BITRATE', 192),
                use_loudnorm=getattr(config, 'AUDIO_LOUDNORM', True),
            )
        except ImportError:
            audio_config = AudioConfig()

        _audio_optimizer = AudioOptimizer(audio_config)
    
    return _audio_optimizer

def set_audio_quality(quality: AudioQuality):
    global _audio_optimizer
    if _audio_optimizer:
        _audio_optimizer.config.quality = quality
        _audio_optimizer.preset = _audio_optimizer.QUALITY_PRESETS[quality]
        _audio_optimizer.config.bitrate = _audio_optimizer.preset["bitrate"]
        logger.info(f"Audio quality changed to {quality.value} ({_audio_optimizer.config.bitrate}kbps)")
    else:
        _audio_optimizer = AudioOptimizer(AudioConfig(quality=quality))
