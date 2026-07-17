"""Event Service for ai-takt — full event lifecycle management.

Lifecycle state machine:
  proposal → budgeting → approval → planning → chat_created
  → program_published → active → completed → archived

Each event goes through the full cycle:
  1. Proposal (format предложение)
  2. Budget estimate (смета)
  3. LPR approval (согласование)
  4. Task calendar (календарь задач)
  5. Event chat creation (чат мероприятия)
  6. Program publication (программа)
  7. Execution (проведение)
  8. Post-event survey (опрос)
  9. Memories video (клип «Воспоминания»)

Persisted to data/events.json — survives bot restarts.
"""
import json
import logging
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Paths ──
DATA_DIR = Path(__file__).parent.parent / "data"
EVENTS_STATE_PATH = DATA_DIR / "events.json"
EVENT_EXCEL_DIR = Path(
    r"C:\Users\User\Ouroboros\Deliverables\excel_data"
)

# ── Valid lifecycle states ──
EVENT_STATES = [
    "proposal",      # Предложение формата
    "budgeting",     # Смета составлена
    "approval",      # На согласовании с ЛПР
    "planning",      # Планирование задач
    "chat_created",  # Чат мероприятия создан
    "program_published",  # Программа опубликована
    "active",        # Мероприятие проводится
    "completed",     # Завершено
    "archived",      # В архиве
]

# ── Event format types ──
EVENT_FORMATS = [
    "team_building",    # Тимбилдинг
    "corporate",        # Корпоратив
    "workshop",         # Воркшоп/тренинг
    "conference",       # Конференция/лекция
    "outdoor",          # Выездное мероприятие
    "online",           # Онлайн-встреча
    "sport",            # Спортивное мероприятие
    "cultural",         # Культурное (кино, театр, выставка)
    "other",            # Другое
]

EVENT_FORMAT_LABELS = {
    "team_building": "Тимбилдинг",
    "corporate": "Корпоратив",
    "workshop": "Воркшоп / Тренинг",
    "conference": "Конференция / Лекция",
    "outdoor": "Выездное мероприятие",
    "online": "Онлайн-встреча",
    "sport": "Спортивное мероприятие",
    "cultural": "Культурное (кино, театр, выставка)",
    "other": "Другое",
}

# ── Budget item categories ──
BUDGET_CATEGORIES = [
    "venue",        # Площадка
    "catering",     # Еда и напитки
    "transport",    # Транспорт
    "equipment",    # Оборудование
    "decoration",   # Декор
    "entertainment",# Развлечения
    "gifts",        # Подарки/призы
    "printing",     # Полиграфия
    "photo_video",  # Фото/видео
    "other",        # Прочее
]

BUDGET_CATEGORY_LABELS = {
    "venue": "Площадка",
    "catering": "Еда и напитки",
    "transport": "Транспорт",
    "equipment": "Оборудование",
    "decoration": "Декор",
    "entertainment": "Развлечения",
    "gifts": "Подарки/призы",
    "printing": "Полиграфия",
    "photo_video": "Фото/видео",
    "other": "Прочее",
}


# ══════════════════════════════════════════════
#  Text templates
# ══════════════════════════════════════════════

def get_format_suggestions_text() -> str:
    """Return the list of available event formats."""
    lines = ["📋 <b>Возможные форматы мероприятий:</b>\n"]
    for key, label in EVENT_FORMAT_LABELS.items():
        lines.append(f"• {label}")
    lines.append("\nНапиши, какой формат тебя интересует, "
                  "или предложи свой вариант.")
    return "\n".join(lines)


def get_proposal_intro_text(first_name: str) -> str:
    return (
        f"🎉 {first_name}, давай создадим новое мероприятие!\n\n"
        f"Я помогу организовать полный цикл: от идеи до "
        f"воспоминаний.\n\n"
        f"Для начала выбери формат мероприятия."
    )


def get_event_status_text(event: dict, detailed: bool = False) -> str:
    """Return a human-readable event status summary."""
    status_labels = {
        "proposal": "📝 Предложение",
        "budgeting": "💰 Составление сметы",
        "approval": "📋 На согласовании с ЛПР",
        "planning": "📅 Планирование задач",
        "chat_created": "💬 Чат создан",
        "program_published": "📢 Программа опубликована",
        "active": "🎉 Проводится",
        "completed": "✅ Завершено",
        "archived": "📦 В архиве",
    }

    fmt = EVENT_FORMAT_LABELS.get(event.get("format", ""), event.get("format", "—"))
    status = status_labels.get(event.get("status", ""), event.get("status", "—"))
    title = event.get("title", "Без названия")
    desc = event.get("description", "")
    date_str = event.get("date", "не назначена")

    lines = [
        f"🎯 <b>{title}</b>",
        f"Формат: {fmt}",
        f"Статус: {status}",
        f"Дата: {date_str}",
    ]

    if desc:
        lines.append(f"\n📄 {desc}")

    if detailed:
        # Budget info
        budget = event.get("budget", {})
        if budget.get("items"):
            total = budget.get("estimated_total", 0)
            lines.append(f"\n💰 <b>Смета:</b> {total:,.0f} ₽")
            for item in budget["items"]:
                cat_label = BUDGET_CATEGORY_LABELS.get(
                    item.get("category", ""), item.get("category", "")
                )
                lines.append(f"  • {cat_label}: {item.get('amount', 0):,.0f} ₽")
                if item.get("notes"):
                    lines.append(f"    ({item['notes']})")

        # LPR approval
        approval = event.get("lpr_approval", {})
        if approval:
            lines.append(f"\n📋 <b>Согласование:</b> "
                         f"{'✅ Согласовано' if approval.get('approved') else '⏳ Ожидает'}")
            if approval.get("comments"):
                lines.append(f"📝 {approval['comments']}")

        # Tasks
        tasks = event.get("tasks", [])
        if tasks:
            done = sum(1 for t in tasks if t.get("status") == "done")
            lines.append(f"\n📅 <b>Задачи:</b> {done}/{len(tasks)} выполнено")

        # Program
        if event.get("program"):
            lines.append(f"\n📢 <b>Программа:</b> опубликована")

        # Survey
        if event.get("survey_id"):
            lines.append(f"\n📊 <b>Опрос:</b> проведён")

    return "\n".join(lines)


def get_taskboard_text(tasks: list) -> str:
    """Render a task board as text."""
    if not tasks:
        return "📅 <b>Задачи не назначены.</b>"

    status_icons = {
        "pending": "⏳",
        "in_progress": "🔄",
        "done": "✅",
        "cancelled": "❌",
    }

    lines = ["📅 <b>Календарь задач:</b>\n"]
    for t in tasks:
        icon = status_icons.get(t.get("status", "pending"), "⏳")
        deadline = t.get("deadline", "—")
        title = t.get("title", "—")
        assigned = t.get("assigned_to_name", "")
        assignee = f" — {assigned}" if assigned else ""
        lines.append(f"{icon} <b>{title}</b>{assignee}")
        lines.append(f"   ⏰ {deadline}")
        if t.get("notes"):
            lines.append(f"   📝 {t['notes']}")
        lines.append("")
    return "\n".join(lines)


def get_program_text(event: dict) -> str:
    """Return a formatted event program."""
    title = event.get("title", "Мероприятие")
    date_str = event.get("date", "TBD")
    program = event.get("program", "")

    lines = [
        f"📢 <b>Программа: {title}</b>",
        f"📅 {date_str}",
        "",
        program,
        "",
        "— — — — — — — — — —",
        "Ждём всех! 🎉",
    ]
    return "\n".join(lines)


def get_event_completion_text(event: dict) -> str:
    """Return a summary when an event is completed."""
    title = event.get("title", "Мероприятие")
    return (
        f"✅ <b>Мероприятие «{title}» завершено!</b>\n\n"
        f"Спасибо всем участникам! 🎉\n\n"
        f"Далее:\n"
        f"📊 /event_survey_post — анонимный опрос (вопросы в личку)\n"
        f"🎬 /event_video — видео-воспоминание (в командный чат)"
    )


# ══════════════════════════════════════════════
#  Event State Machine
# ══════════════════════════════════════════════

class EventService:
    """Persistent event lifecycle manager.

    Manages the full event lifecycle from proposal to archive.
    State transitions are validated — illegal transitions are rejected.
    """

    def __init__(self, state_path: Optional[Path] = None):
        self.state_path = state_path or EVENTS_STATE_PATH
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {}
        self._load()

    # ── Persistence ──

    def _load(self) -> None:
        if self.state_path.exists():
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, Exception):
                logger.warning("Failed to load events, resetting")
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    # ── Event CRUD ──

    def create_event(
        self,
        title: str,
        event_format: str,
        description: str,
        proposed_by: int,
        proposed_by_name: str = "",
    ) -> dict:
        """Create a new event proposal.

        Returns the event data dict.
        """
        import time as time_module
        event_id = f"event_{int(time_module.time())}"

        event = {
            "event_id": event_id,
            "title": title,
            "format": event_format,
            "description": description,
            "proposed_by": proposed_by,
            "proposed_by_name": proposed_by_name,
            "proposed_at": datetime.utcnow().isoformat(),
            "status": "proposal",
            "date": "",
            "budget": {
                "estimated_total": 0,
                "items": [],
                "currency": "RUB",
            },
            "lpr_approval": {
                "approved": False,
                "approved_by": None,
                "approved_at": None,
                "comments": "",
            },
            "tasks": [],
            "event_chat_id": None,
            "program": "",
            "survey_id": None,
            "video_path": None,
            "completed_at": None,
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._data[event_id] = event
        self._save()
        logger.info("Created event '%s' (id=%s, format=%s)", title, event_id, event_format)
        return event

    def get_event(self, event_id: str) -> Optional[dict]:
        """Get an event by its event_id."""
        return self._data.get(event_id)

    def get_all_events(self) -> dict:
        """Get all events."""
        return dict(self._data)

    def get_events_by_status(self, status: str) -> dict:
        """Get all events in a given status."""
        return {
            eid: e for eid, e in self._data.items()
            if e.get("status") == status
        }

    def get_active_events(self) -> dict:
        """Get all non-archived events."""
        return {
            eid: e for eid, e in self._data.items()
            if e.get("status") not in ("completed", "archived")
        }

    def get_latest_event(self) -> Optional[dict]:
        """Get the most recently created event."""
        if not self._data:
            return None
        # Sort by proposed_at descending
        sorted_events = sorted(
            self._data.values(),
            key=lambda e: e.get("proposed_at", ""),
            reverse=True,
        )
        return sorted_events[0]

    # ── State machine ──

    # Allowed transitions: from_state -> list of to_state
    _TRANSITIONS = {
        "proposal":          ["budgeting", "archived"],
        "budgeting":         ["approval", "proposal", "archived"],
        "approval":          ["planning", "budgeting", "archived"],
        "planning":          ["chat_created", "approval", "archived"],
        "chat_created":      ["program_published", "planning", "archived"],
        "program_published": ["active", "planning", "archived"],
        "active":            ["completed", "archived"],
        "completed":         ["archived"],
        "archived":          [],  # Terminal state
    }

    def _validate_transition(self, current_status: str, new_status: str) -> bool:
        """Check if a state transition is valid."""
        allowed = self._TRANSITIONS.get(current_status, [])
        if new_status not in allowed:
            logger.warning(
                "Invalid transition: %s -> %s (allowed: %s)",
                current_status, new_status, allowed,
            )
            return False
        return True

    def transition_event(self, event_id: str, new_status: str) -> bool:
        """Transition an event to a new status.

        Validates the transition. Returns True on success.
        """
        event = self._data.get(event_id)
        if not event:
            logger.error("Event %s not found", event_id)
            return False

        current = event.get("status", "")
        if not self._validate_transition(current, new_status):
            return False

        event["status"] = new_status
        event["updated_at"] = datetime.utcnow().isoformat()

        if new_status == "completed":
            event["completed_at"] = datetime.utcnow().isoformat()

        self._save()
        logger.info("Event %s transitioned: %s -> %s", event_id, current, new_status)
        return True

    # ── Budget management ──

    def set_budget_items(self, event_id: str, items: list) -> bool:
        """Set the budget line items for an event.

        Each item: {"category": str, "amount": float, "notes": str}
        """
        event = self._data.get(event_id)
        if not event:
            return False

        total = sum(item.get("amount", 0) for item in items)
        event["budget"]["items"] = items
        event["budget"]["estimated_total"] = total
        event["updated_at"] = datetime.utcnow().isoformat()
        self._save()
        logger.info("Budget set for %s: %.0f ₽ (%d items)", event_id, total, len(items))
        return True

    def get_budget_text(self, event_id: str) -> str:
        """Return a formatted budget estimate."""
        event = self._data.get(event_id)
        if not event:
            return "Событие не найдено."

        budget = event.get("budget", {})
        items = budget.get("items", [])
        total = budget.get("estimated_total", 0)

        if not items:
            return "💰 <b>Смета не составлена.</b>"

        lines = [
            f"💰 <b>Смета: {event.get('title', '')}</b>\n"
        ]
        for item in items:
            cat_label = BUDGET_CATEGORY_LABELS.get(
                item.get("category", ""), item.get("category", "")
            )
            amount = item.get("amount", 0)
            notes = item.get("notes", "")
            line = f"• {cat_label}: {amount:,.0f} ₽"
            if notes:
                line += f" — {notes}"
            lines.append(line)

        lines.append(f"\n<b>Итого: {total:,.0f} ₽</b>")
        return "\n".join(lines)

    # ── LPR approval ──

    def approve_event(self, event_id: str, approved_by: int,
                      comments: str = "") -> bool:
        """Approve an event by LPR."""
        event = self._data.get(event_id)
        if not event:
            return False

        event["lpr_approval"]["approved"] = True
        event["lpr_approval"]["approved_by"] = approved_by
        event["lpr_approval"]["approved_at"] = datetime.utcnow().isoformat()
        event["lpr_approval"]["comments"] = comments
        event["updated_at"] = datetime.utcnow().isoformat()
        self._save()
        logger.info("Event %s approved by %s", event_id, approved_by)
        return True

    def reject_event(self, event_id: str, rejected_by: int,
                     comments: str = "") -> bool:
        """Reject an event proposal (send back to budgeting)."""
        event = self._data.get(event_id)
        if not event:
            return False

        event["lpr_approval"]["approved"] = False
        event["lpr_approval"]["approved_by"] = rejected_by
        event["lpr_approval"]["approved_at"] = datetime.utcnow().isoformat()
        event["lpr_approval"]["comments"] = comments
        event["updated_at"] = datetime.utcnow().isoformat()
        # Transition back to budgeting
        self.transition_event(event_id, "budgeting")
        logger.info("Event %s rejected by %s: %s", event_id, rejected_by, comments)
        return True

    # ── Task calendar ──

    def add_task(self, event_id: str, title: str, deadline: str = "",
                 assigned_to: int = 0, assigned_to_name: str = "",
                 notes: str = "") -> bool:
        """Add a task to the event calendar."""
        event = self._data.get(event_id)
        if not event:
            return False

        import time as time_module
        task_id = f"task_{int(time_module.time())}_{len(event['tasks'])}"

        task = {
            "task_id": task_id,
            "title": title,
            "deadline": deadline,
            "assigned_to": assigned_to,
            "assigned_to_name": assigned_to_name,
            "status": "pending",
            "notes": notes,
            "created_at": datetime.utcnow().isoformat(),
        }
        event["tasks"].append(task)
        event["updated_at"] = datetime.utcnow().isoformat()
        self._save()
        logger.info("Task added to %s: %s", event_id, title)
        return True

    def update_task_status(self, event_id: str, task_id: str,
                           new_status: str) -> bool:
        """Update the status of a task."""
        event = self._data.get(event_id)
        if not event:
            return False

        for task in event["tasks"]:
            if task["task_id"] == task_id:
                task["status"] = new_status
                event["updated_at"] = datetime.utcnow().isoformat()
                self._save()
                logger.info("Task %s in %s: %s", task_id, event_id, new_status)
                return True
        return False

    def get_incomplete_tasks(self, event_id: str) -> list:
        """Get all incomplete tasks for an event."""
        event = self._data.get(event_id)
        if not event:
            return []
        return [
            t for t in event["tasks"]
            if t.get("status") in ("pending", "in_progress")
        ]

    # ── Event chat ──

    def set_event_chat(self, event_id: str, chat_id: int) -> bool:
        """Record the event chat ID."""
        event = self._data.get(event_id)
        if not event:
            return False
        event["event_chat_id"] = chat_id
        event["updated_at"] = datetime.utcnow().isoformat()
        self._save()
        return True

    # ── Program ──

    def set_program(self, event_id: str, program_text: str) -> bool:
        """Set the event program."""
        event = self._data.get(event_id)
        if not event:
            return False
        event["program"] = program_text
        event["updated_at"] = datetime.utcnow().isoformat()
        self._save()
        return True

    # ── Survey ──

    def set_survey_id(self, event_id: str, survey_id: str) -> bool:
        """Link a post-event survey to the event."""
        event = self._data.get(event_id)
        if not event:
            return False
        event["survey_id"] = survey_id
        event["updated_at"] = datetime.utcnow().isoformat()
        self._save()
        return True

    # ── Memories video ──

    def set_video_path(self, event_id: str, video_path: str) -> bool:
        """Record the memories video file path."""
        event = self._data.get(event_id)
        if not event:
            return False
        event["video_path"] = video_path
        event["updated_at"] = datetime.utcnow().isoformat()
        self._save()
        return True

    # ── Event date ──

    def set_event_date(self, event_id: str, date_str: str) -> bool:
        """Set the planned event date."""
        event = self._data.get(event_id)
        if not event:
            return False
        event["date"] = date_str
        event["updated_at"] = datetime.utcnow().isoformat()
        self._save()
        return True

    # ── Event title ──

    def set_title(self, event_id: str, title: str) -> bool:
        """Update the event title."""
        event = self._data.get(event_id)
        if not event:
            return False
        event["title"] = title
        event["updated_at"] = datetime.utcnow().isoformat()
        self._save()
        return True

    # ── Utility ──

    def get_events_need_reminder(self) -> list:
        """Get events that need attention (stuck in a state)."""
        import time as time_module
        now = time_module.time()
        stuck = []
        for eid, event in self._data.items():
            status = event.get("status", "")
            # Skip completed/archived events
            if status in ("completed", "archived"):
                continue
            stuck.append(event)
        return stuck

    def get_event_summary_for_taskboard(self, event_id: str) -> str:
        """Return a taskboard summary for an event."""
        event = self._data.get(event_id)
        if not event:
            return "Событие не найдено."

        title = event.get("title", "—")
        status = event.get("status", "—")
        date_str = event.get("date", "не назначена")
        tasks = event.get("tasks", [])

        total = len(tasks)
        done = sum(1 for t in tasks if t.get("status") == "done")
        pending = sum(1 for t in tasks if t.get("status") == "pending")
        in_progress = sum(1 for t in tasks if t.get("status") == "in_progress")
        budget = event.get("budget", {}).get("estimated_total", 0)
        approved = event.get("lpr_approval", {}).get("approved", False)

        lines = [
            f"🎯 <b>{title}</b>",
            f"📅 {date_str}",
            f"📋 Статус: {status}",
            f"💰 Бюджет: {budget:,.0f} ₽",
            f"✅ Согласовано: {'Да' if approved else 'Нет'}",
            f"",
            f"📅 <b>Задачи:</b> {done}/{total} выполнено",
        ]
        if pending:
            lines.append(f"⏳ Ожидают: {pending}")
        if in_progress:
            lines.append(f"🔄 В работе: {in_progress}")

        return "\n".join(lines)


# ══════════════════════════════════════════════
#  Budget suggestion templates
# ══════════════════════════════════════════════

def get_default_budget_items(event_format: str, participant_count: int = 10) -> list:
    """Return default budget items for a given event format.

    These are starting estimates — LPR adjusts them.
    """
    base_items = []

    if event_format == "team_building":
        base_items = [
            {"category": "venue", "amount": 15000 * max(1, participant_count // 10), "notes": "Аренда площадки"},
            {"category": "catering", "amount": 8000 * max(1, participant_count // 5), "notes": "Еда и напитки"},
            {"category": "equipment", "amount": 5000, "notes": "Реквизит для игр"},
            {"category": "transport", "amount": 10000, "notes": "Трансфер (если нужен)"},
        ]
    elif event_format == "corporate":
        base_items = [
            {"category": "venue", "amount": 30000 * max(1, participant_count // 10), "notes": "Ресторан / банкетный зал"},
            {"category": "catering", "amount": 15000 * max(1, participant_count // 5), "notes": "Банкет"},
            {"category": "entertainment", "amount": 20000, "notes": "Ведущий / музыка"},
            {"category": "decoration", "amount": 10000, "notes": "Декор"},
            {"category": "photo_video", "amount": 15000, "notes": "Фото/видео"},
        ]
    elif event_format == "workshop":
        base_items = [
            {"category": "venue", "amount": 10000, "notes": "Переговорка / лофт"},
            {"category": "catering", "amount": 5000, "notes": "Кофе-брейк"},
            {"category": "equipment", "amount": 5000, "notes": "Материалы для воркшопа"},
            {"category": "printing", "amount": 2000, "notes": "Раздаточные материалы"},
        ]
    elif event_format == "outdoor":
        base_items = [
            {"category": "venue", "amount": 20000, "notes": "База отдыха / парк"},
            {"category": "catering", "amount": 10000, "notes": "Шашлык / пикник"},
            {"category": "transport", "amount": 15000, "notes": "Автобус"},
            {"category": "equipment", "amount": 8000, "notes": "Спортинвентарь"},
        ]
    elif event_format == "sport":
        base_items = [
            {"category": "venue", "amount": 12000, "notes": "Аренда поля / зала"},
            {"category": "equipment", "amount": 5000, "notes": "Инвентарь"},
            {"category": "catering", "amount": 5000, "notes": "Вода и снеки"},
            {"category": "gifts", "amount": 5000, "notes": "Призы победителям"},
        ]
    elif event_format == "cultural":
        base_items = [
            {"category": "venue", "amount": 15000, "notes": "Билеты"},
            {"category": "catering", "amount": 5000, "notes": "Фуршет / перекус"},
            {"category": "transport", "amount": 8000, "notes": "Такси / трансфер"},
        ]
    else:
        # Default for conference, online, other
        base_items = [
            {"category": "venue", "amount": 10000, "notes": "Площадка"},
            {"category": "catering", "amount": 5000, "notes": "Еда и напитки"},
            {"category": "other", "amount": 5000, "notes": "Прочие расходы"},
        ]

    return base_items