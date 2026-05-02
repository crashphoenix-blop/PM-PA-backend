# Surprise Backend (Amvera-ready)

FastAPI backend для проекта Surprise.

## Что уже настроено для Amvera

- `amvera.yaml` — конфигурация окружения и запуска
- `start.py` — автоматический запуск миграций, создание admin, сидинг и старт API
- `.env.amvera` — шаблон переменных окружения

## Переменные окружения

Минимально нужно заполнить:

- `SURPRISE_DATABASE_URL`
- `SURPRISE_JWT_SECRET_KEY`
- `SURPRISE_ADMIN_LOGIN`
- `SURPRISE_ADMIN_PASSWORD`

Остальные можно оставить как есть.

## Администратор

При старте сервиса выполняется `scripts.ensure_admin`:

- если admin с указанным логином не существует — создаётся
- если существует — пароль и имя обновляются по env

После этого admin может логиниться в web-frontend и добавлять подарки через `/admin/gifts/new`.

## Локальный запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m scripts.ensure_admin
python -m scripts.seed_gifts
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
