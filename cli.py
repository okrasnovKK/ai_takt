"""ai-takt — командная утилита для отправки сообщений и фото.

Использование:
    python cli.py chat "Текст сообщения"              # в командный чат
    python cli.py user <user_id> "Текст"               # конкретному пользователю
    python cli.py broadcast "Текст"                    # всем зарегистрированным
    python cli.py users                                # список пользователей
    python cli.py photo <путь_к_файлу> [подпись]       # отправить фото в чат
    python cli.py video <путь> [подпись]               # отправить видео в чат
    python cli.py incoming                             # входящие сообщения
    python cli.py pulse_survey                         # запустить pulse-опрос
    python cli.py events                               # список мероприятий
    python cli.py event-create <название> <формат>      # создать мероприятие
    python cli.py event-status [id]                    # статус мероприятия
    python cli.py event-approve <event_id> [коммент]   # согласовать
    python cli.py event-budget <event_id>              # показать смету
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from aiogram.types import FSInputFile

from src.config import BOT_TOKEN, TEAM_CHAT_ID
from src.services.database import UserDatabase
from src.services.messenger import Messenger
from src.services.message_logger import MessageLogger


async def main():
    # Windows console encoding fix
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

    if len(sys.argv) < 2:
        print(__doc__)
        return

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    db = UserDatabase()
    messenger = Messenger(bot, db)
    cmd = sys.argv[1]

    if cmd == "chat" and len(sys.argv) >= 3:
        text = " ".join(sys.argv[2:])
        msg = await messenger.send_to_team_chat(text)
        print(f"[OK] Sent to chat: {'success' if msg else 'FAILED'}")

    elif cmd == "user" and len(sys.argv) >= 4:
        user_id = int(sys.argv[2])
        text = " ".join(sys.argv[3:])
        ok = await messenger.send_to_user(user_id, text)
        print(f"[OK] Sent to user {user_id}: {'success' if ok else 'FAILED'}")

    elif cmd == "broadcast" and len(sys.argv) >= 3:
        text = " ".join(sys.argv[2:])
        results = await messenger.broadcast_to_all_users(text)
        sent = sum(1 for v in results.values() if v)
        print(f"[OK] Broadcast: {sent}/{len(results)} users reached")

    elif cmd == "users":
        users = db.get_all_users()
        if not users:
            print("[INFO] No registered users yet")
        else:
            print(f"[LIST] Registered users ({len(users)}):")
            for uid, u in users.items():
                print(f"  {uid}: {u['first_name']} {u['last_name']} (@{u['username']})")

    elif cmd == "photo" and len(sys.argv) >= 3:
        photo_path = sys.argv[2]
        caption = " ".join(sys.argv[3:]) if len(sys.argv) >= 4 else None
        photo = FSInputFile(photo_path)
        msg = await messenger.send_photo_to_team_chat(photo, caption=caption)
        print(f"[OK] Photo sent to chat: {'success' if msg else 'FAILED'}")

    elif cmd == "video" and len(sys.argv) >= 3:
        video_path = sys.argv[2]
        caption = " ".join(sys.argv[3:]) if len(sys.argv) >= 4 else None
        video = FSInputFile(video_path)
        msg = await messenger.send_video_to_team_chat(video, caption=caption)
        print(f"[OK] Video sent to chat: {'success' if msg else 'FAILED or BLOCKED (duplicate)'}")

    elif cmd == "incoming":
        logger = MessageLogger()
        msgs = logger.get_recent_messages(limit=50)
        if not msgs:
            print("[INFO] No incoming messages logged yet.")
        else:
            print(f"[INCOMING] Messages ({len(msgs)}):")
            for m in msgs:
                print(f"  [{m['timestamp']}] {m['first_name']} (@{m['username']}): {m['text']}")

    elif cmd == "pulse_survey":
        from src.services.pulse_survey_service import (
            PulseSurveyState,
            get_pulse_survey_intro,
            get_pulse_survey_questions_text,
            get_pulse_announce_text,
        )
        import time as time_module
        survey_id = f"pulse_cli_{int(time_module.time())}"
        pulse = PulseSurveyState()
        pulse.create_survey(survey_id=survey_id, created_by=0, created_in_chat=0)
        announce = get_pulse_announce_text()
        msg = await messenger.send_to_team_chat(announce, parse_mode="HTML")
        if msg:
            print(f"[OK] Pulse survey announced in team chat")
        all_users = db.get_all_users()
        sent_count = 0
        for uid_str, user_data in all_users.items():
            uid = int(uid_str)
            intro = get_pulse_survey_intro()
            questions = get_pulse_survey_questions_text()
            try:
                await bot.send_message(chat_id=uid, text=intro)
                await bot.send_message(chat_id=uid, text=questions, parse_mode="HTML")
                pulse.add_participant(survey_id, uid)
                sent_count += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                print(f"[ERROR] Could not send to user {uid}: {e}")
        print(f"[OK] Pulse survey sent to {sent_count}/{len(all_users)} users")

    # ══════════════════════════════════════════════
    #  EVENT MANAGEMENT COMMANDS
    # ══════════════════════════════════════════════

    elif cmd == "events":
        from src.services.event_service import EventService
        es = EventService()
        all_events = es.get_all_events()
        if not all_events:
            print("[INFO] No events yet")
        else:
            active = es.get_active_events()
            completed = es.get_events_by_status("completed")
            print(f"[EVENTS] Total: {len(all_events)}, Active: {len(active)}, Completed: {len(completed)}")
            for eid, ev in sorted(all_events.items(),
                                   key=lambda x: x[1].get("proposed_at", ""),
                                   reverse=True):
                print(f"  [{ev.get('status', '?')}] {ev.get('title', '—')} ({eid})")

    elif cmd == "event-create" and len(sys.argv) >= 4:
        from src.services.event_service import EventService, EVENT_FORMAT_LABELS
        es = EventService()
        title = sys.argv[2]
        fmt = sys.argv[3].lower()
        if fmt not in EVENT_FORMAT_LABELS:
            print(f"[ERROR] Unknown format: {fmt}. Available: {', '.join(EVENT_FORMAT_LABELS.keys())}")
            return
        event = es.create_event(title=title, event_format=fmt, description="", proposed_by=0)
        print(f"[OK] Event created: {title} ({fmt}) — id={event['event_id']}")

    elif cmd == "event-status":
        from src.services.event_service import EventService, get_event_status_text
        es = EventService()
        if len(sys.argv) >= 3:
            event = es.get_event(sys.argv[2])
        else:
            event = es.get_latest_event()
        if not event:
            print("[ERROR] Event not found")
        else:
            text = get_event_status_text(event, detailed=True)
            print(text)

    elif cmd == "event-approve" and len(sys.argv) >= 3:
        from src.services.event_service import EventService
        es = EventService()
        event_id = sys.argv[2]
        comment = " ".join(sys.argv[3:]) if len(sys.argv) >= 4 else ""
        ok = es.approve_event(event_id, 0, comment)
        if ok:
            es.transition_event(event_id, "approval")
            es.transition_event(event_id, "planning")
            print(f"[OK] Event {event_id} approved")
        else:
            print(f"[ERROR] Could not approve event {event_id}")

    elif cmd == "event-budget" and len(sys.argv) >= 3:
        from src.services.event_service import EventService
        es = EventService()
        text = es.get_budget_text(sys.argv[2])
        print(text)

    else:
        print(f"[ERROR] Unknown command: {cmd}")
        print(__doc__)

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())