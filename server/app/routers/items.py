import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.database import db_session


router = APIRouter(
    prefix="/items",
    tags=["Items"]
)


class ItemCreate(BaseModel):
    item_type_id: int
    box_id: int | None = None
    quantity: int = Field(default=1, gt=0)


class ItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Проверка gt=0 снята с type-уровня и выполняется ниже вручную:
    # мобильное приложение (Gson serializeNulls) шлёт все поля тела сразу,
    # и null в quantity — это «не менять», а не ошибка. Валидация значения
    # осталась в обработчике (см. update_item).
    quantity: int | None = None
    box_id: int | None = None
    item_type_id: int | None = None


def ensure_box_exists(db, box_id):
    exists = db.execute(
        "SELECT 1 FROM box WHERE box_id = ?",
        (box_id,)
    ).fetchone()

    if exists is None:
        raise HTTPException(
            status_code=404,
            detail="Box not found"
        )


def item_row_to_dict(row):
    return {
        "id": row["item_id"],
        "item_type_id": row["item_type_id"],
        "item_type_name": row["item_type_name"],
        "weight_g": row["weight_g"],
        "box_id": row["box_id"],
        "box_name": row["box_name"],
        "quantity": row["quantity"],
        "total_weight_g": (
            row["quantity"] * row["weight_g"]
            if row["weight_g"] is not None
            else None
        ),
    }


ITEM_SELECT = """
SELECT
    i.item_id,
    i.item_type_id,
    it.item_type_name,
    it.weight_g,
    i.box_id,
    b.box_name,
    i.quantity
FROM item i
JOIN item_type it ON it.item_type_id = i.item_type_id
LEFT JOIN box b ON b.box_id = i.box_id
"""


def _fetch_item_row(db, item_id: int):
    """Строка ITEM_SELECT по id — используется и для чтения, и для ответа
    сразу после записи, чтобы не открывать второе соединение."""
    return db.execute(
        ITEM_SELECT + " WHERE i.item_id = ?",
        (item_id,)
    ).fetchone()


@router.get("")
def get_items(
    box_id: int | None = None,
    include_children: bool = False,
    unboxed: bool = False,
):
    # Порядок фильтров значим: `unboxed` — отдельный режим «предметы вне коробок»,
    # поэтому при unboxed=true параметр box_id игнорируется (осознанно, раньше это
    # тоже было так). include_children имеет смысл только вместе с box_id.
    query = ITEM_SELECT
    params: list = []

    if unboxed:
        query += " WHERE i.box_id IS NULL"
    elif box_id is not None and include_children:
        query += """
        WHERE i.box_id IN (
            WITH RECURSIVE subtree(id) AS (
                SELECT ?
                UNION ALL
                SELECT b.box_id FROM box b JOIN subtree s ON b.parent_id = s.id
            )
            SELECT id FROM subtree
        )
        """
        params.append(box_id)
    elif box_id is not None:
        query += " WHERE i.box_id = ?"
        params.append(box_id)

    query += " ORDER BY i.item_id"

    with db_session() as db:
        rows = db.execute(query, params).fetchall()

    return [item_row_to_dict(row) for row in rows]


def _resolve_item_id(db, item_id: int) -> int | None:
    """Разрешение устаревшего id позиции (тот же fallback, что и в get_item).

    Возвращает актуальный item_id либо None, если разрешить нечего.
    Нужен потому, что QR-этикетки (`qwentory:item:<id>`) десктоп печатает по
    id позиции, а `item_id` меняется при пересоздании записей (слияние
    остатков при удалении контейнера, повторный обход seed-скрипта). Без
    разрешения GET /items/{id} находил позицию через fallback, а PATCH/DELETE
    по тому же id падали с «Item not found» — приложение редактировало чужую
    запись или не находила её вовсе.
    """
    if db.execute("SELECT 1 FROM item WHERE item_id = ?", (item_id,)).fetchone():
        return item_id
    if item_id > 0 and db.execute(
        "SELECT 1 FROM item_type WHERE item_type_id = ?", (item_id,)
    ).fetchone():
        row = db.execute(
            "SELECT item_id FROM item"
            " WHERE item_type_id = ?"
            " ORDER BY (box_id IS NULL), item_id"
            " LIMIT 1",
            (item_id,),
        ).fetchone()
        if row is not None:
            return row["item_id"]
    return item_id


@router.get("/{item_id}")
def get_item(item_id: int):
    """Позиция по id.

    Если позиции с таким id больше нет, пробуем найти запись того же типа
    товара (_resolve_item_id) — иначе приложение получало «Item not found»
    на полностью валидной этикетке.
    """
    with db_session() as db:
        row = _fetch_item_row(db, _resolve_item_id(db, item_id))

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Item not found"
        )

    return item_row_to_dict(row)


@router.post("")
def create_item(item: ItemCreate):
    created_id = None
    try:
        with db_session() as db:
            # Проверяем существование типа товара
            type_exists = db.execute(
                "SELECT 1 FROM item_type WHERE item_type_id = ?",
                (item.item_type_id,)
            ).fetchone()

            if type_exists is None:
                raise HTTPException(
                    status_code=404,
                    detail="Item type not found"
                )

            # Если указана коробка, проверяем её существование
            if item.box_id is not None:
                ensure_box_exists(db, item.box_id)

            cursor = db.execute(
                """
                INSERT INTO item (item_type_id, box_id, quantity)
                VALUES (?, ?, ?)
                """,
                (item.item_type_id, item.box_id, item.quantity)
            )

            created_id = cursor.lastrowid
            assert created_id is not None, "INSERT в item не вернул идентификатор"
            # Читаем результат в том же соединении — так не открывается
            # второе подключение (и не возникает read-your-writes гонки).
            row = _fetch_item_row(db, created_id)

    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=(
                "This item type is already stored in the given box "
                "(or unboxed)"
            )
        )

    return item_row_to_dict(row)


@router.patch("/{item_id}")
def update_item(item_id: int, update: ItemUpdate):
    # «Что менять» определяем по НЕнулевым полям. Это важно для мобильного
    # приложения: Gson с serializeNulls шлёт тело целиком ({"quantity": 5,
    # "box_id": null, "item_type_id": null}), и раньше сервер принимал null в
    # item_type_id за намерение сменить тип, валидировал его как id типа и
    # отвечал «Item type not found» на обычное изменение количества.
    # Явное «вынуть из контейнера» (box_id = null) приложение присылает вместе
    # с текущим типом — оно обрабатывается ниже по model_fields_set.
    changed_fields = {
        name for name in ("quantity", "box_id", "item_type_id")
        if getattr(update, name) is not None
    }
    move_out_requested = (
        "box_id" in update.model_fields_set and update.box_id is None
    )
    if not changed_fields and not move_out_requested:
        raise HTTPException(
            status_code=400,
            detail="Nothing to update: provide quantity and/or box_id"
        )

    if update.quantity is not None and update.quantity <= 0:
        raise HTTPException(
            status_code=422,
            detail="Quantity must be greater than 0"
        )

    try:
        with db_session() as db:
            target_id = _resolve_item_id(db, item_id)
            current = db.execute(
                """
                SELECT item_id, box_id, item_type_id
                FROM item
                WHERE item_id = ?
                """,
                (target_id,)
            ).fetchone()

            if current is None:
                raise HTTPException(
                    status_code=404,
                    detail="Item not found"
                )
            item_id = current["item_id"]

            if move_out_requested:
                new_box_id = None
            elif "box_id" in changed_fields:
                new_box_id = update.box_id
            else:
                new_box_id = current["box_id"]

            if "item_type_id" in changed_fields:
                new_type_id = update.item_type_id
                type_exists = db.execute(
                    "SELECT 1 FROM item_type WHERE item_type_id = ?",
                    (new_type_id,),
                ).fetchone()
                if type_exists is None:
                    raise HTTPException(
                        status_code=404,
                        detail="Item type not found",
                    )
            else:
                new_type_id = current["item_type_id"]

            if new_box_id is not None:
                ensure_box_exists(db, new_box_id)

            db.execute(
                """
                UPDATE item
                SET quantity = COALESCE(?, quantity),
                    box_id = ?,
                    item_type_id = ?
                WHERE item_id = ?
                """,
                (
                    update.quantity,
                    new_box_id,
                    new_type_id,
                    item_id
                )
            )

            row = _fetch_item_row(db, item_id)

    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=(
                "This item type is already stored in the given box "
                "(or unboxed)"
            )
        )

    return item_row_to_dict(row)


@router.delete("/{item_id}")
def delete_item(item_id: int):
    with db_session() as db:
        # Устаревший id (пересозданная позиция) разрешаем так же, как в GET —
        # иначе приложение удаляло бы чужую запись или получало 404 на
        # валидной этикетке.
        target_id = _resolve_item_id(db, item_id)
        cursor = db.execute(
            "DELETE FROM item WHERE item_id = ?",
            (target_id,)
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Item not found"
            )

    return {
        "message": "Item deleted"
    }
