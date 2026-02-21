"""Suno API client via SunoAPI.org v1 API."""

import asyncio
import logging
from typing import Optional

import httpx

from app.config import config

logger = logging.getLogger(__name__)


class SunoApiError(Exception):
    """Raised when Suno API returns an error."""
    pass


class ContentPolicyError(SunoApiError):
    """Raised when content violates Suno's policy."""
    pass


class SunoClient:
    """Client for interacting with Suno API through SunoAPI.org v1 API."""

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

    async def generate_lyrics(self, prompt: str) -> dict:
        """
        Generate lyrics from a description via Lyrics API.

        Returns:
            dict with task_id for polling lyrics status
        """
        payload = {"prompt": prompt}

        # Add callback URL if configured (required by the API)
        if config.callback_base_url:
            payload["callBackUrl"] = f"{config.callback_base_url.rstrip('/')}/callback/lyrics"
        else:
            payload["callBackUrl"] = "https://example.com/callback/lyrics"

        logger.info(f"Lyrics generation request: /api/v1/lyrics | {payload}")

        try:
            response = await self.client.post("/api/v1/lyrics", json=payload)
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 200:
                msg = result.get("msg", "Unknown error")
                raise SunoApiError(f"Lyrics API error: {msg}")

            task_id = result.get("data", {}).get("taskId")
            if not task_id:
                raise SunoApiError(f"No taskId in lyrics response: {result}")

            return {"task_id": task_id}

        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            if "sensitive" in error_body.lower() or "content policy" in error_body.lower():
                raise ContentPolicyError(f"Lyrics content filtered: {error_body}")
            raise SunoApiError(f"Lyrics API error {e.response.status_code}: {error_body}")
        except httpx.RequestError as e:
            raise SunoApiError(f"Lyrics request failed: {e}")

    async def wait_for_lyrics(
        self, task_id: str, timeout: int = 120, poll_interval: int = 5
    ) -> dict:
        """
        Poll until lyrics generation is complete.

        Returns:
            dict with 'text' (lyrics with structure tags) and 'title'
        """
        start_time = asyncio.get_event_loop().time()
        await asyncio.sleep(3)  # Initial wait

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            try:
                response = await self.client.get(
                    f"/api/v1/lyrics/record-info?taskId={task_id}"
                )
                response.raise_for_status()
                result = response.json()

                if result.get("code") != 200:
                    raise SunoApiError(f"Lyrics status check failed: {result.get('msg')}")

                data = result.get("data", {})
                status = data.get("status", "")

                logger.info(f"Lyrics task {task_id} status: {status}")

                if status == "SUCCESS":
                    response_data = data.get("response", {})
                    lyrics_list = response_data.get("data", [])
                    if lyrics_list:
                        first = lyrics_list[0]
                        lyrics_text = first.get("text", "")
                        lyrics_title = first.get("title", "Untitled")
                        logger.info(f"Lyrics generated: title='{lyrics_title}', length={len(lyrics_text)}")
                        return {"text": lyrics_text, "title": lyrics_title}
                    raise SunoApiError(f"No lyrics data in response: {data}")

                elif status == "SENSITIVE_WORD_ERROR":
                    error_msg = data.get("errorMessage", "Lyrics filtered")
                    raise ContentPolicyError(error_msg)

                elif status in ("CREATE_TASK_FAILED", "GENERATE_LYRICS_FAILED", "CALLBACK_EXCEPTION"):
                    error_msg = data.get("errorMessage", f"Lyrics generation failed: {status}")
                    raise SunoApiError(error_msg)

            except httpx.HTTPStatusError as e:
                raise SunoApiError(f"Lyrics status error {e.response.status_code}: {e.response.text}")

            await asyncio.sleep(poll_interval)

        raise SunoApiError(f"Lyrics generation timeout after {timeout}s")

    async def generate(
        self,
        prompt: str,
        style: str = "",
        voice_gender: Optional[str] = None,
        mode: str = "description",
        lyrics: Optional[str] = None,
        instrumental: bool = False,
        on_lyrics_ready: Optional[callable] = None,
    ) -> dict:
        """
        Start a song generation via v1 API.

        In description mode, first generates lyrics from the description,
        then uses those lyrics in custom mode for music generation.

        Args:
            on_lyrics_ready: optional async callback called when lyrics are generated
                             (for updating user-facing status messages)

        Returns:
            dict with task_id for polling
        """
        # Build the style tag incorporating gender
        full_style = style
        if not instrumental and voice_gender:
            full_style = f"{voice_gender} vocal, {style}" if style else f"{voice_gender} vocal"

        if mode == "custom" and lyrics:
            # Custom mode: customMode=true, prompt=lyrics, style & title required
            payload = {
                "prompt": lyrics,
                "customMode": True,
                "instrumental": False,
                "model": config.suno_model,
                "style": full_style or "Pop",
                "title": (prompt[:77] + "..." if len(prompt) > 80 else prompt) if prompt else "Untitled",
            }
        elif mode == "instrumental":
            # Instrumental: customMode=false, instrumental=true
            payload = {
                "prompt": f"{prompt}, {style}" if style else prompt,
                "customMode": False,
                "instrumental": True,
                "model": config.suno_model,
            }
        else:
            # Description mode: two-step generation
            # Step 1: Generate lyrics from user's description
            logger.info(f"Description mode: generating lyrics from description...")
            lyrics_result = await self.generate_lyrics(prompt)
            lyrics_data = await self.wait_for_lyrics(lyrics_result["task_id"])

            generated_lyrics = lyrics_data["text"]
            generated_title = lyrics_data["title"]

            logger.info(f"Lyrics ready, title='{generated_title}', generating music...")

            # Notify caller that lyrics are ready (for UI updates)
            if on_lyrics_ready:
                try:
                    await on_lyrics_ready(generated_lyrics, generated_title)
                except Exception as e:
                    logger.warning(f"on_lyrics_ready callback error: {e}")

            # Step 2: Use generated lyrics in custom mode
            payload = {
                "customMode": True,
                "instrumental": False,
                "model": config.suno_model,
                "prompt": generated_lyrics[:5000],
                "style": full_style[:1000] if full_style else "Pop",
                "title": generated_title[:80],
            }

        # Add callback URL if configured
        if config.callback_base_url:
            payload["callBackUrl"] = f"{config.callback_base_url.rstrip('/')}/callback/suno"

        logger.info(f"Suno v1 generate request: /api/v1/generate | {payload}")

        try:
            response = await self.client.post("/api/v1/generate", json=payload)
            response.raise_for_status()
            result = response.json()

            # v1 API response: {"code": 200, "msg": "success", "data": {"taskId": "..."}}
            if result.get("code") != 200:
                msg = result.get("msg", "Unknown error")
                raise SunoApiError(f"API error: {msg}")

            task_id = result.get("data", {}).get("taskId")
            if not task_id:
                raise SunoApiError(f"No taskId in response: {result}")

            return {"task_id": task_id, "raw_response": result}

        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            if "content policy" in error_body.lower() or "moderation" in error_body.lower():
                raise ContentPolicyError(f"Content policy violation: {error_body}")
            if "sensitive" in error_body.lower():
                raise ContentPolicyError(f"Content filtered: {error_body}")
            raise SunoApiError(f"API error {e.response.status_code}: {error_body}")
        except httpx.RequestError as e:
            raise SunoApiError(f"Request failed: {e}")

    async def get_task_status(self, task_id: str) -> dict:
        """Check task status via polling endpoint."""
        try:
            response = await self.client.get(
                f"/api/v1/generate/record-info?taskId={task_id}"
            )
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 200:
                raise SunoApiError(f"Status check failed: {result.get('msg', 'Unknown error')}")

            return result.get("data", {})
        except httpx.HTTPStatusError as e:
            raise SunoApiError(f"Status check error {e.response.status_code}: {e.response.text}")

    async def wait_for_completion(
        self, task_id: str, timeout: int = 300, poll_interval: int = 10
    ) -> list[dict]:
        """
        Poll until task is complete or timeout.

        Returns list of song dicts from sunoData with audioUrl populated.
        """
        start_time = asyncio.get_event_loop().time()
        await asyncio.sleep(5)  # Initial wait

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            status_data = await self.get_task_status(task_id)
            status = status_data.get("status", "")

            logger.info(f"Task {task_id} status: {status}")

            if status in ("SUCCESS", "FIRST_SUCCESS"):
                # Extract sunoData from response
                response = status_data.get("response", {})
                suno_data = response.get("sunoData", [])
                if suno_data:
                    return suno_data
                raise SunoApiError(f"No sunoData in successful response: {status_data}")

            elif status == "SENSITIVE_WORD_ERROR":
                error_msg = status_data.get("errorMessage", "Content filtered due to sensitive words")
                raise ContentPolicyError(error_msg)

            elif status in ("CREATE_TASK_FAILED", "GENERATE_AUDIO_FAILED", "CALLBACK_EXCEPTION"):
                error_msg = status_data.get("errorMessage", f"Generation failed: {status}")
                raise SunoApiError(error_msg)

            elif status == "PENDING":
                pass  # Still processing

            else:
                logger.warning(f"Unknown task status: {status}")
                if status_data.get("errorMessage"):
                    logger.warning(f"Error message: {status_data['errorMessage']}")

            await asyncio.sleep(poll_interval)

        # Timeout
        logger.warning(f"Generation timeout for task: {task_id}")
        raise SunoApiError(f"Generation timeout after {timeout}s for task {task_id}")


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
