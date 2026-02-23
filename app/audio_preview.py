"""Audio preview utilities for creating short voice previews."""

import logging
from io import BytesIO

from app.config import config

logger = logging.getLogger(__name__)


async def create_preview(audio_data: bytes) -> bytes:
    """
    Trim MP3 to a short preview and convert to OGG Opus for Telegram voice message.
    
    Uses config.preview_start_percent and config.preview_duration_sec for settings.
    The preview starts at the configured percentage of the track (default ~1/3,
    closer to the chorus) rather than the beginning, which is usually an intro.
    
    Args:
        audio_data: Raw MP3 bytes
    
    Returns:
        OGG Opus bytes suitable for Telegram voice message
    """
    from pydub import AudioSegment

    duration_sec = config.preview_duration_sec
    start_percent = config.preview_start_percent

    try:
        audio = AudioSegment.from_mp3(BytesIO(audio_data))
        
        # Start from the configured percentage of the track
        total_ms = len(audio)
        start_ms = max(0, int(total_ms * start_percent / 100))
        end_ms = min(start_ms + duration_sec * 1000, total_ms)
        
        # If not enough audio from that point, take from the beginning
        if end_ms - start_ms < duration_sec * 1000 * 0.5:
            start_ms = 0
            end_ms = min(duration_sec * 1000, total_ms)
        
        preview = audio[start_ms:end_ms]
        
        # Fade in/out for smooth transitions
        preview = preview.fade_in(500).fade_out(1000)
        
        buf = BytesIO()
        preview.export(buf, format="ogg", codec="libopus", bitrate="64k")
        buf.seek(0)
        return buf.read()
        
    except Exception as e:
        logger.error(f"Failed to create audio preview: {e}")
        raise
