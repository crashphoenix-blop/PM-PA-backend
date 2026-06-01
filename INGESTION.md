# Парсинг подарков (локально)

Сервис собирает кандидатов с магазинов и складывает их в очередь модерации. На сайт подарок попадает только после approve администратора — через тот же `POST /gifts`, что и ручное добавление. Визуал на сайте не меняется: карточки используют общие компоненты и шрифты Helvetica / Miama Nueva.

## Источники

- GRIDMIR — `plakaty`, `hudi`
- Darkrain — `/catalog/`
- Kutezh — `/catalog/`

## Запуск

```bash
cd PM-PA-backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
pip install aiosqlite
python scripts/init_local_db.py
python scripts/run_ingestion.py
```

Локально используется **SQLite** (`surprise.db` в папке backend). PostgreSQL на Mac не нужен.

Не запускайте `alembic upgrade head` для SQLite — миграции рассчитаны на Postgres.
Если уже пробовали alembic и получили ошибку, удалите битую базу и создайте заново:

```bash
rm -f surprise.db
python scripts/init_local_db.py
```

После прогона в stdout выводится **JSON-список** в формате каталога (`gifts[]` с полями `name`, `price`, `image_url`, `store_name`, `store_url` — как в API сайта).

Сохранить в файл:

```bash
python scripts/run_ingestion.py --out data/ingestion_latest.json
```

Только показать уже собранные (без нового прогона):

```bash
python scripts/run_ingestion.py --list-only --status pending
```

Через API (нужен admin JWT):

- `POST /admin/ingestion/run`
- `GET /admin/ingestion/candidates?status=pending`
- `POST /admin/ingestion/candidates/{id}/approve`
- `POST /admin/ingestion/candidates/{id}/reject`

## Переменные окружения

- `SURPRISE_INGESTION_MAX_PER_RUN` — лимит за прогон (по умолчанию 100)
- `SURPRISE_INGESTION_PER_SOURCE_LIMIT` — лимит с одного сайта (по умолчанию 35)
- `SURPRISE_UPLOADS_DIR` — папка для `/media` (по умолчанию `data/uploads`)

## Расписание

На сервере позже: cron раз в неделю → `POST /admin/ingestion/run` с service token или внутренним вызовом `scripts/run_ingestion.py`.
