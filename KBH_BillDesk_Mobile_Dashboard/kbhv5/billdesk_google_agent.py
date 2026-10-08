
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BILLDESK_URL = "https://payments.billdesk.com/bdcollect/pay?p1=6634&p2=15"
API_URL = "https://script.google.com/macros/s/AKfycbwaRv7MJoPudhwA3c71hSqlOwUjFu-8_Ssn43fuAMWnIcD1TfGYqmPf1fNb1Z_HCPmQ/exec"
TOKEN = "KBH_BILLDESK_2026"

WORKERS = int(os.getenv("KBH_WORKERS", "40"))
# Keep Playwright browsers inside the deployed application so the Render build
# browser cache is available to the runtime process as well.
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
RETRIES = int(os.getenv("KBH_RETRIES", "6"))
PAGE_TIMEOUT = int(os.getenv("KBH_PAGE_TIMEOUT", "35000"))
HEADLESS = os.getenv("KBH_HEADLESS", "true").lower() in {"1", "true", "yes", "y"}
DEBUG = Path(__file__).parent / "debug"
DEBUG.mkdir(exist_ok=True)

def _decode_api_response(raw, operation):
    text = raw.decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise RuntimeError(f"Google Apps Script returned an empty response during {operation}.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        preview = text[:500].replace("\\n", " ")
        raise RuntimeError(
            f"Google Apps Script did not return JSON during {operation}. "
            f"Response starts with: {preview!r}"
        ) from e

def api_get(params, retries=4):
    q = urlencode(params)
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(
                API_URL + "?" + q,
                headers={"User-Agent": "KBH-BillDesk-Auto/2.0"}
            )
            with urlopen(req, timeout=30) as r:
                return _decode_api_response(r.read(), f"GET {params.get('action','')}")
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(attempt * 1.5)
    raise last

def api_post(payload, retries=4):
    body = json.dumps(payload).encode("utf-8")
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(
                API_URL,
                data=body,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "User-Agent": "KBH-BillDesk-Auto/2.0",
                },
                method="POST",
            )
            with urlopen(req, timeout=30) as r:
                return _decode_api_response(r.read(), "POST")
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(attempt * 1.5)
    raise last

def get_months():
    r = api_get({"action": "months"})
    if not r.get("ok") and r.get("status") != "ok":
        raise RuntimeError(r.get("error") or r.get("message") or "Could not read Google Sheet months")
    months = r.get("months")
    if not isinstance(months, list) or not months:
        raise RuntimeError(
            "Google Apps Script returned no months. This usually means the latest Code.gs "
            "was not redeployed. Open the /exec URL with ?action=months and confirm it returns "
            "{\"ok\":true,\"months\":[...]} before running the agent."
        )
    return [str(m).strip() for m in months if str(m).strip()]

def get_students(month):
    r = api_get({"action": "students", "month": month, "token": TOKEN})
    if not r.get("ok") and r.get("status") != "ok":
        raise RuntimeError(r.get("error") or r.get("message") or "Could not read students")
    return r.get("students", [])

def choose_month(months):
    print("\n============================================================")
    print("GOOGLE SHEET MONTHS")
    print("============================================================")
    for i, m in enumerate(months, 1):
        print(f"{i:2}. {m}")
    while True:
        try:
            n = int(input("\nEnter month number: ").strip())
            if 1 <= n <= len(months):
                return months[n - 1]
        except ValueError:
            pass
        print("Invalid choice.")

def choose_run_mode():
    print("\nRun mode:")
    print("1. Process all students")
    print("2. Retry ONLY students marked ERROR")
    print("3. Run ONLY students marked NOT PAID")
    while True:
        choice = input("Enter choice (1/2/3): ").strip()
        if choice in {"1", "2", "3"}:
            return choice
        print("Invalid choice. Enter 1 or 2.")

def normalize_text(s):
    return re.sub(r"\s+", " ", s or "").strip()

def parse_payments(text):
    """
    Parse every visible SUCCESSFUL card. The BillDesk cards normally contain:
    SUCCESSFUL -> amount -> YYYY-MM-DD HH:MM:SS -> Transaction Id -> Payment Ref No.
    We deliberately keep a generous window so slow/expanded cards are still matched.
    """
    lines = [normalize_text(x) for x in text.splitlines() if normalize_text(x)]
    results = []

    for i, line in enumerate(lines):
        if "SUCCESSFUL" not in line.upper():
            continue

        block = " ".join(lines[i:i + 24])

        date_m = re.search(
            r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\s+\d{1,2}:\d{2}:\d{2}",
            block,
            re.I,
        )
        ref_m = re.search(
            r"Payment\s*Ref\s*No\s*:?\s*([A-Za-z0-9]+)",
            block,
            re.I,
        )
        amount_m = re.search(
            r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d{1,2})?)",
            block,
            re.I,
        )

        if date_m and ref_m:
            amount = None
            if amount_m:
                amount = float(amount_m.group(1).replace(",", ""))

            date_s = (
                f"{date_m.group(1)}-"
                f"{int(date_m.group(2)):02d}-"
                f"{int(date_m.group(3)):02d}"
            )
            results.append((date_s, ref_m.group(1), amount))

    unique = []
    seen = set()
    for x in results:
        if x not in seen:
            seen.add(x)
            unique.append(x)
    return unique

async def visible_first(locator):
    try:
        count = await locator.count()
        for i in range(count):
            el = locator.nth(i)
            if await el.is_visible():
                return el
    except Exception:
        pass
    return None

async def find_admission_input(page):
    selectors = [
        'input[placeholder*="Admission" i]',
        'input[name*="admission" i]',
        'input[id*="admission" i]',
        'input[type="text"]',
    ]
    for selector in selectors:
        el = await visible_first(page.locator(selector))
        if el:
            return el
    return None

async def find_submit(page):
    candidates = [
        page.get_by_role("button", name=re.compile(r"^\s*submit\s*$", re.I)),
        page.locator('input[type="submit"]'),
        page.locator("button").filter(has_text=re.compile(r"^\s*submit\s*$", re.I)),
        page.locator("button").filter(has_text=re.compile(r"submit", re.I)),
    ]
    for loc in candidates:
        el = await visible_first(loc)
        if el:
            return el
    return None

async def find_past_payments(page):
    candidates = [
        page.get_by_text("Past Payments", exact=True),
        page.locator('a').filter(has_text=re.compile(r"^\s*Past\s*Payments\s*$", re.I)),
        page.locator('button').filter(has_text=re.compile(r"^\s*Past\s*Payments\s*$", re.I)),
        page.locator('[role="tab"]').filter(has_text=re.compile(r"Past\s*Payments", re.I)),
        page.locator('[role="button"]').filter(has_text=re.compile(r"Past\s*Payments", re.I)),
        page.locator("text=Past Payments"),
    ]
    for loc in candidates:
        el = await visible_first(loc)
        if el:
            return el

    # Broad fallback: inspect visible links/buttons/tabs and use JS click if needed.
    loc = page.locator("a,button,[role=tab],[role=button]")
    try:
        for i in range(await loc.count()):
            el = loc.nth(i)
            if not await el.is_visible():
                continue
            t = normalize_text(await el.inner_text())
            if "past" in t.lower() and "payment" in t.lower():
                return el
    except Exception:
        pass
    return None

async def click_past_payments(page):
    past = await find_past_payments(page)
    if not past:
        raise RuntimeError("Past Payments tab not found")

    try:
        await past.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass

    # Try normal click first.
    try:
        await past.click(timeout=7000)
    except Exception:
        # The site can use a JS tab handler on a parent element.
        try:
            await past.evaluate("(el) => el.click()")
        except Exception:
            try:
                await past.click(force=True, timeout=5000)
            except Exception as e:
                raise RuntimeError(f"Past Payments could not be opened: {e}")

async def wait_for_student_details(page, roll):
    deadline = time.monotonic() + 35
    last_text = ""
    while time.monotonic() < deadline:
        try:
            text = await page.locator("body").inner_text(timeout=3000)
        except Exception:
            text = ""
        last_text = text

        # The page in the screenshot shows Verify Student details + Admission No.
        if (
            re.search(r"Verify\s+Student\s+details", text, re.I)
            and roll.upper() in text.upper()
        ):
            await page.wait_for_timeout(1000)
            # One extra check prevents reading the page during a partial render.
            text2 = await page.locator("body").inner_text(timeout=3000)
            if roll.upper() in text2.upper():
                return

        await page.wait_for_timeout(500)

    raise RuntimeError("Student details did not load after Submit")

async def wait_for_payment_history(page):
    """
    Wait for the history to actually render. We don't parse the page immediately
    after clicking the tab. We require the body text to stop changing and either
    find a payment card or an explicit empty-history message.
    """
    deadline = time.monotonic() + 40
    stable = 0
    previous_signature = None
    best_text = ""

    while time.monotonic() < deadline:
        try:
            text = await page.locator("body").inner_text(timeout=4000)
        except Exception:
            text = ""

        best_text = text
        low = text.lower()

        payments = parse_payments(text)
        empty_history = any(
            phrase in low
            for phrase in [
                "no payment history",
                "no payments found",
                "no records found",
                "no record found",
                "no past payments",
            ]
        )

        signature = (len(text), len(payments), text[-500:])
        if signature == previous_signature:
            stable += 1
        else:
            stable = 0
            previous_signature = signature

        # At least 2 seconds of unchanged content after a payment is visible.
        if payments and stable >= 2:
            return text

        if empty_history and stable >= 2:
            return text

        await page.wait_for_timeout(1000)

    # One final wait + read before declaring failure.
    await page.wait_for_timeout(2500)
    try:
        best_text = await page.locator("body").inner_text(timeout=5000)
    except Exception:
        pass

    if parse_payments(best_text):
        return best_text

    raise RuntimeError("Past Payments opened but payment history did not finish loading")

async def block_heavy_resources(route):
    if route.request.resource_type in {"image", "font", "media"}:
        await route.abort()
    else:
        await route.continue_()

async def one_attempt(browser, roll, month, index, total, attempt):
    page = await browser.new_page()
    try:
        page.set_default_timeout(10000)
        await page.route("**/*", block_heavy_resources)

        await page.goto(
            BILLDESK_URL,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT,
        )

        inp = await find_admission_input(page)
        if not inp:
            raise RuntimeError("Admission input not found")

        await inp.fill(roll)

        submit = await find_submit(page)
        if not submit:
            raise RuntimeError("Submit button not found")

        await submit.click()
        await wait_for_student_details(page, roll)

        # Important: wait for the complete student view before clicking Past Payments.
        await page.wait_for_timeout(1200)

        await click_past_payments(page)

        # Important: give the Past Payments screen time to populate.
        text = await wait_for_payment_history(page)
        payments = parse_payments(text)

        target = datetime.strptime(month, "%B %Y")
        matches = []
        for payment in payments:
            d = datetime.strptime(payment[0], "%Y-%m-%d")
            if d.year == target.year and d.month == target.month:
                matches.append(payment)

        if matches:
            # If there are multiple successful payments in a month, use the latest.
            date_s, ref, amount = sorted(matches, key=lambda x: x[0])[-1]
            return ("PAID", ref, date_s, amount, "")

        return ("NOT PAID", "", "", None, "")

    except Exception as e:
        # Screenshots are expensive. Save one only on the final failed attempt.
        if attempt >= RETRIES:
            try:
                await page.screenshot(
                    path=str(DEBUG / f"{roll}_attempt_{attempt}.png"),
                    full_page=False,
                )
            except Exception:
                pass
        raise
    finally:
        await page.close()

async def process_student(browser, student, month, index, total, update_lock, progress_callback=None):
    roll = student["rollNo"]

    if progress_callback:
        try:
            progress_callback({"event":"checking", "index":index, "total":total, "rollNo":roll})
        except Exception:
            pass

    # If already marked PAID in Google Sheet, don't waste another BillDesk request.
    existing = str(student.get("status", "")).strip().upper()
    if existing == "PAID":
        print(f"[{index}/{total}] {roll} -> ALREADY PAID (Google Sheet)")
        if progress_callback:
            try: progress_callback({"event":"result", "index":index, "total":total, "rollNo":roll, "status":"ALREADY", "amount":student.get("amount", "")})
            except Exception: pass
        return "ALREADY", None

    last_error = ""
    for attempt in range(1, RETRIES + 1):
        try:
            result = await one_attempt(
                browser, roll, month, index, total, attempt
            )
            status, ref, date_s, amount, error = result

            payload = {
                "token": TOKEN,
                "month": month,
                "rollNo": roll,
                "status": status,
            }
            if status == "PAID":
                payload.update({
                    "paymentRef": ref,
                    "paymentDate": date_s,
                    "amount": amount if amount is not None else "",
                })

            # Google Apps Script can receive several updates simultaneously, but
            # a small lock prevents bursts from overwhelming the endpoint.
            async with update_lock:
                try:
                    api_result = await asyncio.to_thread(api_post, payload)
                    if not api_result.get("ok"):
                        raise RuntimeError(api_result.get("error", "Google Sheet update failed"))
                except Exception as e:
                    print(f"[{index}/{total}] {roll} -> SHEET UPDATE ERROR: {e}")
                    # Retry the Sheet update separately.
                    sheet_ok = False
                    for _ in range(3):
                        try:
                            api_result = await asyncio.to_thread(api_post, payload)
                            if api_result.get("ok"):
                                sheet_ok = True
                                break
                        except Exception:
                            await asyncio.sleep(1)
                    if not sheet_ok:
                        raise RuntimeError("Google Sheet update failed after retries")

            if status == "PAID":
                amount_text = f"₹{amount:g}" if isinstance(amount, (int, float)) else "₹N/A"
                print(
                    f"[{index}/{total}] {roll} -> PAID {date_s} "
                    f"{amount_text} {ref}"
                )
                if progress_callback:
                    try: progress_callback({"event":"result", "index":index, "total":total, "rollNo":roll, "status":"PAID", "amount":amount, "paymentDate":date_s, "paymentRef":ref})
                    except Exception: pass
                return "PAID", None

            print(f"[{index}/{total}] {roll} -> NOT PAID FOR {month}")
            if progress_callback:
                try: progress_callback({"event":"result", "index":index, "total":total, "rollNo":roll, "status":"NOT PAID", "amount":student.get("amount", "")})
                except Exception: pass
            return "NOT PAID", None

        except Exception as e:
            last_error = str(e)
            print(
                f"[{index}/{total}] {roll} -> ATTEMPT {attempt}/{RETRIES} "
                f"ERROR: {last_error}"
            )
            if attempt < RETRIES:
                # Short backoff. A new page is created on the next attempt.
                await asyncio.sleep(min(15, 2.0 * attempt))

    # Final error goes to Google Sheet so it can be retried later.
    payload = {
        "token": TOKEN,
        "month": month,
        "rollNo": roll,
        "status": "ERROR",
        "error": last_error,
    }
    try:
        async with update_lock:
            await asyncio.to_thread(api_post, payload)
    except Exception:
        pass

    if progress_callback:
        try: progress_callback({"event":"result", "index":index, "total":total, "rollNo":roll, "status":"ERROR", "error":last_error})
        except Exception: pass
    return "ERROR", last_error

async def run_update(month, mode="3", progress_callback=None):
    """Run an automatic BillDesk update for the selected month.

    mode:
      1 = all students
      2 = ERROR only
      3 = NOT PAID only
    Returns a summary dict for the web dashboard.
    """
    all_students = get_students(month)
    if mode == "2":
        students = [
            s for s in all_students
            if str(s.get("status", "")).strip().upper() == "ERROR"
        ]
    elif mode == "3":
        students = [
            s for s in all_students
            if str(s.get("status", "")).strip().upper()
            in {"NOT PAID", "NOT_PAID", "NOTPAID"}
        ]
    else:
        students = all_students

    print("\nSelected:", month)
    run_mode_label = {
        "1": "ALL STUDENTS",
        "2": "RETRY ERRORS ONLY",
        "3": "NOT PAID ONLY",
    }.get(mode, "NOT PAID ONLY")
    print("Run mode:", run_mode_label)
    print("Students to process:", len(students))
    if progress_callback:
        try: progress_callback({"event":"started", "month":month, "total":len(students)})
        except Exception: pass
    print("Workers:", WORKERS)
    print("Headless browser:", HEADLESS)
    print("Retries per student:", RETRIES)
    print("Destination: Google Sheet")
    print("\nStarting automatic update...\n")

    counts = {"PAID": 0, "ALREADY": 0, "NOT PAID": 0, "ERROR": 0}
    if not students:
        print("No students found for this run.")
        return counts

    semaphore = asyncio.Semaphore(WORKERS)
    update_lock = asyncio.Semaphore(12)

    async with async_playwright() as p:
        # With PLAYWRIGHT_BROWSERS_PATH=0, Chromium is installed alongside the
        # Playwright package during the Render build and is available at runtime.
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--no-sandbox",
            ],
        )

        async def worker(student, index):
            async with semaphore:
                return await process_student(
                    browser, student, month, index, len(students), update_lock, progress_callback
                )

        tasks = [
            worker(student, i)
            for i, student in enumerate(students, 1)
        ]
        results = await asyncio.gather(*tasks)

        for status, _ in results:
            counts[status] = counts.get(status, 0) + 1

        print("\n" + "=" * 55)
        print("COMPLETED")
        print("=" * 55)
        print("Paid:", counts["PAID"])
        print("Already paid:", counts["ALREADY"])
        print("Not paid:", counts["NOT PAID"])
        print("Errors after retries:", counts["ERROR"])
        print("Google Sheet: UPDATED")
        if progress_callback:
            try: progress_callback({"event":"completed", "month":month, "total":len(students), "counts":counts})
            except Exception: pass
        print("=" * 55)

        await browser.close()

    return counts


async def main_async():
    months = get_months()
    month = choose_month(months)
    mode = choose_run_mode()
    await run_update(month, mode)

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as e:
        print("\nFATAL ERROR:", repr(e))
        input("\nPress Enter to close...")

if __name__ == "__main__":
    main()
