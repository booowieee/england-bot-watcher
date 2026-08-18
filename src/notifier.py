import json
from pathlib import Path
from typing import Optional, List
import aiohttp
from src.config import Config
from src.logger import logger

TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024


class TelegramNotifier:
    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        self.token = token or Config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or Config.TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self._external_session = session
        self._owned_session: Optional[aiohttp.ClientSession] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id and ":" in self.token)

    @property
    def _session(self) -> aiohttp.ClientSession:
        if self._external_session and not self._external_session.closed:
            return self._external_session
        if not self._owned_session or self._owned_session.closed:
            self._owned_session = aiohttp.ClientSession()
        return self._owned_session

    async def close(self):
        if self._owned_session and not self._owned_session.closed:
            await self._owned_session.close()

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
            logger.warning("Telegram not configured, skipping notification.")
            return False

        inline_keyboard = {
            "inline_keyboard": [
                [{"text": "Открыть анкету", "url": url}]
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

    async def send_resolved(self, target_name: str, url: str) -> bool:
        if not self.is_configured:
            return False
        message = (
            f"<b>Форма закрыта</b>\n\n"
            f"<b>Цель:</b> {target_name}\n"
            f"<b>Ссылка:</b> <code>{url}</code>\n\n"
            f"Прием заявок прекращен."
        )
        return await self._send_message(message)

    async def send_heartbeat(self, status_summary: str) -> bool:
        if not self.is_configured:
            return False
        message = (
            f"<b>SWS Watcher: Статус мониторинга</b>\n\n"
            f"{status_summary}\n\n"
            f"<i>Интервал проверки: {Config.CHECK_INTERVAL_SECONDS}с.</i>"
        )
        return await self._send_message(message, disable_notification=True)

    async def _send_message(
        self,
        text: str,
        reply_markup: Optional[dict] = None,
        disable_notification: bool = False,
    ) -> bool:
        url = f"{self.api_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text[:TELEGRAM_TEXT_LIMIT],
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
            "disable_notification": disable_notification,
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)

        try:
            async with self._session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if resp.status == 200 and data.get("ok"):
                    logger.info("Telegram message sent.")
                    return True
                logger.error(f"Telegram API error: {data}")
                if resp.status == 400:
                    return await self._send_plaintext_fallback(text)
                return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def _send_plaintext_fallback(self, text: str) -> bool:
        url = f"{self.api_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text[:TELEGRAM_TEXT_LIMIT],
            "disable_notification": False,
        }
        try:
            async with self._session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                return resp.status == 200 and data.get("ok", False)
        except Exception:
            return False

    async def _send_photo(
        self,
        photo_path: str,
        caption: str,
        reply_markup: Optional[dict] = None,
    ) -> bool:
        url = f"{self.api_url}/sendPhoto"

        try:
            data = aiohttp.FormData()
            data.add_field("chat_id", self.chat_id)
            data.add_field("caption", caption[:TELEGRAM_CAPTION_LIMIT])
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
                content_type="image/png",
            )

            async with self._session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp_data = await resp.json()
                if resp.status == 200 and resp_data.get("ok"):
                    logger.info("Telegram photo sent.")
                    return True
                logger.error(f"Telegram sendPhoto error: {resp_data}")
                return await self._send_message(caption, reply_markup)

        except Exception as e:
            logger.error(f"Failed to send Telegram photo: {e}")
            return await self._send_message(caption, reply_markup)
