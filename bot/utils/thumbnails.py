"""Thumbnail generation for Now Playing cards."""

import logging
import os
from typing import Optional
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import aiohttp
from bot.utils.formatters import create_progress_bar, format_duration

logger = logging.getLogger(__name__)

# Default thumbnail size
THUMB_WIDTH = 1280
THUMB_HEIGHT = 720

# Cache for downloaded thumbnails
_thumb_cache: dict = {}


class ThumbnailGenerator:
    """Generate Now Playing thumbnail cards."""
    
    def __init__(self):
        self.session: aiohttp.ClientSession = None
        self.font_large = None
        self.font_medium = None
        self.font_small = None
        self._init_fonts()
    
    def _init_fonts(self):
        """Initialize fonts (use defaults if custom fonts not available)."""
        try:
            # Try to load system fonts
            self.font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
            self.font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
            self.font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        except Exception:
            # Fall back to default fonts
            self.font_large = ImageFont.load_default()
            self.font_medium = ImageFont.load_default()
            self.font_small = ImageFont.load_default()
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def download_thumbnail(self, url: str) -> Optional[bytes]:
        """Download thumbnail image.
        
        Args:
            url: Image URL
            
        Returns:
            Image bytes or None
        """
        if not url:
            return None
        
        # Check cache
        if url in _thumb_cache:
            return _thumb_cache[url]
        
        try:
            session = await self._get_session()
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    _thumb_cache[url] = data
                    return data
        except Exception as e:
            logger.warning(f"Failed to download thumbnail: {e}")
        
        return None
    
    async def generate_now_playing(
        self,
        title: str,
        artist: str = "",
        duration: int = 0,
        position: int = 0,
        thumbnail_url: Optional[str] = None,
        source: str = "unknown"
    ) -> Optional[bytes]:
        """Generate Now Playing card.
        
        Args:
            title: Track title
            artist: Artist name
            duration: Total duration in seconds
            position: Current position in seconds
            thumbnail_url: Album art URL
            source: Source platform
            
        Returns:
            PNG image bytes or None
        """
        try:
            # Download background thumbnail
            bg_data = await self.download_thumbnail(thumbnail_url) if thumbnail_url else None
            
            # Create base image
            if bg_data:
                bg = Image.open(BytesIO(bg_data))
                bg = bg.convert("RGB")
                bg = bg.resize((THUMB_WIDTH, THUMB_HEIGHT), Image.Resampling.LANCZOS)
            else:
                # Create gradient background base (15, 15, 35)
                bg = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), (15, 15, 35))
                draw = ImageDraw.Draw(bg)
                
                # Add gradient effect
                for y in range(THUMB_HEIGHT):
                    r = int(15 + (40 - 15) * y / THUMB_HEIGHT)
                    g = int(15 + (40 - 15) * y / THUMB_HEIGHT)
                    b = int(35 + (80 - 35) * y / THUMB_HEIGHT)
                    draw.line([(0, y), (THUMB_WIDTH, y)], fill=(r, g, b))
            
            # Add overlay for text readability
            overlay = Image.new("RGBA", (THUMB_WIDTH, THUMB_HEIGHT), (0, 0, 0, 128))
            bg = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
            
            draw = ImageDraw.Draw(bg)
            
            # Source emoji/icon
            source_emoji = {
                "vk": "🟦 VK Music",
                "deezer": "🎧 Deezer",
                "telegram": "✈️ Telegram",
            }.get((source or "").lower(), "🎵 Music")
            
            # Draw source badge
            draw.text((40, 40), source_emoji, fill=(255, 255, 255), font=self.font_small)
            
            # Draw title (truncated if needed)
            max_width = THUMB_WIDTH - 80
            title_text = title[:50] + "..." if len(title) > 50 else title
            
            # Calculate text position (centered vertically in top half)
            draw.text((40, 200), title_text, fill=(255, 255, 255), font=self.font_large)
            
            # Draw artist if available
            if artist:
                draw.text((40, 270), f"by {artist[:40]}", fill=(200, 200, 200), font=self.font_medium)
            
            # Draw progress bar
            bar_y = 450
            bar_height = 8
            bar_color = (255, 215, 0)  # Gold highlight
            bg_bar_color = (60, 60, 80)
            
            # Background bar
            draw.rectangle(
                [(40, bar_y), (THUMB_WIDTH - 40, bar_y + bar_height)],
                fill=bg_bar_color
            )
            
            # Progress fill
            if duration > 0:
                progress = min(position / duration, 1.0)
                fill_width = int((THUMB_WIDTH - 80) * progress)
                draw.rectangle(
                    [(40, bar_y), (40 + fill_width, bar_y + bar_height)],
                    fill=bar_color
                )
            
            # Draw time labels
            current_str = format_duration(position)
            total_str = format_duration(duration)
            
            draw.text((40, bar_y + 20), current_str, fill=(200, 200, 200), font=self.font_small)
            
            # Right-align total time
            total_bbox = draw.textbbox((0, 0), total_str, font=self.font_small)
            total_width = total_bbox[2] - total_bbox[0]
            draw.text((THUMB_WIDTH - 40 - total_width, bar_y + 20), total_str, fill=(200, 200, 200), font=self.font_small)
            
            # Draw "Now Playing" indicator with purple accents
            draw.text((40, 550), "▶ Now Playing", fill=(138, 43, 226), font=self.font_medium)
            
            # Convert to bytes
            output = BytesIO()
            bg.save(output, format="PNG")
            output.seek(0)
            
            return output.getvalue()
            
        except Exception as e:
            logger.error(f"Thumbnail generation failed: {e}")
            return None


# Global generator
thumb_generator = ThumbnailGenerator()


async def generate_np_thumbnail(
    title: str,
    artist: str = "",
    duration: int = 0,
    position: int = 0,
    thumbnail_url: Optional[str] = None,
    source: str = "unknown"
) -> Optional[bytes]:
    """Generate Now Playing thumbnail."""
    return await thumb_generator.generate_now_playing(
        title, artist, duration, position, thumbnail_url, source
    )
