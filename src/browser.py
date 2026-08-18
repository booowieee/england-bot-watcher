import asyncio
import math
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional, List
from playwright.async_api import async_playwright, Browser, Playwright
from src.config import Config
from src.logger import logger

BLOCKED_RESOURCE_TYPES = {"media"}
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

    async def capture_chunks(
        self,
        url: str,
        target_id: str,
        max_chunks: int = 3,
        viewport_height: int = 900,
        timeout_ms: int = 30000,
    ) -> List[str]:
        """
        Captures one or multiple human-readable viewport slices of a webpage.
        Prevents Telegram from compressing ultra-tall pages into unreadable strips.
        """
        if not Config.ENABLE_SCREENSHOTS:
            return []

        if not self._browser:
            await self.initialize()

        timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        generated_paths: List[str] = []
        context = None

        try:
            context = await self._browser.new_context(
                user_agent=Config.DEFAULT_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": viewport_height},
                device_scale_factor=1.25,
                locale="en-GB",
            )
            page = await context.new_page()
            await page.route("**/*", _route_blocker)

            logger.debug(f"Navigating to {url} for screenshots")
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            # Calculate total page height
            total_height = await page.evaluate(
                "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, 900)"
            )

            # If page is short (<= 1400px), capture a single clean screenshot
            if total_height <= 1400:
                output_path = Config.SCREENSHOTS_DIR / f"{target_id}_{timestamp_str}.png"
                await page.screenshot(
                    path=str(output_path),
                    full_page=True,
                    timeout=15000,
                    animations="disabled"
                )
                generated_paths.append(str(output_path))
            else:
                # If page is tall (like HOPS), split into readable viewport slices
                step = viewport_height - 100  # 100px overlap for context
                num_slices = min(max_chunks, math.ceil(total_height / step))

                for i in range(num_slices):
                    scroll_y = i * step
                    await page.evaluate(f"window.scrollTo(0, {scroll_y})")
                    await asyncio.sleep(0.3)

                    chunk_path = Config.SCREENSHOTS_DIR / f"{target_id}_{timestamp_str}_part{i+1}.png"
                    await page.screenshot(
                        path=str(chunk_path),
                        full_page=False,
                        timeout=15000,
                        animations="disabled"
                    )
                    generated_paths.append(str(chunk_path))

            logger.info(f"Captured {len(generated_paths)} screenshot(s) for {target_id}")
            return generated_paths

        except Exception as e:
            logger.error(f"Screenshot capture failed for {url}: {e}")
            return []
        finally:
            if context:
                await context.close()

    async def capture(self, url: str, target_id: str, timeout_ms: int = 30000) -> Optional[str]:
        """Convenience helper returning first screenshot path."""
        chunks = await self.capture_chunks(url, target_id, max_chunks=1, timeout_ms=timeout_ms)
        return chunks[0] if chunks else None


async def capture_screenshots(url: str, target_id: str, max_chunks: int = 3) -> List[str]:
    """Standalone convenience function for test mode."""
    engine = ScreenshotEngine()
    try:
        await engine.initialize()
        return await engine.capture_chunks(url, target_id, max_chunks=max_chunks)
    finally:
        await engine.close()
