# Frontend (Next.js Dashboard)

## Stack
- Next.js App Router
- Tailwind CSS
- shadcn/ui-style component primitives

## Run locally
1. Start backend (FastAPI) first on `http://127.0.0.1:8000`
2. In another terminal:
   ```powershell
   cd frontend
   copy .env.example .env.local
   npm install
   npm run dev
   ```
3. Open `http://127.0.0.1:3000`

## Backend proxy
- Next rewrites `/api/*` to `BACKEND_URL/*`.
- Default `BACKEND_URL` is `http://127.0.0.1:8000`.

## Routes
- `/dashboard` -> metrics cards and breakdowns
- `/jobs` -> job table with filters + sorting + CSV export
- `/jobs/[id]` -> job details, score breakdown, status update, materials generation
- `/followups` -> jobs needing follow-up (`follow_up_date != null` OR `status=applied`)
