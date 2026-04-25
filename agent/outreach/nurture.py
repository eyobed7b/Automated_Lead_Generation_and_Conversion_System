import json
import os
import time
from typing import Optional
import structlog

log = structlog.get_logger()

STATES = ["new", "email_sent", "email_replied", "sms_sent", "call_booked", "qualified", "stalled", "closed"]

TRANSITIONS = {
    "new": ["email_sent"],
    "email_sent": ["email_replied", "stalled"],
    "email_replied": ["sms_sent", "call_booked", "qualified"],
    "sms_sent": ["call_booked", "qualified", "stalled"],
    "call_booked": ["qualified", "closed"],
    "qualified": ["closed"],
    "stalled": ["email_sent"],
    "closed": [],
}

STALL_AFTER_DAYS = 14


class NurtureStateMachine:
    def __init__(self, state_dir: str = None):
        self.state_dir = state_dir or os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "nurture_states"
        )
        os.makedirs(self.state_dir, exist_ok=True)
        self._cache: dict[str, dict] = {}

    def _path(self, prospect_id: str) -> str:
        safe = prospect_id.replace("/", "_").replace("@", "_at_")
        return os.path.join(self.state_dir, f"{safe}.json")

    def get_state(self, prospect_id: str) -> str:
        data = self._load(prospect_id)
        return data.get("state", "new")

    def get_brief(self, prospect_id: str) -> Optional[dict]:
        return self._load(prospect_id).get("brief")

    def save_brief(self, prospect_id: str, brief: dict) -> None:
        data = self._load(prospect_id)
        data["brief"] = brief
        data["updated_at"] = time.time()
        self._save(prospect_id, data)

    def transition(self, prospect_id: str, event: str) -> str:
        data = self._load(prospect_id)
        current = data.get("state", "new")

        state_map = {
            "email_sent": "email_sent",
            "email_replied": "email_replied",
            "sms_sent": "sms_sent",
            "call_booked": "call_booked",
            "qualified": "qualified",
            "stalled": "stalled",
            "closed": "closed",
        }

        new_state = state_map.get(event)
        if not new_state:
            log.warning("invalid_event", transition=event)
            return current

        allowed = TRANSITIONS.get(current, [])
        if new_state not in allowed:
            log.warning("invalid_transition",
                        current=current, transition=event, new_state=new_state)
            return current

        data["state"] = new_state
        data["updated_at"] = time.time()
        history = data.get("history", [])
        history.append({"from": current, "to": new_state, "at": time.time()})
        data["history"] = history
        self._save(prospect_id, data)

        log.info("nurture_transition", prospect=prospect_id,
                 from_state=current, to_state=new_state)
        return new_state

    def check_stalls(self) -> list[str]:
        """Return prospect IDs that have stalled (no update in STALL_AFTER_DAYS)."""
        stalled = []
        cutoff = time.time() - STALL_AFTER_DAYS * 86400
        for fname in os.listdir(self.state_dir):
            if not fname.endswith(".json"):
                continue
            prospect_id = fname[:-5]
            data = self._load(prospect_id)
            state = data.get("state", "new")
            updated = data.get("updated_at", 0)
            if state in ("email_sent", "sms_sent") and updated < cutoff:
                stalled.append(prospect_id)
        return stalled

    def _load(self, prospect_id: str) -> dict:
        if prospect_id in self._cache:
            return self._cache[prospect_id]
        path = self._path(prospect_id)
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            self._cache[prospect_id] = data
            return data
        return {"state": "new", "history": [], "updated_at": time.time()}

    def _save(self, prospect_id: str, data: dict) -> None:
        self._cache[prospect_id] = data
        path = self._path(prospect_id)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
