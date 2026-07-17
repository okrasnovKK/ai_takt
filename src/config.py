"""Bot configuration loaded from .env file."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
TEAM_CHAT_ID: int = int(os.getenv("TEAM_CHAT_ID", "0"))
LPR_USER_ID: int = int(os.getenv("LPR_USER_ID", "0"))
"""User ID of the Лицо Принимающее Решения (LPR).

Указывается в .env: LPR_USER_ID=123456789
Если не указан (0), то ЛПР считается тот, кто вводит команды управления
мероприятиями. Рекомендуется явно указать для корректной маршрутизации
предложений и смет только в личку ЛПР, минуя общий командный чат.
"""

OUROBOROS_WS_URL: str = os.getenv("OUROBOROS_WS_URL", "ws://localhost:8765/ws")
"""WebSocket URL for Ouroboros agent connection.
Used by /obo command to bridge Telegram messages to Ouroboros.
"""

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set in .env file")
if not TEAM_CHAT_ID:
    raise ValueError("TEAM_CHAT_ID not set in .env file")