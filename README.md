# ERIMS — Emergency Resource & Inventory Management System

Django + PostgreSQL. Week 1 build: database, stock logic, roles, demo data, deployment.

---

## Week 1 guide (day by day)

Commands are shown for **Windows (PowerShell / Command Prompt)**. Mac/Linux differences are noted.

### What you should have at the end of Week 1
- [ ] Project runs locally on PostgreSQL
- [ ] ER diagram done (`docs/er-diagram.md`)
- [ ] All tables created with migrations
- [ ] Login works; 3 roles (Admin, Inventory Manager, Viewer)
- [ ] Demo data loaded (5 locations, 12 supplies, 2 emergencies)
- [ ] Stock logic tested (`python manage.py test` passes)
- [ ] App live on Render

---

### Day 1 — Set up the project

**1. Copy the files into your repo.** Unzip and copy everything inside the `erims` folder
(including the hidden files `.gitignore` and `.env.example`) into your git repo folder, so
`manage.py` is at the top level of the repo.

**2. Create a virtual environment and install packages.** Open a terminal in the repo folder:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
(Mac/Linux: `python3 -m venv venv` then `source venv/bin/activate`.)

You should see `(venv)` at the start of the prompt. Activate it again every time you open a new terminal.

> If PowerShell says "running scripts is disabled", run this once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

**3. Create the PostgreSQL database.** Open **SQL Shell (psql)** from the Start menu (press Enter
for the defaults, then type the `postgres` password you chose during installation) — or use
pgAdmin → Query Tool. Run:

```sql
CREATE USER erims_user WITH PASSWORD 'erims_pass';
ALTER USER erims_user CREATEDB;   -- needed so Django can create a test database
CREATE DATABASE erims OWNER erims_user;
```

**4. Create your `.env` file.**

```powershell
copy .env.example .env
```
(Mac/Linux: `cp .env.example .env`.) Open `.env` and check `DATABASE_URL` matches the user,
password and database above. If you changed the password, change it here too.

**5. Check that Django can reach the database.**

```powershell
python manage.py check
```
Expected: `System check identified no issues (0 silenced).`

**6. Study the ER diagram** in `docs/er-diagram.md` (it renders on GitHub). The "Design notes"
section explains *why* the schema looks like this — know these points for your viva.

**7. Commit.**
```powershell
git add .
git commit -m "Day 1: Django project setup with PostgreSQL"
git push
```
Check on GitHub that `.env` and `venv/` were **not** uploaded (`.gitignore` prevents it).

---

### Day 2 — Create the tables

Read `inventory/models.py` and `emergencies/models.py`. Then generate and apply migrations:

```powershell
python manage.py makemigrations inventory emergencies
python manage.py migrate
```

Open pgAdmin → `erims` database → Schemas → public → Tables. You should see
`inventory_location`, `inventory_supply`, `inventory_stockbatch`, `inventory_stocktransaction`,
`emergencies_emergencyevent`, `emergencies_eventrequirement` and Django's own tables.

```powershell
git add .
git commit -m "Day 2: models and migrations"
git push
```
Commit the generated `migrations/0001_initial.py` files — Render needs them.

---

### Day 3 — Login and roles

```powershell
python manage.py setup_roles
python manage.py createsuperuser
python manage.py runserver
```

- Open http://127.0.0.1:8000 → you are sent to the login page → sign in → home page shows your role as **Admin**.
- Open http://127.0.0.1:8000/admin → you can see Locations, Supplies, Stock batches, Stock transactions and Emergency events.
- Notice that **Stock batches** and **Stock transactions** are read-only in Admin. That's deliberate:
  stock only changes through `inventory/services.py`, so every change is recorded.

Read `accounts/roles.py` to see what each role can do. In Week 2 you protect pages with:

```python
from accounts.roles import ADMIN, MANAGER, RoleRequiredMixin, role_required

@role_required(ADMIN, MANAGER)
def receive_stock_view(request): ...
```

```powershell
git commit -am "Day 3: login and roles"
git push
```

---

### Day 4 — Demo data and SQL queries

```powershell
python manage.py seed_data --with-users
```

This creates demo users **admin / manager / viewer** (password `Erims@2026`), 5 locations,
12 supplies, ~45 stock batches, 2 emergencies and some sample transfers/dispatches.
Log in as each user and check the role badge in the top bar.

The Cox's Bazar cyclone stock matches the readiness example in your proposal slides
(water 7,500 of 10,000 → short; rice 5,500 of 5,000 → ready; first aid kits 320 of 500 → short;
blankets 900 of 800 → ready).

Now open `docs/sql-queries.sql` in pgAdmin's Query Tool and run each query. They answer
the project's core questions directly in SQL: current stock, low-stock alerts, expiry alerts,
the readiness check, transfer candidates, and the audit trail. Take screenshots for your report.

To wipe and reload demo stock later: `python manage.py seed_data --reset`

---

### Day 5 — Stock logic and tests

Read `inventory/services.py` carefully — it's the heart of the project:

| Function | What it does |
|---|---|
| `receive_stock` | New stock arrives; merges into a matching batch or creates one |
| `dispatch_stock` | Stock goes out; takes the **earliest-expiring batch first** (FEFO); skips expired stock |
| `transfer_stock` | Moves stock between locations; batch number and expiry travel with it |
| `adjust_stock` | Correct a batch after a physical count; reason required |
| `write_off_stock` | Remove damaged or expired stock |

Every function is atomic (all-or-nothing), locks the rows it changes, refuses to go negative,
and writes a `StockTransaction`.

Try it in the Django shell:

```powershell
python manage.py shell
```
```python
from inventory.models import *
from inventory import services
water = Supply.objects.get(sku="WAT-001")
dhk = Location.objects.get(code="DHK-CW")
cxb = Location.objects.get(code="CXB-RC")
services.available_quantity(water, cxb)          # 7500
services.transfer_stock(supply=water, from_location=dhk, to_location=cxb, quantity=2500, reason="Cyclone")
services.available_quantity(water, cxb)          # 10000
services.dispatch_stock(supply=water, location=dhk, quantity=999999)   # raises StockError
exit()
```

Run the tests:

```powershell
python manage.py test
```
Expected: all tests pass (`OK`). If you see "permission denied to create database",
run `ALTER USER erims_user CREATEDB;` in psql.

```powershell
git commit -am "Day 5: stock services and tests"
git push
```

---

### Day 6 — Deploy to Render

1. Make sure everything is pushed to GitHub (including the `migrations` folders).
2. Go to https://dashboard.render.com → **New** → **Blueprint** → connect your GitHub repo.
3. Render reads `render.yaml` and creates the **PostgreSQL database** and the **web service**.
   It asks for `DEMO_PASSWORD` — enter a password for the demo users.
4. Wait for the build (`build.sh` installs packages, collects static files, migrates,
   creates roles and loads demo data).
5. Open the `https://erims-xxxx.onrender.com` URL and log in as `admin` with your DEMO_PASSWORD.

Notes:
- The free web service sleeps when idle; the first visit after a while takes ~1 minute. Open it
  a few minutes before any demo.
- Free Render PostgreSQL databases expire after a limited time (check Render's current free-tier terms).
  Note the expiry date in your dashboard so it doesn't disappear before your final presentation.
- If the build fails, open the service → **Logs**. The most common cause is forgetting to commit
  the migration files.

---

### Day 7 — Buffer and review

- Fix anything that didn't work.
- Update the proposal slides: remove the Next.js architecture slide, change the timeline to 3 weeks.
- Add the ER diagram image (export from https://mermaid.live) to your report.
- Write down anything you want to ask your supervisor.

---

## Project structure

```
config/          settings, URLs
accounts/        roles (Admin, Inventory Manager, Viewer), home page, setup_roles command
inventory/       locations, supplies, stock batches, transactions, stock services, seed_data command
emergencies/     emergency events and their required resources
templates/       base layout, login, home
static/          CSS
docs/            ER diagram, SQL queries
build.sh         Render build script
render.yaml      Render blueprint (database + web service)
```

## Useful commands

| Command | Purpose |
|---|---|
| `python manage.py runserver` | Run locally at http://127.0.0.1:8000 |
| `python manage.py makemigrations` | After changing models |
| `python manage.py migrate` | Apply migrations |
| `python manage.py setup_roles` | Create/update role groups |
| `python manage.py seed_data --with-users` | Load demo data and demo users |
| `python manage.py seed_data --reset` | Wipe stock/events and reload |
| `python manage.py test` | Run tests |
| `python manage.py createsuperuser` | Create an admin account |

## Coming in Week 2
Inventory pages and transaction forms, alerts page, emergency event pages, readiness check
and transfer suggestions.
