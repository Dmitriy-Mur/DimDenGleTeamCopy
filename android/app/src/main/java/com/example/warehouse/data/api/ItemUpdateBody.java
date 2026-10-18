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

    /** Текущие значения позиции; не сериализуются (private — Gson их игнорирует). */
    private Integer currentBoxId;
    private Integer currentTypeId;

    /** Запоминает текущие box/type позиции, чтобы фабрики подставляли их в тело. */
    public ItemUpdateBody withCurrent(Integer boxId, Integer typeId) {
        this.currentBoxId = boxId;
        this.currentTypeId = typeId;
        return this;
    }

    public static ItemUpdateBody moveTo(Integer boxId, Integer currentBoxId, Integer currentTypeId) {
        ItemUpdateBody body = new ItemUpdateBody();
        body.box_id = boxId;
        // Тип передаём текущим: при «вынуть из контейнера» (box_id == null)
        // в теле должно остаться хотя бы одно ненулевое поле, иначе сервер
        // решит, что обновлять нечего.
        body.item_type_id = currentTypeId;
        return body;
    }

    /** Смена типа товара позиции. */
    public static ItemUpdateBody itemType(int itemTypeId, Integer currentBoxId) {
        ItemUpdateBody body = new ItemUpdateBody();
        body.item_type_id = itemTypeId;
        // Контейнер передаём текущим — иначе null в box_id сервер прочтёт
        // как намерение «вынуть позицию из контейнера», и товар исчезнет
        // из открытого контейнера.
        body.box_id = currentBoxId;
        return body;
    }
}
