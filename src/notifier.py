import asyncio
import json
from pathlib import Path
from typing import Optional, List, Any
import aiohttp
from src.config import Config
from src.logger import logger
from src.whitelist import WhitelistManager

TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024


class TelegramNotifier:
    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        token: Optional[str] = None,
        admin_chat_id: Optional[str] = None,
    ):
        self.token = token or Config.TELEGRAM_BOT_TOKEN
        self.admin_chat_id = admin_chat_id or Config.ADMIN_CHAT_ID or Config.TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self._external_session = session
        self._owned_session: Optional[aiohttp.ClientSession] = None
        self._is_polling = False
        self.whitelist = WhitelistManager()

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.admin_chat_id and ":" in self.token)

    @property
    def _session(self) -> aiohttp.ClientSession:
        if self._external_session and not self._external_session.closed:
            return self._external_session
        if not self._owned_session or self._owned_session.closed:
            self._owned_session = aiohttp.ClientSession()
        return self._owned_session

    async def close(self):
        self._is_polling = False
        if self._owned_session and not self._owned_session.closed:
            await self._owned_session.close()

    async def send_alert(
        self,
        title: str,
        target_name: str,
        url: str,
        details: str,
        screenshots: Optional[List[str]] = None,
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

        valid_screenshots = [p for p in (screenshots or []) if Path(p).is_file()]
        target_chat_ids = self.whitelist.get_all_chat_ids()

        if not target_chat_ids:
            target_chat_ids = [self.admin_chat_id]

        overall_success = True

        for cid in target_chat_ids:
            if not valid_screenshots:
                ok = await self._send_message_to(cid, caption, inline_keyboard)
                if not ok:
                    overall_success = False
            else:
                total = len(valid_screenshots)
                for i, photo_path in enumerate(valid_screenshots):
                    part_label = f" (Часть {i+1}/{total})" if total > 1 else ""
                    part_caption = f"<b>{title}</b>{part_label}\n<b>Цель:</b> {target_name}\n\n{details}" if i == 0 else f"<b>{target_name}</b>{part_label}"
                    markup = inline_keyboard if (i == total - 1) else None
                    ok = await self._send_photo_to(cid, photo_path, part_caption, markup)
                    if not ok:
                        overall_success = False

        return overall_success

    async def send_resolved(self, target_name: str, url: str) -> bool:
        if not self.is_configured:
            return False
        message = (
            f"<b>Форма закрыта</b>\n\n"
            f"<b>Цель:</b> {target_name}\n"
            f"<b>Ссылка:</b> <code>{url}</code>\n\n"
            f"Прием заявок прекращен."
        )
        for cid in self.whitelist.get_all_chat_ids():
            await self._send_message_to(cid, message)
        return True

    async def send_heartbeat(self, status_summary: str) -> bool:
        if not self.is_configured:
            return False
        message = (
            f"<b>SWS Watcher: Статус мониторинга</b>\n\n"
            f"{status_summary}\n\n"
            f"<i>Интервал проверки: {Config.CHECK_INTERVAL_SECONDS}с.</i>"
        )
        for cid in self.whitelist.get_all_chat_ids():
            await self._send_message_to(cid, message, disable_notification=True)
        return True

    async def _send_message_to(
        self,
        chat_id: str,
        text: str,
        reply_markup: Optional[dict] = None,
        disable_notification: bool = False,
    ) -> bool:
        url = f"{self.api_url}/sendMessage"
        payload = {
            "chat_id": chat_id,
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
                    return True
                logger.error(f"Telegram API error for chat {chat_id}: {data}")
                if resp.status == 400:
                    return await self._send_plaintext_fallback_to(chat_id, text)
                return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message to {chat_id}: {e}")
            return False

    async def _send_plaintext_fallback_to(self, chat_id: str, text: str) -> bool:
        url = f"{self.api_url}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text[:TELEGRAM_TEXT_LIMIT],
            "disable_notification": False,
        }
        try:
            async with self._session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                return resp.status == 200 and data.get("ok", False)
        except Exception:
            return False

    async def _send_photo_to(
        self,
        chat_id: str,
        photo_path: str,
        caption: str,
        reply_markup: Optional[dict] = None,
    ) -> bool:
        url = f"{self.api_url}/sendPhoto"

        try:
            data = aiohttp.FormData()
            data.add_field("chat_id", str(chat_id))
            data.add_field("caption", caption[:TELEGRAM_CAPTION_LIMIT])
            data.add_field("parse_mode", "HTML")
            data.add_field("disable_notification", "false")
            if reply_markup:
                data.add_field("reply_markup", json.dumps(reply_markup))

            photo_bytes = await asyncio.to_thread(Path(photo_path).read_bytes)
            data.add_field(
                "photo",
                photo_bytes,
                filename=Path(photo_path).name,
                content_type="image/png",
            )

            async with self._session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp_data = await resp.json()
                if resp.status == 200 and resp_data.get("ok"):
                    return True
                logger.error(f"Telegram sendPhoto error for chat {chat_id}: {resp_data}")
                return await self._send_message_to(chat_id, caption, reply_markup)

        except Exception as e:
            logger.error(f"Failed to send Telegram photo to {chat_id}: {e}")
            return await self._send_message_to(chat_id, caption, reply_markup)

    async def _answer_callback_query(self, callback_id: str, text: str) -> None:
        url = f"{self.api_url}/answerCallbackQuery"
        payload = {"callback_query_id": callback_id, "text": text}
        try:
            async with self._session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)):
                pass
        except Exception:
            pass

    async def _edit_message_text(self, chat_id: str, message_id: int, text: str) -> None:
        url = f"{self.api_url}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
        }
        try:
            async with self._session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)):
                pass
        except Exception:
            pass

    async def start_polling(self, engine: Any) -> None:
        """Asynchronous long-polling task for processing Telegram commands and access requests."""
        if not self.is_configured:
            logger.warning("Telegram not configured, command listener disabled.")
            return

        self._is_polling = True
        offset = 0
        logger.info("Telegram command listener & whitelist manager started.")

        while self._is_polling:
            try:
                url = f"{self.api_url}/getUpdates"
                params = {"offset": offset, "timeout": 25}
                async with self._session.get(
                    url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=35)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for update in data.get("result", []):
                            offset = update["update_id"] + 1

                            # 1. Handle Callback Query from Admin
                            callback = update.get("callback_query")
                            if callback:
                                await self._handle_callback(callback)
                                continue

                            # 2. Handle Messages
                            message = update.get("message")
                            if not message:
                                continue

                            chat = message.get("chat", {})
                            chat_id = str(chat.get("id", ""))
                            from_user = message.get("from", {})
                            username = from_user.get("username", "")
                            first_name = from_user.get("first_name", "")
                            text = message.get("text", "").strip()

                            if not chat_id:
                                continue

                            # Check whitelist access
                            if not self.whitelist.is_allowed(chat_id):
                                await self._handle_unauthorized_user(chat_id, username, first_name)
                                continue

                            # Process authorized commands
                            if text.startswith("/"):
                                await self._handle_command(chat_id, text, engine)
                    else:
                        await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Telegram polling exception: {e}")
                await asyncio.sleep(5)

    async def _handle_unauthorized_user(self, chat_id: str, username: str, first_name: str) -> None:
        """Notifies admin about a new access request and informs the user."""
        logger.info(f"Access request from unauthorized user: {chat_id} (@{username})")

        # Reply to user
        await self._send_message_to(
            chat_id,
            "⏳ <b>Запрос на доступ отправлен</b>\n\n"
            "Ваш ID не найден в белом списке. Администратор бота получил уведомление. "
            "Как только доступ будет одобрен, вы получите сообщение."
        )

        # Notify Admin with inline buttons
        uname_display = f"@{username}" if username else first_name or "Не указано"
        admin_msg = (
            "<b>Запрос на доступ к SWS Watcher Bot</b>\n\n"
            f"<b>Пользователь:</b> {uname_display}\n"
            f"<b>Имя:</b> {first_name}\n"
            f"<b>ID:</b> <code>{chat_id}</code>\n\n"
            "Предоставить доступ к боту и рассылке алертов?"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "Одобрить", "callback_data": f"auth_approve:{chat_id}:{username}"},
                    {"text": "Отклонить", "callback_data": f"auth_deny:{chat_id}:{username}"},
                ]
            ]
        }
        await self._send_message_to(self.admin_chat_id, admin_msg, reply_markup=keyboard)

    async def _handle_callback(self, callback: dict) -> None:
        """Handles admin approval or rejection of access requests."""
        callback_id = callback.get("id")
        from_id = str(callback.get("from", {}).get("id", ""))
        data = callback.get("data", "")
        message = callback.get("message", {})
        msg_id = message.get("message_id")
        chat_id = str(message.get("chat", {}).get("id", ""))

        if not self.whitelist.is_admin(from_id):
            await self._answer_callback_query(callback_id, "Только администратор может одобрять доступ.")
            return

        if data.startswith("auth_approve:"):
            _, target_cid, target_uname = data.split(":", 2)
            self.whitelist.add_user(target_cid, username=target_uname)
            await self._answer_callback_query(callback_id, "Доступ одобрен!")

            if msg_id:
                await self._edit_message_text(
                    chat_id, msg_id,
                    f"<b>Доступ одобрен</b> для пользователя @{target_uname} (<code>{target_cid}</code>)."
                )

            # Inform approved user
            await self._send_message_to(
                target_cid,
                "<b>Доступ предоставлен!</b>\n\n"
                "Администратор одобрил ваш доступ к SWS Watcher Bot.\n"
                "Вы будете получать уведомления об открытии анкет операторов UK SWS.\n\n"
                "<b>Команды управления:</b>\n"
                "/status — Текущий статус целей\n"
                "/check — Полная визуальная проверка прямо сейчас\n"
                "/help — Справка"
            )

        elif data.startswith("auth_deny:"):
            _, target_cid, target_uname = data.split(":", 2)
            await self._answer_callback_query(callback_id, "Запрос отклонен.")

            if msg_id:
                await self._edit_message_text(
                    chat_id, msg_id,
                    f"<b>Запрос отклонен</b> для пользователя @{target_uname} (<code>{target_cid}</code>)."
                )

            # Inform rejected user
            await self._send_message_to(
                target_cid,
                "<b>В доступе отказано</b>\n\nАдминистратор отклонил ваш запрос на доступ к боту."
            )

    async def _handle_command(self, chat_id: str, text: str, engine: Any) -> None:
        parts = text.split()
        cmd = parts[0].lower() if parts else ""
        is_adm = self.whitelist.is_admin(chat_id)

        if cmd in ("/start", "/help"):
            admin_section = (
                "\n\n<b>Команды администратора:</b>\n"
                "/users — Список пользователей с доступом\n"
                "/revoke <id> — Отозвать доступ у пользователя\n"
                "/add <id> — Добавить пользователя вручную"
            ) if is_adm else ""

            msg = (
                "<b>SWS Watcher Bot</b>\n\n"
                "Сервис непрерывного мониторинга визовых операторов UK SWS.\n\n"
                "<b>Доступные команды:</b>\n"
                "/status — Текстовый отчет о статусе всех ресурсов\n"
                "/check — Полная визуальная проверка со скриншотами\n"
                "/help — Справка по командам"
                f"{admin_section}"
            )
            await self._send_message_to(chat_id, msg)

        elif cmd == "/status":
            report = engine.get_status_report()
            await self._send_message_to(chat_id, report)

        elif cmd == "/check":
            await self._send_message_to(chat_id, "Запускаю внеочередную проверку всех ресурсов со скриншотами...")
            await engine.run_manual_visual_check_for(chat_id)

        elif cmd in ("/users", "/whitelist") and is_adm:
            report = self.whitelist.get_users_report()
            await self._send_message_to(chat_id, report)

        elif cmd == "/revoke" and is_adm:
            if len(parts) < 2:
                await self._send_message_to(chat_id, "Использование: <code>/revoke <ID></code>")
                return
            target_id = parts[1].strip()
            if self.whitelist.remove_user(target_id):
                await self._send_message_to(chat_id, f"Доступ пользователя <code>{target_id}</code> успешно отозван.")
                await self._send_message_to(target_id, "Ваш доступ к SWS Watcher Bot был отозван администратором.")
            else:
                await self._send_message_to(chat_id, f"Не удалось отозвать доступ (пользователь не найден или является главным админом).")

        elif cmd == "/add" and is_adm:
            if len(parts) < 2:
                await self._send_message_to(chat_id, "Использование: <code>/add <ID> [username]</code>")
                return
            target_id = parts[1].strip()
            uname = parts[2].strip() if len(parts) > 2 else ""
            if self.whitelist.add_user(target_id, username=uname):
                await self._send_message_to(chat_id, f"Пользователь <code>{target_id}</code> добавлен в белый список.")
                await self._send_message_to(target_id, "Вам предоставлен доступ к SWS Watcher Bot!")
            else:
                await self._send_message_to(chat_id, "Не удалось добавить пользователя.")
