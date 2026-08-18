import asyncio
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, Playwright
from src.config import Config
from src.logger import logger


BLOCKED_RESOURCE_TYPES = {"image", "font", "media", "stylesheet"}
BLOCKED_URL_FRAGMENTS = {"google-analytics", "googletagmanager", "facebook.net", "doubleclick"}


async def _route_blocker(route):
    if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
        await route.abort()
        return
    if any(frag in route.request.url for frag in BLOCKED_URL_FRAGMENTS):
        await route.abort()
        return
    await route.continue_()


class ScreenshotEngine:
    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    async def initialize(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        logger.info("Playwright browser initialized.")

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Playwright browser closed.")

    async def capture(self, url: str, target_id: str, timeout_ms: int = 30000) -> Optional[str]:
        if not Config.ENABLE_SCREENSHOTS:
            return None

        if not self._browser:
            await self.initialize()

        timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"{target_id}_{timestamp_str}.png"
        output_path = Config.SCREENSHOTS_DIR / filename

        context = None
        try:
            context = await self._browser.new_context(
                user_agent=Config.DEFAULT_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 900},
                locale="en-GB",
            )
            page = await context.new_page()
            await page.route("**/*", _route_blocker)

            logger.debug(f"Navigating to {url} for screenshot")
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            await page.screenshot(path=str(output_path), full_page=True)
            logger.info(f"Screenshot saved: {output_path}")
            return str(output_path)

        except Exception as e:
            logger.error(f"Screenshot capture failed for {url}: {e}")
            return None
        finally:
            if context:
                await context.close()


async def capture_screenshot(url: str, target_id: str, timeout_ms: int = 30000) -> Optional[str]:
    """Standalone convenience function for one-off captures (test mode)."""
    engine = ScreenshotEngine()
    try:
        await engine.initialize()
        return await engine.capture(url, target_id, timeout_ms)
    finally:
        await engine.close()
