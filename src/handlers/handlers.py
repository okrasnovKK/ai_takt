"""Handler for the /start command, general message handling, and surveys."""
import logging
import asyncio
import os
import time
import json
from datetime import datetime
from typing import Optional

from aiogram import Router, types
from aiogram.filters import Command

from src.services.database import UserDatabase
from src.services.messenger import Messenger
from src.services.message_logger import MessageLogger
from src.services.event_survey_service import (
    EventSurveyState,
    parse_event_answers,
    get_event_answered_count,
    write_event_survey_excel,
    get_missing_questions_text as get_event_survey_missing,
    EVENT_SURVEY_KEYS as EVENT_SURVEY_QUESTION_KEYS,
)
from src.services.survey_service import (
    SurveyState,
    get_survey_intro_text,
    get_survey_questions_text,
    get_first_reminder_text,
    get_missing_questions_text,
    parse_answers,
    get_answered_count,
    answers_to_excel_data,
    write_to_employee_base,
    SURVEY_QUESTION_KEYS,
)
from src.services.pulse_survey_service import (
    PulseSurveyState,
    get_pulse_survey_intro,
    get_pulse_survey_questions_text,
    get_pulse_announce_text,
    get_pulse_completion_text,
    get_pulse_missing_questions_text,
    get_pulse_summary_text,
    get_pulse_answered_count,
    parse_pulse_answers,
    write_pulse_survey_excel,
    PULSE_QUESTION_KEYS,
)
from src.config import LPR_USER_ID
from src.services.ouroboros_bridge import ask_ouroboros
from src.services.holiday_decor_service import (
    HolidayDecorState,
)
from src.services.event_service import (
    EventService,
    get_event_status_text,
    get_taskboard_text,
    get_program_text,
    get_format_suggestions_text,
    get_proposal_intro_text,
    EVENT_FORMAT_LABELS,
    EVENT_FORMATS,
    get_default_budget_items,
    BUDGET_CATEGORY_LABELS,
)
from src.services.event_calendar import (
    get_task_template,
    get_timeline_text,
    get_preparation_progress,
    get_progress_bar,
    format_deadline,
)

logger = logging.getLogger(__name__)


def register_handlers(
    router: Router,
    db: UserDatabase,
    messenger: Messenger,
    msg_logger: MessageLogger,
    survey: Optional[SurveyState] = None,
    pulse_survey: Optional[PulseSurveyState] = None,
    event_service: Optional[EventService] = None,
    decor: Optional[HolidayDecorState] = None,
) -> None:
    """Register all message handlers."""
    if survey is None:
        survey = SurveyState()
    if pulse_survey is None:
        pulse_survey = PulseSurveyState()
    if event_service is None:
        event_service = EventService()
    if decor is None:
        decor = HolidayDecorState()

    # ──────────────────────────────────────────────
    # New members joining the team chat
    # ──────────────────────────────────────────────
    @router.message(lambda msg: msg.new_chat_members is not None)
    async def on_new_members(message: types.Message):
        """Detect new members added to the team chat and DM them."""
        for member in message.new_chat_members:
            if member.is_bot:
                continue
            # Send DM asking to start a conversation
            try:
                await message.bot.send_message(
                    chat_id=member.id,
                    text=get_first_reminder_text(),
                )
                survey.set_state(member.id, "new_member_alerted")
                logger.info(
                    "Sent welcome DM to new member %s (%s %s)",
                    member.id, member.first_name, member.last_name or "",
                )
            except Exception as e:
                logger.warning(
                    "Could not DM new member %s: %s", member.id, e,
                )

    # ──────────────────────────────────────────────
    # /start command
    # ──────────────────────────────────────────────
    @router.message(Command("start"))
    async def cmd_start(message: types.Message):
        """Handle /start command — register user and send welcome + survey."""
        msg_logger.log_message(message)
        user = message.from_user
        db.register_user(
            user_id=user.id,
            username=user.username or "",
            first_name=user.first_name or "",
            last_name=user.last_name or "",
        )

        name = user.first_name or "друг"
        welcome_text = (
            f"👋 Привет, {name}!\n\n"
            f"Я — ai-takt, корпоративный ассистент команды.\n"
            f"Я буду отправлять тебе уведомления о мероприятиях, "
            f"поздравления и опросы.\n\n"
            f"Ты добавлен в список рассылки! ✅"
        )
        await message.answer(welcome_text)

        # Check if user was alerted to take the survey
        current_state = survey.get_state(user.id)
        if current_state == "new_member_alerted":
            # Send the survey
            intro = get_survey_intro_text(name)
            questions = get_survey_questions_text()
            await message.answer(intro)
            await message.answer(questions, parse_mode="HTML")
            survey.set_state(user.id, "survey_sent")
            survey.set_answers(user.id, {})
            logger.info("Survey sent to user %s", user.id)

        # Notify team chat about new user
        await messenger.send_to_team_chat(
            f"👤 Новый участник в боте: {user.first_name} "
            f"{'@' + user.username if user.username else ''}"
        )

    # ──────────────────────────────────────────────
    # /help command
    # ──────────────────────────────────────────────
    @router.message(Command("help"))
    async def cmd_help(message: types.Message):
        """Show available commands."""
        help_text = (
            "🤖 <b>ai-takt — Команды</b>\n\n"
            "/start — Зарегистрироваться в боте\n"
            "/help — Показать это сообщение\n"
            "/me — Показать мои данные\n"
            "/obo <текст> — Задать вопрос Ouroboros\n\n"
            "<b>Мероприятия:</b>\n"
            "/event_help — Все команды мероприятий\n"
            "/event_propose — Предложить мероприятие\n"
            "/event_create — Быстро создать мероприятие\n"
            "/event_list — Список мероприятий\n"
            "/event_status — Статус мероприятия"
        )
        await message.answer(help_text, parse_mode="HTML")

    # ──────────────────────────────────────────────
    # /me command
    # ──────────────────────────────────────────────
    @router.message(Command("me"))
    async def cmd_me(message: types.Message):
        """Show user's registration info."""
        curr_user = message.from_user
        db_user = db.get_user(curr_user.id)
        if db_user:
            text = (
                "📋 <b>Твои данные:</b>\n"
                f"ID: {db_user['user_id']}\n"
                f"Имя: {db_user['first_name']} {db_user['last_name']}\n"
                f"Username: @{db_user['username'] or 'не указан'}"
            )
        else:
            text = "Ты ещё не зарегистрирован. Отправь /start"
        await message.answer(text, parse_mode="HTML")

    # ──────────────────────────────────────────────
    # /obo <text> — Talk to Ouroboros (LPR only)
    # ──────────────────────────────────────────────
    @router.message(Command("obo"))
    async def cmd_obo(message: types.Message):
        """Bridge to Ouroboros agent via WebSocket."""
        user = message.from_user
        if not user or user.id != LPR_USER_ID:
            await message.answer("Эта команда доступна только для ЛПР.")
            return

        text = message.text or ""
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.answer("Использование: /obo <текст сообщения>")
            return

        query = parts[1].strip()
        thinking_msg = await message.answer("⏳ Думаю...")
        try:
            response = await ask_ouroboros(query)
        finally:
            try:
                await thinking_msg.delete()
            except Exception:
                pass

        # Send response (split if > 4096 chars, no HTML parse to avoid injection)
        if len(response) <= 4096:
            await message.answer(response, parse_mode=None)
        else:
            for i in range(0, len(response), 4096):
                await message.answer(response[i:i + 4096], parse_mode=None)

    # ──────────────────────────────────────────────
    # /pulse_survey command
    # ──────────────────────────────────────────────
    @router.message(Command("pulse_survey"))
    async def cmd_pulse_survey(message: types.Message):
        """Start a quarterly pulse survey - send to ALL registered users."""
        user = message.from_user
        if not user:
            return

        # Admin check: only group admins or LPR can start pulse survey
        chat = message.chat
        if chat.type in ("group", "supergroup"):
            try:
                admins = await chat.get_administrators()
                admin_ids = [a.user.id for a in admins]
                if user.id not in admin_ids:
                    await message.answer(
                        "❌ Только администраторы чата могут запускать "
                        "опрос вовлечённости."
                    )
                    return
            except Exception as e:
                logger.warning("Could not check admin status: %s", e)
                await message.answer(
                    "❌ Не удалось проверить права. Попробуй позже."
                )
                return
        else:
            # Not a group chat - refuse
            await message.answer(
                "❌ Команда /pulse_survey работает только в групповом чате."
            )
            return

        # Generate a unique survey id
        import time as time_module
        survey_id = f"pulse_{int(time_module.time())}"

        # Create survey
        pulse_survey.create_survey(
            survey_id=survey_id,
            created_by=user.id,
            created_in_chat=chat.id,
        )

        # Announce in group chat
        announce_text = get_pulse_announce_text()
        await message.answer(announce_text, parse_mode="HTML")

        # Send to all registered users
        all_users = db.get_all_users()
        sent_count = 0
        for uid_str, user_data in all_users.items():
            uid = int(uid_str)
            intro = get_pulse_survey_intro()
            questions = get_pulse_survey_questions_text()

            try:
                await message.bot.send_message(
                    chat_id=uid,
                    text=intro,
                )
                await message.bot.send_message(
                    chat_id=uid,
                    text=questions,
                    parse_mode="HTML",
                )
                pulse_survey.add_participant(survey_id, uid)
                sent_count += 1
                # Small delay to avoid Telegram rate limits
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.warning(
                    "Could not send pulse survey to user %s: %s", uid, e
                )

        logger.info(
            "Pulse survey %s sent to %d/%d users",
            survey_id, sent_count, len(all_users),
        )
        await message.answer(
            f"✅ Опрос вовлечённости запущен! "
            f"Разослан {sent_count} из {len(all_users)} пользователям.\n\n"
            f"Через 24 часа тем, кто не ответил, будет отправлено "
            f"напоминание."
        )

    # ══════════════════════════════════════════════════
    # Holiday Decor — photo handler (BEFORE generic media handler)
    # Catches photos ONLY when decor is in awaiting_photo state.
    # When not in decor flow, the filter fails and handle_media catches it.
    # ══════════════════════════════════════════════════
    from src.config import LPR_USER_ID

    @router.message(lambda msg: msg.photo is not None and decor.get_state() == "awaiting_photo")
    async def on_holiday_photo(message: types.Message):
        """Handle photo sent during decoration workflow."""
        user_id = message.from_user.id
        if LPR_USER_ID and not decor.is_lpr(user_id):
            return

        photo = message.photo[-1]
        file_info = await message.bot.get_file(photo.file_id)
        file_path = file_info.file_path or ""
        decor.set_photo(file_path, photo.file_id)

        await message.answer(
            "✅ Фото получено!\n\n"
            "Шаг 2 из 6: Теперь расскажи подробнее:\n"
            "1️⃣ <b>Какой праздник?</b>\n"
            "2️⃣ <b>Бюджет</b> (в рублях)\n"
            "3️⃣ <b>Особые пожелания/правила</b>\n\n"
            "Напиши всё одним сообщением, например:\n"
            "<code>Новый год, бюджет 10000, "
            "нужна ёлка, бело-голубая гамма</code>",
            parse_mode="HTML",
        )

    # ──────────────────────────────────────────────
    # Media handler — save photos/videos to disk
    # ──────────────────────────────────────────────
    @router.message(lambda msg: msg.photo is not None or msg.video is not None or msg.document is not None)
    async def handle_media(message: types.Message):
        """Save incoming photos and videos to the media input directory."""
        msg_logger.log_message(message)
        user = message.from_user
        if not user:
            return

        # Auto-register
        db.register_user(
            user_id=user.id,
            username=user.username or "",
            first_name=user.first_name or "",
            last_name=user.last_name or "",
        )

        media_dir = r"C:\Users\User\Ouroboros\Deliverables\video_media\input"
        os.makedirs(media_dir, exist_ok=True)
        saved_count = 0

        if message.photo:
            # Get the largest photo
            photo = message.photo[-1]
            file_info = await message.bot.get_file(photo.file_id)
            file_path = file_info.file_path
            ext = os.path.splitext(file_path)[1] or ".jpg"
            dest = os.path.join(media_dir, f"photo_{user.id}_{int(time.time())}{ext}")
            await message.bot.download_file(file_path, dest)
            logger.info("Saved photo from %s: %s (%d bytes)", user.id, dest, photo.file_size)
            saved_count += 1

        if message.video:
            video = message.video
            file_info = await message.bot.get_file(video.file_id)
            file_path = file_info.file_path
            ext = os.path.splitext(file_path)[1] or ".mp4"
            dest = os.path.join(media_dir, f"video_{user.id}_{int(time.time())}{ext}")
            await message.bot.download_file(file_path, dest)
            logger.info("Saved video from %s: %s (%d bytes, %ds)", user.id, dest, video.file_size, video.duration or 0)
            saved_count += 1

        if message.document:
            doc = message.document
            mime = doc.mime_type or ""
            if mime.startswith("video/") or mime.startswith("image/"):
                file_info = await message.bot.get_file(doc.file_id)
                file_path = file_info.file_path
                ext = os.path.splitext(doc.file_name or file_path)[1] or ".bin"
                dest = os.path.join(media_dir, f"doc_{user.id}_{int(time.time())}{ext}")
                await message.bot.download_file(file_path, dest)
                logger.info("Saved document from %s: %s (%d bytes)", user.id, dest, doc.file_size)
                saved_count += 1
            else:
                await message.answer("📎 Принял документ, но сохраняю только фото и видео.")
                return

        if saved_count:
            await message.answer(
                f"✅ Получено и сохранено {saved_count} медиафайл(ов) "
                f"для генерации видео. Спасибо!"
            )

    # ══════════════════════════════════════════════════
    # Holiday Decor — command & text handlers
    # Registered BEFORE the general survey handler, so they take priority
    # when the decor state machine is active.
    # Text handler only matches when decor is in awaiting_details state.
    # ══════════════════════════════════════════════════

    @router.message(Command("holiday_start"))
    async def cmd_holiday_start(message: types.Message):
        """Начать процесс украшения помещения к празднику."""
        user_id = message.from_user.id
        if LPR_USER_ID and user_id != LPR_USER_ID:
            await message.answer("❌ Только ЛПР может запустить украшение помещения.")
            return

        if decor.is_active():
            await message.answer(
                "⚠️ Уже есть активный процесс украшения.\n"
                f"Текущий статус:\n{decor.get_status_text()}\n\n"
                "Чтобы начать заново — /holiday_cancel",
                parse_mode="HTML",
            )
            return

        decor.start(user_id)
        await message.answer(
            "🎄 <b>Украшение помещения</b>\n\n"
            "Шаг 1 из 6: Пришли мне, пожалуйста, <b>фото помещения</b>, "
            "которое будем украшать.\n\n"
            "Просто отправь фото в этот чат 📸",
            parse_mode="HTML",
        )

    @router.message(Command("holiday_status"))
    async def cmd_holiday_status(message: types.Message):
        """Показать текущий статус украшения."""
        await message.answer(decor.get_status_text(), parse_mode="HTML")

    @router.message(Command("holiday_cancel"))
    async def cmd_holiday_cancel(message: types.Message):
        """Отменить процесс украшения."""
        if not decor.is_active():
            await message.answer("ℹ️ Нет активного процесса украшения.")
            return
        decor.cancel()
        await message.answer("❌ Украшение помещения отменено.")

    @router.message(Command("holiday_approve"))
    async def cmd_holiday_approve(message: types.Message):
        """Утвердить концепцию или смету украшения."""
        user_id = message.from_user.id
        if not decor.is_lpr(user_id):
            await message.answer("❌ Только ЛПР может утверждать.")
            return

        state = decor.get_state()

        if state == "awaiting_approval":
            decor.approve_concept()
            all_data = decor.get_all()
            theme = all_data.get("holiday_theme", "Праздник")
            budget = all_data.get("budget", "—")

            estimate = (
                f"💰 <b>Смета украшения помещения — {theme}</b>\n\n"
                f"Бюджет: {budget} ₽\n\n"
                f"<b>Примерная смета расходов:</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🎈 Воздушные шары (гелий, 20 шт) — 1 500 ₽\n"
                f"🎀 Гирлянды и растяжки (набор) — 1 200 ₽\n"
                f"🖼️ Плакаты/наклейки на стены — 800 ₽\n"
                f"✨ Декоративные элементы (мишура, звёзды) — 1 000 ₽\n"
                f"📦 Доставка и прочее — 500 ₽\n"
                f"━━━━━━━━━━━━━━━\n"
                f"<b>ИТОГО: ~5 000 ₽</b>\n\n"
                f"Если всё устраивает — нажми /holiday_approve ещё раз.\n"
                f"Если нужны правки — /holiday_reject"
            )
            decor.set_estimate(estimate)
            await message.answer(estimate, parse_mode="HTML")

        elif state == "awaiting_estimate_approval":
            decor.approve_estimate()
            await message.answer(
                "✅ <b>Смета утверждена!</b> 🎉\n\n"
                "Украшение помещения согласовано!\n\n"
                "🎄 <b>Что нужно купить:</b>\n"
                "1. Ёлка искусственная 150-180 см\n"
                "2. Набор ёлочных шаров (50-100 шт, небьющиеся)\n"
                "3. Гирлянда светодиодная 10-15 м\n"
                "4. Воздушные шары (гелий, 20 шт)\n"
                "5. Мишура, дождик, декор\n"
                "6. Новогодние наклейки/плакаты\n\n"
                "🔗 <b>Ссылки на закупку:</b>\n"
                "• Ozon: <a href=\"https://www.ozon.ru/category/elka-iskusstvennaya-gollandskaya/\">Ёлки искусственные</a>\n"
                "• Ozon: <a href=\"https://www.ozon.ru/category/elochnye-igrushki-100-shtuk/\">Наборы шаров</a>\n"
                "• Ozon: <a href=\"https://www.ozon.ru/category/dozhdik-mishura-zelenyy/\">Мишура и декор</a>\n"
                "• Wildberries: поиск «гирлянда светодиодная 10м»\n"
                "• Wildberries: поиск «воздушные шары гелий 20 шт»\n\n"
                "Желаю удачи в подготовке! 🎄✨",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        else:
            await message.answer(
                f"ℹ️ Сейчас нечего утверждать.\n{decor.get_status_text()}",
                parse_mode="HTML",
            )

    @router.message(Command("holiday_reject"))
    async def cmd_holiday_reject(message: types.Message):
        """Отклонить концепцию украшения."""
        user_id = message.from_user.id
        if not decor.is_lpr(user_id):
            await message.answer("❌ Только ЛПР может отклонить.")
            return

        if decor.get_state() == "awaiting_approval":
            decor.reject_concept()
            await message.answer(
                "🔄 Понял, давай переделаем.\n\n"
                "Напиши, что именно нужно изменить, "
                "или просто пришли новые пожелания по тематике и бюджету.\n"
                "Когда будешь готов — напиши тему, бюджет и правила одной строкой, "
                "например:\n"
                "<code>Новый год, бюджет 8000, "
                "нужна ёлка и гирлянды</code>",
                parse_mode="HTML",
            )
        else:
            await message.answer("ℹ️ Сейчас нет концепции на утверждении.")

    # ── Decor text handler — only fires when awaiting_details ──
    @router.message(lambda msg: msg.text and not msg.text.startswith("/") and decor.get_state() == "awaiting_details")
    async def on_holiday_details(message: types.Message):
        """Handle theme/budget details from LPR."""
        user_id = message.from_user.id
        if LPR_USER_ID and not decor.is_lpr(user_id):
            return

        text = message.text.strip()
        parts = [p.strip() for p in text.split(",")]

        theme = parts[0] if len(parts) > 0 else text
        budget = parts[1] if len(parts) > 1 else "5000"
        rules = ", ".join(parts[2:]) if len(parts) > 2 else "Без особых правил"

        decor.set_details(theme, budget, rules)

        await message.answer(
            f"✅ Принято!\n\n"
            f"🎉 Праздник: <b>{theme}</b>\n"
            f"💰 Бюджет: <b>{budget} ₽</b>\n"
            f"📋 Правила: <b>{rules}</b>\n\n"
            f"Шаг 3 из 6: Идёт подготовка концепции... 🎨\n\n"
            f"🖼️ <b>Пример украшения</b>\n\n"
            f"Для «{theme}» на основе твоего фото предложу:\n"
            f"🎈 Воздушные шары в тематических цветах\n"
            f"🎀 Праздничная растяжка\n"
            f"✨ Декор по периметру\n"
            f"🖼️ Тематические плакаты\n\n"
            f"Шаг 4 из 6: Если нравится — /holiday_approve\n"
            f"Хочешь изменить — /holiday_reject\n"
            f"Или напиши новые пожелания.",
            parse_mode="HTML",
        )

    # ──────────────────────────────────────────────
    # Survey answer handler
    # ──────────────────────────────────────────────
    @router.message()
    async def survey_or_general(message: types.Message):
        """Handle survey answers, then fall back to auto-registration."""
        # Skip explicit commands — they are handled by their own @router.message(Command(...)) handlers
        if message.text and message.text.startswith("/"):
            return

        msg_logger.log_message(message)
        user = message.from_user
        if not user:
            return

        # Auto-register any user
        db.register_user(
            user_id=user.id,
            username=user.username or "",
            first_name=user.first_name or "",
            last_name=user.last_name or "",
        )

        # Check if user is in event survey FIRST (before other surveys)
        # АНОНИМНОСТЬ: ответы на опрос мероприятия НИКОГДА не показываются
        # ни в каких чатах. Только анонимная запись в Excel-файл.
        event_survey = EventSurveyState()
        event_active = event_survey.get_all_active_surveys()
        if event_active:
            for sid, s_data in event_active.items():
                es_state = event_survey.get_participant_state(sid, user.id)
                if es_state == "survey_sent":
                    await _handle_event_survey_answer(
                        message, sid, user.id, event_survey, event_service, messenger
                    )
                    return

        # Check if user is in pulse survey
        pulse_active = pulse_survey.get_all_active_surveys()
        if pulse_active:
            for sid, s_data in pulse_active.items():
                p_state = pulse_survey.get_participant_state(sid, user.id)
                if p_state == "survey_sent":
                    await _handle_pulse_answer(
                        message, sid, user.id, pulse_survey, messenger
                    )
                    return

        # Check if user is in onboarding survey
        current_state = survey.get_state(user.id)
        if current_state == "survey_sent":
            await _handle_survey_answer(message, user.id, user.first_name or "",
                                        survey, db, messenger)
            return

        # If user is new_member_alerted, ask them to use /start
        if current_state == "new_member_alerted":
            await message.answer(
                "👋 Чтобы начать, отправь команду /start — "
                "я задам тебе несколько вопросов, чтобы узнать тебя лучше."
            )
            return

        # Fallback: first-time auto-registration (only once)
        if db.count_users() == 1:
            welcome = (
                "✅ Ты зарегистрирован! Я запомнил тебя. "
                "Используй /help для списка команд."
            )
            await message.answer(welcome)

    # ══════════════════════════════════════════════════
    #  EVENT MANAGEMENT COMMANDS (inside register_handlers)
    # ══════════════════════════════════════════════════

    # ──────────────────────────────────────────────
    # /event_help — Справка по мероприятиям
    # ──────────────────────────────────────────────
    @router.message(Command("event_help"))
    async def cmd_event_help(message: types.Message):
        """Show event management help."""
        help_text = (
            "📋 <b>Event-менеджмент — команды</b>\n\n"
            "<b>Создание и предложение:</b>\n"
            "/event_propose — предложить новый формат\n"
            "/event_create <название> — <формат> — быстрое создание\n\n"
            "<b>Финансы и согласование:</b>\n"
            "/event_budget — сформировать смету\n"
            "/event_approve — согласовать (ЛПР)\n"
            "/event_reject <причина> — отклонить (ЛПР)\n"
            "/event_vote — вынести на голосование команды\n\n"
            "<b>Планирование:</b>\n"
            "/event_date <дата> — назначить дату\n"
            "/event_tasks — календарь задач\n"
            "/event_task_done <N> — отметить задачу\n"
            "/event_task_work <N> — взять в работу\n\n"
            "<b>Чат и публикация:</b>\n"
            "/event_chat — инструкция по созданию чата\n"
            "/event_chat_set <id> — указать ID созданного чата\n"
            "/event_invite — опубликовать приглашение в командный чат\n"
            "/event_program <текст> — опубликовать программу\n"
            "/event_launch — запустить\n\n"
            "<b>Завершение:</b>\n"
            "/event_complete — завершить\n"
            "/event_survey_post — отправить опрос\n"
            "/event_video — видео-воспоминание\n\n"
            "<b>Статус:</b>\n"
            "/event_list — список мероприятий\n"
            "/event_status — статус текущего\n\n"
            "— — — — — — — — — —\n"
            "📌 Предложения приходят только ЛПР в личку.\n"
            "☝️ ЛПР решает: /event_vote для голосования в команде.\n"
            "💬 Чат мероприятия создаётся вручную: /event_chat"
        )
        await message.answer(help_text, parse_mode="HTML")

    # ──────────────────────────────────────────────
    # /event_propose — Предложить мероприятие
    # ──────────────────────────────────────────────
    @router.message(Command("event_propose"))
    async def cmd_event_propose(message: types.Message):
        user = message.from_user
        if not user:
            return
        msg_logger.log_message(message)
        intro = get_proposal_intro_text(user.first_name or "друг")
        formats = get_format_suggestions_text()
        await message.answer(intro)
        await message.answer(formats, parse_mode="HTML")
        await message.answer(
            "Напиши название мероприятия и выбери формат, например:\n\n"
            "«Новогодний корпоратив — корпоратив»\n"
            "«Летний тимбилдинг — outdoor»\n"
            "«Воркшоп по Python — workshop»"
        )

    # ──────────────────────────────────────────────
    # /event_list — Список мероприятий
    # ──────────────────────────────────────────────
    @router.message(Command("event_list"))
    async def cmd_event_list(message: types.Message):
        all_events = event_service.get_all_events()
        if not all_events:
            await message.answer("📭 Мероприятий пока нет. /event_propose — создать")
            return
        active = event_service.get_active_events()
        completed = event_service.get_events_by_status("completed")
        lines = ["📋 <b>Все мероприятия:</b>\n"]
        if active:
            lines.append(f"🎯 <b>Активные ({len(active)}):</b>")
            for eid, ev in sorted(active.items(), key=lambda x: x[1].get("proposed_at",""), reverse=True)[:5]:
                lines.append(f"• {ev.get('title','—')} ({ev.get('status','—')})")
            lines.append("")
        if completed:
            lines.append(f"✅ <b>Завершённые ({len(completed)}):</b>")
            for eid, ev in sorted(completed.items(), key=lambda x: x[1].get("completed_at",""), reverse=True)[:5]:
                lines.append(f"• {ev.get('title','—')}")
            lines.append("")
        lines.append("Используй /event_status <id> для просмотра деталей.")
        await message.answer("\n".join(lines), parse_mode="HTML")

    # ──────────────────────────────────────────────
    # /event_status — Статус мероприятия
    # ──────────────────────────────────────────────
    @router.message(Command("event_status"))
    async def cmd_event_status(message: types.Message):
        parts = message.text.strip().split(maxsplit=1)
        all_events = event_service.get_active_events()
        if not all_events:
            await message.answer("Нет активных мероприятий.")
            return
        event = event_service.get_event(parts[1].strip()) if len(parts) > 1 else event_service.get_latest_event()
        if not event:
            await message.answer("Мероприятие не найдено.")
            return
        text = get_event_status_text(event, detailed=True)
        status = event.get("status", "")
        actions = []
        if status == "proposal": actions.append("/event_budget — Составить смету")
        elif status == "budgeting": actions.append("/event_approve — Согласовать")
        elif status == "approval":
            actions.append("/event_approve — ✅ Принять")
            actions.append("/event_reject — ❌ Отклонить")
        elif status == "planning":
            actions.append("/event_tasks — Задачи")
            actions.append("/event_chat — Создать чат")
        elif status == "chat_created": actions.append("/event_program — Программа")
        elif status == "program_published": actions.append("/event_launch — Запустить!")
        elif status == "completed":
            actions.append("/event_survey_post — Опрос")
            actions.append("/event_video — Видео")
        if actions:
            text += "\n\n<b>Доступные действия:</b>\n" + "\n".join(f"{a}" for a in actions)
        await message.answer(text, parse_mode="HTML")

    # ──────────────────────────────────────────────
    # /event_budget — Смета
    # ──────────────────────────────────────────────
    @router.message(Command("event_budget"))
    async def cmd_event_budget(message: types.Message):
        latest = event_service.get_latest_event()
        if not latest:
            await message.answer("Нет активных мероприятий.")
            return
        event_id = latest["event_id"]
        budget = latest.get("budget", {})
        if not budget.get("items"):
            fmt = latest.get("format", "other")
            items = get_default_budget_items(fmt)
            event_service.set_budget_items(event_id, items)
            event_service.transition_event(event_id, "budgeting")
        text = event_service.get_budget_text(event_id)
        if not latest.get("lpr_approval", {}).get("approved"):
            text += "\n\n⏳ <b>Ожидает согласования ЛПР</b>\n/event_approve — согласовать\n/event_reject — отправить на доработку"
        await message.answer(text, parse_mode="HTML")

    # ──────────────────────────────────────────────
    # /event_approve — Согласовать
    # ──────────────────────────────────────────────
    @router.message(Command("event_approve"))
    async def cmd_event_approve(message: types.Message):
        user = message.from_user
        if not user: return
        latest = event_service.get_latest_event()
        if not latest:
            await message.answer("Нет мероприятий на согласовании.")
            return
        event_id = latest["event_id"]
        status = latest.get("status", "")
        if status not in ("budgeting", "approval"):
            await message.answer("❌ Мероприятие не на этапе согласования.")
            return
        parts = message.text.strip().split(maxsplit=1)
        comment = parts[1] if len(parts) > 1 else ""
        success = event_service.approve_event(event_id, user.id, comment)
        if success:
            if status == "budgeting":
                event_service.transition_event(event_id, "approval")
            event_service.transition_event(event_id, "planning")
            # Auto-generate tasks
            tasks = get_task_template(latest.get("format", "other"))
            for task_title, days_before in tasks:
                deadline = format_deadline(days_before, latest.get("date", ""))
                event_service.add_task(event_id, task_title, deadline)
            await message.answer(
                f"✅ <b>Мероприятие согласовано!</b>\n\n"
                f"«{latest.get('title', '')}» одобрено.\n\n"
                f"📅 Задачи по подготовке сформированы.\n"
                f"📋 /event_tasks — посмотреть задачи\n"
                f"💬 /event_chat — создать чат участников",
                parse_mode="HTML")
            # НЕ отправляем в командный чат! ЛПР решает, когда и что
            # публиковать. Для публикации в команде:
            # /event_vote — инициировать голосование в командном чате

    # ──────────────────────────────────────────────
    # /event_reject — Отклонить
    # ──────────────────────────────────────────────
    @router.message(Command("event_reject"))
    async def cmd_event_reject(message: types.Message):
        user = message.from_user
        if not user: return
        latest = event_service.get_latest_event()
        if not latest:
            await message.answer("Нет мероприятий на рассмотрении.")
            return
        parts = message.text.strip().split(maxsplit=1)
        comment = parts[1] if len(parts) > 1 else "Причина не указана"
        success = event_service.reject_event(latest["event_id"], user.id, comment)
        if success:
            await message.answer(
                f"❌ <b>Мероприятие отправлено на доработку</b>\n\n"
                f"«{latest.get('title', '')}»\nПричина: {comment}\n\n"
                f"Отредактируй смету: /event_budget", parse_mode="HTML")
            # Решение ЛПР о доработке — приватно, не в командный чат

    # ──────────────────────────────────────────────
    # /event_date — Назначить дату
    # ──────────────────────────────────────────────
    @router.message(Command("event_date"))
    async def cmd_event_date(message: types.Message):
        parts = message.text.strip().split(maxsplit=1)
        latest = event_service.get_latest_event()
        if not latest:
            await message.answer("Нет активных мероприятий.")
            return
        if len(parts) < 2:
            await message.answer("📅 Укажи дату: /event_date 25.12.2026")
            return
        date_str = parts[1].strip()
        event_service.set_event_date(latest["event_id"], date_str)
        tasks = get_task_template(latest.get("format", "other"))
        for task_title, days_before in tasks:
            deadline = format_deadline(days_before, date_str)
            event_service.add_task(latest["event_id"], task_title, deadline)
        await message.answer(
            f"📅 Дата мероприятия: <b>{date_str}</b>\n\n"
            f"Задачи пересчитаны: /event_tasks", parse_mode="HTML")

    # ──────────────────────────────────────────────
    # /event_tasks — Календарь задач
    # ──────────────────────────────────────────────
    @router.message(Command("event_tasks"))
    async def cmd_event_tasks(message: types.Message):
        latest = event_service.get_latest_event()
        if not latest:
            await message.answer("Нет активных мероприятий.")
            return
        tasks = latest.get("tasks", [])
        if not tasks:
            await message.answer("📅 Задачи не назначены.")
            return
        text = get_timeline_text(tasks, latest.get("date", ""))
        progress = get_preparation_progress(tasks)
        progress_line = get_progress_bar(progress["progress_pct"])
        full_text = f"{text}\n\n📊 <b>Прогресс:</b>\n{progress_line}\n\nКоманды:\n/event_task_done <N> — ✅\n/event_task_work <N> — 🔄"
        await message.answer(full_text, parse_mode="HTML")

    # ──────────────────────────────────────────────
    # /event_task_done — Задача выполнена
    # ──────────────────────────────────────────────
    @router.message(Command("event_task_done"))
    async def cmd_event_task_done(message: types.Message):
        parts = message.text.strip().split(maxsplit=1)
        latest = event_service.get_latest_event()
        if not latest or len(parts) < 2:
            await message.answer("Укажи номер задачи: /event_task_done 1")
            return
        try:
            task_num = int(parts[1].strip()) - 1
            tasks = latest.get("tasks", [])
            if 0 <= task_num < len(tasks):
                task = tasks[task_num]
                event_service.update_task_status(latest["event_id"], task["task_id"], "done")
                await message.answer(f"✅ Задача «{task.get('title', '')}» выполнена!")
            else:
                await message.answer(f"❌ Нет задачи с номером {parts[1]}")
        except ValueError:
            await message.answer("Укажи номер задачи числом.")

    # ──────────────────────────────────────────────
    # /event_task_work — Взять в работу
    # ──────────────────────────────────────────────
    @router.message(Command("event_task_work"))
    async def cmd_event_task_work(message: types.Message):
        parts = message.text.strip().split(maxsplit=1)
        latest = event_service.get_latest_event()
        if not latest or len(parts) < 2:
            await message.answer("Укажи номер задачи: /event_task_work 1")
            return
        try:
            task_num = int(parts[1].strip()) - 1
            tasks = latest.get("tasks", [])
            if 0 <= task_num < len(tasks):
                task = tasks[task_num]
                event_service.update_task_status(latest["event_id"], task["task_id"], "in_progress")
                await message.answer(f"🔄 Задача «{task.get('title', '')}» взята в работу!")
            else:
                await message.answer(f"❌ Нет задачи с номером {parts[1]}")
        except ValueError:
            await message.answer("Укажи номер задачи числом.")

    # ──────────────────────────────────────────────
    # /event_chat — Создать чат
    # ──────────────────────────────────────────────
    @router.message(Command("event_chat"))
    async def cmd_event_chat(message: types.Message):
        latest = event_service.get_latest_event()
        if not latest:
            await message.answer("Нет активных мероприятий.")
            return
        title = latest.get("title", "Мероприятие")
        await message.answer(
            f"💬 <b>Чат «{title}»</b>\n\n"
            f"Я не могу создать группу в Telegram — для этого нужны права администратора.\n\n"
            f"<b>Как создать чат:</b>\n"
            f"1. Создай группу в Telegram вручную\n"
            f"2. Добавь бота @ai_takt_bot в группу\n"
            f"3. Напиши мне ID чата (команда /event_chat_set <id>)\n\n"
            f"После этого я смогу публиковать программу, расписание и напоминания.",
            parse_mode="HTML")
        # Статус НЕ переключается в chat_created — чат ещё не создан.
        # Реальный переход произойдёт после /event_chat_set <id>
        # Запоминаем, что запрос на создание чата был отправлен
        event_service.set_event_chat(latest["event_id"], -1)

    # ──────────────────────────────────────────────
    # /event_program — Опубликовать программу
    # ──────────────────────────────────────────────
    @router.message(Command("event_program"))
    async def cmd_event_program(message: types.Message):
        parts = message.text.strip().split(maxsplit=1)
        latest = event_service.get_latest_event()
        if not latest:
            await message.answer("Нет активных мероприятий.")
            return
        if len(parts) > 1:
            program_text = parts[1]
            event_service.set_program(latest["event_id"], program_text)
            event_service.transition_event(latest["event_id"], "program_published")
            await message.answer("📢 <b>Программа опубликована!</b>", parse_mode="HTML")
            full_program = get_program_text(latest)
            event_chat_id = latest.get("event_chat_id", 0)
            if event_chat_id and event_chat_id != -1:
                await messenger.send_to_event_chat(event_chat_id, full_program, parse_mode="HTML")
            else:
                await messenger.send_to_team_chat(full_program, parse_mode="HTML")
        else:
            if latest.get("program"):
                await message.answer(get_program_text(latest), parse_mode="HTML")
            else:
                await message.answer(
                    "📢 Напиши /event_program <текст> чтобы опубликовать программу.\n\n"
                    "Пример:\n<code>/event_program 15:00 — Сбор\n16:00 — Начало</code>",
                    parse_mode="HTML")

    # ──────────────────────────────────────────────
    # /event_launch — Запустить
    # ──────────────────────────────────────────────
    @router.message(Command("event_launch"))
    async def cmd_event_launch(message: types.Message):
        latest = event_service.get_latest_event()
        if not latest:
            await message.answer("Нет активных мероприятий.")
            return
        if latest.get("status") != "program_published":
            await message.answer("❌ Сначала опубликуй программу: /event_program <текст>")
            return
        success = event_service.transition_event(latest["event_id"], "active")
        if success:
            title = latest.get("title", "Мероприятие")
            await message.answer(f"🎉 <b>«{title}» началось!</b> 🚀", parse_mode="HTML")
            await messenger.send_to_team_chat(
                f"🎉 <b>«{title}» — НАЧАЛОСЬ!</b> 🚀", parse_mode="HTML")

    # ──────────────────────────────────────────────
    # /event_complete — Завершить
    # ──────────────────────────────────────────────
    @router.message(Command("event_complete"))
    async def cmd_event_complete(message: types.Message):
        latest = event_service.get_latest_event()
        if not latest:
            await message.answer("Нет активных мероприятий.")
            return
        if latest.get("status") not in ("active", "program_published"):
            await message.answer("❌ Мероприятие ещё не запущено.")
            return
        success = event_service.transition_event(latest["event_id"], "completed")
        if success:
            text = get_event_completion_text(latest)
            await message.answer(text, parse_mode="HTML")
            # Завершение — приватно ЛПР. Для публикации в команде:
            # /event_survey_post — опрос участников
            # /event_video — видео-воспоминание

    # ──────────────────────────────────────────────
    # /event_survey_post — Отправить пост-опрос
    # ──────────────────────────────────────────────
    @router.message(Command("event_survey_post"))
    async def cmd_event_survey_post(message: types.Message):
        """
        Send post-event survey to all registered users.

        ANONYMITY RULES:
        - Announcement → ONLY to team chat (send_to_team_chat)
        - Survey questions → ONLY via DM (private) to each user
        - NEVER send survey to the event chat (anonymity is lost)
        """
        from src.services.event_survey_service import EventSurveyState, get_event_survey_intro, get_event_survey_questions_text, get_event_announce_text
        user = message.from_user
        if not user: return
        latest = event_service.get_latest_event()
        if not latest or latest.get("status") not in ("completed", "active"):
            await message.answer("❌ Сначала заверши: /event_complete")
            return
        event_survey = EventSurveyState()
        title = latest.get("title", "Мероприятие")
        date_str = latest.get("date", "")
        import time as time_module
        survey_id = f"ev_{latest['event_id']}_{int(time_module.time())}"
        event_survey.create_survey(event_id=survey_id, title=title, date_str=date_str, created_by=user.id, created_in_chat=message.chat.id)
        event_service.set_survey_id(latest["event_id"], survey_id)
        # Анонс → только в командный чат (не в чат мероприятия!)
        await messenger.send_to_team_chat(get_event_announce_text(title, date_str), parse_mode="HTML")
        all_users = db.get_all_users()
        sent_count = 0
        for uid_str, user_data in all_users.items():
            uid = int(uid_str)
            try:
                # Вопросы → только в ЛС (анонимно)
                await message.bot.send_message(chat_id=uid, text=get_event_survey_intro(title, date_str))
                await message.bot.send_message(chat_id=uid, text=get_event_survey_questions_text(), parse_mode="HTML")
                event_survey.add_participant(survey_id, uid)
                sent_count += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.warning("Could not send to user %s: %s", uid, e)
        await message.answer(f"📊 <b>Опрос по «{title}» отправлен!</b> {sent_count} пользователям.", parse_mode="HTML")

    # ──────────────────────────────────────────────
    # /event_video — Видео-воспоминание
    # ──────────────────────────────────────────────
    @router.message(Command("event_video"))
    async def cmd_event_video(message: types.Message):
        """
        Initiate video memory generation.

        RULES:
        - Generated video is sent ONLY to the team chat (send_photo_to_team_chat)
        - Video is NOT sent to the event chat
        - Use send_photo_to_team_chat() for the final clip
        """
        latest = event_service.get_latest_event()
        if not latest or latest.get("status") not in ("completed", "active"):
            await message.answer("❌ Сначала заверши: /event_complete")
            return
        title = latest.get("title", "Мероприятие")
        await message.answer(
            f"🎬 <b>Видео-воспоминание «{title}»</b>\n\n"
            f"Отправь фото/видео в этот чат, и я сгенерирую клип!\n"
            f"Медиа автоматически сохраняются.", parse_mode="HTML")

    # ──────────────────────────────────────────────
    # /event_create — Быстрое создание
    # ──────────────────────────────────────────────
    @router.message(Command("event_create"))
    async def cmd_event_create(message: types.Message):
        user = message.from_user
        if not user: return
        msg_logger.log_message(message)
        parts = message.text.strip().split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "📝 /event_create <название> — <формат>\n\n"
                "Форматы: " + ", ".join(EVENT_FORMAT_LABELS.values()))
            return
        text = parts[1].strip()
        title = text
        event_format = "other"
        for sep in [" — ", " - ", " – ", " (", " / "]:
            if sep in text:
                ps = text.split(sep, 1)
                title = ps[0].strip()
                hint = ps[1].strip().rstrip(")").lower()
                for fk, fl in EVENT_FORMAT_LABELS.items():
                    if hint == fk or hint == fl.lower() or hint in fl.lower():
                        event_format = fk
                        break
                break
        event = event_service.create_event(title=title, event_format=event_format,
            description=f"Создано через /event_create", proposed_by=user.id, proposed_by_name=user.first_name or "")
        await message.answer(
            f"✅ <b>Мероприятие создано!</b>\n\n🎯 {title}\n📋 Формат: {EVENT_FORMAT_LABELS.get(event_format, event_format)}\n\n"
            f"💰 /event_budget — смета\n📋 /event_status — статус", parse_mode="HTML")
        # Предложение приходит ТОЛЬКО ЛПР в личку (не в командный чат).
        # ЛПР рассматривает, потом решает — выносить ли в командный чат
        # через /event_vote.

    # ──────────────────────────────────────────────
    # /event_chat_set — Установить ID чата мероприятия
    # ──────────────────────────────────────────────
    @router.message(Command("event_chat_set"))
    async def cmd_event_chat_set(message: types.Message):
        """Установить ID чата мероприятия (созданного вручную)."""
        user = message.from_user
        if not user:
            return
        parts = message.text.strip().split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("📝 /event_chat_set <chat_id> — укажи ID созданной группы")
            return
        try:
            chat_id = int(parts[1].strip())
        except ValueError:
            await message.answer("❌ ID чата должен быть числом. Получить ID можно через @getidsbot")
            return
        latest = event_service.get_latest_event()
        if not latest:
            await message.answer("Нет активных мероприятий.")
            return
        event_service.set_event_chat(latest["event_id"], chat_id)
        event_service.transition_event(latest["event_id"], "chat_created")
        title = latest.get("title", "Мероприятие")
        await message.answer(
            f"✅ <b>Чат мероприятия зарегистрирован!</b>\n\n"
            f"«{title}» — ID чата: {chat_id}\n\n"
            f"Теперь я могу публиковать программу и напоминания:\n"
            f"/event_program <текст> — опубликовать программу",
            parse_mode="HTML")

    # ──────────────────────────────────────────────
    # /event_invite — Создать пригласительную ссылку
    # ──────────────────────────────────────────────
    @router.message(Command("event_invite"))
    async def cmd_event_invite(message: types.Message):
        """Создать пригласительную ссылку на чат мероприятия и
        опубликовать в командном общем чате.

        Используется ПОСЛЕ /event_chat_set <id>.
        Бот должен быть администратором чата мероприятия.
        """
        user = message.from_user
        if not user:
            return
        latest = event_service.get_latest_event()
        if not latest:
            await message.answer("Нет активных мероприятий.")
            return
        chat_id = latest.get("event_chat_id", 0)
        if not chat_id or chat_id == -1:
            await message.answer(
                "❌ Сначала укажи ID чата: /event_chat_set <id>\n\n"
                "1. Создай группу в Telegram\n"
                "2. Добавь бота @ai_takt_bot админом\n"
                "3. Узнай ID группы (@getidsbot)\n"
                "4. Отправь /event_chat_set <id>")
            return
        try:
            link = await message.bot.create_chat_invite_link(
                chat_id=chat_id,
                member_limit=20,
            )
            title = latest.get("title", "Мероприятие")
            invite_text = (
                f"📢 <b>Приглашение: {title}</b>\n\n"
                f"Создан чат для участников мероприятия! "
                f"Переходи по ссылке, чтобы присоединиться:\n"
                f"{link.invite_link}\n\n"
                f"🎉 Ждём всех!"
            )
            await messenger.send_to_team_chat(invite_text, parse_mode="HTML")
            await message.answer(
                f"✅ <b>Приглашение опубликовано в командном чате!</b>\n\n"
                f"Ссылка: {link.invite_link}",
                parse_mode="HTML")
        except Exception as e:
            logger.error(
                "Failed to create invite link for chat %s: %s", chat_id, e
            )
            await message.answer(
                f"❌ Не удалось создать приглашение. "
                f"Убедись, что бот — администратор чата.\n"
                f"Ошибка: {e}"
            )

    # ──────────────────────────────────────────────
    # /event_vote — Инициировать голосование в команде
    # ──────────────────────────────────────────────
    @router.message(Command("event_vote"))
    async def cmd_event_vote(message: types.Message):
        """Опубликовать предложение в командном чате для голосования.

        Используется ТОЛЬКО после согласования ЛПР. ЛПР решает,
        выносить ли вопрос на голосование команды.
        """
        user = message.from_user
        if not user:
            return
        latest = event_service.get_latest_event()
        if not latest:
            await message.answer("Нет активных мероприятий.")
            return
        title = latest.get("title", "Мероприятие")
        desc = latest.get("description", "")
        fmt = EVENT_FORMAT_LABELS.get(latest.get("format", ""), "")
        budget = latest.get("budget", {}).get("estimated_total", 0)
        date_str = latest.get("date", "не назначена")
        vote_text = (
            f"📢 <b>Голосование: {title}</b>\n\n"
            f"📋 Формат: {fmt}\n"
            f"📅 Дата: {date_str}\n"
            f"💰 Бюджет: {budget:,.0f} ₽\n\n"
            f"{desc}\n\n"
            f"— — — — — — — — — —\n"
            f"👇 <b>Реакции для голосования:</b>\n"
            f"✅ — За\n"
            f"❌ — Против\n"
            f"🤷 — Воздержусь"
        )
        await messenger.send_to_team_chat(vote_text, parse_mode="HTML")
        await message.answer(
            f"📢 <b>Голосование опубликовано в командном чате!</b>\n\n"
            f"«{title}» — участники могут голосовать реакциями ✅ ❌ 🤷",
            parse_mode="HTML")

    # ══════════════════════════════════════════════════
    #  MEDIA REVIEW COMMANDS (pre-montage ethical check)
    # ══════════════════════════════════════════════════

    @router.message(Command("media_review"))
    async def cmd_media_review(message: types.Message):
        """
        Start a new media review scan.

        Scans the media input directory, produces metadata for each file,
        and creates a review report. The actual Vision LLM analysis is
        done by the agent (Ouroboros) in a separate step.
        """
        from src.services.media_review_service import MediaReviewService

        mr = MediaReviewService()
        media = mr.scan_media()

        if not media:
            await message.answer(
                "📭 В папке входящих медиа нет файлов.\n"
                "Сначала пришли фото/видео в бот — они сохранятся "
                "автоматически."
            )
            return

        report = mr.create_report(media)

        # Show initial scan results
        lines = [
            f"📋 <b>Сканирование медиа завершено</b>",
            f"",
            f"📁 Найдено файлов: {len(media)}",
            f"",
        ]
        for i, m in enumerate(media, 1):
            lines.append(
                f"{i}. {'📷' if m['media_type']=='photo' else '🎥'} "
                f"<b>{m['filename']}</b> "
                f"({m['file_size_mb']} MB)"
            )

        lines.append("")
        lines.append(
            f"🆔 Review ID: <code>{report.review_id}</code>\n\n"
            f"Теперь я проанализирую каждый файл через Vision AI.\n"
            f"Это займёт несколько минут..."
        )

        await message.answer("\n".join(lines), parse_mode="HTML")

        # Now the agent (Ouroboros) will analyze each file using Vision LLM.
        # This is handled by the agent's task loop — the bot just sends
        # the scan results and waits for the agent to proceed.

    @router.message(Command("media_report"))
    async def cmd_media_report(message: types.Message):
        """Show the full review report for a given review ID."""
        from src.services.media_review_service import MediaReviewService

        parts = message.text.strip().split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "📋 Укажи ID отчёта: /media_report <review_id>\n\n"
                "Пример: /media_report review_1784196006"
            )
            return

        review_id = parts[1].strip()
        mr = MediaReviewService()
        report = mr.get_report(review_id)

        if not report:
            await message.answer(
                f"❌ Отчёт <code>{review_id}</code> не найден.",
                parse_mode="HTML"
            )
            return

        text = mr.generate_report_text(report)
        # Split long messages if needed
        if len(text) > 4000:
            parts_list = [text[i:i+4000] for i in range(0, len(text), 4000)]
            for part in parts_list:
                await message.answer(part, parse_mode="HTML")
        else:
            await message.answer(text, parse_mode="HTML")

    @router.message(Command("media_approve"))
    async def cmd_media_approve(message: types.Message):
        """Approve a media review and proceed with montage."""
        from src.services.media_review_service import MediaReviewService

        user = message.from_user
        if not user:
            return

        parts = message.text.strip().split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "📋 Укажи ID отчёта: /media_approve <review_id>"
            )
            return

        review_id = parts[1].strip()
        mr = MediaReviewService()
        report = mr.get_report(review_id)

        if not report:
            await message.answer(
                f"❌ Отчёт <code>{review_id}</code> не найден.",
                parse_mode="HTML"
            )
            return

        if mr.has_red_flags(report):
            await message.answer(
                "🚫 <b>В отчёте есть заблокированные файлы!</b>\n\n"
                "Их нужно удалить из папки input перед утверждением.\n"
                "После удаления запусти /media_review заново.",
                parse_mode="HTML"
            )
            return

        # Approve
        report.status = "approved"
        report.approved_by = user.first_name or "owner"
        report.approved_at = datetime.utcnow().isoformat()
        mr.update_report(report)

        await message.answer(
            f"✅ <b>Медиа утверждены!</b>\n\n"
            f"Все {len(report.media_files)} файлов чисты.\n"
            f"Можно приступать к монтажу видео.\n\n"
            f"Отчёт: /media_report {review_id}",
            parse_mode="HTML"
        )

    @router.message(Command("media_reject"))
    async def cmd_media_reject(message: types.Message):
        """Reject a media review — mark as blocked."""
        from src.services.media_review_service import MediaReviewService

        user = message.from_user
        if not user:
            return

        parts = message.text.strip().split(maxsplit=2)
        if len(parts) < 2:
            await message.answer(
                "📋 Укажи ID отчёта: /media_reject <review_id> [причина]"
            )
            return

        review_id = parts[1].strip()
        reason = parts[2].strip() if len(parts) > 2 else "Отклонено пользователем"

        mr = MediaReviewService()
        report = mr.get_report(review_id)

        if not report:
            await message.answer(
                f"❌ Отчёт <code>{review_id}</code> не найден.",
                parse_mode="HTML"
            )
            return

        report.status = "rejected"
        report.summary = reason
        mr.update_report(report)

        await message.answer(
            f"❌ <b>Медиа отклонены</b>\n\n"
            f"Причина: {reason}\n\n"
            f"Можно удалить проблемные файлы из папки input\n"
            f"и запустить /media_review заново.",
            parse_mode="HTML"
        )


async def _handle_survey_answer(
    message: types.Message,
    user_id: int,
    first_name: str,
    survey: SurveyState,
    db: UserDatabase,
    messenger: Messenger,
) -> None:
    """Process a survey answer message and save progress."""
    text = message.text or ""
    if not text.strip():
        await message.answer(
            "Напиши ответы текстом. Если не хочешь отвечать — "
            "напиши «пропуск»."
        )
        return

    # Check if user wants to skip the whole survey
    if text.lower().strip() in ("пропустить", "skip all", "не хочу участвовать"):
        await message.answer(
            "Хорошо, я не буду задавать вопросы. Если передумаешь — "
            "просто напиши мне."
        )
        survey.clear_user(user_id)
        return

    # Parse answers
    existing = survey.get_answers(user_id)
    answers = parse_answers(text, existing)
    survey.set_answers(user_id, answers)

    answered = get_answered_count(answers)
    total = len(SURVEY_QUESTION_KEYS)

    if answered >= total:
        # All questions answered — save to Excel
        db_user = db.get_user(user_id)
        username = f"@{db_user['username']}" if db_user and db_user.get("username") else ""

        excel_data = answers_to_excel_data(answers, username)
        success = write_to_employee_base(excel_data)

        if success:
            await message.answer(
                f"✅ Спасибо, {first_name}! Твои ответы сохранены.\n\n"
                f"Я запомнил:"
                f"\n• Имя: {excel_data['full_name']}"
                f"\n• Должность: {answers.get('q3', '—')}"
                f"\n• Хобби: {excel_data['hobby'] or '—'}"
                f"\n\nТеперь я буду держать тебя в курсе событий команды! 🎉"
            )
            # Notify team chat — ONLY the team chat (NOT event chat!)
            # ⚠️ ЛИЧНЫЕ ДАННЫЕ НИКОГДА НЕ ОТПРАВЛЯТЬ В ЧАТ МЕРОПРИЯТИЯ!
            # send_to_team_chat использует TEAM_CHAT_ID (основной корпоративный чат).
            # Никогда не использовать send_to_event_chat для онбординг-данных!
            await messenger.send_to_team_chat(
                f"🎉 Новый сотрудник прошёл онбординг: "
                f"{excel_data['full_name']}!\n"
                f"Должность: {answers.get('q3', '—')}"
            )
        else:
            await message.answer(
                "❌ Произошла ошибка при сохранении данных. "
                "Пожалуйста, свяжись с руководителем."
            )

        survey.clear_user(user_id)

    else:
        # Still have unanswered questions — ask for more
        remaining = total - answered
        await message.answer(
            f"✅ Принято ({answered}/{total}). "
            f"Осталось {remaining} вопросов."
        )

        missing_text = get_missing_questions_text(answers)
        if missing_text:
            await message.answer(missing_text, parse_mode="HTML")


async def _handle_pulse_answer(
    message: types.Message,
    survey_id: str,
    user_id: int,
    pulse_survey: PulseSurveyState,
    messenger: Messenger,
) -> None:
    """Process a pulse survey answer message and save progress."""
    text = message.text or ""
    if not text.strip():
        await message.answer(
            "Напиши ответы текстом. Если не хочешь отвечать — "
            "напиши «пропуск»."
        )
        return

    # Check if user wants to skip the whole survey
    if text.lower().strip() in ("пропустить", "skip all", "не хочу участвовать"):
        await message.answer(
            "Хорошо, я не буду задавать вопросы. Если передумаешь — "
            "просто напиши мне."
        )
        pulse_survey.set_participant_state(survey_id, user_id, "survey_completed")
        return

    # Parse answers
    existing = pulse_survey.get_participant_answers(survey_id, user_id)
    answers = parse_pulse_answers(text, existing)
    pulse_survey.set_participant_answers(survey_id, user_id, answers)

    answered = get_pulse_answered_count(answers)
    total = len(PULSE_QUESTION_KEYS)

    if answered >= total:
        # All questions answered
        pulse_survey.set_participant_state(survey_id, user_id, "survey_completed")
        await message.answer(get_pulse_completion_text())

        # Check if all participants have answered — auto-complete
        survey_data = pulse_survey.get_survey(survey_id)
        if survey_data:
            participants = survey_data.get("participants", {})
            all_done = all(
                p.get("state") == "survey_completed"
                for p in participants.values()
            )
            if all_done:
                # Write Excel
                all_answers = pulse_survey.get_completed_answers(survey_id)
                filepath = write_pulse_survey_excel(all_answers)
                if filepath:
                    pulse_survey.complete_survey(survey_id, str(filepath))
                    # Notify group chat
                    summary = get_pulse_summary_text(survey_data)
                    await messenger.send_to_team_chat(summary, parse_mode="HTML")
    else:
        # Still have unanswered questions
        remaining = total - answered
        await message.answer(
            f"✅ Принято ({answered}/{total}). "
            f"Осталось {remaining} вопросов."
        )

        missing_text = get_pulse_missing_questions_text(answers)
        if missing_text:
            await message.answer(missing_text, parse_mode="HTML")


async def _handle_event_survey_answer(
    message: types.Message,
    survey_id: str,
    user_id: int,
    event_survey: EventSurveyState,
    event_service: EventService,
    messenger: Messenger,
) -> None:
    """Process an event survey answer ANONYMOUSLY.

    АНОНИМНОСТЬ (ABSOLUTE RULE):
    - Ответы НИКОГДА не отправляются ни в какой чат.
    - Ответы сохраняются только в анонимный Excel-файл (без user_id).
    - Пользователь получает только короткое «спасибо» в личку.
    - В командный чат уходит только количество ответивших (без содержания).
    """
    text = message.text or ""
    if not text.strip():
        await message.answer(
            "Напиши ответы текстом. Если не хочешь отвечать — "
            "напиши «пропуск»."
        )
        return

    # Allow skipping
    if text.lower().strip() in ("пропустить", "skip all", "не хочу участвовать", "пропуск"):
        event_survey.set_participant_state(survey_id, user_id, "survey_completed")
        await message.answer(
            "✅ Хорошо, твой ответ принят! "
            "Результаты опроса будут переданы организаторам анонимно."
        )
        return

    # Parse answers
    existing = event_survey.get_participant_answers(survey_id, user_id)
    answers = parse_event_answers(text, existing)
    event_survey.set_participant_answers(survey_id, user_id, answers)

    answered = get_event_answered_count(answers)
    total = len(EVENT_SURVEY_QUESTION_KEYS)

    if answered >= total:
        # All questions answered — mark completed
        event_survey.set_participant_state(survey_id, user_id, "survey_completed")

        # ANONYMOUS thank-you — NO answers shown in any chat!
        await message.answer(
            "✅ Спасибо, твой ответ принят! "
            "Результаты опроса будут переданы организаторам анонимно."
        )

        # Check if all participants have answered
        survey_data = event_survey.get_survey(survey_id)
        if survey_data:
            participants = survey_data.get("participants", {})
            all_done = all(
                p.get("state") == "survey_completed"
                for p in participants.values()
            )
            if all_done:
                # All done — save anonymized Excel (no user_id in output)
                title = survey_data.get("title", "Мероприятие")
                date_str = survey_data.get("date", "")
                all_answers = {
                    uid: p.get("answers", {})
                    for uid, p in participants.items()
                    if p.get("state") == "survey_completed"
                }
                filepath = write_event_survey_excel(title, date_str, all_answers)
                if filepath:
                    event_survey.complete_survey(survey_id, str(filepath))
                    # Find linked event to update survey_id reference
                    from src.services.event_service import DATA_DIR as EV_DATA_DIR
                    ev_path = EV_DATA_DIR / "events.json"
                    try:
                        with open(ev_path, "r", encoding="utf-8") as f:
                            events = json.load(f)
                        for eid, ev in events.items():
                            if ev.get("survey_id") == survey_id:
                                ev["survey_id"] = survey_id  # keep linked
                                break
                    except Exception:
                        pass

                    # Send ONLY a count summary to team chat (no answers!)
                    completed = sum(
                        1 for p in participants.values()
                        if p.get("state") == "survey_completed"
                    )
                    total_p = len(participants)
                    summary = (
                        f"📊 <b>Опрос по мероприятию завершён</b>\n\n"
                        f"Ответили: {completed} из {total_p}\n"
                        f"Результаты сохранены в анонимный файл.\n"
                        f"Спасибо всем за участие! 🙌"
                    )
                    await messenger.send_to_team_chat(summary, parse_mode="HTML")
    else:
        # Still have unanswered questions
        remaining = total - answered
        await message.answer(
            f"✅ Принято ({answered}/{total}). "
            f"Осталось {remaining} вопросов."
        )

        missing_text = get_event_survey_missing(answers)
        if missing_text:
            await message.answer(missing_text, parse_mode="HTML")

    # Holiday Decor handlers are registered BEFORE the general survey/media
    # handlers (see above, before survey_or_general), so they take priority
    # when the decor state machine is active. Photo/text handlers use
    # state-specific filters — non-decor messages fall through naturally.