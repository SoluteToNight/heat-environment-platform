"""API Call Quota Manager with Hard Cutoff Protection.

Strictly protects the QWeather API call budget for Shanghai Urban Heat Exposure project:
- Budget Limit: 5,000 calls (2026-09-17 to 2026-09-26)
- Soft Warning Threshold: 4,500 calls (90%)
- Hard Cutoff Limit: 4,800 calls (96%)
- Daily Planned Consumption: 100 points x 1 call/day = 100 calls/day (1,000 calls / 10 days = 20%)
"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "forecast_cache"
QUOTA_FILE = DATA_DIR / "quota_state.json"

GLOBAL_BUDGET_LIMIT = 5000
SOFT_WARNING_LIMIT = 4500
HARD_CUTOFF_LIMIT = 4800

_lock = threading.Lock()


class QuotaExceededException(RuntimeError):
    """Raised when API call would exceed safe quota limit."""
    pass


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not QUOTA_FILE.exists():
        initial_state = {
            "budget_limit": GLOBAL_BUDGET_LIMIT,
            "soft_warning_limit": SOFT_WARNING_LIMIT,
            "hard_cutoff_limit": HARD_CUTOFF_LIMIT,
            "total_used": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "history": []
        }
        with open(QUOTA_FILE, "w", encoding="utf-8") as f:
            json.dump(initial_state, f, ensure_ascii=False, indent=2)


def get_quota_status() -> dict:
    """Read current quota status."""
    with _lock:
        _ensure_data_dir()
        try:
            with open(QUOTA_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {
                "budget_limit": GLOBAL_BUDGET_LIMIT,
                "soft_warning_limit": SOFT_WARNING_LIMIT,
                "hard_cutoff_limit": HARD_CUTOFF_LIMIT,
                "total_used": 0,
                "history": []
            }
        
        used = state.get("total_used", 0)
        remaining = max(0, GLOBAL_BUDGET_LIMIT - used)
        remaining_safe = max(0, HARD_CUTOFF_LIMIT - used)
        is_blocked = used >= HARD_CUTOFF_LIMIT
        is_warning = used >= SOFT_WARNING_LIMIT

        return {
            "budget_limit": GLOBAL_BUDGET_LIMIT,
            "hard_cutoff_limit": HARD_CUTOFF_LIMIT,
            "soft_warning_limit": SOFT_WARNING_LIMIT,
            "total_used": used,
            "remaining_quota": remaining,
            "remaining_safe_quota": remaining_safe,
            "usage_percentage": round((used / GLOBAL_BUDGET_LIMIT) * 100, 2),
            "is_blocked": is_blocked,
            "is_warning": is_warning,
            "last_updated": state.get("last_updated"),
            "recent_history": state.get("history", [])[-15:]
        }


def can_consume(count: int = 100) -> bool:
    """Check if consuming `count` calls will exceed hard cutoff limit."""
    status = get_quota_status()
    return (status["total_used"] + count) <= HARD_CUTOFF_LIMIT


def record_consumption(count: int, purpose: str, metadata: dict | None = None) -> dict:
    """Record an API consumption event. Raises QuotaExceededException if blocked."""
    with _lock:
        _ensure_data_dir()
        with open(QUOTA_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        current_used = state.get("total_used", 0)
        if current_used + count > HARD_CUTOFF_LIMIT:
            raise QuotaExceededException(
                f"API Quota Hard Cutoff Reached! Current: {current_used}, "
                f"Requested: {count}, Hard Limit: {HARD_CUTOFF_LIMIT}. "
                f"Operation blocked to protect API key."
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        state["total_used"] = current_used + count
        state["last_updated"] = now_iso
        
        event = {
            "timestamp": now_iso,
            "consumed": count,
            "cumulative_used": state["total_used"],
            "purpose": purpose,
            "metadata": metadata or {}
        }
        state.setdefault("history", []).append(event)

        with open(QUOTA_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        return {
            "success": True,
            "consumed": count,
            "cumulative_used": state["total_used"],
            "remaining_safe": HARD_CUTOFF_LIMIT - state["total_used"]
        }
