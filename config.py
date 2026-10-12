# ---------------------------------------------------------------------------
# config.py  --  ALL settings and selectors live here.
#
# If Walmart changes their page, you only need to edit the SELECTORS section
# at the bottom of this file. Everything else is normal settings.
# ---------------------------------------------------------------------------

# ===== GOOGLE SHEET =========================================================
# You can paste either the plain ID or a full Google Sheets URL; the GUI and
# bot both know how to pull the ID out of a URL.
SPREADSHEET_ID = "1Rz5WgXMAGU6XCiG70O4Yf1kGZiMECa9clCvOzpY1oSI"

TAB_NAME = "Sheet1"      # the worksheet / tab name (your sheet's tab is "Sheet1")

# First row that contains real data (1-based). Your sheet has a header row
# ("email | order no | status") in row 1, so HEADER_ROWS = 1 -> data starts row 2.
HEADER_ROWS = 1
FIRST_DATA_ROW = HEADER_ROWS + 1   # computed; usually leave this as is

# Which columns to use (letters, as they appear in the sheet).
# Matches your sheet:  A = email,  B = order no,  C = status.
EMAIL_COL = "A"      # customer email
ORDERS_COL = "B"     # one or two Walmart order numbers (newline separated)
STATUS_COL = "C"     # bot writes the status here
TRACKING_COL = ""    # disabled (Walmart rarely shows a tracking #, so we skip it).
# Set TRACKING_COL = "D" if you ever want harvested tracking numbers in column D.

# Column where the bot writes the "last checked" date+time. Set "" to disable.
CHECKED_COL = "D"

# Skip a row if its status was checked within this many hours (0 = never skip).
# Great for repeat runs so you don't re-check the same orders constantly.
SKIP_IF_CHECKED_WITHIN_HOURS = 0

# Color the status cell by result (green/blue/amber/red). Set False to disable.
COLOR_CELLS = True

# Play a short "done" chime when a run finishes.
DONE_CHIME = True

# Optional: a Discord/Slack-style webhook URL. If set, the bot POSTs a summary
# of status CHANGES at the end of each run. Leave blank to disable.
NOTIFY_WEBHOOK_URL = ""

# Path to the Google service-account key file (keep it in this folder).
SERVICE_ACCOUNT_FILE = "service_account.json"


# ===== RUN BEHAVIOUR ========================================================
# Delay between individual order lookups (seconds). Set LOW for speed.
# (If Walmart starts captcha-ing every lookup, raise these a bit.)
MIN_DELAY = 1
MAX_DELAY = 3

# After this many lookups, take a short breather.
LONG_PAUSE_EVERY = 40
LONG_PAUSE_MIN = 8
LONG_PAUSE_MAX = 15

# Safety cap on how many sheet rows to process in one run (0 = no cap).
# The --limit command-line flag / GUI field overrides this.
MAX_ROWS_PER_RUN = 0

# If True, print what WOULD be written but do not touch the sheet.
DRY_RUN = False


# ===== CAPTCHA-FREE REFRESH (carrier tracking) ==============================
# Once an order has shipped, Walmart shows a carrier tracking number. The bot
# harvests it into TRACKING_COL. On later runs, orders that already have a
# tracking number can be refreshed straight from the carrier via AfterShip --
# NO browser, NO captcha. Get a free key at https://www.aftership.com/ (free
# tier). Leave blank to skip the carrier phase and only harvest tracking #s.
AFTERSHIP_API_KEY = ""

# Carriers Walmart uses. Names here are matched against the order page text.
# "Walmart" / "GoLocal" deliveries have NO public carrier -> always via Walmart.
CARRIER_NAMES = ["FedEx", "UPS", "USPS", "LaserShip", "OnTrac", "DHL",
                 "GoLocal", "Walmart"]

# Visit this first each run to warm up a human-looking session (fewer captchas).
WARMUP_URL = "https://www.walmart.com/"


# ===== BROWSER ==============================================================
# Walmart blocks bots, so we run a VISIBLE window.
HEADLESS = False

# Open a FRESH TAB for each order lookup and close it after (instead of reusing
# one tab). Can reduce how often the bot-check fires. Set False to reuse one tab.
NEW_TAB_PER_ORDER = True

# When a captcha appears, beep repeatedly until you solve it (so you don't have
# to watch the screen). Set False to stay silent.
SOUND_ALERT = True
SOUND_INTERVAL = 2.0   # seconds between beeps

# Persistent profile folder keeps cookies/sessions between runs so you do not
# have to pass bot-checks every single time. This folder is git-ignored.
USER_DATA_DIR = "browser_profile"

# Walmart (PerimeterX) fingerprints automated browsers and then refuses to let
# the "press & hold" check pass. These options make the browser look like a
# normal human Chrome, which usually lets the check succeed.
USE_REAL_CHROME = True   # use your installed Google Chrome instead of bundled Chromium

# How long (ms) to wait for pages / elements before giving up.
PAGE_TIMEOUT_MS = 45000
ELEMENT_TIMEOUT_MS = 15000


# ===== LOGGING ==============================================================
LOG_FILE = "bot.log"


# ===========================================================================
# ===== SELECTORS  (the only part you edit if Walmart changes the page) =====
# ===========================================================================
#
# The guest "Track your order" page (confirmed working): email + order number
# + "View order status", no login required.
#   -> https://www.walmart.com/orders  shows the guest form.
#   (Do NOT use /orders/track -- that one redirects to the sign-in page.)
TRACK_ORDER_URL = "https://www.walmart.com/orders"

# Each selector is a LIST of candidate "locator strings" tried in order; the
# first one that is visible on the page wins. This makes selectors resilient.
#
# Supported prefixes (prefer label/role/placeholder/text over css):
#   label=<text>        -> matches a form field by its visible <label>
#   placeholder=<text>  -> matches an input by its placeholder text
#   role=<role>|<name>  -> e.g.  role=button|Track order
#   text=<text>         -> any element containing this text
#   testid=<id>         -> element with data-testid / data-automation-id
#   css=<css selector>  -> raw CSS as a last resort
#
# Text matching is case-insensitive and partial by default.

SELECTORS = {
    # The order-number input box.  (Form label on walmart.com/orders: "Order number")
    "order_number_input": [
        "label=Order number",
        "placeholder=Order number",
        "placeholder=order number",
        "testid=order-number",
        "css=input[name='orderId']",
        "css=input[id*='order' i]",
    ],

    # The email input box.  (Form label on walmart.com/orders: "Email address")
    "email_input": [
        "label=Email address",
        "label=Email",
        "placeholder=Email address",
        "placeholder=Email",
        "testid=email",
        "css=input[type='email']",
        "css=input[name='email']",
    ],

    # The submit button.  (Button text on walmart.com/orders: "View order status")
    "submit_button": [
        "role=button|View order status",
        "text=View order status",
        "role=button|Track order",
        "role=button|Continue",
        "css=button[type='submit']",
    ],

    # The element(s) that contain the status text once results load.
    # The bot reads text from the first match AND also scans the whole page
    # as a fallback, so a loose selector here is fine.
    "status_text": [
        "testid=order-status",
        "testid=shipment-status",
        "css=[class*='status' i]",
        "css=[data-testid*='status' i]",
    ],
}

# Phrases that mean Walmart could not find the order.
NOT_FOUND_PHRASES = [
    "we can't find",
    "we couldn't find",
    "couldn't find that order",
    "couldn't locate",
    "no order found",
    "unable to find",
    "double-check",
    "doesn't match",
]

# Phrases that mean Walmart wants an extra verification step automation
# cannot complete (e.g. it emails you a link instead of showing status).
NEEDS_HUMAN_PHRASES = [
    "we've sent you an email",
    "we sent you an email",
    "check your email",
    "verification code",
    "enter the code",
    "verify your phone",
    "text message",
]

# Phrases that mean a captcha / bot-check wall is showing.
# (Verified against Walmart's real block page: title "Robot or human?",
#  body "Activate and hold the button to confirm that you're human".)
CAPTCHA_PHRASES = [
    "verify you are human",
    "are you a robot",
    "robot or human",
    "activate and hold",
    "press & hold",
    "press and hold",
    "confirm that you're human",
    "confirm that you are human",
    "access denied",
    "activity has been blocked",
    "unusual activity",
    "captcha",
]

# If the URL contains any of these, we're on a bot-block page.
CAPTCHA_URL_MARKERS = ["/blocked"]

# How to turn page text into a clean status. Order matters: the FIRST keyword
# found (searched top to bottom) wins, so put the most specific first.
STATUS_KEYWORDS = [
    ("out for delivery", "Out for delivery"),
    ("delivered", "Delivered"),
    ("dropped off", "Delivered"),
    ("arrived", "Delivered"),
    ("ready for pickup", "Ready for pickup"),
    ("picked up", "Picked up"),
    ("shipped", "Shipped"),
    ("on its way", "Shipped"),
    ("on the way", "Shipped"),
    ("arriving", "Shipped"),
    ("out the door", "Shipped"),
    ("delayed", "Delayed"),
    ("preparing", "Processing"),
    ("being prepared", "Processing"),
    ("processing", "Processing"),
    ("order received", "Processing"),
    ("order confirmed", "Processing"),
    ("in progress", "Processing"),
    ("cancelled", "Cancelled"),    # NOT "cancell" -> avoids the "Request cancellation" button
    ("canceled", "Cancelled"),
    ("refund", "Refunded"),
    ("returned", "Returned"),
]
