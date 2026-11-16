"""
Full-chain trace logging + data masking — ported from Design `logger.py`.
Generates trace_id, saves structured JSON logs, auto-masks PII.
"""
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def generate_trace_id() -> str:
    return str(uuid.uuid4())


def mask_sensitive(text: str) -> str:
    """
    Mask PII: phone numbers, ID card numbers, student IDs.
    - Phone:   138****1234
    - ID card: *****************
    - Student: *****
    """
    if not text:
        return text
    text = re.sub(r"1[3-9]\d{9}", "138****1234", str(text))
    text = re.sub(r"\d{17}[\dXx]", "*****************", text)
    text = re.sub(r"[A-Za-z]+\d{8}", "*****", text)
    return text


def save_trace(data: dict) -> str:
    """
    Write logs/{trace_id}.json, return trace_id.
    Auto-masks question, answer, prompt fields.
    """
    enable_masking = os.getenv("ENABLE_DATA_MASKING", "true").lower() == "true"

    if enable_masking:
        for field in ["question", "answer", "prompt"]:
            if field in data and data[field]:
                data[field] = mask_sensitive(str(data[field]))

    trace_id = data.get("trace_id") or generate_trace_id()
    data["trace_id"] = trace_id

    if "timestamp" not in data:
        data["timestamp"] = datetime.now(timezone.utc).isoformat()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"{trace_id}.json"

    try:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        print(f"[trace_logger] Write failed: {e}")

    return trace_id
