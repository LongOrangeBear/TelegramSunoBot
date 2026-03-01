"""Automatic Russian stress accent placement using ruaccent."""

import logging
import re

logger = logging.getLogger(__name__)

# Singleton accentizer instance
_accentizer = None
_init_error = False


def _get_accentizer():
    """Lazy-load the RUAccent model (heavy, ~200MB on first download)."""
    global _accentizer, _init_error
    if _init_error:
        return None
    if _accentizer is None:
        try:
            from ruaccent import RUAccent
            _accentizer = RUAccent()
            _accentizer.load(
                omograph_model_size='big_poetry',
                use_dictionary=True,
                tiny_mode=False,
            )
            logger.info("RUAccent model loaded successfully")
        except Exception as e:
            _init_error = True
            logger.error(f"Failed to load RUAccent model: {e}", exc_info=True)
            return None
    return _accentizer


# Regex for structure tags like [Verse], [Chorus], [Bridge], etc.
_TAG_RE = re.compile(r'^\[.*\]$')


def _accent_line(accentizer, line: str) -> str:
    """Process a single line: skip tags, accent text lines."""
    stripped = line.strip()
    if not stripped or _TAG_RE.match(stripped):
        return line

    try:
        # Lowercase first so only stress-marked vowels are uppercase in output
        accented = accentizer.process_all(stripped.lower())
    except Exception as e:
        logger.warning(f"RUAccent processing failed for line: {e}")
        return line

    # Convert '+' notation to uppercase: м+аша → мАша
    result = []
    i = 0
    while i < len(accented):
        if accented[i] == '+' and i + 1 < len(accented):
            result.append(accented[i + 1].upper())
            i += 2
        else:
            result.append(accented[i])
            i += 1
    return ''.join(result)


def apply_stress_accents(text: str) -> str:
    """
    Apply Russian stress accents to lyrics text.

    Stressed vowels are uppercased: маша пришла домой → мАша пришлА домОй.
    Structure tags like [Verse], [Chorus] are preserved unchanged.

    This is a synchronous (blocking) function — call via asyncio.to_thread().
    """
    if not text or not text.strip():
        return text

    accentizer = _get_accentizer()
    if accentizer is None:
        logger.warning("RUAccent not available, returning text as-is")
        return text

    lines = text.split('\n')
    accented_lines = [_accent_line(accentizer, line) for line in lines]
    return '\n'.join(accented_lines)
