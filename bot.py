"""
bot.py -- read Walmart orders from a Google Sheet, look up each order's status
on Walmart's guest "Track order" page, and write the status back to the sheet.

Run a safe test first:
    python bot.py --limit 5 --dry-run

Inspect the real Walmart page (do this ONCE to confirm selectors):
    python bot.py --inspect

Real run:
    python bot.py

The GUI (gui.py) imports run_bot() from this file, so all the logic lives here.
"""

import argparse
import datetime
import logging
import os
import random
import re
import sys
import threading
import time

import config


# ---------------------------------------------------------------------------
# Audible alarm: beep on a loop until stopped (used while a captcha is waiting).
# ---------------------------------------------------------------------------
def _beep():
    try:
        import winsound
        winsound.Beep(1000, 400)   # 1000 Hz for 400 ms
    except Exception:
        try:
            sys.stdout.write("\a")
            sys.stdout.flush()
        except Exception:
            pass


class SoundAlarm:
    """Beeps every SOUND_INTERVAL seconds in a background thread until stopped."""
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if not getattr(config, "SOUND_ALERT", True):
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        interval = getattr(config, "SOUND_INTERVAL", 2.0)
        while not self._stop.is_set():
            _beep()
            self._stop.wait(interval)

    def stop(self):
        self._stop.set()


# ---------------------------------------------------------------------------
# App folder: where service_account.json / settings.json / logs / the browser
# profile live. When run as an .exe this is the exe's folder (NOT the temp
# folder PyInstaller unpacks into), so files you drop next to the exe are found.
# ---------------------------------------------------------------------------
def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resolve_path(path):
    """Make a relative path absolute, anchored at the app folder."""
    if not path:
        return path
    return path if os.path.isabs(path) else os.path.join(app_dir(), path)


# When packaged as an exe WITH the browser bundled in, point Playwright at it
# so it never needs to download Chromium at runtime.
if getattr(sys, "frozen", False):
    try:
        _base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        for _cand in (os.path.join(_base, "ms-playwright"),
                      os.path.join(os.path.dirname(sys.executable), "ms-playwright")):
            if os.path.isdir(_cand):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _cand
                break
    except Exception:
        pass

# Playwright and gspread are imported lazily inside functions so that
# `--help` and the GUI can start even before `pip install` is finished.


# ---------------------------------------------------------------------------
# Reporter: a tiny interface so the SAME core logic works from the command
# line and from the GUI. The CLI version uses print()/input(); the GUI passes
# its own object that writes to the log window and uses a Continue button.
# ---------------------------------------------------------------------------
class Reporter:
    def log(self, msg, level="info"):
        getattr(logging, level, logging.info)(msg)

    def progress(self, done, total, counts):
        """Report progress (done/total rows) and a dict of status counts."""
        pass

    def should_pause(self):
        """Return True to pause between lookups."""
        return False

    def notify_done(self, summary):
        """Called at the end of a run with a one-line summary string."""
        logging.info(summary)

    def wait_for_human(self, msg):
        """Block until a human has dealt with a captcha / manual step."""
        logging.warning(msg)
        print("\n" + "=" * 60)
        print(msg)
        print(">>> SOLVE THE CAPTCHA in the browser, then press ENTER here.")
        alarm = SoundAlarm()
        alarm.start()
        try:
            input(">>> (beeping until solved) press ENTER when done... ")
        except EOFError:
            pass
        finally:
            alarm.stop()
        print("=" * 60 + "\n")

    def should_stop(self):
        return False


# ---------------------------------------------------------------------------
# Logging setup: file + terminal.
# ---------------------------------------------------------------------------
def setup_logging():
    logger = logging.getLogger()
    if logger.handlers:
        return  # already configured
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    fh = logging.FileHandler(resolve_path(config.LOG_FILE), encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)


# ---------------------------------------------------------------------------
# Browser bootstrap: make sure Chromium is present; download it if not.
# This is what makes the .exe "just work" on a fresh PC with no manual
# `playwright install chromium` step.
# ---------------------------------------------------------------------------
def _run_playwright_install(reporter):
    """Run `playwright install chromium`, working both from source and frozen."""
    if getattr(sys, "frozen", False):
        # Running as a PyInstaller .exe: there is no python.exe to call, so
        # invoke Playwright's own CLI in-process.
        try:
            from playwright.__main__ import main as pw_main
            saved = sys.argv[:]
            sys.argv = ["playwright", "install", "chromium"]
            try:
                pw_main()
            except SystemExit:
                pass
            finally:
                sys.argv = saved
        except Exception as e:
            reporter.log(f"Auto-install failed: {e}", level="error")
    else:
        import subprocess
        try:
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                           check=True)
        except Exception as e:
            reporter.log(f"Auto-install failed: {e}", level="error")


# Anti-detection: launch flags + an init script that hides the tell-tale
# `navigator.webdriver` flag and a few other automation fingerprints.
STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--start-maximized",
    "--no-first-run",
    "--no-default-browser-check",
]

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


def launch_stealth_context(p, reporter, headless=None):
    """Launch a persistent browser context tuned to look like a real human."""
    if headless is None:
        headless = config.HEADLESS
    kwargs = dict(
        user_data_dir=resolve_path(config.USER_DATA_DIR),
        headless=headless,
        no_viewport=True,
        args=STEALTH_ARGS,
        ignore_default_args=["--enable-automation"],
    )
    use_chrome = getattr(config, "USE_REAL_CHROME", False)
    if use_chrome:
        try:
            ctx = p.chromium.launch_persistent_context(channel="chrome", **kwargs)
            reporter.log("Using your installed Google Chrome (better at passing bot checks).")
        except Exception as e:
            reporter.log(f"Real Chrome not available ({e}); falling back to Chromium.",
                         level="warning")
            ctx = p.chromium.launch_persistent_context(**kwargs)
    else:
        ctx = p.chromium.launch_persistent_context(**kwargs)
    try:
        ctx.add_init_script(STEALTH_JS)
    except Exception:
        pass
    return ctx


def ensure_chromium(reporter):
    """
    Return True if Chromium is ready. If it is missing, download it once
    (~150 MB) and then re-check. Safe to call before every run.
    """
    import os
    from playwright.sync_api import sync_playwright

    def chromium_path():
        try:
            with sync_playwright() as p:
                exe = p.chromium.executable_path
            return exe if (exe and os.path.exists(exe)) else None
        except Exception:
            return None

    if chromium_path():
        return True

    reporter.log("Chromium browser not found. Downloading it now "
                 "(one-time, ~150 MB). This can take a few minutes...")
    _run_playwright_install(reporter)

    if chromium_path():
        reporter.log("Browser ready.")
        return True

    reporter.log("Could not install the browser automatically. Open a terminal "
                 "and run:  playwright install chromium", level="error")
    return False


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def extract_spreadsheet_id(value):
    """Accept a full Google Sheets URL or a bare ID and return the ID."""
    value = (value or "").strip()
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", value)
    return m.group(1) if m else value


def col_to_index(letter):
    """'A' -> 0, 'B' -> 1, ... 'H' -> 7 (0-based)."""
    letter = letter.strip().upper()
    idx = 0
    for ch in letter:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def clean_order_numbers(cell_text):
    """
    Split a cell on newlines / commas / spaces, then for each token keep only
    digits and dashes. Returns a de-duplicated list of cleaned order numbers.
    """
    if not cell_text:
        return []
    tokens = re.split(r"[\n\r,;\s]+", str(cell_text))
    cleaned = []
    for tok in tokens:
        kept = re.sub(r"[^0-9\-]", "", tok)
        kept = kept.strip("-")
        if len(re.sub(r"\D", "", kept)) >= 6:   # needs at least 6 digits
            if kept not in cleaned:
                cleaned.append(kept)
    return cleaned


def normalize_status(page_text):
    """Turn raw page text into a clean status word using config.STATUS_KEYWORDS."""
    low = page_text.lower()
    for keyword, label in config.STATUS_KEYWORDS:
        if keyword in low:
            return label
    return ""


def _any_phrase(text, phrases):
    low = text.lower()
    return any(p in low for p in phrases)


def parse_walmart_status(body):
    """
    Read the TRUE status from a Walmart order-details page.

    The page shows a progress tracker where each stage is prefixed with its
    state, e.g.:
        Complete,     Placed
        Current,      Delayed        <- the real current stage
        Not complete, On the way
        Not complete, Delivered      <- a FUTURE stage (must NOT be read as the status)

    So we trust the stage marked "Current," first, then the headline line,
    then a completed "Delivered" stage, and only fall back to a loose scan.
    Returns (normalized_status, raw_text_seen).
    """
    low = body.lower()

    # 0) Refund / return take priority -- even if the item was delivered first,
    #    a refunded order should read "Refunded".
    if "refund issued" in low or "refunded" in low or "refund has been issued" in low:
        return "Refunded", "Refund issued"
    if "return received" in low or "item returned" in low or "return complete" in low:
        return "Returned", "Returned"

    # 1) The active stage is marked "Current,". This is the authoritative status.
    #    (Guard against matching "Not complete," which also contains "complete".)
    m = re.search(r"\bCurrent,\s*\n?\s*([A-Za-z][A-Za-z '\-]+)", body)
    if m:
        stage = m.group(1).strip()
        norm = normalize_status(stage)
        if norm:
            return norm, stage

    # 2) Headline status line, e.g. "Delivery\nDelayed, check back for updates"
    m = re.search(r"(?:Delivery|Pickup|Shipping)[^\n]*\n\s*([^\n]{3,60})", body)
    if m:
        norm = normalize_status(m.group(1))
        if norm:
            return norm, m.group(1).strip()

    # 3) A completed final stage means the order is actually delivered/picked up.
    if re.search(r"Complete,\s*\n?\s*Delivered", body):
        return "Delivered", "Complete, Delivered"
    if re.search(r"Complete,\s*\n?\s*Picked up", body):
        return "Picked up", "Complete, Picked up"

    # 4) Last resort: loose whole-page scan (can be wrong; used only if nothing else hit).
    return normalize_status(body), ""


# NOTE: these tracking patterns are a first pass. Once you run --test-order on a
# SHIPPED order, send Claude the dump and they'll be tuned to Walmart's exact text.
_UPS_RE = re.compile(r"\b1Z[0-9A-Z]{16}\b")
_USPS_RE = re.compile(r"\b9[0-9]{19,25}\b")
_LABELLED_RE = re.compile(r"[Tt]racking\s*(?:number|no\.?|#)\s*:?\s*\n?\s*([0-9A-Z]{10,35})")


def parse_tracking(body):
    """
    Best-effort: pull a carrier tracking number + carrier name off the order page.
    Returns (tracking_number, carrier) -- either may be '' if not shown
    (e.g. the order hasn't shipped yet, or it's a Walmart/GoLocal delivery).
    """
    carrier = ""
    for name in config.CARRIER_NAMES:
        if re.search(r"\b" + re.escape(name) + r"\b", body, re.I):
            carrier = name
            break

    tracking = ""
    m = _UPS_RE.search(body)
    if m:
        tracking = m.group(0)
        carrier = carrier or "UPS"
    if not tracking:
        m = _LABELLED_RE.search(body)
        if m:
            cand = m.group(1)
            # Avoid grabbing the order number itself (15 digits, starts 2000).
            if not (cand.isdigit() and len(cand) == 15 and cand.startswith("2000")):
                tracking = cand
    if not tracking:
        m = _USPS_RE.search(body)
        if m:
            tracking = m.group(0)
            carrier = carrier or "USPS"
    return tracking, carrier


# ---------------------------------------------------------------------------
# Carrier refresh via AfterShip (captcha-free). Dormant until a key is set.
# ---------------------------------------------------------------------------
_CARRIER_SLUGS = {
    "ups": "ups", "fedex": "fedex", "usps": "usps", "dhl": "dhl",
    "lasership": "lasership", "ontrac": "ontrac",
}
_AFTERSHIP_TAG_TO_STATUS = {
    "Delivered": "Delivered",
    "OutForDelivery": "Out for delivery",
    "InTransit": "Shipped",
    "InfoReceived": "Processing",
    "Pending": "Processing",
    "AttemptFail": "Delayed",
    "Exception": "Check manually",
    "Expired": "Check manually",
}


def carrier_enabled():
    return bool(getattr(config, "AFTERSHIP_API_KEY", "").strip())


def _tracking_line_map(cell_text):
    """Parse a column-D cell ('order: tracking (carrier)' per line) -> {order: (tracking, carrier)}."""
    out = {}
    for line in (cell_text or "").splitlines():
        m = re.match(r"\s*(\d{6,})\s*:\s*(\S+)(?:\s*\(([^)]+)\))?", line)
        if m:
            out[m.group(1)] = (m.group(2), (m.group(3) or "").strip())
    return out


def get_carrier_status(tracking, carrier, reporter):
    """Look up delivery status from AfterShip. Returns a status string or None on failure."""
    key = getattr(config, "AFTERSHIP_API_KEY", "").strip()
    if not key or not tracking:
        return None
    slug = _CARRIER_SLUGS.get((carrier or "").lower())
    import requests
    headers = {"aftership-api-key": key, "Content-Type": "application/json"}
    base = "https://api.aftership.com/v4/trackings"
    body = {"tracking": {"tracking_number": tracking}}
    if slug:
        body["tracking"]["slug"] = slug
    try:
        # Create the tracking (ignored/409 if it already exists), then fetch it.
        requests.post(base, json=body, headers=headers, timeout=20)
        if slug:
            url = f"{base}/{slug}/{tracking}"
        else:
            url = f"{base}/{tracking}"
        r = requests.get(url, headers=headers, timeout=20)
        tag = r.json().get("data", {}).get("tracking", {}).get("tag")
        if tag:
            return _AFTERSHIP_TAG_TO_STATUS.get(tag, "Shipped")
    except Exception as e:
        reporter.log(f"      carrier lookup failed ({e}); will use Walmart instead",
                     level="warning")
    return None


# ---------------------------------------------------------------------------
# Locator resolution: turn a config selector string into a Playwright locator.
# ---------------------------------------------------------------------------
def resolve_locator(page, spec):
    """Return a Playwright Locator for one selector string, or None if unknown."""
    if spec.startswith("label="):
        return page.get_by_label(re.compile(re.escape(spec[6:]), re.I))
    if spec.startswith("placeholder="):
        return page.get_by_placeholder(re.compile(re.escape(spec[12:]), re.I))
    if spec.startswith("text="):
        return page.get_by_text(re.compile(re.escape(spec[5:]), re.I))
    if spec.startswith("testid="):
        val = spec[7:]
        return page.locator(
            f"[data-testid*='{val}' i], [data-automation-id*='{val}' i]"
        )
    if spec.startswith("role="):
        body = spec[5:]
        if "|" in body:
            role, name = body.split("|", 1)
            return page.get_by_role(role.strip(),
                                    name=re.compile(re.escape(name.strip()), re.I))
        return page.get_by_role(body.strip())
    if spec.startswith("css="):
        return page.locator(spec[4:])
    return page.locator(spec)   # assume raw css


def first_visible(page, specs, timeout_ms=None):
    """Try each selector string in `specs`; return the first visible locator."""
    timeout_ms = timeout_ms or config.ELEMENT_TIMEOUT_MS
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        for spec in specs:
            try:
                loc = resolve_locator(page, spec).first
                if loc.count() > 0 and loc.is_visible():
                    return loc
            except Exception:
                continue
        page.wait_for_timeout(300)
    return None


# ---------------------------------------------------------------------------
# Captcha / bot-check handling
# ---------------------------------------------------------------------------
def handle_captcha_if_present(page, reporter):
    """If a bot-check wall is showing, pause for the human to solve it."""
    try:
        body = page.inner_text("body", timeout=3000)
    except Exception:
        body = ""
    url_blocked = any(m in (page.url or "") for m in getattr(config, "CAPTCHA_URL_MARKERS", []))
    if url_blocked or _any_phrase(body, config.CAPTCHA_PHRASES):
        reporter.wait_for_human(
            "CAPTCHA / bot-check detected. Please solve it in the visible "
            "browser window, then continue."
        )
        return True
    return False


# ---------------------------------------------------------------------------
# Look up ONE order number. Returns a clean status string.
# ---------------------------------------------------------------------------
def lookup_one_order(page, order_number, email, reporter):
    page.goto(config.TRACK_ORDER_URL, timeout=config.PAGE_TIMEOUT_MS,
              wait_until="domcontentloaded")
    handle_captcha_if_present(page, reporter)

    order_box = first_visible(page, config.SELECTORS["order_number_input"])
    email_box = first_visible(page, config.SELECTORS["email_input"])
    if not order_box or not email_box:
        # Page structure not as expected -- maybe captcha appeared mid-load.
        if handle_captcha_if_present(page, reporter):
            order_box = first_visible(page, config.SELECTORS["order_number_input"])
            email_box = first_visible(page, config.SELECTORS["email_input"])
    if not order_box or not email_box:
        raise RuntimeError(
            "Could not find the order-number/email fields. "
            "Run `python bot.py --inspect` and fix SELECTORS in config.py."
        )

    order_box.fill("")
    order_box.fill(order_number)
    email_box.fill("")
    email_box.fill(email)

    submit = first_visible(page, config.SELECTORS["submit_button"])
    if submit:
        submit.click()
    else:
        email_box.press("Enter")

    # Fast wait: the result page URL becomes /orders/<number>. No slow networkidle.
    try:
        page.wait_for_url("**/orders/*", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(500)
    handle_captcha_if_present(page, reporter)

    # Wait for the order-details content to actually render before reading,
    # so a fast page load doesn't give us a half-empty page.
    body = ""
    for _ in range(14):   # up to ~7s
        try:
            body = page.inner_text("body", timeout=3000)
        except Exception:
            body = ""
        low = body.lower()
        if ("order#" in low or "order #" in low
                or _any_phrase(body, config.NOT_FOUND_PHRASES)
                or _any_phrase(body, config.NEEDS_HUMAN_PHRASES)):
            break
        page.wait_for_timeout(500)

    if _any_phrase(body, config.NOT_FOUND_PHRASES):
        return "Not found", "", ""
    if _any_phrase(body, config.NEEDS_HUMAN_PHRASES):
        return "Needs email/phone verification - check manually", "", ""

    # Read the true status from the order-details progress tracker.
    status, raw = parse_walmart_status(body)
    tracking, carrier = parse_tracking(body)
    if status:
        if raw:
            reporter.log(f"      (read stage: {raw!r})")
        if tracking:
            reporter.log(f"      (tracking: {tracking} {carrier})")
        return status, tracking, carrier
    return "Check manually", tracking, carrier


def lookup_with_retry(ctx, order_number, email, reporter, new_tab=True):
    """Look up an order, retry once on failure. Returns (status, tracking, carrier).

    new_tab=True opens a fresh tab per lookup and closes it after (can reduce
    bot-checks); new_tab=False reuses the context's first tab.
    """
    for attempt in (1, 2):
        if new_tab:
            page = ctx.new_page()
        else:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            status, tracking, carrier = lookup_one_order(page, order_number, email, reporter)
            reporter.log(f"    order {order_number}: {status}")
            return status, tracking, carrier
        except Exception as e:
            reporter.log(f"    order {order_number}: attempt {attempt} failed: {e}",
                         level="warning")
        finally:
            if new_tab:
                try:
                    page.close()
                except Exception:
                    pass
        if attempt == 1:
            time.sleep(3)
    return "Check manually", "", ""


# ---------------------------------------------------------------------------
# Build the final status string for a row (handles 1 or 2 order numbers).
# ---------------------------------------------------------------------------
def format_row_status(results):
    """
    results: list of (order_number, status).
    - 2 orders both Delivered  -> "Delivered"
    - otherwise                -> "<order>: <status>" per line
    - 1 order                  -> just the status
    """
    if len(results) == 1:
        return results[0][1]
    if results and all(s.lower() == "delivered" for _, s in results):
        return "Delivered"
    return "\n".join(f"{num}: {status}" for num, status in results)


def format_row_tracking(results):
    """
    results: list of (order_number, tracking, carrier).
    One line per order that has a tracking number: "<order>: <tracking> (<carrier>)".
    Orders with no tracking yet are skipped. Returns '' if none have tracking.
    """
    lines = []
    for num, tracking, carrier in results:
        if tracking:
            lines.append(f"{num}: {tracking}" + (f" ({carrier})" if carrier else ""))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Status categories: coloring, problem detection, summary counting.
# ---------------------------------------------------------------------------
_CAT_RGB = {
    "good":    {"red": 0.80, "green": 0.92, "blue": 0.80},   # green
    "transit": {"red": 0.80, "green": 0.88, "blue": 0.97},   # blue
    "wait":    {"red": 1.00, "green": 0.95, "blue": 0.76},   # amber
    "bad":     {"red": 0.97, "green": 0.80, "blue": 0.80},   # red
}


def status_category(final_status):
    """Classify a final cell string into good / transit / wait / bad / '' ."""
    s = (final_status or "").lower()
    if any(w in s for w in ("cancel", "refund", "return", "not found", "check manually")):
        return "bad"
    if any(w in s for w in ("delay", "processing", "pending", "preparing")):
        return "wait"
    if any(w in s for w in ("shipped", "out for delivery", "arriv", "on the way",
                            "ready for pickup")):
        return "transit"
    if any(w in s for w in ("delivered", "picked up")):
        return "good"
    return ""


def cell_color(final_status):
    return _CAT_RGB.get(status_category(final_status))


def is_problem(final_status):
    return status_category(final_status) in ("bad", "wait")


def done_chime():
    if not getattr(config, "DONE_CHIME", True):
        return
    try:
        import winsound
        for f in (660, 880, 990):
            winsound.Beep(f, 140)
    except Exception:
        pass


def post_webhook(text):
    url = getattr(config, "NOTIFY_WEBHOOK_URL", "").strip()
    if not url or not text:
        return
    try:
        import requests
        requests.post(url, json={"content": text, "text": text}, timeout=15)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Google Sheets access
# ---------------------------------------------------------------------------
def open_worksheet(settings):
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        resolve_path(settings["SERVICE_ACCOUNT_FILE"]), scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(settings["SPREADSHEET_ID"])
    return sh.worksheet(settings["TAB_NAME"])


# ---------------------------------------------------------------------------
# Inspect mode: open the real page and pause so you can read the fields.
# ---------------------------------------------------------------------------
INSPECT_JS = r"""
() => {
  const out = {inputs: [], buttons: [], selects: []};
  const labelFor = (el) => {
    // explicit <label for=id>
    if (el.id) {
      const l = document.querySelector(`label[for="${el.id}"]`);
      if (l) return l.innerText.trim();
    }
    // wrapping <label>
    let p = el.closest('label');
    if (p) return p.innerText.trim();
    // aria-label / aria-labelledby
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const n = document.getElementById(lb); if (n) return n.innerText.trim(); }
    return '';
  };
  document.querySelectorAll('input, textarea').forEach(el => {
    out.inputs.push({
      tag: el.tagName.toLowerCase(), type: el.type || '', name: el.name || '',
      id: el.id || '', placeholder: el.placeholder || '',
      testid: el.getAttribute('data-testid') || el.getAttribute('data-automation-id') || '',
      autocomplete: el.getAttribute('autocomplete') || '',
      label: labelFor(el),
      visible: !!(el.offsetParent !== null)
    });
  });
  document.querySelectorAll('button, [role="button"], input[type="submit"]').forEach(el => {
    out.buttons.push({
      text: (el.innerText || el.value || '').trim().slice(0, 60),
      type: el.getAttribute('type') || '', id: el.id || '',
      testid: el.getAttribute('data-testid') || el.getAttribute('data-automation-id') || '',
      visible: !!(el.offsetParent !== null)
    });
  });
  out.title = document.title;
  out.url = location.href;
  out.bodyHead = (document.body ? document.body.innerText : '').slice(0, 600);
  return out;
}
"""


def _dump_page(page, dump_path):
    import json
    try:
        data = page.evaluate(INSPECT_JS)
    except Exception as e:
        data = {"error": str(e)}
    with open(dump_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n==== PAGE DUMP (also saved to {dump_path}) ====")
    print(f"URL:   {data.get('url')}")
    print(f"Title: {data.get('title')}")
    print("\n-- INPUT fields --")
    for i in data.get("inputs", []):
        if i.get("type") in ("hidden",):
            continue
        print(f"  type={i.get('type')!r} name={i.get('name')!r} id={i.get('id')!r} "
              f"placeholder={i.get('placeholder')!r} label={i.get('label')!r} "
              f"testid={i.get('testid')!r} visible={i.get('visible')}")
    print("\n-- BUTTONS --")
    for b in data.get("buttons", []):
        print(f"  text={b.get('text')!r} type={b.get('type')!r} id={b.get('id')!r} "
              f"testid={b.get('testid')!r} visible={b.get('visible')}")
    print("\n-- first 600 chars of page text --")
    print(data.get("bodyHead", ""))
    print("==== END DUMP ====\n")


def test_single_order(order_number, email):
    """Do ONE guest lookup in a visible browser and print the status.
    Lets you verify the Walmart half works before touching Google Sheets."""
    from playwright.sync_api import sync_playwright
    reporter = Reporter()
    print(f"Testing one order lookup:  order={order_number}  email={email}")
    if not ensure_chromium(reporter):
        return
    with sync_playwright() as p:
        ctx = launch_stealth_context(p, reporter, headless=False)
        ctx.set_default_timeout(config.ELEMENT_TIMEOUT_MS)
        status, tracking, carrier = lookup_with_retry(
            ctx, order_number, email, reporter,
            new_tab=getattr(config, "NEW_TAB_PER_ORDER", True))
        print("\n=====================================")
        print(f"ORDER:    {order_number}")
        print(f"EMAIL:    {email}")
        print(f"STATUS:   {status}")
        print(f"TRACKING: {tracking or '(none shown)'}  {carrier}")
        print("=====================================")
        print("If STATUS looks wrong, run with --inspect and send Claude the dump.")
        # Dump the current result page (last open tab) to refine selectors if needed.
        try:
            pages = ctx.pages
            if pages:
                _dump_page(pages[-1], resolve_path("inspect_dump.json"))
        except Exception:
            pass
        try:
            input("\nPress ENTER to close the browser... ")
        except EOFError:
            pass
        ctx.close()


def inspect_page_gui(reporter):
    """GUI-safe inspect: opens the browser, handles captcha via the reporter,
    auto-captures the page once the form (or order content) appears. No input()."""
    from playwright.sync_api import sync_playwright
    if not ensure_chromium(reporter):
        return
    dump_path = resolve_path("inspect_dump.json")
    with sync_playwright() as p:
        ctx = launch_stealth_context(p, reporter, headless=False)
        ctx.set_default_timeout(config.ELEMENT_TIMEOUT_MS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(config.TRACK_ORDER_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            reporter.log(f"inspect: page load issue ({e})", level="warning")
        reporter.log("Inspect: solve any captcha in the browser; "
                     "capturing the page automatically when the form appears...")
        deadline = time.time() + 150
        captured = False
        while time.time() < deadline and not reporter.should_stop():
            handle_captcha_if_present(page, reporter)
            ob = first_visible(page, config.SELECTORS["order_number_input"], timeout_ms=1500)
            eb = first_visible(page, config.SELECTORS["email_input"], timeout_ms=1500)
            if ob and eb:
                _dump_page(page, dump_path)
                captured = True
                break
            page.wait_for_timeout(1000)
        if not captured:
            try:
                _dump_page(page, dump_path)
            except Exception:
                pass
        reporter.log(f"Inspect captured to {dump_path}. Closing in ~8s.")
        page.wait_for_timeout(8000)
        try:
            ctx.close()
        except Exception:
            pass


def inspect_page():
    from playwright.sync_api import sync_playwright
    print("Opening Walmart track-order page for inspection...")
    print("A visible browser opens. If a 'verify you are human' wall appears,")
    print("solve it in that window. Then come back here and press ENTER to dump")
    print("the real form fields (saved to inspect_dump.json).")
    print("Close the browser window when finished.\n")
    print("[1/4] Checking the browser is installed...", flush=True)
    if not ensure_chromium(Reporter()):
        return
    dump_path = resolve_path("inspect_dump.json")
    print("[2/4] Launching the browser window (watch for a new window)...", flush=True)
    with sync_playwright() as p:
        try:
            ctx = launch_stealth_context(p, Reporter(), headless=False)
        except Exception as e:
            print(f"\nERROR launching the browser: {e}", flush=True)
            print("Tell Claude this exact error.", flush=True)
            return
        print("[3/4] Browser launched. Opening the Walmart page...", flush=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(config.TRACK_ORDER_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"\nNote: page load issue ({e}); continuing anyway.", flush=True)
        print("[4/4] Page opened. A browser window should now be visible.", flush=True)
        try:
            input(">>> Solve any captcha, wait for the form to show, "
                  "then press ENTER here to capture fields... ")
        except EOFError:
            pass
        _dump_page(page, dump_path)
        try:
            input(">>> Done. Press ENTER to close the browser... ")
        except EOFError:
            pass
        ctx.close()


# ---------------------------------------------------------------------------
# The main run. Reusable by both CLI and GUI.
# `overrides` is a dict that replaces values from config.py (used by the GUI).
# ---------------------------------------------------------------------------
def run_bot(overrides=None, reporter=None):
    reporter = reporter or Reporter()
    overrides = overrides or {}

    settings = {
        "SPREADSHEET_ID": extract_spreadsheet_id(
            overrides.get("SPREADSHEET_ID", config.SPREADSHEET_ID)),
        "TAB_NAME": overrides.get("TAB_NAME", config.TAB_NAME),
        "FIRST_DATA_ROW": overrides.get("FIRST_DATA_ROW", config.FIRST_DATA_ROW),
        "EMAIL_COL": overrides.get("EMAIL_COL", config.EMAIL_COL),
        "ORDERS_COL": overrides.get("ORDERS_COL", config.ORDERS_COL),
        "STATUS_COL": overrides.get("STATUS_COL", config.STATUS_COL),
        "TRACKING_COL": overrides.get("TRACKING_COL", getattr(config, "TRACKING_COL", "")),
        "CHECKED_COL": overrides.get("CHECKED_COL", getattr(config, "CHECKED_COL", "")),
        "SKIP_HOURS": overrides.get("SKIP_HOURS",
                                    getattr(config, "SKIP_IF_CHECKED_WITHIN_HOURS", 0)),
        "COLOR_CELLS": overrides.get("COLOR_CELLS", getattr(config, "COLOR_CELLS", True)),
        "SERVICE_ACCOUNT_FILE": overrides.get("SERVICE_ACCOUNT_FILE",
                                              config.SERVICE_ACCOUNT_FILE),
        "DRY_RUN": overrides.get("DRY_RUN", config.DRY_RUN),
        "LIMIT": overrides.get("LIMIT", config.MAX_ROWS_PER_RUN),
    }

    from playwright.sync_api import sync_playwright

    # Make sure the browser exists (downloads it on first run if needed).
    if not ensure_chromium(reporter):
        return

    reporter.log(f"Spreadsheet: {settings['SPREADSHEET_ID']}  tab: {settings['TAB_NAME']}")
    reporter.log(f"DRY_RUN={settings['DRY_RUN']}  limit={settings['LIMIT'] or 'none'}")

    ws = open_worksheet(settings)
    all_values = ws.get_all_values()      # one read call
    reporter.log(f"Sheet has {len(all_values)} rows total.")

    e_idx = col_to_index(settings["EMAIL_COL"])
    o_idx = col_to_index(settings["ORDERS_COL"])
    s_idx = col_to_index(settings["STATUS_COL"])
    chk_col = settings["CHECKED_COL"]
    chk_idx = col_to_index(chk_col) if chk_col else None
    skip_hours = settings["SKIP_HOURS"] or 0
    now = datetime.datetime.now()

    # Build the work list.
    rows_to_do = []
    skipped_recent = 0
    for r in range(settings["FIRST_DATA_ROW"], len(all_values) + 1):
        row = all_values[r - 1]

        def cell(i):
            return row[i].strip() if (i is not None and i < len(row)) else ""

        email = cell(e_idx)
        orders_raw = cell(o_idx)
        status_now = cell(s_idx)

        if "delivered" in status_now.lower():
            continue
        if not email or not orders_raw:
            continue
        # Skip rows checked very recently (if enabled).
        if skip_hours and chk_idx is not None:
            last = _parse_checked(cell(chk_idx))
            if last and (now - last).total_seconds() < skip_hours * 3600:
                skipped_recent += 1
                continue
        orders = clean_order_numbers(orders_raw)
        if not orders:
            continue
        rows_to_do.append((r, email, orders, status_now))

    if settings["LIMIT"] and settings["LIMIT"] > 0:
        rows_to_do = rows_to_do[: settings["LIMIT"]]

    if skipped_recent:
        reporter.log(f"Skipped {skipped_recent} row(s) checked within {skip_hours}h.")
    reporter.log(f"{len(rows_to_do)} row(s) to process.")
    if not rows_to_do:
        reporter.log("Nothing to do. Done.")
        reporter.notify_done("Nothing to do — no rows needed checking.")
        return

    total = len(rows_to_do)
    counts = {"good": 0, "transit": 0, "wait": 0, "bad": 0, "other": 0}
    changes = []          # (row, old, new)
    problems = []         # (row, final)
    lookups_done = 0
    done_rows = 0

    with sync_playwright() as p:
        ctx = launch_stealth_context(p, reporter, headless=config.HEADLESS)
        ctx.set_default_timeout(config.ELEMENT_TIMEOUT_MS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # Warm up a human-looking session first (helps reduce bot-checks).
        warm = getattr(config, "WARMUP_URL", "")
        if warm:
            try:
                reporter.log("Warming up session (visiting Walmart home)...")
                page.goto(warm, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT_MS)
                handle_captcha_if_present(page, reporter)
                page.wait_for_timeout(int(random.uniform(2500, 5000)))
            except Exception as e:
                reporter.log(f"Warm-up skipped: {e}", level="warning")

        try:
            for row_num, email, orders, old_status in rows_to_do:
                if reporter.should_stop():
                    reporter.log("Stop requested. Exiting cleanly.")
                    break
                _wait_while_paused(reporter)

                reporter.log(f"Row {row_num}  email={email}  orders={orders}")
                results = []
                for order_number in orders:
                    if reporter.should_stop():
                        break
                    _wait_while_paused(reporter)
                    status, tracking, carrier = lookup_with_retry(
                        ctx, order_number, email, reporter,
                        new_tab=getattr(config, "NEW_TAB_PER_ORDER", True))
                    results.append((order_number, status, tracking, carrier))
                    lookups_done += 1

                    if lookups_done % config.LONG_PAUSE_EVERY == 0:
                        pause = random.uniform(config.LONG_PAUSE_MIN, config.LONG_PAUSE_MAX)
                        reporter.log(f"  Long break: sleeping {int(pause)}s "
                                     f"(after {lookups_done} lookups)")
                    else:
                        pause = random.uniform(config.MIN_DELAY, config.MAX_DELAY)
                    _interruptible_sleep(pause, reporter)

                final = format_row_status([(n, s) for n, s, _, _ in results])
                track_str = format_row_tracking([(n, t, c) for n, s, t, c in results])
                track_col = settings["TRACKING_COL"]

                # Tally + change detection.
                cat = status_category(final) or "other"
                counts[cat] = counts.get(cat, 0) + 1
                if is_problem(final):
                    problems.append((row_num, final))
                if old_status and old_status.strip() and old_status.strip() != final.strip():
                    changes.append((row_num, old_status.strip(), final.strip()))
                    reporter.log(f"  CHANGED: {old_status.strip()!r} -> {final.strip()!r}")

                if settings["DRY_RUN"]:
                    reporter.log(f"  [DRY RUN] would write {settings['STATUS_COL']}{row_num}:\n{final}")
                else:
                    cell_ref = f"{settings['STATUS_COL']}{row_num}"
                    try:
                        ws.update_acell(cell_ref, final)
                        reporter.log(f"  wrote {cell_ref}")
                    except Exception as e:
                        reporter.log(f"  FAILED to write {cell_ref}: {e}", level="error")
                    # Color the status cell.
                    if settings["COLOR_CELLS"]:
                        rgb = cell_color(final)
                        if rgb:
                            try:
                                ws.format(cell_ref, {"backgroundColor": rgb})
                            except Exception:
                                pass
                    # Tracking column (if enabled).
                    if track_col and track_str:
                        try:
                            ws.update_acell(f"{track_col}{row_num}", track_str)
                        except Exception as e:
                            reporter.log(f"  FAILED tracking write: {e}", level="error")
                    # Last-checked timestamp.
                    if chk_col:
                        try:
                            ws.update_acell(f"{chk_col}{row_num}",
                                            now.strftime("%Y-%m-%d %H:%M"))
                        except Exception:
                            pass

                done_rows += 1
                reporter.progress(done_rows, total, dict(counts))
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    # ---- summary ----
    summary = (f"Done: {counts.get('good',0)} delivered · "
               f"{counts.get('transit',0)} in transit · "
               f"{counts.get('wait',0)} processing/delayed · "
               f"{counts.get('bad',0)} need attention")
    reporter.log("")
    reporter.log("=" * 48)
    reporter.log(summary)
    if problems:
        reporter.log(f"Rows needing attention ({len(problems)}):")
        for rn, fin in problems:
            reporter.log(f"   row {rn}: {fin.splitlines()[0] if fin else ''}")
    if changes:
        reporter.log(f"Status changes this run ({len(changes)}):")
        for rn, old, new in changes:
            reporter.log(f"   row {rn}: {old.splitlines()[0]} -> {new.splitlines()[0]}")
    reporter.log("=" * 48)

    # Optional webhook with the changes/problems.
    if changes or problems:
        lines = [summary]
        if changes:
            lines.append("Changes: " + "; ".join(
                f"row {rn}: {old.splitlines()[0]}->{new.splitlines()[0]}"
                for rn, old, new in changes[:20]))
        post_webhook("\n".join(lines))

    done_chime()
    reporter.notify_done(summary)


def _parse_checked(text):
    """Parse a 'last checked' timestamp cell back to a datetime, or None."""
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _wait_while_paused(reporter):
    """Block while the reporter says we're paused (but allow stop)."""
    while reporter.should_pause() and not reporter.should_stop():
        time.sleep(0.3)


def _interruptible_sleep(seconds, reporter):
    """Sleep but check the stop flag every second."""
    end = time.time() + seconds
    while time.time() < end:
        if reporter.should_stop():
            return
        time.sleep(min(1.0, end - time.time()))


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Walmart order status bot")
    parser.add_argument("--limit", type=int, default=None,
                        help="process only N rows (for testing)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print results, do NOT write to the sheet")
    parser.add_argument("--tab", type=str, default=None,
                        help="override the tab name")
    parser.add_argument("--inspect", action="store_true",
                        help="open the Walmart page so you can inspect selectors")
    parser.add_argument("--test-order", nargs=2, metavar=("ORDER", "EMAIL"),
                        help="look up ONE order (no Google Sheet needed) and print status")
    args = parser.parse_args()

    setup_logging()

    if args.inspect:
        inspect_page()
        return

    if args.test_order:
        test_single_order(args.test_order[0], args.test_order[1])
        return

    overrides = {}
    if args.limit is not None:
        overrides["LIMIT"] = args.limit
    if args.dry_run:
        overrides["DRY_RUN"] = True
    if args.tab:
        overrides["TAB_NAME"] = args.tab

    try:
        run_bot(overrides)
    except KeyboardInterrupt:
        logging.warning("Interrupted by user.")


if __name__ == "__main__":
    main()
