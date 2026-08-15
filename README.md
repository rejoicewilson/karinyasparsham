# Karunya Sparsham PWA

Mobile-first helping-fund collection application implemented from
`money-collection-pwa-complete-blueprint.md`.

## Run locally

```powershell
npm install
npm run dev
```

Open `http://localhost:5173`. The login page includes preview access for each
role so the member, agent, and admin workflows can be reviewed without external
credentials.

## Production build

```powershell
npm run build
npm run preview
```

The optimized installable PWA is written to `dist/`.

## Implemented application surface

- Member dashboard, cases, dues, payment history, permanent-membership ledger,
  notifications, and account views
- Agent dashboard, collection recording, member directory, multi-entry deposit
  creation, and deposit status history
- Admin dashboard, death-case publication, exact-match deposit review,
  member/taluk views, reports, settings, and status summaries
- Responsive member/agent bottom navigation and admin mobile drawer/desktop
  sidebar
- Static app-shell caching, install manifest, update-ready service worker, and
  online-only financial controls

The supplied organization logo is used for app branding and install icons.
The current build uses in-browser demonstration records so every role and
workflow can be evaluated before Supabase project credentials and the FastAPI
deployment are connected.

## FastAPI backend

Create and activate the isolated Python environment, then install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
```

Apply the initial Supabase migration:

```powershell
python -m alembic -c backend\alembic.ini upgrade head
python -m alembic -c backend\alembic.ini current
```

Start FastAPI on port 8000:

```powershell
python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

Development API documentation is available at `http://localhost:8000/docs`.
Health endpoints are `/health/live` and `/health/ready`.

After the first migration, bootstrap the initial administrator:

```powershell
python backend\scripts\bootstrap_admin.py --login-id admin --full-name "System Administrator"
```

The command prompts for a temporary password without echoing it. The first
successful login remains marked for a mandatory password change.

## Database migration contents

The initial Alembic revision creates the complete organization and financial
ledger schema, notification outbox, audit storage, financial constraints,
idempotency records, indexes, default-deny RLS configuration, controlled
database triggers, and private Supabase Storage buckets. The versioned SQL
payload is in `backend/alembic/sql/0001_initial_schema.sql`.
