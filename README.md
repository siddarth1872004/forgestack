# ForgeStock

ForgeStock is a Node.js inventory and production dashboard backed by Supabase Postgres and deployed as a Vercel serverless application.

## Deploy to Vercel

1. Run `supabase/schema.sql` once in Supabase SQL Editor.
2. Import this repository at [vercel.com/new](https://vercel.com/new).
3. Add two environment variables for Production, Preview, and Development: `DATABASE_URL` and a long unique `ADMIN_PASSWORD`.
4. Deploy and sign in as `admin` with `ADMIN_PASSWORD`.
5. Check `/api/health` for database connectivity.

**Important:** use the Supabase *Transaction pooler* connection string (port 6543) for `DATABASE_URL`. The direct `db.<ref>.supabase.co:5432` host is IPv6-only, which makes Vercel functions hang or time out.

`DATABASE_URL` remains server-side and also derives the session signature, avoiding a separate session-secret variable.

## Local development

```bash
npm install
npx vercel dev
```
