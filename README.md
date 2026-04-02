# Marketing Analytics Dashboard

## Shrnutí

Webová **multi-tenant SaaS aplikace** pro přehled marketingových kampaní: uživatel nahraje CSV s denními metrikami, aplikace je uloží do databáze **izolovaně per klient** a zobrazí **KPI, doporučení, tabulku rozhodnutí a časové grafy** (tržby, náklady, příspěvek).

Řeší problém **rychlé orientace ve výkonu reklam** bez vlastního BI nástroje — jeden projekt, jeden import, přehledné ROAS a bod zvratu vůči zvolené marži.

---

## Hlavní funkce

| Oblast | Popis |
|--------|--------|
| **Landing page** | Veřejná úvodní stránka produktu |
| **Registrace / přihlášení** | JWT access token + HTTP-only refresh cookie |
| **CSV import** | Nahrání exportu (UTF-8), validace a uložení metrik per tenant |
| **Dashboard** | Souhrnné KPI, doporučení, tabulka kampaní, trendy v čase |
| **Doporučení** | Texty z business vrstvy podle stavu kampaní (např. zisková / riziková) |
| **Grafy** | Tržby, náklady, čistý příspěvek (řádky ze serveru) |
| **Multi-tenant izolace** | Data vázaná na `client_id`; dotazy přes repository vrstvu |
| **Smazání importu** | API pro odstranění importovaných kampaní a metrik (s potvrzením) |
| **Admin** | Základní admin rozhraní pro oprávněné účty (role v aplikaci) |

---

## Screenshoty

> Nahrajte vlastní obrázky do `docs/screenshots/` a cesty nechte, nebo je upravte.

![Landing page](docs/screenshots/landing.png)

*Obrázek 1: veřejná landing page*

![Dashboard s daty](docs/screenshots/dashboard-filled.png)

*Obrázek 2: dashboard po načtení CSV — KPI, tabulka, grafy*

![Prázdný dashboard](docs/screenshots/dashboard-empty.png)

*Obrázek 3: prázdný stav / výzva k nahrání dat*

---

## Tech stack

| Vrstva | Technologie |
|--------|-------------|
| Backend | **FastAPI**, **SQLModel** (SQLAlchemy), **Alembic** |
| Auth | **JWT** (access), refresh token v cookie, **passlib/bcrypt** |
| Databáze | **PostgreSQL** (produkce), **SQLite** lokálně (`marketing.db` nebo `DATABASE_URL`) |
| Frontend | **Jinja2** šablony, **vanilla JavaScript**, vlastní **CSS** |
| Testy | **pytest** |

---

## Architektura

- **`app/api/routes/`** — HTTP vrstva: routy, závislosti, serializace odpovědí; bez business logiky.
- **`app/services/`** — business pravidla (dashboard, marketing, CSV, auth, …).
- **`app/repositories/`** — přístup k DB (dotazy, tenant scope).
- **`app/models/`** — SQLModel entity a schémata.
- **`app/database.py`** — engine, session, migrace při startu (`create_db_and_tables`).

Tok typicky: **route → service → repository → model**.

---

## Lokální spuštění

**Požadavky:** Python **3.12+** (viz `runtime.txt` pro PaaS).

### 1. Klonování a virtuální prostředí

```bash
git clone <url-repo>
cd <projekt>
python -m venv .venv
```

**Windows (PowerShell):** `.\.venv\Scripts\Activate.ps1`  
**Linux / macOS:** `source .venv/bin/activate`

### 2. Závislosti

```bash
pip install -r requirements.txt
```

### 3. Konfigurace prostředí

```bash
copy .env.example .env   # Windows
# cp .env.example .env    # Unix
```

V `.env` nastavte minimálně:

| Proměnná | Poznámka |
|----------|----------|
| `JWT_SECRET` | Min. **32 znaků** (silný náhodný řetězec) |

Ostatní volitelné — viz `.env.example` (`APP_ENV`, cookies, `DATABASE_URL`, …).

### 4. Migrace (volitelně)

Migrace se při startu aplikace spouští z `app/database.py`. Ručně:

```bash
alembic upgrade head
```

### 5. Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Aplikace: `http://127.0.0.1:8000` (dashboard např. `/dashboard`)  
- OpenAPI: `http://127.0.0.1:8000/docs`

### Testy

```bash
pytest
```

---

## Formát CSV importu

Import očekává **UTF-8** (včetně BOM). Oddělovač se detekuje (`;`, `,` nebo tabulátor).

Aplikace rozpozná několik profilů hlaviček; typický **vlastní export** potřebuje sloupce (normalizované názvy):

- **`date`** — datum řádku  
- **`campaign`** — název kampaně *(nebo `campaign id` + interní ID, viz kód)*  
- **`revenue`** — tržby  
- Náklady na reklamu: jeden z aliasů např. **`spend`**, `cost`, `ad_spend`, …  

Podporované jsou i vybrané exporty typu **Shopify** / **Shoptet** (detekce podle hlaviček). Detailní mapování je v `app/services/csv_service.py`.

**Příklad minimální hlavičky (vlastní formát):**

```csv
date,campaign,revenue,spend
2026-03-01,Brand Search,15000,6000
2026-03-01,Performance Max,8200,3100
```

Max. velikost uploadu: **15 MB** (konstanta v `CSVService`).

---

## Produkční nasazení

- **Platformy typu Render / Railway / VPS**: build `pip install -r requirements.txt`, start např. `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (viz `Procfile`).
- **PostgreSQL**: nastavte `DATABASE_URL` (např. connection string z **Render PostgreSQL**, **Neon**, nebo jiného poskytovatele). Aplikace normalizuje běžný prefix `postgres://` na `postgresql://`.
- V produkci typicky **`APP_ENV=production`**, **`COOKIE_SECURE=true`**, silný **`JWT_SECRET`**. Podrobnosti a volitelné proměnné (logy, proxy, rate limit) jsou v `.env.example` a v původní technické dokumentaci v repozitáři.

Migrace mohou běžet při startu procesu; pro CI/CD lze spouštět `alembic upgrade head` zvlášť.

---

## Co je hotové

- End-to-end tok: registrace → přihlášení → upload CSV → dashboard s KPI a grafy  
- Multi-tenant izolace dat v PostgreSQL / SQLite  
- JWT + obnovení relace přes cookie  
- Alembic migrace  
- API pro smazání importovaných dat (s explicitním potvrzením)  
- Základní admin a strukturované logování (konfigurovatelné přes env)  

---

## Možný další rozvoj

- Úprava marže a dalších parametrů přímo v UI  
- Vlastní časové okno (date range) nad rámec předvoleb 7/30/90 dní  
- Hlubší integrace reklamních platforem (mimo CSV)  
- Sdílený rate limit (Redis) při více workerech  

---

## Licence

Licence není v repozitáři vynucena — použití a šíření podle rozhodnutí vlastníka projektu.

---

*Tento repozitář slouží jako ukázka full-stack práce: návrh API, vrstvená architektura, bezpečné přihlášení a praktický dashboard pro reálná marketingová data.*
