import asyncio
from typing import Dict, List, Optional
from urllib.parse import quote
import aiohttp
from src.config import Config
from src.logger import logger
from src.models import TargetConfig

WAYBACK_SAVE_URL = "https://web.archive.org/save/"


class WaybackArchiver:
    """Submits target URLs to the Internet Archive Wayback Machine for historical preservation."""

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self._session = session

    async def save_url(self, target_url: str, session: Optional[aiohttp.ClientSession] = None) -> Optional[str]:
        """
        Sends a save request to Wayback Machine for a given URL.
        Returns the snapshot URL or None if submission timed out.
        """
        sess = session or self._session
        if not sess or sess.closed:
            return None

        save_endpoint = f"{WAYBACK_SAVE_URL}{target_url}"
        headers = {
            **Config.DEFAULT_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        try:
            logger.info(f"Submitting to Wayback Machine: {target_url}")
            async with sess.get(
                save_endpoint,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=True,
            ) as resp:
                final_url = str(resp.url)
                if "web.archive.org/web/" in final_url:
                    logger.info(f"Wayback snapshot created: {final_url}")
                    return final_url
                if resp.status in (200, 302):
                    logger.info(f"Wayback request accepted for {target_url} (status: {resp.status})")
                    return f"https://web.archive.org/web/*/{target_url}"
                logger.warning(f"Wayback returned status {resp.status} for {target_url}")
                return None
        except asyncio.TimeoutError:
            logger.warning(f"Wayback Machine timeout for {target_url} (server is processing in background)")
            return f"https://web.archive.org/web/*/{target_url}"
        except Exception as e:
            logger.error(f"Failed to submit {target_url} to Wayback Machine: {e}")
            return None

    async def archive_targets(
        self,
        targets: List[TargetConfig],
        session: aiohttp.ClientSession
    ) -> Dict[str, Optional[str]]:
        """Archives all enabled targets with gentle 2-second delays to respect rate limits."""
        results: Dict[str, Optional[str]] = {}
        for target in targets:
            if not target.enabled:
                continue
            snapshot_url = await self.save_url(target.url, session=session)
            results[target.name] = snapshot_url
            await asyncio.sleep(2)  # Respect Wayback fair use
        return results
