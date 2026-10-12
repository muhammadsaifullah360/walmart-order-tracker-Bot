# Walmart Order Status Bot

Reads Walmart orders from a Google Sheet, looks up each order's status on
Walmart's guest **Track order** page in a visible browser, and writes the
status back to the sheet.

Your sheet layout (tab **Wagenblast**):

| A (email) | B (order no) | C (status) |
|-----------|--------------|------------|
| row 1 is the header | | |
| MarrsGentille30@hotmail.com | 200015569995882<br>200015112102319 | *(bot fills this)* |

Column B can hold **one or two** order numbers on separate lines. All of
this is configurable (see **Settings** below and the fields in the UI).

---

## What you get

- **A small window (UI)** – paste your Sheet URL, set the tab and columns,
  press **Start**. Best way to run it day to day.
- **Command line** – for quick tests (`--limit`, `--dry-run`, `--inspect`).
- **An optional .exe** – double-click to open the UI (see *Make an .exe*).

---

## Step-by-step setup (Windows, beginner friendly)

### 1. Install Python
1. Go to <https://www.python.org/downloads/> and install **Python 3.10 or newer**.
2. On the first install screen, **tick "Add Python to PATH"**, then install.

### 2. Get the project files
Put all these files in one folder (you already have them in
`Downloads\boot`): `bot.py`, `gui.py`, `config.py`, `requirements.txt`.

### 3. Open a terminal in that folder
Open the folder in File Explorer, click the address bar, type `cmd`, press Enter.

### 4. Install the libraries
```
pip install -r requirements.txt
```
You do **not** need to run `playwright install chromium` by hand — the bot
downloads the browser automatically the first time it runs if it's missing
(one-time, ~150 MB). If you prefer to pre-download it, you still can:
```
playwright install chromium
```

### 5. Add your Google key file
Put your service-account file named **`service_account.json`** in this same
folder. You already shared the sheet with its `client_email` as **Editor** –
good. (This file is secret; `.gitignore` keeps it out of git.)

### 6. Confirm the Walmart page (one time)
Walmart changes their page sometimes, so confirm the form fields:
```
python bot.py --inspect
```
A browser opens the track-order page. Look at the **order number** box, the
**email** box, and the **Track** button. If the page looks different from what
`config.py` expects, tell me what you see and I'll adjust the `SELECTORS`
section in `config.py` (that is the only place selectors live).

---

## Run a safe 5-row test FIRST (nothing gets written)
```
python bot.py --limit 5 --dry-run
```
This prints what it *would* write to column C, but does not change the sheet.
Check the output looks right.

## Then a small real run
```
python bot.py --limit 5
```

## Full run
```
python bot.py
```

## Using the window (UI) instead
```
python gui.py
```
- Paste your **Sheet URL or ID**, set **Tab name**.
- Set **Email col / Orders col / Status col** (defaults A / B / C). Change
  these if your columns move – e.g. Email col = `H`, Status col = `J`.
- **Header rows** = 1 for your sheet (data starts on row 2).
- **Limit** = 5 for a test, 0 for everything.
- Leave **Dry run** ticked for a safe test; untick it for a real run.
- Press **Start**. Watch the live log at the bottom.
- If a captcha appears, the log tells you to solve it in the browser, then
  click **Continue (captcha solved)**.
- **Stop** ends cleanly after the current step.

---

## How statuses are written
- One order number → just the status, e.g. `Delivered`.
- Two order numbers → one per line:
  ```
  200015569995882: Delivered
  200015112102319: Shipped
  ```
- If **both** are Delivered → just `Delivered` (keeps the sheet clean).
- A row is **skipped** if column C already contains "Delivered", or if the
  email or order cell is empty.

---

## Settings (`config.py`)
All settings are at the top of `config.py`, including:

| Setting | Meaning |
|---|---|
| `SPREADSHEET_ID` | your sheet (URL or ID) |
| `TAB_NAME` | the tab, e.g. `Sheet1` |
| `HEADER_ROWS` | header rows to skip (1 for your sheet) |
| `EMAIL_COL`, `ORDERS_COL`, `STATUS_COL` | which columns to use |
| `CHECKED_COL` | column for the "last checked" time (set "" to disable) |
| `MIN_DELAY`, `MAX_DELAY` | pause between lookups (fast: 1–3s) |
| `SKIP_IF_CHECKED_WITHIN_HOURS` | skip rows checked within N hours (0 = off) |
| `LONG_PAUSE_EVERY` | longer break every N lookups |
| `MAX_ROWS_PER_RUN` | cap rows per run (0 = all) |
| `DRY_RUN` | print instead of write |
| `HEADLESS` | keep **False** – Walmart blocks headless bots |

**Selectors** for the Walmart page are in the `SELECTORS` block at the bottom
of `config.py`. If Walmart changes their page, that is the only thing to edit.

---

## Running on MULTIPLE PCs (recommended: setup.bat + run.bat)

Copy the whole project folder to each PC, then:

1. Install Python once (python.org — tick "Add python.exe to PATH").
2. Double-click **`setup.bat`** (installs the libraries). Do this once per PC.
3. Put **`service_account.json`** in the folder.
4. Double-click **`run.bat`** → the app opens. Use it from the window.

That's two double-clicks (`setup.bat`, then `run.bat`). The web browser it uses
downloads itself the first time you press **Start**. Settings are saved per PC
in `settings.json`, so each machine can use a different tab/columns.

### What about the .exe?
`build.bat` makes `dist\WalmartBot.exe` (no Python needed). **But** Windows 11's
**Smart App Control** blocks unsigned apps, so the exe may be **blocked** on PCs
that have it on. If so, use the `setup.bat` + `run.bat` route above instead — it
runs through Python (a signed, recognized app) and is never blocked. The exe is
fine on PCs where Smart App Control is off.

### If PCs share one Google Sheet
That's fine — they can all use the same `service_account.json`. To avoid two
PCs working the same rows, give each PC a different tab, or run them at
different times. (The bot writes after every row, so no finished work is lost.)

### Changing the bundled defaults
`config.py` is baked into the exe (delays, selectors, etc.). To change those,
edit `config.py` and run `build.bat` again. Day-to-day sheet/tab/column changes
do **not** need a rebuild — use the window fields + Save settings.

For a single personal PC, `python gui.py` is still the simplest route.

---

## Good-citizen rules this bot follows
- Visible browser, human-like random delays, long breaks every 20 lookups.
- **Never** auto-solves captchas – it pauses and waits for you.
- Keeps request volume modest. Writes progress after every row, so a crash
  never loses finished work.
- If a lookup fails twice, it writes `Check manually` and moves on – one bad
  row never stops the whole run.

## When automation can't finish a lookup
If Walmart asks to email you a link or send a code, the bot writes
`Needs email/phone verification - check manually` for that order – those steps
need a real inbox/phone and can't be automated safely.
