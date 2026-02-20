"""Suno API client via third-party provider (Kie.ai / musicapi.ai)."""

import asyncio
import logging
from typing import Optional

import httpx

from app.config import config

logger = logging.getLogger(__name__)

# Suno API response statuses
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_COMPLETE = "complete"
STATUS_ERROR = "error"


class SunoApiError(Exception):
    """Raised when Suno API returns an error."""
    pass


class ContentPolicyError(SunoApiError):
    """Raised when content violates Suno's policy."""
    pass


class SunoClient:
    """Client for interacting with Suno API through a third-party provider."""

    def __init__(self):
        self.base_url = config.suno_api_url.rstrip("/")
        self.api_key = config.suno_api_key
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=120.0,
        )

    async def close(self):
        await self.client.aclose()

    async def generate(
        self,
        prompt: str,
        style: str = "",
        voice_gender: Optional[str] = None,
        mode: str = "description",
        lyrics: Optional[str] = None,
        instrumental: bool = False,
    ) -> dict:
        """
        Start a song generation.

        Args:
            prompt: Text description or title
            style: Music style/genre tag
            voice_gender: 'male' or 'female' (ignored for instrumental)
            mode: 'description', 'custom', or 'instrumental'
            lyrics: Custom lyrics text (for custom mode)
            instrumental: Whether to generate instrumental only

        Returns:
            dict with generation task info including song IDs
        """
        # Build the style tag incorporating gender
        full_style = style
        if not instrumental and voice_gender:
            full_style = f"{voice_gender} vocal, {style}" if style else f"{voice_gender} vocal"

        if mode == "custom" and lyrics:
            payload = {
                "prompt": lyrics,
                "tags": full_style,
                "title": prompt or "Untitled",
                "make_instrumental": False,
            }
            endpoint = "/api/custom_generate"
        elif mode == "instrumental":
            payload = {
                "prompt": f"{prompt}, {style}" if style else prompt,
                "make_instrumental": True,
            }
            endpoint = "/api/generate"
        else:
            # Description mode
            payload = {
                "prompt": f"{prompt}, style: {full_style}" if full_style else prompt,
                "make_instrumental": False,
            }
            endpoint = "/api/generate"

        logger.info(f"Suno generate request: {endpoint} | {payload}")

        try:
            response = await self.client.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, list):
                song_ids = [item.get("id") for item in data if item.get("id")]
            elif isinstance(data, dict):
                if "data" in data and isinstance(data["data"], list):
                    song_ids = [item.get("id") for item in data["data"] if item.get("id")]
                elif "id" in data:
                    song_ids = [data["id"]]
                else:
                    song_ids = []
            else:
                song_ids = []

            if not song_ids:
                raise SunoApiError(f"No song IDs in response: {data}")

            return {
                "song_ids": song_ids,
                "raw_response": data,
            }

        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            if "content policy" in error_body.lower() or "moderation" in error_body.lower():
                raise ContentPolicyError(f"Content policy violation: {error_body}")
            raise SunoApiError(f"API error {e.response.status_code}: {error_body}")
        except httpx.RequestError as e:
            raise SunoApiError(f"Request failed: {e}")

    async def get_songs(self, song_ids: list[str]) -> list[dict]:
        """Get song info by IDs."""
        ids_param = ",".join(song_ids)
        try:
            response = await self.client.get(f"/api/get?ids={ids_param}")
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "data" in data:
                return data["data"]
            return [data]
        except httpx.HTTPStatusError as e:
            raise SunoApiError(f"Get songs error {e.response.status_code}: {e.response.text}")

    async def wait_for_completion(
        self, song_ids: list[str], timeout: int = 300, poll_interval: int = 8
    ) -> list[dict]:
        """
        Poll until songs are complete or timeout.

        Returns list of song dicts with audio_url populated.
        """
        start_time = asyncio.get_event_loop().time()
        await asyncio.sleep(5)  # Initial wait

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            songs = await self.get_songs(song_ids)

            all_done = all(
                s.get("status") in ("complete", "streaming")
                for s in songs
            )
            any_error = any(s.get("status") == "error" for s in songs)

            if all_done or any_error:
                return songs

            await asyncio.sleep(poll_interval)

        # Timeout — return whatever we have
        logger.warning(f"Generation timeout for songs: {song_ids}")
        return await self.get_songs(song_ids)


# Global client instance
suno_client: SunoClient | None = None


def get_suno_client() -> SunoClient:
    global suno_client
    if suno_client is None:
        suno_client = SunoClient()
    return suno_client


async def close_suno_client():
    global suno_client
    if suno_client:
        await suno_client.close()
        suno_client = None
