# OnoiPark API — Phase 2

FastAPI backend for the OnoiPark automated parking system (Osh, Kyrgyzstan).

---

## Architecture

```
Mobile App  ─────────────────────────────────────────────────────────────┐
  (React Native)                                                          │
  POST /auth/signin   GET /parkings   POST /bookings/create               │
  GET /qr/generate                                                        │
                                                                          ▼
                              ┌─────────────────────────┐
Dashboard  ──────────────────►│   OnoiPark_API (FastAPI) │
  (Next.js)                   │   Vercel Serverless      │
  GET /admin/sessions/all     │                          │
  POST /qr/validate           │  app/routers/            │
  GET /admin/history          │    auth.py               │
  POST /admin/sessions/       │    parkings.py           │
    manual-start              │    sessions.py           │
    manual-end                │    bookings.py           │
                              │    qr.py  ← JWT nonces  │
                              │    admin.py              │
                              └────────────┬────────────┘
                                           │ supabase-py (service role)
                                           ▼
                              ┌─────────────────────────┐
                              │  Supabase (Postgres)     │
                              │  project: rhckohqfbvk…  │
                              │                          │
                              │  profiles               │
                              │  parkings               │
                              │  spots                  │
                              │  bookings               │
                              │  parking_sessions  ──►Realtime
                              │  qr_nonces              │
                              └─────────────────────────┘
                                           │ Realtime channel
                                           ▼
                              Local Python bridge → Arduino gate
```

---

## QR Flow

```
1. Driver opens mobile app → taps "Show QR"
2. App  →  GET /api/qr/generate
3. API  → inserts row in qr_nonces (TTL 15 min)
         → signs JWT { sub, plt, kid=nonce_id, exp, iss }
         → returns { token, expiresAt }
4. App displays QR code containing the JWT token.

5. Scanner reads QR → calls  POST /api/qr/validate
   with { token, parkingId, spotNumber? }

6. API decodes JWT, checks iss == "onoipark-api"
   → if expired  → 400 { code: "expired" }
   → if bad sig  → 400 { code: "invalid_token" }

7. API checks qr_nonces row:
   → if used == true → 400 { code: "already_used" }
   → marks used = true, used_at = now

8. API determines action:
   a. User has status='waiting' session  → set active, entered_at=now
      returns { action:"entry", session_id }
   b. User has status='active'  session  → set exiting, compute cost, free spot,
      schedule background task: set completed after 5 s
      returns { action:"exit", session_id, cost }
   c. User has active booking (not expired) → create session in active,
      mark booking completed
      returns { action:"entry", session_id }
   d. Otherwise → create fresh active session (walk-in)
      returns { action:"entry", session_id }

9. Supabase Realtime publishes parking_sessions row change.
10. Local Python bridge receives event → triggers Arduino gate open.
```

---

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/auth/signup | — | Register (creates Supabase auth + profiles row) |
| POST | /api/auth/signin | — | Sign in → access_token |
| GET  | /api/auth/me | driver | Current user profile |
| POST | /api/auth/reset-password | — | Change phone number |
| GET  | /api/parkings | — | List parkings (seeds if empty) |
| GET  | /api/parkings/{id}/spots | — | List spots with live status |
| GET  | /api/sessions/active | driver | Caller's active session |
| GET  | /api/sessions/all | admin/scanner | All active sessions |
| POST | /api/sessions/start | admin/scanner | Start session by plate |
| POST | /api/sessions/end | admin/scanner | End session, compute cost |
| GET  | /api/bookings/list | driver | Caller's active bookings |
| POST | /api/bookings/create | driver | Reserve spot (15-min hold) |
| POST | /api/bookings/cancel | driver | Cancel booking |
| GET  | /api/qr/generate | driver | Generate JWT QR token |
| POST | /api/qr/validate | admin/scanner | Validate token → entry/exit |
| GET  | /api/admin/sessions/all | admin | All active sessions |
| GET  | /api/admin/history | admin | Completed sessions + filters |
| GET  | /api/admin/users | admin | All registered users |
| POST | /api/admin/sessions/manual-start | admin | Manual entry without QR |
| POST | /api/admin/sessions/manual-end | admin | Manual exit without QR |
| GET  | /api/history | driver | Caller's parking history |
| GET  | /api/history/all | admin | All users list |
| GET  | /api/user/profile | driver | User profile |
| POST | /api/user/update-settings | driver | Update notification settings |
| DELETE | /api/user/delete-account | driver | Delete account |

All routes are also registered without `/api` prefix for backward compatibility.

---

## Deployment (Vercel)

Set these environment variables in your Vercel project settings:

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | `https://rhckohqfbvkeinsqyesh.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | From Supabase → Settings → API |
| `SUPABASE_ANON_KEY` | From Supabase → Settings → API |
| `JWT_SECRET` | Random 32-byte secret: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `CORS_ORIGINS` | Comma-separated allowed origins, e.g. `https://onoipark-admin.vercel.app,exp://…` |

Deploy:
```
vercel --prod
```

---

## Running Locally

1. Copy the env template and fill in your keys:
   ```
   cp .env.example .env
   # edit .env
   ```

2. Run migrations — paste each file into the Supabase SQL editor in order:
   ```
   migrations/001_init_schema.sql
   migrations/002_migrate_kv_to_tables.sql
   ```
   See `migrations/README.md` for details.

3. Start the server:
   ```
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```

4. Open `http://localhost:8000/docs` to explore all endpoints interactively.

---

## Running Tests

```
pip install -r requirements.txt
pytest tests/ -v
```

Tests mock the Supabase client — no live project needed.

---

## Future Work (Phase 3)

- **Client integration** — point the mobile app and dashboard `BASE_URL` at the new API.
- **Row-Level Security** — add RLS policies to Supabase tables (currently deferred, auth enforced in API layer).
- **Payments** — integrate payment gateway for paid parking time.
- **Push notifications** — send FCM/APNS alerts for booking expiry and session events.
- **Admin role assignment UI** — currently roles are set directly in the profiles table.
