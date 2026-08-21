-- =====================================================================
-- Историчная таблица по остаткам для public.warehouse_stocks
-- Механизм: триггер на INSERT/UPDATE/DELETE — каждое изменение строки
-- в warehouse_stocks автоматически копируется в warehouse_stocks_history.
--
-- ВАЖНО: скрипт построен на колонках, видимых в вашем скриншоте
-- (quantity_instock, quantity_ordered, created_at, nomenclatura_id,
--  warehouse_id, quantity_reserved, quantity_forshipment, quantity_total).
-- Если в public.warehouse_stocks есть ещё столбцы (например id),
-- добавьте их в CREATE TABLE ниже и в триггерную функцию по аналогии.
-- =====================================================================

-- 1. Таблица истории
CREATE TABLE IF NOT EXISTS public.warehouse_stocks_history (
    history_id            BIGSERIAL PRIMARY KEY,
    operation_type         CHAR(1)      NOT NULL,      -- 'I' insert, 'U' update, 'D' delete
    changed_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    nomenclatura_id         UUID,
    warehouse_id            UUID,
    quantity_instock        NUMERIC,
    quantity_ordered        NUMERIC,
    quantity_reserved       NUMERIC,
    quantity_forshipment    NUMERIC,
    quantity_total          NUMERIC,
    created_at              TIMESTAMP                   -- created_at исходной строки
);

CREATE INDEX IF NOT EXISTS idx_warehouse_stocks_history_lookup
    ON public.warehouse_stocks_history (nomenclatura_id, warehouse_id, changed_at);

-- 2. Функция-триггер
CREATE OR REPLACE FUNCTION public.fn_warehouse_stocks_history()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        INSERT INTO public.warehouse_stocks_history (
            operation_type, nomenclatura_id, warehouse_id,
            quantity_instock, quantity_ordered, quantity_reserved,
            quantity_forshipment, quantity_total, created_at
        ) VALUES (
            'D', OLD.nomenclatura_id, OLD.warehouse_id,
            OLD.quantity_instock, OLD.quantity_ordered, OLD.quantity_reserved,
            OLD.quantity_forshipment, OLD.quantity_total, OLD.created_at
        );
        RETURN OLD;
    ELSE
        INSERT INTO public.warehouse_stocks_history (
            operation_type, nomenclatura_id, warehouse_id,
            quantity_instock, quantity_ordered, quantity_reserved,
            quantity_forshipment, quantity_total, created_at
        ) VALUES (
            LEFT(TG_OP, 1), NEW.nomenclatura_id, NEW.warehouse_id,
            NEW.quantity_instock, NEW.quantity_ordered, NEW.quantity_reserved,
            NEW.quantity_forshipment, NEW.quantity_total, NEW.created_at
        );
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- 3. Триггер на исходной таблице
DROP TRIGGER IF EXISTS trg_warehouse_stocks_history ON public.warehouse_stocks;

CREATE TRIGGER trg_warehouse_stocks_history
AFTER INSERT OR UPDATE OR DELETE ON public.warehouse_stocks
FOR EACH ROW EXECUTE FUNCTION public.fn_warehouse_stocks_history();

-- 4. (Опционально) зафиксировать текущее состояние как первый снимок истории
INSERT INTO public.warehouse_stocks_history (
    operation_type, nomenclatura_id, warehouse_id,
    quantity_instock, quantity_ordered, quantity_reserved,
    quantity_forshipment, quantity_total, created_at
)
SELECT
    'I', nomenclatura_id, warehouse_id,
    quantity_instock, quantity_ordered, quantity_reserved,
    quantity_forshipment, quantity_total, created_at
FROM public.warehouse_stocks;

-- =====================================================================
-- 4.5. Управленческая себестоимость за единицу товара по SKU.
--
-- Источник — public.dim_cost_price (= таблица 'Себестоимость и товары' в
-- модели Power BI, грузится dax_queries.py/pbi_to_postgres.py). Формула НЕ
-- придумана заново — воспроизводит уже одобренную пользователем PBI-меру
-- "Запас на FBO, руб WB/Oz" (таблица '_МЕРЫ WAREHOUSE', папка "Запас FBO"):
--   • dim_cost_price."Артикул поставщика" сопоставляется с SKU по ЛЮБОМУ из
--     4 полей dim_sku — SKU_upper (через UPPER(), как в мере), WB Артикул,
--     Ozon Артикул, Yandex SKU (без учёта регистра для этих трёх — так же,
--     как в самой мере);
--   • для каждого совпавшего SKU берётся строка с САМЫМ ПОЗДНИМ "Месяц
--     себестоимости", её "Сумма себестоимость" — это и есть цена за
--     единицу. NULLS LAST на сортировке по месяцу — чтобы строки с пустым
--     месяцем не перебивали реальный последний месяц;
--   • при равенстве месяца у нескольких строк на один SKU берётся строка с
--     МАКСИМАЛЬНЫМ значением себестоимости — так же, как MAXX(...) в самой
--     DAX-мере поступает с "тёзками".
--
-- "Сумма себестоимость" в источнике — text (см. комментарий про
-- разнотипность после pandas.to_sql в начале join_marketplaces.sql),
-- приводится к numeric через NULLIF(...,'')::numeric. ЕСЛИ CREATE VIEW
-- упадёт с "invalid input syntax for type numeric" — значит в "Сумма
-- себестоимость" попал нечисловой текст (пробел, разделитель тысяч и т.п.),
-- нужно почистить исходный лист в Google Sheets, на котором построена
-- 'Себестоимость и товары' в модели.
--
-- ОТЛИЧИЕ от PBI-меры: там IFERROR(VALUE(...),0) молча превращает ошибку
-- парсинга в 0. Здесь вместо этого NULL — чтобы "нет данных о себестоимости"
-- нельзя было спутать с "себестоимость равна нулю", глядя на рублёвую
-- колонку. На SUM() в Google Sheets разницы нет (NULL и 0 суммируются
-- одинаково), меняется только то, что видно в самой ячейке.
--
-- Отдаёт себестоимость под ДВУМЯ ключами одновременно: "SKU (ключ)" (для
-- join_marketplaces.sql — там остатки идут по этому ключу) и "SKU_upper"
-- (для join'ов в этом файле, где остатки идут по nomenclatura.articul).
CREATE OR REPLACE VIEW public.v_cost_per_sku AS
WITH cost_matched AS (
    SELECT
        s."SKU (ключ)",
        s."SKU_upper",
        cp."Месяц себестоимости"                         AS month_ss,
        NULLIF(cp."Сумма себестоимость", '')::numeric     AS cost_value
    FROM public.dim_cost_price cp
    JOIN public.dim_sku s
        ON cp."Артикул поставщика" IS NOT NULL
       AND cp."Артикул поставщика" <> ''
       AND (
            UPPER(cp."Артикул поставщика") = s."SKU_upper"
         OR cp."Артикул поставщика" = s."WB Артикул"
         OR cp."Артикул поставщика" = s."Ozon Артикул"
         OR cp."Артикул поставщика" = s."Yandex SKU"
       )
    WHERE cp."Сумма себестоимость" IS NOT NULL AND cp."Сумма себестоимость" <> ''
)
SELECT DISTINCT ON ("SKU (ключ)")
    "SKU (ключ)",
    "SKU_upper",
    cost_value AS "Себестоимость_ед, руб"
FROM cost_matched
ORDER BY "SKU (ключ)", month_ss DESC NULLS LAST, cost_value DESC NULLS LAST;

-- =====================================================================
-- 5. Витрина остатков по датам для выгрузки в Google Sheets (второй лист).
--
-- Меры (public.warehouse_stocks / warehouse_stocks_history):
--   quantity_instock     -> "Доступно"
--   quantity_reserved    -> "Зарезервировано"
--   quantity_forshipment -> "Отгружается"
--   quantity_total       -> "Всего"
--   quantity_ordered     -> "Заказано"
--
-- Джойны по ID:
--   warehouse_stocks_history.nomenclatura_id -> public.nomenclatura.id
--   warehouse_stocks_history.warehouse_id    -> public.warehouses.id
--
-- "SKU" = nomenclatura.articul (артикул) — по аналогии с "WB Артикул" /
-- "Ozon Артикул" в dax_queries.py. Если нужен внутренний код
-- (вида "00-00001583"), замените n.articul на n.code ниже.
-- "Склад" = warehouses.name.
--
-- "Дата" — в исходной warehouse_stocks даты нет (только created_at строки),
-- поэтому дата берётся из warehouse_stocks_history.changed_at (момент
-- фиксации изменения). Если за один день по одной паре SKU+склад было
-- несколько изменений, берётся ПОСЛЕДНЕЕ состояние за день (DISTINCT ON
-- ... ORDER BY changed_at DESC) — то есть остаток "на конец дня". Строки
-- с operation_type = 'D' (DELETE) исключены, т.к. они фиксируют состояние
-- ПЕРЕД удалением строки, а не актуальный остаток.
--
-- ПЕРЕИМЕНОВАНО: v_warehouse_stocks_full -> v_warehouse_stocks_fbs, т.к.
-- warehouse_stocks — это остатки именно по схеме FBS (склад продавца).
-- Остатки по FBW/Ozon/Yandex считаются отдельно (см. v_stocks_all_total
-- и v_stocks_by_marketplace ниже).
--
-- CREATE OR REPLACE VIEW под новым именем не удаляет старую вьюху —
-- поэтому явно дропаем v_warehouse_stocks_full, иначе она останется в
-- базе как "осиротевшая" копия старых данных.
-- =====================================================================
DROP VIEW IF EXISTS public.v_warehouse_stocks_full CASCADE;

-- "Товары в пути" из Power BI (таблица Transfer_items — только в модели,
-- не в исходных Postgres-таблицах, грузится через dax_queries.py/
-- pbi_to_postgres.py в public.transfer_items). В таблице есть колонка
-- "Дата отгрузки" (в модели тип String; проверено на реальных данных —
-- формат "ДД.ММ.ГГГГ", например "16.04.2026", поэтому обычный
-- CAST(... AS date) падает с DatetimeFieldOverflow — ниже используется
-- TO_DATE с явным форматом).
--
-- ИСПРАВЛЕНО (было): раньше "В пути" суммировалось по ВСЕМ строкам на
-- SKU+Склад без учёта даты — это задваивало старые, уже неактуальные
-- отгрузки. Затем брали только САМУЮ ПОСЛЕДНЮЮ дату отгрузки по паре
-- SKU+Склад.
--
-- ИЗМЕНЕНО: теперь "В пути" — это сумма "Количество (в единицах
-- хранения)" по паре SKU+Склад за отгрузки с "Дата отгрузки" в
-- скользящем окне последних 14 дней от CURRENT_DATE (на момент
-- выполнения запроса), а не только по одной последней дате. Окно
-- пересчитывается при каждом обновлении вьюхи, поэтому набор дат,
-- попадающих в сумму, "едет" вперёд вместе с CURRENT_DATE.
CREATE OR REPLACE VIEW public.v_transfer_items_by_sku_warehouse AS
SELECT
    "Заказ клиента.Склад"                            AS "Склад",
    UPPER("Номенклатура.Артикул")                    AS "SKU",
    SUM("Количество (в единицах хранения)")          AS "В пути"
FROM public.transfer_items
WHERE "Номенклатура.Артикул" IS NOT NULL
  AND "Дата отгрузки" IS NOT NULL
  AND TO_DATE("Дата отгрузки", 'DD.MM.YYYY') BETWEEN CURRENT_DATE - INTERVAL '14 days' AND CURRENT_DATE
GROUP BY "Заказ клиента.Склад", UPPER("Номенклатура.Артикул");

-- Transfer_items — это текущий снимок без даты по SKU+Складу за историю,
-- поэтому "В пути" (сумма за последние 14 дней, см. выше) проставляется
-- только на самую свежую дату по каждой паре SKU+Склад в
-- v_warehouse_stocks_fbs (а не дублируется на всех исторических датах,
-- где эта цифра была бы неверной задним числом).
-- ВАЖНО (тайм-зона): changed_at — TIMESTAMPTZ. Прямой каст changed_at::date
-- зависит от session timezone текущего подключения к Postgres, а она нигде
-- в пайплайне явно не зафиксирована (psql-клиент и python/sqlalchemy-сессия
-- из pbi_to_postgres.py/postgres_to_gsheets.py могут иметь разный TimeZone).
-- Из-за этого одна и та же запись могла попадать в разные календарные дни
-- в зависимости от того, откуда выполняется запрос — отсюда расхождения
-- значений по одной и той же дате между запусками. Явно фиксируем UTC
-- через AT TIME ZONE, чтобы бакетинг по дате был детерминированным.
CREATE OR REPLACE VIEW public.v_warehouse_stocks_fbs AS
WITH base AS (
    SELECT DISTINCT ON ((h.changed_at AT TIME ZONE 'UTC')::date, h.nomenclatura_id, h.warehouse_id)
        (h.changed_at AT TIME ZONE 'UTC')::date      AS "Дата",
        n.articul                AS "SKU",
        w.name                    AS "Склад",
        h.quantity_instock          AS "Доступно",
        h.quantity_reserved         AS "Зарезервировано",
        h.quantity_forshipment      AS "Отгружается",
        h.quantity_total              AS "Всего",
        h.quantity_ordered            AS "Заказано"
    FROM public.warehouse_stocks_history h
    LEFT JOIN public.nomenclatura n ON n.id = h.nomenclatura_id
    LEFT JOIN public.warehouses   w ON w.id = h.warehouse_id
    WHERE h.operation_type <> 'D'
    ORDER BY (h.changed_at AT TIME ZONE 'UTC')::date, h.nomenclatura_id, h.warehouse_id, h.changed_at DESC
),
max_date AS (
    SELECT UPPER("SKU") AS sku_u, "Склад" AS sklad, MAX("Дата") AS max_dt
    FROM base
    GROUP BY UPPER("SKU"), "Склад"
)
-- Рублёвые колонки (FR_Доступно/FR_Зарезервировано/.../FR_В пути, руб —
-- префикс FR_ по запросу пользователя, как у аналогичных колонок в
-- join_marketplaces.sql) добавлены В КОНЕЦ, ПОСЛЕ всех "штучных" колонок —
-- см. раздел 4.5 выше (v_cost_per_sku)
-- про формулу и источник себестоимости. Присоединяются через CREATE OR
-- REPLACE VIEW (допускает только дописывание новых колонок в конец, не
-- трогая существующие), поэтому потребители этой вьюхи (лист "Остатки FBS",
-- daily_sales_report.py, telegram_bot.py) не ломаются — просто получают
-- 6 новых колонок справа.
SELECT
    b."Дата",
    b."SKU",
    b."Склад",
    b."Доступно",
    b."Зарезервировано",
    b."Отгружается",
    b."Всего",
    b."Заказано",
    CASE WHEN b."Дата" = md.max_dt THEN t."В пути" ELSE NULL END AS "В пути",
    (b."Доступно" * cps."Себестоимость_ед, руб")         AS "FR_Доступно, руб",
    (b."Зарезервировано" * cps."Себестоимость_ед, руб")  AS "FR_Зарезервировано, руб",
    (b."Отгружается" * cps."Себестоимость_ед, руб")      AS "FR_Отгружается, руб",
    (b."Всего" * cps."Себестоимость_ед, руб")             AS "FR_Всего, руб",
    (b."Заказано" * cps."Себестоимость_ед, руб")          AS "FR_Заказано, руб",
    (CASE WHEN b."Дата" = md.max_dt THEN t."В пути" ELSE NULL END * cps."Себестоимость_ед, руб") AS "FR_В пути, руб"
FROM base b
LEFT JOIN max_date md ON md.sku_u = UPPER(b."SKU") AND md.sklad = b."Склад"
LEFT JOIN public.v_transfer_items_by_sku_warehouse t
       ON t."SKU" = UPPER(b."SKU") AND t."Склад" = b."Склад"
LEFT JOIN public.v_cost_per_sku cps
       ON cps."SKU_upper" = UPPER(b."SKU");

-- =====================================================================
-- 6. Витрины остатков по всем маркетплейсам (v_stocks_all_total,
--    v_stocks_by_marketplace). Источники — fact_revenue_wb/ozon/yandex
--    (загружаются pbi_to_postgres.py из dax_queries.py, где для каждого
--    маркетплейса добавлены новые остатковые меры из '_МЕРЫ WAREHOUSE':
--      WB     -> "Остаток FBW, шт" / "Остаток FBS, шт" (уже были)
--      Ozon   -> "Остаток Ozon, шт" / "Резерв Ozon, шт"
--      Yandex -> "Остаток Yandex, шт" / "Резерв Yandex, шт"
--    ) + v_warehouse_stocks_fbs (см. раздел 5, FBS/склад продавца).
--
-- КЛЮЧ СОЕДИНЕНИЯ SKU: fact_revenue_* используют "SKU (ключ)" из модели
-- (та же дименсия 'Справочник SKU', что и в join_marketplaces.sql), а
-- v_warehouse_stocks_fbs — nomenclatura.articul ("SKU" в этой вьюхе). Это
-- разные исходные колонки, поэтому ниже они сравниваются через UPPER(...)
-- — по аналогии с моделью Power BI, где вычисляемые колонки SKU_key на
-- фактовых таблицах всегда строятся как UPPER(источник) перед связью со
-- 'Справочник SKU'[SKU (ключ)]. Если после проверки реальных данных
-- окажется, что артикулы не совпадают даже без учёта регистра — потребуется
-- отдельный маппинг (например через 'Справочник SKU'[SKU_upper] и
-- nomenclatura.articul_upper, которые уже используются для этой связи в
-- самой модели).
--
-- "Всего" в v_stocks_all_total — это ОДНО суммарное число на SKU+Дата,
-- складывающее ДОСТУПНЫЕ остатки со всех источников: FBS (Доступно) + FBW
-- + Ozon (Остаток Ozon, т.е. free_to_sell) + Yandex (Остаток Yandex, т.е.
-- stock_available). Резервы (Зарезервировано / Резерв Ozon / Резерв Yandex)
-- сюда сознательно не включены — это отдельные "занятые" остатки, не
-- доступные к продаже прямо сейчас.
-- =====================================================================

-- "FR_Всего, руб" добавлена В КОНЕЦ (после "Всего") — рублёвая оценка суммарного
-- остатка, Количество × Себестоимость_ед (см. v_cost_per_sku, раздел 4.5).
CREATE OR REPLACE VIEW public.v_stocks_all_total AS
WITH totals AS (
    SELECT
        "Дата",
        "SKU",
        SUM("Остаток") AS "Всего"
    FROM (
        SELECT h."Дата" AS "Дата", UPPER(h."SKU") AS "SKU", SUM(h."Доступно") AS "Остаток"
        FROM public.v_warehouse_stocks_fbs h
        WHERE h."SKU" IS NOT NULL
        GROUP BY h."Дата", UPPER(h."SKU")

        UNION ALL

        SELECT wb."Date"::date AS "Дата", UPPER(wb."SKU (ключ)") AS "SKU", SUM(wb."Остаток FBW, шт") AS "Остаток"
        FROM public.fact_revenue_wb wb
        WHERE wb."Остаток FBW, шт" IS NOT NULL AND wb."SKU (ключ)" IS NOT NULL
        GROUP BY wb."Date", UPPER(wb."SKU (ключ)")

        UNION ALL

        SELECT oz."Date"::date AS "Дата", UPPER(oz."SKU (ключ)") AS "SKU", SUM(oz."Остаток Ozon, шт") AS "Остаток"
        FROM public.fact_revenue_ozon oz
        WHERE oz."Остаток Ozon, шт" IS NOT NULL AND oz."SKU (ключ)" IS NOT NULL
        GROUP BY oz."Date", UPPER(oz."SKU (ключ)")

        UNION ALL

        SELECT ya."Date"::date AS "Дата", UPPER(ya."SKU (ключ)") AS "SKU", SUM(ya."Остаток Yandex, шт") AS "Остаток"
        FROM public.fact_revenue_yandex ya
        WHERE ya."Остаток Yandex, шт" IS NOT NULL AND ya."SKU (ключ)" IS NOT NULL
        GROUP BY ya."Date", UPPER(ya."SKU (ключ)")
    ) combined
    GROUP BY "Дата", "SKU"
)
SELECT
    t."Дата",
    t."SKU",
    t."Всего",
    (t."Всего" * cps."Себестоимость_ед, руб") AS "FR_Всего, руб"
FROM totals t
LEFT JOIN public.v_cost_per_sku cps ON cps."SKU_upper" = t."SKU";

-- "Остатки МП" — то же самое, но БЕЗ FBS и БЕЗ агрегации по маркетплейсам
-- (одна строка на Дата+SKU+Маркетплейс), только WB/Ozon/Yandex.
-- "FR_Остаток, руб" добавлена В КОНЕЦ (после "Остаток, шт") — см. v_cost_per_sku,
-- раздел 4.5.
CREATE OR REPLACE VIEW public.v_stocks_by_marketplace AS
SELECT
    base."Дата",
    base."SKU",
    base."Маркетплейс",
    base."Остаток, шт",
    (base."Остаток, шт" * cps."Себестоимость_ед, руб") AS "FR_Остаток, руб"
FROM (
    SELECT wb."Date"::date AS "Дата", UPPER(wb."SKU (ключ)") AS "SKU", 'WB'::text AS "Маркетплейс", wb."Остаток FBW, шт" AS "Остаток, шт"
    FROM public.fact_revenue_wb wb
    WHERE wb."Остаток FBW, шт" IS NOT NULL AND wb."SKU (ключ)" IS NOT NULL

    UNION ALL

    SELECT oz."Date"::date AS "Дата", UPPER(oz."SKU (ключ)") AS "SKU", 'Ozon'::text AS "Маркетплейс", oz."Остаток Ozon, шт" AS "Остаток, шт"
    FROM public.fact_revenue_ozon oz
    WHERE oz."Остаток Ozon, шт" IS NOT NULL AND oz."SKU (ключ)" IS NOT NULL

    UNION ALL

    SELECT ya."Date"::date AS "Дата", UPPER(ya."SKU (ключ)") AS "SKU", 'Yandex'::text AS "Маркетплейс", ya."Остаток Yandex, шт" AS "Остаток, шт"
    FROM public.fact_revenue_yandex ya
    WHERE ya."Остаток Yandex, шт" IS NOT NULL AND ya."SKU (ключ)" IS NOT NULL
) base
LEFT JOIN public.v_cost_per_sku cps ON cps."SKU_upper" = base."SKU";
