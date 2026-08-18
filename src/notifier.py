import json
from pathlib import Path
from typing import Optional, List
import aiohttp
from src.config import Config
from src.logger import logger


class TelegramNotifier:
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
        if not self.is_configured:
            logger.warning("Telegram Bot is not configured. Skipping notification.")
            return False

        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "Открыть анкету", "url": url}
                ]
            ]
        }

        caption = (
            f"<b>{title}</b>\n\n"
            f"<b>Цель:</b> {target_name}\n"
            f"<b>Ссылка:</b> <code>{url}</code>\n\n"
            f"<b>Детали:</b>\n{details}\n"
        )

        if detected_links:
            caption += "\n<b>Обнаруженные ссылки:</b>\n"
            for link in detected_links[:5]:
                caption += f"- <code>{link}</code>\n"

        if screenshot_path and Path(screenshot_path).is_file():
            return await self._send_photo(screenshot_path, caption, inline_keyboard)
        return await self._send_message(caption, inline_keyboard)

    async def send_heartbeat(self, status_summary: str) -> bool:
        if not self.is_configured:
            return False

        message = (
            f"<b>SWS Watcher: Статус мониторинга</b>\n\n"
            f"{status_summary}\n\n"
            f"<i>Интервал проверки: {Config.CHECK_INTERVAL_SECONDS}с.</i>"
        )
        return await self._send_message(message)

    async def _send_message(self, text: str, reply_markup: Optional[dict] = None) -> bool:
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
                        logger.info("Telegram message sent successfully.")
                        return True
                    logger.error(f"Telegram API error: {data}")
                    return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def _send_photo(self, photo_path: str, caption: str, reply_markup: Optional[dict] = None) -> bool:
        url = f"{self.api_url}/sendPhoto"

        try:
            data = aiohttp.FormData()
            data.add_field("chat_id", self.chat_id)
            data.add_field("caption", caption[:1024])
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
                        logger.info("Telegram photo sent successfully.")
                        return True
                    logger.error(f"Telegram sendPhoto error: {resp_data}")
                    return await self._send_message(caption, reply_markup)

        except Exception as e:
            logger.error(f"Failed to send Telegram photo: {e}")
            return await self._send_message(caption, reply_markup)
