# Marketing Analytics (FastAPI)

Multi-tenant marketing analytics API with HTML/CSS/vanilla JS dashboard, JWT + refresh cookie auth, and SQLModel/Alembic.

## Požadavky

- Python 3.12+ (viz `runtime.txt` pro služby typu Render)
- Závislosti: `pip install -r requirements.txt`

## Lokální spuštění

1. Zkopíruj `.env.example` na `.env` a nastav minimálně `JWT_SECRET` (≥ 32 znaků).
2. Z kořene projektu:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

3. Aplikace: `http://127.0.0.1:8000/dashboard` · OpenAPI: `http://127.0.0.1:8000/docs`

Při startu se spustí **Alembic migrace** (`create_db_and_tables()` v `app/database.py`). Samostatný příkaz (CI nebo ruční kontrola):

```bash
alembic upgrade head
```

## Produkční / cloud nasazení

### Proměnné prostředí

Použij `.env.example` jako checklist. V produkci musí být mimo jiné:

- `JWT_SECRET` — silný tajný klíč (≥ 32 znaků).
- `APP_ENV=production` (nebo `prod`).
- `COOKIE_SECURE=true` (povinné při `APP_ENV=production`; jinak aplikace při startu spadne).
- `DATABASE_URL` — pro PostgreSQL např. `postgresql+psycopg2://...` (do `requirements.txt` si doplň `psycopg2-binary`). Pro SQLite na disku nastav cestu na **persistní svazek** (ephemeral filesystem data ztratí).

Volitelně:

- `TRUST_PROXY_HEADERS=true` za reverse proxy (správná IP u rate limitu).
- `ENABLE_BACKGROUND_SYNC=false` na webovém procesu (výchozí); synchronizaci spouštěj zvlášť, pokud ji nechceš v jednom workeru.

### Start command

Obecný vzor (Railway/Render nastaví `PORT`):

```bash
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Soubor `Procfile` obsahuje stejný příkaz pro platformy s Procfile.

Migrace běží **automaticky při startu** aplikace; není nutné spouštět `alembic` zvlášť, pokud nechceš migrace oddělit v CI.

### Poznámky k platformám

- **Render / Railway**: nastav env z dashboardu, build `pip install -r requirements.txt`, start viz výše nebo Procfile.
- **VPS**: systemd služba s `WorkingDirectory` v kořeni projektu, stejný `uvicorn` příkaz; před `ExecStart` volitelně `alembic upgrade head` pokud nechceš spoléhat na migrace v procesu.

### Logy

- Strukturovaný přístupový log: logger `app.access` (middleware).
- JSON řádky: `JSON_LOGS=1` nebo výchozí JSON při `APP_ENV=production` (vypnout `JSON_LOGS=0`).
- Úroveň: `LOG_LEVEL` (např. `WARNING` v produkci pro méně šumu).

### Rate limit

Login/register mají jednoduchý **in-process** limit (viz `app/core/rate_limit.py`). U více workerů se limity nesdílejí — pro vyšší nároky později sdílený úložiště (Redis apod.).

## Testy

```bash
pytest
```

## Licence

Podle uvážení vlastníka repozitáře.
