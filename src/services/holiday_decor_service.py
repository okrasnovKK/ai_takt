"""Holiday Decor Service — управление украшением помещений к праздникам.

State machine:
  idle → awaiting_photo → awaiting_details → awaiting_approval
  → awaiting_estimate_approval → completed

Persisted to data/holiday_decor.json.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
STATE_PATH = DATA_DIR / "holiday_decor.json"


class HolidayDecorState:
    """Manages a single holiday decoration workflow session."""

    def __init__(self, state_path: Optional[Path] = None):
        self._state_path = state_path or STATE_PATH
        self._state: dict = self._load()

    # ── Persistence ──

    def _load(self) -> dict:
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return self._empty()

    def _empty(self) -> dict:
        return {
            "state": "idle",
            "lpr_id": 0,
            "photo_path": "",
            "photo_file_id": "",
            "holiday_theme": "",
            "budget": "",
            "rules": "",
            "generated_image_path": "",
            "estimate": "",
            "created_at": "",
            "updated_at": "",
        }

    def _save(self):
        self._state["updated_at"] = datetime.now().isoformat(timespec="minutes")
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._state_path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)

    # ── State transitions ──

    def start(self, lpr_id: int):
        """Initiate a new decoration workflow."""
        self._state = self._empty()
        self._state.update({
            "state": "awaiting_photo",
            "lpr_id": lpr_id,
            "created_at": datetime.now().isoformat(timespec="minutes"),
            "updated_at": datetime.now().isoformat(timespec="minutes"),
        })
        self._save()
        logger.info("Holiday decor started by LPR %s", lpr_id)

    def set_photo(self, file_path: str, file_id: str):
        """Save the photo of the premises."""
        self._state["photo_path"] = file_path
        self._state["photo_file_id"] = file_id
        self._state["state"] = "awaiting_details"
        self._save()

    def set_details(self, holiday_theme: str, budget: str, rules: str):
        """Save theme, budget, and rules from LPR."""
        self._state["holiday_theme"] = holiday_theme
        self._state["budget"] = budget
        self._state["rules"] = rules
        self._state["state"] = "awaiting_approval"
        self._save()

    def approve_concept(self):
        """LPR approved the visual concept — move to estimate stage."""
        self._state["state"] = "awaiting_estimate_approval"
        self._save()

    def reject_concept(self, reason: str = ""):
        """LPR rejected — go back to awaiting_details for rework."""
        self._state["state"] = "awaiting_details"
        self._state["rejection_reason"] = reason
        self._save()

    def set_estimate(self, estimate_text: str):
        """Save the cost estimate."""
        self._state["estimate"] = estimate_text
        self._save()

    def approve_estimate(self):
        """LPR approved the estimate — done."""
        self._state["state"] = "completed"
        self._save()

    def set_purchase_links(self, links_text: str):
        """Save purchase links after estimate approval."""
        self._state["purchase_links"] = links_text
        self._save()

    def get_purchase_links(self) -> str:
        return self._state.get("purchase_links", "")

    def cancel(self):
        """Cancel the workflow and reset to idle."""
        self._state = self._empty()
        self._save()
        logger.info("Holiday decor cancelled by LPR")

    # ── Getters ──

    def get_state(self) -> str:
        return self._state.get("state", "idle")

    def get_all(self) -> dict:
        return dict(self._state)

    def is_active(self) -> bool:
        return self._state.get("state", "idle") not in ("idle", "completed")

    def is_lpr(self, user_id: int) -> bool:
        """Check if the user is the LPR for this session."""
        if not self._state.get("lpr_id"):
            return True  # no LPR set — any user can act
        return self._state.get("lpr_id") == user_id

    def get_status_text(self) -> str:
        """Return a human-readable status of the current workflow."""
        s = self._state
        state = s.get("state", "idle")

        state_labels = {
            "idle": "⏸ Ожидание",
            "awaiting_photo": "📸 Шаг 1: ожидание фото помещения",
            "awaiting_details": "📋 Шаг 2: ожидание тематики и бюджета",
            "awaiting_approval": "🔄 Шаг 3-4: согласование концепции",
            "awaiting_estimate_approval": "💰 Шаг 5: согласование сметы",
            "completed": "✅ Завершено",
        }

        lines = [
            f"🎄 <b>Украшение помещения</b>",
            f"━━━━━━━━━━━━━━━",
            f"<b>Статус:</b> {state_labels.get(state, state)}",
        ]
        if s.get("holiday_theme"):
            lines.append(f"<b>Праздник:</b> {s['holiday_theme']}")
        if s.get("budget"):
            lines.append(f"<b>Бюджет:</b> {s['budget']} ₽")
        if s.get("estimate"):
            lines.append(f"<b>Смета:</b> {'утверждена ✅' if state == 'completed' else 'составлена'}")
        return "\n".join(lines)


# Singleton for easy import
decor_state = HolidayDecorState()