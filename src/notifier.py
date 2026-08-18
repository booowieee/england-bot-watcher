"""
Telegram Bot notification engine for instant alerts, screenshots, and heartbeat reports.
"""
import json
from pathlib import Path
from typing import Optional, List
import aiohttp
from src.config import Config
from src.logger import logger


class TelegramNotifier:
    """Handles communications with Telegram Bot API."""

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or Config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or Config.TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}"

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id and ":" in self.token)

    async def send_alert(
        self,
        title: str,
        target_name: str,
        url: str,
        details: str,
        screenshot_path: Optional[str] = None,
        detected_links: Optional[List[str]] = None,
    ) -> bool:
        """
        Sends an urgent, high-priority alert to Telegram with HTML formatting,
        an optional screenshot, and an inline direct action button.
        """
        if not self.is_configured:
            logger.warning("Telegram Bot is not configured (missing token or chat_id). Skipping alert.")
            return False

        # Build inline keyboard button for 1-click action
        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🚀 Открыть анкету прямо сейчас", "url": url}
                ]
            ]
        }

        # Build formatted message
        caption = (
            f"🚨 <b>{title}</b>\n\n"
            f"🎯 <b>Цель:</b> {target_name}\n"
            f"🔗 <b>Ссылка:</b> <code>{url}</code>\n\n"
            f"📝 <b>Детали изменения:</b>\n{details}\n"
        )

        if detected_links:
            caption += "\n🔍 <b>Обнаруженные ссылки:</b>\n"
            for link in detected_links[:5]:
                caption += f"• <code>{link}</code>\n"

        caption += "\n⚡ <i>Срочно перейдите по ссылке и заполните анкету!</i>"

        # If a screenshot is available, send via sendPhoto
        if screenshot_path and Path(screenshot_path).is_file():
            return await self._send_photo(screenshot_path, caption, inline_keyboard)
        else:
            return await self._send_message(caption, inline_keyboard)

    async def send_heartbeat(self, status_summary: str) -> bool:
        """Sends a periodic status/heartbeat message confirming monitoring is active."""
        if not self.is_configured:
            return False

        message = (
            f"🟢 <b>SWS Bot Watcher: Мониторинг активен</b>\n\n"
            f"📊 <b>Статус отслеживания:</b>\n{status_summary}\n\n"
            f"⏱ <i>Интервал проверки: {Config.CHECK_INTERVAL_SECONDS} сек. Все системы в норме.</i>"
        )
        return await self._send_message(message)

    async def _send_message(self, text: str, reply_markup: Optional[dict] = None) -> bool:
        """Sends a text message using sendMessage."""
        url = f"{self.api_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
            "disable_notification": False,
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=15) as resp:
                    data = await resp.json()
                    if resp.status == 200 and data.get("ok"):
                        logger.info("Telegram message successfully sent.")
                        return True
                    else:
                        logger.error(f"Telegram API error: {data}")
                        return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def _send_photo(self, photo_path: str, caption: str, reply_markup: Optional[dict] = None) -> bool:
        """Sends a photo with caption and inline keyboard using sendPhoto (multipart/form-data)."""
        url = f"{self.api_url}/sendPhoto"

        try:
            data = aiohttp.FormData()
            data.add_field("chat_id", self.chat_id)
            data.add_field("caption", caption[:1024])  # Telegram limit for captions
            data.add_field("parse_mode", "HTML")
            data.add_field("disable_notification", "false")
            if reply_markup:
                data.add_field("reply_markup", json.dumps(reply_markup))

            with open(photo_path, "rb") as f:
                photo_bytes = f.read()

            data.add_field(
                "photo",
                photo_bytes,
                filename=Path(photo_path).name,
                content_type="image/png"
            )

            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data, timeout=30) as resp:
                    resp_data = await resp.json()
                    if resp.status == 200 and resp_data.get("ok"):
                        logger.info("Telegram photo alert successfully sent.")
                        return True
                    else:
                        logger.error(f"Telegram sendPhoto error: {resp_data}")
                        # Fallback to plain text message
                        return await self._send_message(caption, reply_markup)

        except Exception as e:
            logger.error(f"Failed to send Telegram photo: {e}")
            # Fallback to plain text message
            return await self._send_message(caption, reply_markup)
