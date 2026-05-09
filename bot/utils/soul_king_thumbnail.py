"""
Soul King Concert Theme - Enhanced Thumbnail Generation.
Creates beautiful Now Playing cards with:
  - Soul King aesthetic (dark background, golden accents)
  - Live progress bar with animated elements
  - Song metadata display
  - Source badges and duration
  - Concert stage effects
"""

import logging
import asyncio
from typing import Optional
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import aiohttp
from bot.utils.http_pool import HTTPConnectionPool
from bot.utils.formatters import format_duration

logger = logging.getLogger(__name__)

# Soul King Color Palette
SOUL_KING_COLORS = {
    "bg_dark": (15, 15, 35),        # Deep dark blue/black
    "accent_gold": (255, 215, 0),   # Gold
    "accent_purple": (138, 43, 226), # Purple
    "text_main": (255, 255, 255),   # White
    "text_secondary": (200, 200, 200), # Light gray
    "bar_filled": (255, 215, 0),    # Gold progress
    "bar_empty": (50, 50, 80),      # Dark blue
}

class SoulKingThumbnailGenerator:
    """Generate Soul King concert-themed now playing thumbnails."""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        self.fonts = {}
        self._init_fonts()
    
    def _init_fonts(self):
        """Initialize fonts with fallback."""
        try:
            self.fonts["title"] = ImageFont.truetype("arial.ttf", 52)
            self.fonts["artist"] = ImageFont.truetype("arial.ttf", 36)
            self.fonts["info"] = ImageFont.truetype("arial.ttf", 24)
            self.fonts["small"] = ImageFont.truetype("arial.ttf", 18)
        except Exception:
            try:
                self.fonts["title"] = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
                self.fonts["artist"] = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
                self.fonts["info"] = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
                self.fonts["small"] = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
            except Exception:
                logger.warning("Could not load fonts, using default")
                for key in ["title", "artist", "info", "small"]:
                    self.fonts[key] = ImageFont.load_default()
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        return await HTTPConnectionPool.get_session()
    
    async def download_image(self, url: str, timeout: int = 10) -> Optional[Image.Image]:
        """Download and return PIL Image from URL."""
        if not url:
            return None
        
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    img = Image.open(BytesIO(data))
                    # Convert to RGB if needed
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    return img
        except Exception as e:
            logger.debug(f"Failed to download image from {url}: {e}")
        
        return None

    async def close(self) -> None:
        """Close the HTTP session cleanly."""
        async with self._session_lock:
            if self.session is not None:
                try:
                    await self.session.close()
                except Exception as e:
                    logger.warning(f"Failed to close thumbnail HTTP session: {e}")
                finally:
                    self.session = None

    def _create_gradient_background(self, width: int, height: int) -> Image.Image:
        """Create a dark Soul King gradient background."""
        img = Image.new("RGB", (width, height), SOUL_KING_COLORS["bg_dark"])
        draw = ImageDraw.Draw(img)
        
        # Add subtle gradient effect using rectangles
        for i in range(height):
            # Slight purple tint towards bottom
            ratio = i / height
            r = int(15 + ratio * 25)
            g = int(15 + ratio * 15)
            b = int(35 + ratio * 40)
            draw.rectangle([(0, i), (width, i + 1)], fill=(r, g, b))
        
        return img
    
    def _draw_decorative_border(self, draw: ImageDraw.ImageDraw, width: int, height: int):
        """Draw decorative Soul King borders."""
        # Top gold line
        draw.rectangle(
            [(0, 0), (width, 4)],
            fill=SOUL_KING_COLORS["accent_gold"]
        )
        # Bottom gold line
        draw.rectangle(
            [(0, height - 4), (width, height)],
            fill=SOUL_KING_COLORS["accent_gold"]
        )
        # Side accents
        draw.rectangle(
            [(0, 0), (4, height)],
            fill=SOUL_KING_COLORS["accent_purple"]
        )
        draw.rectangle(
            [(width - 4, 0), (width, height)],
            fill=SOUL_KING_COLORS["accent_purple"]
        )
    
    def _draw_progress_bar(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        width: int,
        height: int,
        progress_ratio: float
    ):
        """Draw an animated progress bar."""
        # Background
        draw.rounded_rectangle(
            [(x, y), (x + width, y + height)],
            radius=height // 2,
            fill=SOUL_KING_COLORS["bar_empty"],
            outline=SOUL_KING_COLORS["accent_gold"],
            width=2
        )
        
        # Filled portion
        if progress_ratio > 0.01:
            filled_width = int(width * min(progress_ratio, 1.0))
            draw.rounded_rectangle(
                [(x, y), (x + filled_width, y + height)],
                radius=height // 2,
                fill=SOUL_KING_COLORS["bar_filled"]
            )
    
    def _truncate_text(self, text: str, max_length: int) -> str:
        """Truncate text with ellipsis."""
        if len(text) > max_length:
            return text[:max_length] + "..."
        return text
    
    async def generate_live_np_card(
        self,
        title: str,
        artist: str,
        duration: int,
        position: int,
        thumbnail_url: Optional[str] = None,
        source: str = "unknown",
        width: int = 1280,
        height: int = 720
    ) -> Optional[bytes]:
        """
        Generate a Soul King concert-themed Now Playing card.
        
        Args:
            title: Song title
            artist: Artist name
            duration: Total duration in seconds
            position: Current position in seconds
            thumbnail_url: Optional song artwork URL
            source: Music source (vk, deezer, telegram, etc.)
            width: Card width
            height: Card height
            
        Returns:
            PNG image bytes or None on error
        """
        try:
            # Create base background
            img = self._create_gradient_background(width, height)
            draw = ImageDraw.Draw(img)
            
            # Add decorative borders
            self._draw_decorative_border(draw, width, height)
            
            # Try to add artwork on the left (if available)
            art_width = 350
            art_x = 40
            art_y = 80
            art_size = height - 160
            
            if thumbnail_url:
                artwork = await self.download_image(thumbnail_url)
                if artwork:
                    # Resize to fit
                    artwork.thumbnail((art_size, art_size), Image.Resampling.LANCZOS)
                    w, h = artwork.size
                    # Add border to artwork
                    bordered = Image.new(
                        "RGB",
                        (art_size + 8, art_size + 8),
                        SOUL_KING_COLORS["accent_gold"]
                    )
                    offset_x = 4 + (art_size - w) // 2
                    offset_y = 4 + (art_size - h) // 2
                    bordered.paste(artwork, (offset_x, offset_y))
                    img.paste(bordered, (art_x, art_y))
            else:
                # Placeholder for missing artwork
                draw.rectangle(
                    [(art_x, art_y), (art_x + art_size, art_y + art_size)],
                    fill=SOUL_KING_COLORS["bar_empty"],
                    outline=SOUL_KING_COLORS["accent_gold"],
                    width=3
                )
                # Draw music note placeholder
                draw.text(
                    (art_x + art_size // 2 - 20, art_y + art_size // 2 - 20),
                    "🎵",
                    font=self.fonts.get("title", ImageFont.load_default()),
                    fill=SOUL_KING_COLORS["accent_gold"]
                )
            
            # Right side content area
            content_x = art_x + art_size + 50
            content_y = 100
            content_width = width - content_x - 40
            max_lines_title = 3
            
            # Title
            title_text = self._truncate_text(title, 80)
            draw.text(
                (content_x, content_y),
                title_text,
                font=self.fonts.get("title", ImageFont.load_default()),
                fill=SOUL_KING_COLORS["text_main"]
            )
            
            # Artist
            content_y += 80
            artist_text = self._truncate_text(artist, 50)
            draw.text(
                (content_x, content_y),
                f"by {artist_text}",
                font=self.fonts.get("artist", ImageFont.load_default()),
                fill=SOUL_KING_COLORS["accent_gold"]
            )
            
            # Source badge
            content_y += 60
            source_badges = {
                "vk": "🟦 VK Music",
                "deezer": "🎧 Deezer",
                "telegram": "✈️ Telegram",
            }
            source_text = source_badges.get(source.lower(), f"🎵 {source}")
            draw.text(
                (content_x, content_y),
                source_text,
                font=self.fonts.get("info", ImageFont.load_default()),
                fill=SOUL_KING_COLORS["text_secondary"]
            )
            
            # Duration info
            content_y += 50
            duration_str = format_duration(duration)
            position_str = format_duration(position)
            draw.text(
                (content_x, content_y),
                f"Duration: {duration_str}",
                font=self.fonts.get("info", ImageFont.load_default()),
                fill=SOUL_KING_COLORS["text_secondary"]
            )
            
            # Progress bar
            bar_y = height - 150
            bar_height = 16
            progress_ratio = (position / duration) if duration > 0 else 0
            
            self._draw_progress_bar(
                draw,
                content_x,
                bar_y,
                content_width,
                bar_height,
                progress_ratio
            )
            
            # Progress text
            bar_y += 25
            progress_text = f"{position_str} / {duration_str} ({int(progress_ratio * 100)}%)"
            draw.text(
                (content_x, bar_y),
                progress_text,
                font=self.fonts.get("info", ImageFont.load_default()),
                fill=SOUL_KING_COLORS["text_secondary"]
            )
            
            # Soul King footer
            footer_y = height - 50
            draw.text(
                (width // 2 - 100, footer_y),
                "🎸 Soul King FM - YOHOHOHO! 💀 🎸",
                font=self.fonts.get("small", ImageFont.load_default()),
                fill=SOUL_KING_COLORS["accent_gold"]
            )
            
            # Convert to bytes
            output = BytesIO()
            img.save(output, format="PNG")
            output.seek(0)
            return output.getvalue()
        
        except Exception as e:
            logger.error(f"Failed to generate live NP card: {e}")
            return None


# Global instance
soul_king_thumbnail = SoulKingThumbnailGenerator()
