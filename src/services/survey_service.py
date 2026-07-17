"""Survey service for ai-takt — onboarding new employees.

Manages the survey state machine and writes results to employee_base.xlsx.

States:
  - new_member_alerted: bot told user to write to it
  - survey_sent: survey questions sent, awaiting answers
  - survey_completed: survey done, data saved to Excel
"""
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Paths
DATA_DIR = Path(__file__).parent.parent / "data"
SURVEY_STATE_PATH = DATA_DIR / "survey_state.json"
EMPLOYEE_BASE = Path(
    r"C:\Users\User\Ouroboros\Deliverables\excel_data\employee_base.xlsx"
)

# Survey questions for new employee onboarding
SURVEY_QUESTIONS = [
    ("1", "Твоё полное имя?"),
    ("2", "Дата рождения (день и месяц, год необязателен)?"),
    ("3", "Твоя должность и основной функционал?"),
    ("4", "Хобби и интересы (чем увлекаешься вне работы)?"),
    ("5", "Семейный статус (по желанию)?"),
    ("6", "Есть ли дети? Если да, укажи пол и возраст (по желанию)?"),
    ("7", "Какие твои ключевые профессиональные навыки (скилы)?"),
]

SURVEY_QUESTION_KEYS = ["q1", "q2", "q3", "q4", "q5", "q6", "q7"]


def get_survey_intro_text(first_name: str) -> str:
    """Return the onboarding survey introduction."""
    return (
        f"👋 Привет, {first_name}! Добро пожаловать в команду!\n\n"
        f"Я — ai-takt, корпоративный ассистент. Я помогу тебе "
        f"влиться в коллектив и буду держать в курсе событий.\n\n"
        f"Давай я задам тебе несколько вопросов, чтобы узнать тебя "
        f"лучше. Ответы — только для команды, конфиденциально.\n\n"
        f"Просто напиши ответы по порядку в одном сообщении "
        f"(или частями). Я запомню только то, что ты укажешь."
    )


def get_survey_questions_text() -> str:
    """Return the full list of survey questions."""
    lines = ["📋 <b>Несколько вопросов:</b>\n"]
    for num, question in SURVEY_QUESTIONS:
        lines.append(f"<b>{num}.</b> {question}")
    lines.append(
        "\nНапиши ответы по порядку (например: «1. Иван Иванов 2. 15.03 ...»)"
        " или частями. Если не хочешь на что-то отвечать — напиши «пропуск»."
    )
    return "\n".join(lines)


def get_first_reminder_text() -> str:
    """Return the first-time 'write to me' DM text."""
    return (
        "👋 Привет! Добро пожаловать в нашу команду!\n\n"
        "Напиши мне личное сообщение (просто отправь /start), "
        "чтобы я мог задать тебе несколько вопросов и запомнить тебя."
    )


class SurveyState:
    """Persistent survey state manager — stores mid-survey progress."""

    def __init__(self, state_path: Optional[Path] = None):
        self.state_path = state_path or SURVEY_STATE_PATH
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self.state_path.exists():
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, Exception):
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get_state(self, user_id: int) -> Optional[str]:
        """Get the current survey state for a user, or None."""
        entry = self._data.get(str(user_id))
        return entry.get("state") if entry else None

    def set_state(self, user_id: int, state: str) -> None:
        """Set the survey state for a user."""
        uid = str(user_id)
        if uid not in self._data:
            self._data[uid] = {"answers": {}}
        self._data[uid]["state"] = state
        self._data[uid]["updated_at"] = datetime.utcnow().isoformat()
        self._save()

    def get_answers(self, user_id: int) -> dict:
        """Get saved answers for a user."""
        entry = self._data.get(str(user_id))
        return entry.get("answers", {}) if entry else {}

    def set_answers(self, user_id: int, answers: dict) -> None:
        """Set answers for a user (merge)."""
        uid = str(user_id)
        if uid not in self._data:
            self._data[uid] = {"state": "survey_sent", "answers": {}}
        self._data[uid]["answers"] = answers
        self._data[uid]["updated_at"] = datetime.utcnow().isoformat()
        self._save()

    def clear_user(self, user_id: int) -> None:
        """Remove a user from survey state after completion."""
        self._data.pop(str(user_id), None)
        self._save()


def parse_answers(text: str, existing: dict) -> dict:
    """Parse survey answers from user message.

    Looks for numbered answers like "1. Ivan Ivanov 2. 15.03..."
    or plain text that gets assigned to the first unanswered question.
    Merges with existing answers.

    Returns dict of {q1: ..., q2: ..., etc}.
    """
    answers = dict(existing)  # copy existing

    # Try to find numbered answers: "1. text 2. text ..." or "1) text 2) text"
    # Also handle "1 - text" style
    found_numbers = set()
    for q_key, q_num_str, _ in _get_question_map():
        # Pattern: number followed by . or ) or -
        pattern = rf"(?:^|(?<=\n)|(?<=[ ])){re.escape(q_num_str)}[.)\-\s]+(.+?)(?=(?:\n\s*(?:[1-7][.)\-\s])|$))"
        # Simpler: split by "N." or "N)" patterns
        pass

    # Simple approach: split by numbered patterns
    # Pattern matches "1." or "1)" or "1 -" at start of line or after whitespace
    parts = re.split(
        r'(?:^|[\s\n])([1-7])\s*[.)\-\s]\s*',
        text.strip(),
        flags=re.MULTILINE,
    )

    # parts will be: [prefix, num1, text1, num2, text2, ...]
    if len(parts) >= 3:
        # Has numbered answers — extract them
        i = 1  # start at index 1 (after any prefix)
        while i + 1 < len(parts):
            num_str = parts[i].strip()
            answer_text = parts[i + 1].strip()
            if num_str in "1234567":
                q_key = f"q{num_str}"
                if answer_text and answer_text.lower() not in ("пропуск", "skip", "-"):
                    # Remove trailing incomplete number (e.g. "text 2." at end)
                    # This happens when the next number is captured as part of text
                    answer_text = re.sub(r'\s*[1-7]\s*[.)\-\s]\s*$', '', answer_text).strip()
                    answers[q_key] = answer_text
                    found_numbers.add(num_str)
                else:
                    answers[q_key] = ""  # explicitly skipped
                    found_numbers.add(num_str)
            i += 2

    if found_numbers:
        return answers

    # No numbered pattern found — try to match by line count or assign to first unanswered
    # Check if the text contains answers separated by newlines
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) >= 2:
        # Try to map lines to unanswered questions
        unanswered = _get_unanswered_keys(answers)
        for i, line in enumerate(lines):
            if i < len(unanswered) and line.lower() not in ("пропуск", "skip", "-", ""):
                answers[unanswered[i]] = line
                # Check if this line starts with a number
            elif i < len(unanswered):
                answers[unanswered[i]] = ""  # skipped
        return answers

    # Single line — assign to first unanswered question
    unanswered = _get_unanswered_keys(answers)
    if unanswered and text.strip().lower() not in ("пропуск", "skip", "-"):
        answers[unanswered[0]] = text.strip()
    elif unanswered:
        answers[unanswered[0]] = ""

    return answers


def _get_question_map():
    """Return list of (q_key, number_str, question_text)."""
    return [
        ("q1", "1", "Твоё полное имя?"),
        ("q2", "2", "Дата рождения?"),
        ("q3", "3", "Должность и функционал?"),
        ("q4", "4", "Хобби и интересы?"),
        ("q5", "5", "Семейный статус?"),
        ("q6", "6", "Дети?"),
        ("q7", "7", "Профессиональные навыки?"),
    ]


def _get_unanswered_keys(answers: dict) -> list:
    """Return list of question keys that don't have answers yet."""
    return [k for k in SURVEY_QUESTION_KEYS if k not in answers or not answers[k]]


def get_answered_count(answers: dict) -> int:
    """Return how many questions have been answered (non-empty)."""
    return sum(1 for k in SURVEY_QUESTION_KEYS if answers.get(k))


def get_missing_questions_text(answers: dict) -> str:
    """Return text of unanswered questions to ask again."""
    q_map = {k: (num, q) for k, num, q in _get_question_map()}
    unanswered = _get_unanswered_keys(answers)
    if not unanswered:
        return ""

    lines = ["📋 <b>Остались вопросы:</b>\n"]
    for key in unanswered:
        num, question = q_map[key]
        lines.append(f"<b>{num}.</b> {question}")
    return "\n".join(lines)


def answers_to_excel_data(answers: dict, telegram_username: str) -> dict:
    """Convert survey answers to Excel row data.

    Returns dict with keys matching Excel columns.
    """
    full_name = answers.get("q1", "").strip()
    birthday = answers.get("q2", "").strip()
    hobby = answers.get("q4", "").strip()

    # Build info from remaining fields
    info_parts = []
    job = answers.get("q3", "").strip()
    if job:
        info_parts.append(f"Должность: {job}")

    family = answers.get("q5", "").strip()
    if family:
        info_parts.append(f"Семейное положение: {family}")

    children = answers.get("q6", "").strip()
    if children:
        info_parts.append(f"Дети: {children}")

    skills = answers.get("q7", "").strip()
    if skills:
        info_parts.append(f"Навыки: {skills}")

    info = "\n".join(info_parts) if info_parts else ""

    return {
        "full_name": full_name,
        "birthday": birthday,
        "telegram_username": telegram_username,
        "hobby": hobby,
        "info": info,
    }


def write_to_employee_base(data: dict) -> bool:
    """Write survey data as a new row to employee_base.xlsx.

    Args:
        data: dict with keys: full_name, birthday, telegram_username,
              hobby, info

    Returns:
        True on success, False on error.
    """
    # Ensure path exists
    EMPLOYEE_BASE.parent.mkdir(parents=True, exist_ok=True)

    try:
        import openpyxl
        from openpyxl.styles import Font, Alignment
    except ImportError:
        logger.error("openpyxl not installed")
        return False

    try:
        if EMPLOYEE_BASE.exists():
            wb = openpyxl.load_workbook(EMPLOYEE_BASE)
            ws = wb.active
            next_row = ws.max_row + 1
        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "total"
            # Header row
            headers = [
                "N п/п", "last, first name", "birthday",
                "telegram_username", "hobby", "info",
            ]
            for col, h in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=h)
                cell.font = Font(bold=True)
            next_row = 2

        # Write data
        ws.cell(row=next_row, column=1, value=next_row - 1)  # N п/п
        ws.cell(row=next_row, column=2, value=data["full_name"])
        ws.cell(row=next_row, column=3, value=data["birthday"])
        ws.cell(row=next_row, column=4, value=data["telegram_username"])
        ws.cell(row=next_row, column=5, value=data["hobby"])
        ws.cell(row=next_row, column=6, value=data["info"])

        # Auto-adjust column widths
        for col in range(1, 7):
            max_len = 0
            for row in range(1, next_row + 1):
                cell = ws.cell(row=row, column=col)
                if cell.value:
                    # Approximate width
                    val = str(cell.value)
                    max_len = max(max_len, min(len(val), 60))
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = max(max_len + 2, 12)

        wb.save(EMPLOYEE_BASE)
        logger.info("Saved survey data to employee_base.xlsx (row %s)", next_row)
        return True

    except Exception as e:
        logger.error("Failed to write to employee_base.xlsx: %s", e)
        return False