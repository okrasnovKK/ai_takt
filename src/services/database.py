"""Simple JSON-based user database for storing registered users.

Stores users who have interacted with the bot, so we can send them
personal messages later.
"""
import json
from pathlib import Path
from typing import Dict, Optional


class UserDatabase:
    """Stores user chat IDs that have interacted with the bot."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent / "data" / "users.json"
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._users: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.db_path.exists():
            with open(self.db_path, "r", encoding="utf-8") as f:
                self._users = json.load(f)
        else:
            self._users = {}

    def _save(self) -> None:
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self._users, f, ensure_ascii=False, indent=2)

    def register_user(self, user_id: int, username: str = "",
                      first_name: str = "", last_name: str = "") -> None:
        """Register or update a user who has interacted with the bot."""
        uid = str(user_id)
        if uid not in self._users:
            self._users[uid] = {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "chat_id": user_id,
                "registered_at": None,
            }
        # Update info
        user = self._users[uid]
        if username:
            user["username"] = username
        if first_name:
            user["first_name"] = first_name
        if last_name:
            user["last_name"] = last_name
        user["chat_id"] = user_id
        self._save()

    def get_all_users(self) -> Dict[str, dict]:
        """Get all registered users."""
        return dict(self._users)

    def get_user(self, user_id: int) -> Optional[dict]:
        return self._users.get(str(user_id))

    def count_users(self) -> int:
        return len(self._users)