"""
Headless browser module utilizing Playwright to capture high-definition full-page screenshots.
"""
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright
from src.config import Config
from src.logger import logger


class ScreenshotEngine:
    """Manages headless browser instances for capturing alert screenshots."""

    @staticmethod
    async def capture(url: str, target_id: str, timeout_ms: int = 30000) -> Optional[str]:
        """
        Navigates to the specified URL using Playwright Chromium and saves a full-page PNG screenshot.
        Returns the absolute file path of the saved image, or None if failed.
        """
        if not Config.ENABLE_SCREENSHOTS:
            return None

        timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{target_id}_{timestamp_str}.png"
        output_path = Config.SCREENSHOTS_DIR / filename

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ]
                )
                context = await browser.new_context(
                    user_agent=Config.DEFAULT_HEADERS["User-Agent"],
                    viewport={"width": 1280, "height": 900},
                    locale="en-GB",
                )
                page = await context.new_page()

                logger.debug(f"Opening page for screenshot: {url}")
                # Use domcontentloaded to handle heavy JS gracefully
                await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                
                # Give a short delay for dynamic JS components to render
                await asyncio.sleep(2.0)

                await page.screenshot(path=str(output_path), full_page=True)
                await browser.close()

                logger.info(f"Screenshot successfully captured: {output_path}")
                return str(output_path)

        except Exception as e:
            logger.error(f"Failed to capture screenshot for {url}: {e}", exc_info=True)
            return None
