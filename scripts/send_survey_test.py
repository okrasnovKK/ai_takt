"""Send onboarding survey to Ekaterina Kabankova."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, r'C:\Users\User\ai-takt')
sys.stdout.reconfigure(encoding='utf-8')

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import BOT_TOKEN
from src.services.survey_service import (
    SurveyState,
    get_first_reminder_text,
    get_survey_intro_text,
    get_survey_questions_text,
)

USER_ID = 467612821
FIRST_NAME = "Екатерина"

async def main():
    # Step 1: Set survey state to "new_member_alerted"
    survey = SurveyState()
    survey.set_state(USER_ID, "new_member_alerted")
    print(f"[OK] Survey state set to 'new_member_alerted' for user {USER_ID}")

    # Step 2: Send welcome DM
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    welcome_text = get_first_reminder_text()
    msg = await bot.send_message(chat_id=USER_ID, text=welcome_text)
    print(f"[OK] Welcome DM sent to Ekaterina (Message ID: {msg.message_id})")

    await bot.session.close()
    print("[OK] Done!")

asyncio.run(main())