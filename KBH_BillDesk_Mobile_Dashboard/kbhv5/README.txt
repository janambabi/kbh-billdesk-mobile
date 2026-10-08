KBH BILLDESK GOOGLE SHEET AUTO AGENT V5 - RETRY/RESUME FIX

This version updates the Google Sheet directly and is designed for unstable BillDesk loading.

KEY FIXES
- Default workers reduced to 10 to reduce BillDesk throttling.
- 6 attempts per student with increasing backoff.
- Safe handling of missing payment amount (prints ₹N/A instead of crashing).
- If BillDesk fails, a fresh browser page is used on the next attempt.
- Adds a run mode: process ALL students OR RETRY ONLY students marked ERROR.
- Google Sheet is updated after each completed student.
- No Excel output is created.

SETUP
1. Keep your deployed Apps Script /exec URL in the Python file.
2. Replace your current billdesk_google_agent.py with this one.
3. Run START_GOOGLE_AGENT.bat.
4. Select the month number.
5. Choose:
   1 = Process all students
   2 = Retry ONLY ERROR students

RECOMMENDED WORKFLOW
First run: choose 1.
If the run finishes with errors, run again and choose 2. It will process only rows whose current status is ERROR.

IMPORTANT
If the Google Sheet shows NOT PAID, that is not treated as an error and is not retried in mode 2.
If you want to re-check NOT PAID students, use mode 1.

OPTIONAL ENVIRONMENT SETTINGS
KBH_WORKERS=10
KBH_RETRIES=6
KBH_PAGE_TIMEOUT=45000

The stable Apps Script URL is the /exec URL, not the googleusercontent /macros/echo redirect URL.


V7 SPEED SETTINGS
- Default workers: 40
- Default browser: headless (faster; no 40 visible windows)
- Google Sheet update concurrency: 12
- Screenshots only on final failed attempt
- Override workers: set KBH_WORKERS=20 or 10 if BillDesk starts throttling
- Override visible browser: set KBH_HEADLESS=false
