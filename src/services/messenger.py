"""Messenger service for sending messages to team chat and personal messages."""
import logging
from typing import Optional, Union

from aiogram import Bot
from aiogram.types import Message, FSInputFile

from src.config import TEAM_CHAT_ID
from src.services.database import UserDatabase

logger = logging.getLogger(__name__)


class Messenger:
    """Handles sending messages to the team chat and personal DMs."""

    # Анти-дубликат: запоминаем последнее отправленное фото/видео/текст
    _last_photo_key = None
    _last_photo_at = 0.0
    _last_text_key = None
    _last_text_at = 0.0
    _last_video_key = None
    _last_video_at = 0.0
    DEDUP_WINDOW_SEC = 60.0

    def __init__(self, bot: Bot, db: UserDatabase):
        self.bot = bot
        self.db = db

    async def send_to_team_chat(self, text: str,
                                parse_mode: Optional[str] = None) -> Optional[Message]:
        """Send a message to the main team chat."""
        # Анти-дубликат: тот же текст в течение 60 секунд
        import time
        _text_key = f"text|{text}"
        if _text_key == self._last_text_key and (time.time() - self._last_text_at) < self.DEDUP_WINDOW_SEC:
            logger.warning("DUPLICATE BLOCKED: same text sent %0.1fs ago — skipping", time.time() - self._last_text_at)
            return None
        try:
            msg = await self.bot.send_message(
                chat_id=TEAM_CHAT_ID,
                text=text,
                parse_mode=parse_mode,
            )
            self._last_text_key = _text_key
            self._last_text_at = time.time()
            logger.info("Sent message to team chat %s", TEAM_CHAT_ID)
            return msg
        except Exception as e:
            logger.error("Failed to send to team chat %s: %s", TEAM_CHAT_ID, e)
            return None

    async def send_to_event_chat(self, chat_id: int, text: str,
                                 parse_mode: Optional[str] = None) -> Optional[Message]:
        """Send a message to the event-specific chat.

        Args:
            chat_id: Telegram chat ID of the event group.
            text: Message text.
            parse_mode: Optional parse mode for formatting.

        Returns:
            Optional[Message]: sent message or None on error.
        """
        if not chat_id or chat_id == -1:
            logger.warning("send_to_event_chat called with invalid chat_id=%s", chat_id)
            return None
        try:
            msg = await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
            )
            logger.info("Sent message to event chat %s (msg_id=%s)", chat_id, msg.message_id)
            return msg
        except Exception as e:
            logger.error("Failed to send to event chat %s: %s", chat_id, e)
            return None

    async def send_to_user(self, user_id: int, text: str,
                           parse_mode: Optional[str] = None) -> bool:
        """Send a personal message to a specific user.

        Returns True if sent successfully, False if the user hasn't
        interacted with the bot or the send failed.
        """
        user = self.db.get_user(user_id)
        if not user:
            logger.warning("User %s not found in database", user_id)
            return False

        try:
            await self.bot.send_message(
                chat_id=user["chat_id"],
                text=text,
                parse_mode=parse_mode,
            )
            logger.info("Sent personal message to user %s", user_id)
            return True
        except Exception as e:
            logger.error("Failed to send to user %s: %s", user_id, e)
            return False

    async def broadcast_to_all_users(self, text: str,
                                     parse_mode: Optional[str] = None) -> dict:
        """Send a message to ALL registered users.

        Returns a dict with {user_id: success_bool}.
        """
        results = {}
        for uid, user in self.db.get_all_users().items():
            success = await self.send_to_user(int(uid), text, parse_mode)
            results[uid] = success
        return results

    async def send_photo_to_team_chat(
        self,
        photo: Union[str, FSInputFile],
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> Optional[Message]:
        """Send a photo to the main team chat.

        ЕДИНСТВЕННЫЙ метод для отправки фото — всегда используй его,
        чтобы не допустить дублирования отправки.

        Анти-дубликат: если то же фото (путь + подпись) уже отправлялось
        в течение DEDUP_WINDOW_SEC секунд, возвращаем None и логируем предупреждение.

        Args:
            photo: Путь к файлу (str) или FSInputFile.
            caption: Подпись к фото.
            parse_mode: Parse mode для caption.

        Returns:
            Optional[Message]: отправленное сообщение или None при ошибке/дубликате.
        """
        import time
        # Определяем ключ для дедупликации
        photo_path = str(photo) if isinstance(photo, str) else str(photo.path) if hasattr(photo, 'path') else str(photo)
        key = f"{photo_path}|{caption}"

        now = time.time()
        if key == self._last_photo_key and (now - self._last_photo_at) < self.DEDUP_WINDOW_SEC:
            logger.warning(
                "DUPLICATE BLOCKED: same photo+caption sent %0.1fs ago — skipping",
                now - self._last_photo_at,
            )
            return None

        try:
            if isinstance(photo, str):
                photo = FSInputFile(photo)
            msg = await self.bot.send_photo(
                chat_id=TEAM_CHAT_ID,
                photo=photo,
                caption=caption,
                parse_mode=parse_mode,
            )
            # Запоминаем успешную отправку
            self._last_photo_key = key
            self._last_photo_at = time.time()
            logger.info(
                "Sent photo to team chat %s (message_id=%s)",
                TEAM_CHAT_ID, msg.message_id,
            )
            return msg
        except Exception as e:
            logger.error("Failed to send photo to team chat %s: %s", TEAM_CHAT_ID, e)
            return None

    async def send_video_to_team_chat(
        self,
        video: Union[str, FSInputFile],
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> Optional[Message]:
        """Send a video to the main team chat.

        ЕДИНСТВЕННЫЙ метод для отправки видео — всегда используй его,
        чтобы не допустить дублирования отправки.

        Анти-дубликат: если то же видео (путь + подпись) уже отправлялось
        в течение DEDUP_WINDOW_SEC секунд, возвращаем None и логируем предупреждение.
        """
        import time
        video_path = str(video) if isinstance(video, str) else str(video.path) if hasattr(video, 'path') else str(video)
        key = f"{video_path}|{caption}"

        now = time.time()
        if key == self._last_video_key and (now - self._last_video_at) < self.DEDUP_WINDOW_SEC:
            logger.warning(
                "DUPLICATE BLOCKED: same video+caption sent %0.1fs ago — skipping",
                now - self._last_video_at,
            )
            return None

        try:
            if isinstance(video, str):
                video = FSInputFile(video)
            msg = await self.bot.send_video(
                chat_id=TEAM_CHAT_ID,
                video=video,
                caption=caption,
                parse_mode=parse_mode,
            )
            self._last_video_key = key
            self._last_video_at = time.time()
            logger.info(
                "Sent video to team chat %s (message_id=%s)",
                TEAM_CHAT_ID, msg.message_id,
            )
            return msg
        except Exception as e:
            logger.error("Failed to send video to team chat %s: %s", TEAM_CHAT_ID, e)
            return None

    async def send_photo_to_user(
        self,
        user_id: int,
        photo: Union[str, FSInputFile],
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> bool:
        """Send a photo to a specific user.

        Returns True if sent successfully, False otherwise.
        """
        user = self.db.get_user(user_id)
        if not user:
            logger.warning("User %s not found in database", user_id)
            return False

        try:
            if isinstance(photo, str):
                photo = FSInputFile(photo)
            await self.bot.send_photo(
                chat_id=user["chat_id"],
                photo=photo,
                caption=caption,
                parse_mode=parse_mode,
            )
            logger.info("Sent photo to user %s", user_id)
            return True
        except Exception as e:
            logger.error("Failed to send photo to user %s: %s", user_id, e)
            return False