package com.example.warehouse.data.api;

/**
 * Тело запроса PATCH /items/{id}.
 *
 * Сервер (app/routers/items.py, ItemUpdate) принимает quantity, box_id и
 * item_type_id; пропущенные поля не меняются. Отправка box_id == null
 * вынимает позицию из контейнера — чтобы Gson сериализовал null, в
 * {@link ApiClient} включён serializeNulls и поле объявлено как Integer.
 *
 * Важно: из-за serializeNulls все три поля всегда попадают в JSON, и сервер
 * определяет «не менять» по значению null. Поэтому неизменяемые поля
 * методов-фабрик заполняются ТЕКУЩИМИ значениями позиции (withCurrent):
 * иначе смена типа молча вынимала бы товар из контейнера (null в box_id —
 * «товар исчезает»), а изменение количества упиралось бы в серверную
 * проверку типа со значением null («Item type not found»).
 */
public class ItemUpdateBody {

    public Integer quantity;
    public Integer box_id;
    public Integer item_type_id;

    /** Изменение количества позиции. */
    public static ItemUpdateBody quantity(int value) {
        ItemUpdateBody body = new ItemUpdateBody();
        body.quantity = value;
        return body;
    }

    /** Перемещение позиции в другой контейнер (boxId == null — вынуть). */
    public static ItemUpdateBody moveTo(Integer boxId) {
        ItemUpdateBody body = new ItemUpdateBody();
        body.box_id = boxId;
        return body;
    }

    /** Смена типа товара позиции. */
    public static ItemUpdateBody itemType(int itemTypeId) {
        ItemUpdateBody body = new ItemUpdateBody();
        body.item_type_id = itemTypeId;
        return body;
    }

    /**
     * Подставляет ТЕКУЩИЕ значения неизменяемых полей в тело запроса.
     * Нужно из-за Gson serializeNulls: все три поля всегда попадают в JSON,
     * и null в них сервер прочёл бы как намерения «вынуть из контейнера» /
     * «сменить тип на null» (товар исчезал из списка; изменение количества
     * падало с «Item type not found»). Аргументы — item.box_id и
     * item.item_type_id позиции. Поле «Вынуть из контейнера» (moveTo(null))
     * остаётся null намеренно; quantity заполняется текущим количеством
     * вызывающим кодом.
     */
    public ItemUpdateBody withCurrent(Integer boxId, Integer typeId) {
        if (this.box_id == null) {
            this.box_id = boxId;
        }
        if (this.item_type_id == null) {
            this.item_type_id = typeId;
        }
        return this;
    }
}
