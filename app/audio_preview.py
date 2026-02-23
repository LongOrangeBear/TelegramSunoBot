"""Audio preview utilities for creating 30-second voice previews."""

import logging
from io import BytesIO

logger = logging.getLogger(__name__)

PREVIEW_DURATION_SEC = 30


async def create_preview(audio_data: bytes, duration_sec: int = PREVIEW_DURATION_SEC) -> bytes:
    """
    Trim MP3 to a short preview and convert to OGG Opus for Telegram voice message.
    
    Takes a segment from ~1/3 of the track (closer to the chorus) rather than
    the beginning, which is usually an intro.
    
    Args:
        audio_data: Raw MP3 bytes
        duration_sec: Duration of preview in seconds (default 30)
    
    Returns:
        OGG Opus bytes suitable for Telegram voice message
    """
    from pydub import AudioSegment

    try:
        audio = AudioSegment.from_mp3(BytesIO(audio_data))
        
        # Start from ~1/3 of the track (usually closer to the chorus)
        total_ms = len(audio)
        start_ms = max(0, total_ms // 3)
        end_ms = min(start_ms + duration_sec * 1000, total_ms)
        
        # If not enough audio from 1/3 point, take from the beginning
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
