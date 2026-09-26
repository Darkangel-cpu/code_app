"""生成履歴をローカルの JSON ファイルに保存する（DB不要）。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List

HISTORY_FILE = Path(__file__).parent / "data" / "history.json"
MAX_ITEMS = 200


def load() -> List[Dict]:
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(items: List[Dict]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(items[:MAX_ITEMS], ensure_ascii=False, indent=2), encoding="utf-8")


def add(tool_id: str, inputs: Dict[str, str], output: str, model: str) -> None:
    items = load()
    items.insert(0, {
        "id": uuid.uuid4().hex,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "tool_id": tool_id,
        "model": model,
        "inputs": inputs,
        "output": output,
    })
    _save(items)


def delete(item_id: str) -> None:
    _save([i for i in load() if i["id"] != item_id])


def clear() -> None:
    _save([])
