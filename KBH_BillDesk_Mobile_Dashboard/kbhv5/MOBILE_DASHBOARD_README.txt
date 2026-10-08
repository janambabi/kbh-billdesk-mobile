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
