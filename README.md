# ForgeStock — Inventory & Production Management

ForgeStock is a FastAPI inventory and production dashboard with raw-material tracking, finished goods, transactions, production orders, material consumption, and reports.

## Deployment architecture

- **Application:** FastAPI + Jinja templates + vanilla JavaScript.
- **Database:** Supabase-hosted PostgreSQL using SQLAlchemy.
- **Hosting:** Vercel Python Functions.
- **Local mode:** SQLite fallback for local development only. Vercel deployments refuse to start without `DATABASE_URL`, because Vercel's local filesystem is not persistent.

## Deploy to Vercel

1. Push this repository to GitHub and import `siddarth1872004/forgestack` at [Vercel](https://vercel.com/new).
2. In Vercel project settings → Environment Variables, add:
   - `DATABASE_URL`: Supabase project's PostgreSQL connection string from Supabase → Project Settings → Database → Connection string. Use a connection string compatible with your runtime; URL-encode special characters in the password.
   - `SESSION_SECRET`: long random value. Generate locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   - `COOKIE_SECURE`: `true` in production.
   - `SEED_DEMO_DATA`: omit or set `false` for production. Only enable for a disposable local demo.
3. Redeploy after setting variables. Vercel detects FastAPI through the root `app.py` entrypoint.
4. Visit `/api/health`. It should return `{"status":"ok","database_configured":true,"mode":"supabase"}`.

## Supabase database setup

The app uses SQLAlchemy models and creates the required tables at startup (`Base.metadata.create_all`). You can also apply [`supabase/schema.sql`](supabase/schema.sql) manually in the Supabase SQL Editor. Table names are `users`, `raw_material_categories`, `suppliers`, `raw_materials`, `products`, `production_orders`, `material_consumptions`, and `inventory_transactions`.

**Authentication warning:** the inherited login is a demo/local username-password flow, not Supabase Auth. It must not be treated as production-grade multi-user authentication. The app accepts seeded plain-text demo credentials only when `SEED_DEMO_DATA=true`, and the setting should remain disabled in production. Before exposing business data publicly, migrate login to Supabase Auth and implement authorization / RLS. Do not expose database passwords or service-role keys in frontend code.

## Run locally

```bash
python -m pip install -r requirements.txt
# Optional disposable demo data:
# PowerShell: $env:SEED_DEMO_DATA="true"
# Linux/macOS: export SEED_DEMO_DATA=true
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`.

## Included functionality

- Dashboard summary, recent completed production and latest activity.
- Raw materials: create, edit, filter, and delete where no consumption history exists.
- Inventory rollup across materials and finished goods.
- Finished goods summary and inventory transaction history.
- Production order lifecycle: create, start, issue raw material, complete and increment finished inventory.
- Material consumption history.
- Inventory, production and consumption reports with filters.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | Required on Vercel | Supabase PostgreSQL connection URL |
| `SESSION_SECRET` | Production | Random secret for signed session cookies |
| `COOKIE_SECURE` | Production | Set `true` to send cookies over HTTPS only |
| `SEED_DEMO_DATA` | Optional, disabled by default | Sample data for local demo only |

## Known limitations before business production use

- Login has not yet been migrated to Supabase Auth; no tenant separation is implemented.
- Supplier management and settings screens remain placeholders.
- Automated test coverage and migration tooling should be expanded before production business use.
