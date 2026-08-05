# Clinic Booking API

A REST API for a small clinic's appointment booking system, built for the
Savannah Informatics backend take-home assessment.

**Stack:** Django + Django REST Framework, PostgreSQL (SQLite fallback for
local dev without a DB server), Docker, GitHub Actions.

---

## Section 1 — System Design

### The scenario
A clinic with 5 doctors. Each doctor has fixed working hours and works in
30-minute slots. Patients view a doctor's free slots for a given day, book
one, and can later cancel or reschedule. A booked slot must not be bookable
by anyone else.

### Models

- **Doctor** — `name`, `specialty`.
- **WorkingHours** — `doctor` (FK), `weekday` (0=Mon..6=Sun), `start_time`,
  `end_time`. A doctor can have zero or more windows per weekday, which
  covers split shifts (e.g. 9–12 and 14–17) without any schema change.
- **Patient** — `name`, `email`.
- **Appointment** — `doctor` (FK), `patient` (FK), `start_time`, `end_time`,
  `status` (`booked` / `cancelled`), `cancellation_reason`, timestamps.

### Key decisions & trade-offs

1. **Slots are computed, not pre-generated rows.** Availability for a
   doctor/date is derived on the fly from `WorkingHours` minus existing
   `booked` appointments for that date, rather than materializing a `Slot`
   row for every 30-minute interval into the future. This avoids a
   background job to pre-generate slots and scales fine at this size
   ("starting small but want to grow" — if the clinic grows to hundreds of
   doctors and search-heavy availability queries, a materialized/cached
   slot table would be the next optimization, not a redesign).

2. **Double-booking is prevented at two layers.** The view checks for a
   clashing `booked` appointment before creating one, but the real
   guarantee is a partial unique constraint at the database level —
   `UNIQUE(doctor, start_time) WHERE status = 'booked'`. Two concurrent
   requests for the same slot will have one succeed and one fail at the DB
   layer even if both pass the application-level check, which closes the
   race condition an application-only check can't.

3. **Cancelling does not delete the row.** `status` flips to `cancelled`
   and the row is kept (with a reason) rather than deleted, so history is
   preserved and the unique constraint above only applies to `booked` rows
   — a cancelled slot becomes immediately bookable again by construction,
   not by a separate "delete and recreate" step.

4. **Rescheduling reuses the exact same validation as a fresh booking**
   (working hours, not in the past, not already taken), excluding the
   appointment's own current slot from the clash check. This was an
   explicit requirement in the brief and also keeps the "what counts as a
   valid slot" logic in one function (`services.validate_slot`) instead of
   duplicated across two endpoints.

5. **No authentication.** The brief doesn't mention login/auth, and
   patients aren't modeled as user accounts — `patient` is just an ID
   passed in the request body, matching the required endpoints
   (`POST /appointments` takes `patient` directly; there's no login flow
   specified). In a real product this would sit behind auth so a patient
   can't cancel someone else's appointment; documented here as a known gap
   rather than silently assumed away.

6. **Booking lead time.** The bonus requirement ("prevention of bookings
   within 1 hour of now") is enforced in `services.validate_slot` via a
   `min_lead_time` parameter, applied to both fresh bookings and
   reschedules.

---

## Section 2 — API

Base path: `/api/`

| Method | Path | Description |
|---|---|---|
| `POST` | `/appointments` | Book a slot. Body: `{doctor, patient, start_time}` |
| `GET` | `/doctors/{id}/availability?date=YYYY-MM-DD` | Free 30-min slots for that doctor/date |
| `PATCH` | `/appointments/{id}/cancel` | Body: `{reason}` |
| `PATCH` | `/appointments/{id}/reschedule` | Body: `{start_time}` |
| `GET` | `/patients/{id}/appointments` | Upcoming booked appointments, sorted by date (bonus) |

Errors return `{"detail": "...", "code": "..."}` with the matching HTTP
status:

| Code | Status |
|---|---|
| `past_slot`, `too_soon`, `invalid_duration` | 400 |
| `outside_working_hours` | 422 |
| `slot_taken`, `already_cancelled` | 409 |

### Endpoints — local vs. deployed

| # | Method | Local | Deployed (Render) |
|---|---|---|---|
| 1 | `POST` | `http://localhost:8000/api/appointments` | `https://savanna-clinic-booking.onrender.com/api/appointments` |
| 2 | `GET` | `http://localhost:8000/api/doctors/{id}/availability?date=YYYY-MM-DD` | `https://savanna-clinic-booking.onrender.com/api/doctors/{id}/availability?date=YYYY-MM-DD` |
| 3 | `PATCH` | `http://localhost:8000/api/appointments/{id}/cancel` | `https://savanna-clinic-booking.onrender.com/api/appointments/{id}/cancel` |
| 4 | `PATCH` | `http://localhost:8000/api/appointments/{id}/reschedule` | `https://savanna-clinic-booking.onrender.com/api/appointments/{id}/reschedule` |
| 5 | `GET` | `http://localhost:8000/api/patients/{id}/appointments` | `https://savanna-clinic-booking.onrender.com/api/patients/{id}/appointments` |

Every endpoint above is browsable directly - open the URL in any browser
(DRF renders an HTML form for `POST`/`PATCH` endpoints, with dropdowns for
doctor/patient) - so testing doesn't require Postman or curl. Recommended
manual test flow, in order:

1. Seed data first (`python manage.py seed_demo_data` locally, or via
   Render's **Shell** tab for the deployed instance) so doctor/patient IDs
   1-5 and 1-2 exist.
2. `GET .../doctors/1/availability?date=<a future weekday>` - copy a
   `start_time` from the response.
3. `POST .../appointments` - book using that `start_time`.
4. `PATCH .../appointments/{id}/cancel` or `.../reschedule` - using the
   `id` returned from step 3.
5. `GET .../patients/1/appointments` - confirm the booking shows up (or
   doesn't, if cancelled).

### Run locally

```bash
# 1. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate            # Windows (Git Bash: source venv/Scripts/activate)

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up environment variables
cp .env.example .env
# Leave DB_HOST blank in .env to use SQLite (simplest for local dev/testing).
# To point locally at the same Supabase database Render uses instead,
# fill in DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME with the Supabase
# transaction pooler values (see "Deploying to Render" below).

# 4. Apply migrations
python manage.py migrate

# 5. (Optional) seed 5 demo doctors + 2 demo patients
python manage.py seed_demo_data

# 6. Run the dev server
python manage.py runserver
```

App now available at `http://localhost:8000/`.

**Note:** whenever you pull changes that touch `requirements.txt` (e.g. after
merging in updates), re-run `pip install -r requirements.txt` before running
any `manage.py` command — a missing package (like `python-dotenv` or
`whitenoise`) will make Django fail to even load `settings.py`.

Or with Docker (spins up a local Postgres container too):

```bash
docker compose up --build
```

### Tests

```bash
python manage.py test
```

14 tests cover: availability generation, booking validation (working
hours, past dates, lead time, double-booking), cancel (including
already-cancelled), and reschedule (including reschedule into a taken
slot and rescheduling a cancelled appointment).

---

## Section 3 — Deployment & CI/CD

- **Deploy target:** [Render](https://render.com) (Docker-based Web Service)
  + [Supabase](https://supabase.com) (managed PostgreSQL, via its
  connection pooler).
- **Public URL:** https://savanna-clinic-booking.onrender.com
- **Which branch triggers a deployment:** `main`. Render's own auto-deploy
  (redeploy on every push to `main`) is disabled in favor of the GitHub
  Actions pipeline below, so a deploy only happens *after* tests pass — not
  on every push regardless of test outcome.
- **What the pipeline does** (`.github/workflows/ci-cd.yml`):
  - **On every PR into `main`:** spins up a throwaway Postgres service
    container in the CI runner and runs `python manage.py test` against it.
  - **On every push/merge into `main`:** after tests pass, calls Render's
    deploy hook URL (`RENDER_DEPLOY_HOOK` GitHub secret) to trigger a
    redeploy of the web service.

### Deploying to Render + Supabase — step by step

**1. Push the repo to GitHub** (Render deploys from a connected repo).

**2. Create a Supabase project and get pooler connection details**
- [supabase.com](https://supabase.com) → **New project** → set a database
  password (save it, you'll need it below)
- Once provisioned: **Project Settings** → **Database** → **Connection
  Pooling**
- Use the **Transaction pooler** values (not the direct connection) — the
  direct connection host is IPv6-only on Supabase's free tier, which
  Render's outbound networking can't reach; the pooler supports IPv4 and
  suits a stateless web app making short-lived per-request connections:
  - Host: `aws-0-<region>.pooler.supabase.com`
  - Port: `6543`
  - User: `postgres.<your-project-ref>`
  - Database: `postgres`

**3. Create the Web Service**
- **New +** → **Web Service** → connect the GitHub repo
- Runtime: **Docker** (Render detects and uses the `Dockerfile` in this
  repo automatically — no build command needed)
- Region: same as the database, to keep latency low
- Instance type: free tier is enough for this assessment

**4. Set environment variables on the Web Service**
Web Service → **Environment** tab → add each of these. This is the only
place these values live in production — none of them are ever written to
a file in the repo:

| Key | Value |
|---|---|
| `SECRET_KEY` | a freshly generated random string (not the dev default in `settings.py`) |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `savanna-clinic-booking.onrender.com` |
| `DB_HOST` | Supabase pooler host, e.g. `aws-0-<region>.pooler.supabase.com` |
| `DB_NAME` | `postgres` |
| `DB_USER` | `postgres.<your-project-ref>` |
| `DB_PASSWORD` | your Supabase database password |
| `DB_PORT` | `6543` |

**5. Deploy**
- Render builds the Docker image and, per the `Dockerfile`'s `CMD`, runs
  `python manage.py migrate` then starts `gunicorn` automatically — no
  separate manual migration step needed on first deploy
- Watch the build/deploy logs; once the service shows **Live**, open the
  URL — e.g. `https://<your-app>.onrender.com/api/appointments`

**6. Wire up the GitHub Actions deploy hook**
- Web Service → **Settings** → **Deploy Hook** → copy the URL
- GitHub repo → **Settings** → **Secrets and variables** → **Actions** →
  **New repository secret**
- Name: `RENDER_DEPLOY_HOOK`, value: the copied URL
- From now on, every merge into `main` runs the test suite first, and only
  calls this hook (triggering a Render redeploy) if the tests pass

**7. (Optional) Seed demo data on the live instance**
- Render Web Service → **Shell** tab (or `render exec`) →
  `python manage.py seed_demo_data`

### Testing the API without Postman

Every endpoint is browsable directly — open the URLs in any browser (local
or the deployed Render URL) and DRF's browsable API renders an HTML page:

- `GET /api/doctors/1/availability?date=2026-08-10` — shows the JSON response.
- `GET /api/appointments` — shows a form with a doctor dropdown, patient
  dropdown, and a start_time field; fill it in and click **POST** to book,
  right from the page. No request-body JSON to hand-write.
- `PATCH /api/appointments/{id}/cancel` — form with just a `reason` field.
- `PATCH /api/appointments/{id}/reschedule` — form with just a `start_time`
  field.
- `GET /api/patients/{id}/appointments` — shows the JSON list.

This was a deliberate design choice, not just a DRF default: the assessment
brief doesn't say what tool the reviewer will test with, so every endpoint
supports full CRUD from nothing but a browser, in addition to
curl/Postman/any HTTP client.

## Section 4 — AI Reflection

1. **What I used AI for across the four sections:** scaffolding the Django
   project/app structure, drafting the model fields and the availability-
   computation logic, writing the initial test suite, and drafting the
   GitHub Actions workflow and Dockerfile.

2. **Two examples of AI suggestions that improved the work:**

   - **Preventing double-booking under concurrent requests.** I asked how
     to guarantee only one of two simultaneous booking requests for the
     same slot succeeds. The suggestion was to move the guarantee from an
     application-level `.exists()` check to a database-level partial
     unique constraint (`UNIQUE(doctor, start_time) WHERE status='booked'`)
     — the actual fix, since an app-level check alone has a race window
     between the check and the insert that a concurrent request can slip
     through.

   - **Diagnosing a production-only styling bug on Render.** After
     deploying, the DRF browsable API rendered with no CSS at all, even
     though it looked correct locally. I described the symptom and the AI
     traced it to `runserver` auto-serving static files in dev while
     `gunicorn` (used in production) doesn't — so DRF's own Bootstrap
     CSS/JS was silently 404ing in production. The fix was adding
     WhiteNoise as static-file middleware plus a `STATIC_ROOT`/`STORAGES`
     config, which resolved it without needing a separate static file host.

3. **Where AI output was wrong/incomplete and how I caught it:** the first
   draft of the availability logic didn't exclude past time slots on
   *today's* date — it would list a 9am slot as "available" at 2pm the
   same day. I caught it by writing a test for "what does availability
   look like for today, right now" and seeing a stale slot come back; the
   fix compares each generated slot's start time against `timezone.now()`.

4. **Two decisions made without AI:** (a) keeping `patient` as a plain
   foreign key with no auth layer, instead of adding a lightweight login —
   the brief doesn't ask for auth and I'd rather document the gap
   explicitly than half-build something out of scope; (b) choosing to
   compute slots on the fly instead of pre-generating slot rows — that's a
   capacity/scaling trade-off specific to "we're starting small but want to
   grow," and it's a judgment call about the product's growth trajectory
   that isn't something to outsource.