"""Event Calendar Service for ai-takt — task scheduling and timeline management.

Manages the event preparation timeline:
  - Task creation and assignment
  - Deadline tracking
  - Task status workflow
  - Timeline visualization

Built on top of EventService — stores tasks within the event data model.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


# ── Task statuses ──
TASK_STATUSES = ["pending", "in_progress", "done", "cancelled"]

# ── Default task templates per event format ──
EVENT_TASK_TEMPLATES = {
    "team_building": [
        ("Выбрать дату мероприятия", 14),
        ("Найти и забронировать площадку", 14),
        ("Составить смету и согласовать с ЛПР", 10),
        ("Организовать трансфер", 7),
        ("Закупить реквизит для игр", 5),
        ("Подготовить программу мероприятия", 5),
        ("Создать чат участников", 4),
        ("Опубликовать программу", 3),
        ("Провести мероприятие", 0),
        ("Собрать фото/видео материалы", 0),
        ("Отправить пост-опрос", 1),
        ("Создать видео-воспоминание", 3),
    ],
    "corporate": [
        ("Выбрать дату", 21),
        ("Выбрать ресторан / площадку", 21),
        ("Составить смету и согласовать", 14),
        ("Пригласить ведущего / артистов", 14),
        ("Продумать меню", 10),
        ("Заказать декор", 7),
        ("Подготовить сценарий", 7),
        ("Создать чат участников", 5),
        ("Опубликовать программу", 3),
        ("Провести мероприятие", 0),
        ("Собрать фото/видео", 0),
        ("Отправить пост-опрос", 1),
        ("Создать видео-воспоминание", 3),
    ],
    "workshop": [
        ("Выбрать дату", 14),
        ("Найти площадку", 10),
        ("Составить смету", 7),
        ("Подготовить материалы", 7),
        ("Разослать приглашения", 5),
        ("Создать чат участников", 3),
        ("Опубликовать программу", 2),
        ("Провести воркшоп", 0),
        ("Отправить пост-опрос", 1),
        ("Собрать отзывы", 2),
    ],
    "outdoor": [
        ("Выбрать дату", 21),
        ("Забронировать базу отдыха", 21),
        ("Составить смету", 14),
        ("Организовать трансфер", 10),
        ("Продумать меню", 7),
        ("Закупить снаряжение", 5),
        ("Создать чат участников", 4),
        ("Опубликовать программу", 3),
        ("Провести выезд", 0),
        ("Собрать фото/видео", 0),
        ("Отправить пост-опрос", 1),
        ("Создать видео-воспоминание", 3),
    ],
    "sport": [
        ("Выбрать дату и вид спорта", 14),
        ("Забронировать площадку", 14),
        ("Составить смету", 10),
        ("Закупить инвентарь и призы", 7),
        ("Создать чат участников", 4),
        ("Опубликовать программу", 2),
        ("Провести соревнование", 0),
        ("Отправить пост-опрос", 1),
        ("Создать видео-нарезку", 3),
    ],
    "cultural": [
        ("Выбрать мероприятие", 10),
        ("Купить билеты", 10),
        ("Составить смету", 7),
        ("Организовать трансфер", 5),
        ("Создать чат участников", 3),
        ("Опубликовать программу", 1),
        ("Посетить мероприятие", 0),
        ("Отправить пост-опрос", 1),
    ],
    "conference": [
        ("Выбрать дату", 21),
        ("Найти площадку", 21),
        ("Составить смету", 14),
        ("Пригласить спикеров", 14),
        ("Подготовить программу", 10),
        ("Разослать приглашения", 7),
        ("Создать чат участников", 4),
        ("Опубликовать программу", 3),
        ("Провести конференцию", 0),
        ("Собрать обратную связь", 1),
        ("Создать видео-дайджест", 3),
    ],
    "online": [
        ("Выбрать дату и время", 7),
        ("Выбрать платформу", 7),
        ("Подготовить материалы", 5),
        ("Разослать приглашения", 3),
        ("Создать чат участников", 2),
        ("Опубликовать программу", 1),
        ("Провести онлайн-встречу", 0),
        ("Отправить пост-опрос", 1),
    ],
    "other": [
        ("Выбрать дату", 14),
        ("Составить смету", 10),
        ("Подготовить программу", 7),
        ("Создать чат участников", 3),
        ("Опубликовать программу", 2),
        ("Провести мероприятие", 0),
        ("Отправить пост-опрос", 1),
    ],
}


def get_task_template(format_key: str) -> list:
    """Get the default task template for a given event format.

    Returns list of (task_title, days_before_event).
    Days are relative to the event date (0 = event day).
    """
    return EVENT_TASK_TEMPLATES.get(format_key, EVENT_TASK_TEMPLATES["other"])


def get_timeline_text(tasks: list, event_date_str: str = "") -> str:
    """Render a timeline of tasks relative to the event date."""
    if not tasks:
        return "📅 Задачи не назначены."

    status_icons = {
        "pending": "⏳",
        "in_progress": "🔄",
        "done": "✅",
        "cancelled": "❌",
    }

    # Group tasks by status
    pending = [t for t in tasks if t.get("status") == "pending"]
    in_progress = [t for t in tasks if t.get("status") == "in_progress"]
    done = [t for t in tasks if t.get("status") == "done"]

    lines = ["📅 <b>Таймлайн подготовки:</b>\n"]

    if in_progress:
        lines.append("🔄 <b>В работе:</b>")
        for t in in_progress:
            lines.append(f"  • {t.get('title', '—')} (⏰ {t.get('deadline', '—')})")
        lines.append("")

    if pending:
        lines.append("⏳ <b>Ожидают:</b>")
        for t in pending:
            lines.append(f"  • {t.get('title', '—')} (⏰ {t.get('deadline', '—')})")
        lines.append("")

    if done:
        lines.append(f"✅ <b>Выполнено ({len(done)}):</b>")
        for t in done[:5]:  # Show last 5 done
            lines.append(f"  • {t.get('title', '—')}")
        if len(done) > 5:
            lines.append(f"  ... и ещё {len(done) - 5}")

    return "\n".join(lines)


def get_preparation_progress(tasks: list) -> dict:
    """Calculate preparation progress metrics.

    Returns dict with total, done, pending, in_progress, progress_pct.
    """
    total = len(tasks)
    if total == 0:
        return {"total": 0, "done": 0, "pending": 0, "in_progress": 0, "progress_pct": 0}

    done = sum(1 for t in tasks if t.get("status") == "done")
    in_progress = sum(1 for t in tasks if t.get("status") == "in_progress")
    pending = sum(1 for t in tasks if t.get("status") == "pending")

    # Progress: done counts fully, in_progress counts half
    progress_pct = int((done + in_progress * 0.5) / total * 100)

    return {
        "total": total,
        "done": done,
        "pending": pending,
        "in_progress": in_progress,
        "progress_pct": progress_pct,
    }


def get_progress_bar(progress_pct: int, width: int = 10) -> str:
    """Render a text progress bar."""
    filled = int(progress_pct / 100 * width)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return f"{bar} {progress_pct}%"


def format_deadline(days_before: int, event_date: Optional[str] = None) -> str:
    """Format a deadline string from days before event.

    If event_date is provided, computes the actual calendar date.
    Otherwise returns a relative description.
    """
    if event_date:
        # Try to parse event date
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y"):
            try:
                dt = datetime.strptime(event_date, fmt)
                deadline = dt - timedelta(days=days_before)
                return deadline.strftime("%d.%m.%Y")
            except ValueError:
                continue
        return f"За {days_before} дн. до"
    elif days_before == 0:
        return "В день мероприятия"
    elif days_before == 1:
        return "За 1 день до"
    elif days_before == 2:
        return "За 2 дня до"
    elif days_before <= 7:
        return f"За {days_before} дн. до"
    elif days_before <= 14:
        return f"За {days_before} дн. до"
    else:
        return f"За {days_before} дн. до"