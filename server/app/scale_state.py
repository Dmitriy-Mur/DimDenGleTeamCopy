"""Состояние весов: единый источник правды для десктопа и Android.

Раньше последнее показание жило в памяти процесса uvicorn (модульная
переменная в routers/scale.py). Из-за этого:

* после перезапуска сервера десктоп продолжал показывать «Весы: …», а
  новый процесс уже ничего не помнил — данные расходились;
* при нескольких воркерах (`uvicorn --workers N`) POST /scale попадал
  в один процесс, GET /scale — в другой, и клиенты видели разные веса.

Теперь состояние хранится в SQLite: рядом с остальными данными склада
(тот же volume/файл БД), поэтому его видят все процессы сервера, и оно
переживает перезапуск. Таблица однострочная: каждое взвешивание — UPDATE
единственной строки, история взвешиваний здесь не ведётся.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone

#: Сколько секунд показание считается «свежим». Клиент может ориентироваться
#: на поле `stale` в ответе, чтобы не принять старое значение за текущее.
FRESH_TTL_SECONDS = 5.0

#: Ключ единственной строки состояния.
_STATE_ROW = "scale"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS scale_state (
    state_key  TEXT PRIMARY KEY,
    weight_g   REAL NOT NULL,
    updated_at TEXT NOT NULL,
    source     TEXT NOT NULL
)
"""


def ensure_table(db: sqlite3.Connection) -> None:
    """Создаёт таблицу состояния весов (идемпотентно).

    Вызывается из init_db() на каждом старте сервера — это самовосстанавливающаяся
    страховка к миграции v2 в app/migrations.py: даже если база была создана
    более новым кодом, а затем открыта более старым, таблица появится снова.
    """
    db.execute(_CREATE_TABLE)


def _as_utc(value: str) -> datetime:
    """datetime из ISO-строки; naive-значения трактуются как UTC."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def publish(db: sqlite3.Connection, weight_g: float, source: str) -> dict:
    """Сохраняет новое показание и возвращает актуальное состояние.

    Значение должно быть конечным — проверку выполняет вызывающий слой
    (эндпоинт), здесь только нормализация типа и метка времени.
    """
    if not math.isfinite(weight_g):
        raise ValueError("weight_g must be a finite number")

    now = datetime.now(timezone.utc)
    db.execute(
        """
        INSERT INTO scale_state (state_key, weight_g, updated_at, source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(state_key) DO UPDATE SET
            weight_g   = excluded.weight_g,
            updated_at = excluded.updated_at,
            source     = excluded.source
        """,
        (_STATE_ROW, float(weight_g), now.isoformat(), source),
    )
    return read(db)


def read(db: sqlite3.Connection) -> dict:
    """Текущее состояние: weight_g/updated_at/source/stale (словарь для модели ответа)."""
    row = db.execute(
        "SELECT weight_g, updated_at, source FROM scale_state WHERE state_key = ?",
        (_STATE_ROW,),
    ).fetchone()

    if row is None:
        return {"weight_g": None, "updated_at": None, "source": "none", "stale": True}

    updated_at = _as_utc(row["updated_at"])
    age = (datetime.now(timezone.utc) - updated_at).total_seconds()
    return {
        "weight_g": float(row["weight_g"]),
        "updated_at": updated_at,
        "source": row["source"],
        "stale": age > FRESH_TTL_SECONDS,
    }


def clear(db: sqlite3.Connection) -> None:
    """Забывает показание (DELETE /scale)."""
    db.execute("DELETE FROM scale_state WHERE state_key = ?", (_STATE_ROW,))
