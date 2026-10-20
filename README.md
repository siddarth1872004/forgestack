# ForgeStock — Inventory & Production Management

ForgeStock is a FastAPI inventory dashboard for raw materials, finished goods, stock transactions, production orders, material consumption, and reports.

## Stack
- FastAPI + Jinja templates + vanilla JavaScript
- PostgreSQL on Supabase, connected through SQLAlchemy
- Vercel Python Functions deployment
- SQLite is only a local-development fallback; Vercel is configured to fail if DATABASE_URL is missing.

## Deploy
1. Create a Supabase project and a Vercel project.
2. In the Supabase SQL Editor, apply `supabase/schema.sql` (or allow the app's SQLAlchemy metadata to create tables on first run).
3. Import `siddarth1872004/forgestack` into [Vercel](https://vercel.com/new).
4. Add these Vercel Environment Variables for Production and Preview as appropriate:
   - `DATABASE_URL`: the Supabase PostgreSQL connection string from Project Settings → Database → Connection string. URL-encode special password characters.
   - `SESSION_SECRET`: a long random value generated with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   - `COOKIE_SECURE=true`.
   - `ADMIN_USERNAME`: the username for the first administrator account.
   - `ADMIN_PASSWORD`: a unique password of at least 12 characters. The app hashes it before storing it and creates the account on startup if it does not already exist.
   - Leave `SEED_DEMO_DATA` unset or false in production.
5. Deploy and check `/api/health`. It should report `mode: supabase`.

## Run locally
```bash
python -m pip install -r requirements.txt
# Optional: populate a disposable local demo database with sample data
# PowerShell: $env:SEED_DEMO_DATA="true"
# Linux/macOS: export SEED_DEMO_DATA=true
uvicorn app:app --reload
```
Browse to http://127.0.0.1:8000.

## Modules included
- Dashboard with counts, recent completed jobs and transaction activity
- Raw-material create/edit/delete, supplier assignment, category filtering and stock validation
- Combined inventory view, finished-goods create/edit/delete and audited stock adjustments
- Supplier contact management and inventory transactions
- Production-order create/start/consume/complete workflow
- Material-consumption history
- Inventory, production and consumption reports with date filters
- `/api/health` performs a real database connectivity check without exposing credentials
- GitHub Actions CI checks Python compilation, JavaScript syntax and smoke tests

## Security/readiness limitations
The inherited login uses the private `users` table with PBKDF2-SHA256 password hashes for provisioned accounts; it is not Supabase Auth and does not yet support password reset, invitations, multi-tenant isolation, or a self-service account-management flow. Use `ADMIN_USERNAME` and `ADMIN_PASSWORD` to create the first administrator. Legacy seeded plaintext credentials are accepted only when `SEED_DEMO_DATA=true`; do not enable that setting in production. Keep the deployment private to trusted users until a full access-control review and any needed tenant isolation are completed. Do not expose database credentials or service-role keys in browser code.
