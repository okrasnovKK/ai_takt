"""ai-takt — Event-Manager-Agent Telegram Bot entry point.

Run: python -m src.bot
"""
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import BOT_TOKEN, TEAM_CHAT_ID
from src.services.database import UserDatabase
from src.services.messenger import Messenger
from src.services.message_logger import MessageLogger
from src.services.survey_service import SurveyState
from src.services.pulse_survey_service import PulseSurveyState
from src.services.event_service import EventService
from src.services.holiday_decor_service import HolidayDecorState
from src.handlers.handlers import register_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Starting ai-takt bot...")
    logger.info("Team chat ID: %s", TEAM_CHAT_ID)

    # Init bot
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Init services
    db = UserDatabase()
    messenger = Messenger(bot, db)
    msg_logger = MessageLogger()
    survey = SurveyState()
    pulse_survey = PulseSurveyState()
    event_service = EventService()
    decor = HolidayDecorState()

    # Init dispatcher
    dp = Dispatcher()
    router = Router(name="main")

    # Register handlers
    register_handlers(router, db, messenger, msg_logger, survey, pulse_survey, event_service, decor)
    dp.include_router(router)

    # Log startup info (no automatic message to chat — prevents duplicate greetings)
    bot_info = await bot.get_me()
    logger.info("Bot started: @%s (ID: %s)", bot_info.username, bot_info.id)

    # Start polling
    logger.info("Starting polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())