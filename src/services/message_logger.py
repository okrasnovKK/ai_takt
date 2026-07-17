"""Message Logger — сохраняет все входящие сообщения в JSONL-файл.

Позволяет Ouroboros читать входящие сообщения от пользователей
без необходимости пересылать их вручную.

Файл: ai-takt/data/incoming_messages.jsonl
Формат: одна JSON-строка на сообщение.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aiogram.types import Message

logger = logging.getLogger(__name__)


class MessageLogger:
    """Appends incoming Telegram messages to a JSONL file for Ouroboros to read."""

    def __init__(self, log_dir: Optional[Path] = None):
        if log_dir is None:
            # ai-takt/data/incoming_messages.jsonl
            log_dir = Path(__file__).parent.parent.parent / "data"
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / "incoming_messages.jsonl"
        logger.info("MessageLogger initialized: %s", self.log_path)

    def log_message(self, message: Message) -> None:
        """Record an incoming message to the JSONL file."""
        user = message.from_user
        if not user:
            return

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user.id,
            "username": user.username or "",
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "text": message.text or "",
            "chat_id": message.chat.id,
            "message_id": message.message_id,
            "is_private": message.chat.type == "private",
        }

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
            logger.debug("Logged message from user %s", user.id)
        except Exception as e:
            logger.error("Failed to log message from user %s: %s", user.id, e)

    def get_recent_messages(self, limit: int = 50) -> list[dict]:
        """Read the last N messages from the log file."""
        if not self.log_path.exists():
            return []

        messages = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            messages.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error("Failed to read message log: %s", e)
            return []

        return messages[-limit:]