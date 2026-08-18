import json
import shutil
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, Any, List
from src.config import Config
from src.logger import logger


class WhitelistManager:
    def __init__(self, file_path: Path | None = None):
        self.file_path = file_path or Config.WHITELIST_FILE
        self.users: Dict[str, Dict[str, Any]] = self._load()
        self._ensure_admin()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self.file_path.is_file():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load whitelist: {e}")
        return {}

    def _save(self) -> None:
        try:
            temp_file = self.file_path.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.users, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.file_path)
        except Exception as e:
            logger.error(f"Failed to save whitelist: {e}")

    def _ensure_admin(self) -> None:
        admin_id = str(Config.ADMIN_CHAT_ID).strip()
        if admin_id and admin_id not in self.users:
            self.users[admin_id] = {
                "chat_id": admin_id,
                "username": "admin",
                "first_name": "Primary Admin",
                "is_admin": True,
                "created_at": datetime.now(UTC).isoformat(),
            }
            self._save()
            logger.info(f"Primary admin registered in whitelist: {admin_id}")

    def is_allowed(self, chat_id: str | int) -> bool:
        cid = str(chat_id).strip()
        return cid in self.users or cid == str(Config.ADMIN_CHAT_ID) or cid == str(Config.TELEGRAM_CHAT_ID)

    def is_admin(self, chat_id: str | int) -> bool:
        cid = str(chat_id).strip()
        if cid == str(Config.ADMIN_CHAT_ID) or cid == str(Config.TELEGRAM_CHAT_ID):
            return True
        user = self.users.get(cid, {})
        return user.get("is_admin", False)

    def add_user(self, chat_id: str | int, username: str = "", first_name: str = "") -> bool:
        cid = str(chat_id).strip()
        if not cid:
            return False
        self.users[cid] = {
            "chat_id": cid,
            "username": username or "",
            "first_name": first_name or "",
            "is_admin": False,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self._save()
        logger.info(f"User added to whitelist: ID {cid} (@{username})")
        return True

    def remove_user(self, chat_id: str | int) -> bool:
        cid = str(chat_id).strip()
        if cid in self.users:
            if self.is_admin(cid):
                logger.warning(f"Cannot revoke access from primary admin {cid}")
                return False
            del self.users[cid]
            self._save()
            logger.info(f"User removed from whitelist: ID {cid}")
            return True
        return False

    def get_all_chat_ids(self) -> List[str]:
        ids = list(self.users.keys())
        admin_id = str(Config.ADMIN_CHAT_ID).strip()
        if admin_id and admin_id not in ids:
            ids.append(admin_id)
        chat_id = str(Config.TELEGRAM_CHAT_ID).strip()
        if chat_id and chat_id not in ids:
            ids.append(chat_id)
        return ids

    def get_users_report(self) -> str:
        lines = ["<b>Список пользователей с доступом к боту:</b>\n"]
        for cid, u in self.users.items():
            tag = "Администратор" if u.get("is_admin") else "Пользователь"
            uname = f"@{u['username']}" if u.get("username") else u.get("first_name", "—")
            lines.append(f"• <code>{cid}</code> — {uname} (<i>{tag}</i>)")
        return "\n".join(lines)
