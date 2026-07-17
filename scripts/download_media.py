
import asyncio, os, sys, json
sys.path.insert(0, r'C:\Users\User\ai-takt')
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv(r'C:\Users\User\ai-takt\.env')
BOT_TOKEN = os.getenv('BOT_TOKEN')

from aiogram import Bot
from aiogram.types import Message

async def download_media():
    bot = Bot(token=BOT_TOKEN)
    input_dir = r'C:\Users\User\Ouroboros\Deliverables\video_media\input'
    os.makedirs(input_dir, exist_ok=True)
    
    # Олег Краснов — user_id=2043389803, message_ids 158-162
    user_id = 2043389803
    message_ids = [158, 159, 160, 161, 162]
    
    downloaded = []
    for msg_id in message_ids:
        try:
            msg = await bot.forward_message(
                chat_id=user_id,
                from_chat_id=user_id,
                message_id=msg_id
            )
            # Actually, we can't forward to ourselves. Let's try get_chat and get the message directly
            # Better approach: use bot.get_chat and then get the message
            # Actually in aiogram 3.x we can't easily get old messages by ID from private chat
            # Let's try a different approach
        except Exception as e:
            downloaded.append(f"msg_{msg_id}: {type(e).__name__}: {e}")
    
    # Alternative: let the user resend the media to the bot right now
    print("Need to use a different approach")
    await bot.session.close()
    return downloaded

result = asyncio.run(download_media())
print(result)
