KBH BILLDESK MOBILE DASHBOARD
=============================

This adds a phone-friendly web dashboard to the existing BillDesk Python agent.
It uses the existing Google Apps Script Code.gs as the data API and keeps the Google Sheet as the source of truth.

QUICK START (Windows)
1. Double-click START_MOBILE_DASHBOARD.bat
2. Open http://127.0.0.1:5000 in the browser.
3. Select a month.
4. Search a Roll No / Admission No.
5. Tap Edit, update payment details, and Save Update.

For phone access on the same Wi-Fi, find this computer's local IP (for example 192.168.1.20) and open:
http://192.168.1.20:5000

IMPORTANT FOR DEPLOYMENT
Set these environment variables on the server instead of putting secrets in frontend code:
KBH_API_URL = your deployed Google Apps Script /exec URL
KBH_API_TOKEN = your Google Apps Script token
PORT = 5000 (optional)

The browser never receives the Google Apps Script token; Flask keeps it server-side.
The existing billdesk_google_agent.py and Code.gs are preserved.


AUTOMATIC "UPDATE NOT PAID STUDENTS"
====================================
The mobile dashboard now includes an "Update NOT PAID Students" button with live progress and terminal-style results.

Workflow:
1. Select the month.
2. Tap "Update NOT PAID Students".
3. The server reads students currently marked NOT PAID.
4. It checks BillDesk for each student using the existing Playwright agent.
5. Successful payments are written back to the Google Sheet as PAID with date, amount and reference.
6. Students with no matching successful payment remain NOT PAID.
7. Failed checks are marked ERROR and can be retried later.

RENDER REQUIREMENT
==================
Because the automatic update uses Playwright/Chromium, use:

Build Command:
pip install -r requirements.txt

Start Command:
PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install chromium && PLAYWRIGHT_BROWSERS_PATH=0 gunicorn web_app:app

Recommended Render environment variables:
KBH_API_URL = your deployed Google Apps Script /exec URL
KBH_API_TOKEN = your Google Apps Script token
KBH_WORKERS = 40
KBH_RETRIES = 6
KBH_HEADLESS = true

Do not use --with-deps on Render.

Keep the Root Directory blank when web_app.py and requirements.txt are in the repository root.
