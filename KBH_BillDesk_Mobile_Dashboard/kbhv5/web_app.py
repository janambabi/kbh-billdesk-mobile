import os, json, asyncio, threading, time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from flask import Flask, jsonify, request, render_template
from billdesk_google_agent import run_update

BASE = os.path.dirname(os.path.abspath(__file__))
API_URL = os.getenv('KBH_API_URL', 'https://script.google.com/macros/s/AKfycbwaRv7MJoPudhwA3c71hSqlOwUjFu-8_Ssn43fuAMWnIcD1TfGYqmPf1fNb1Z_HCPmQ/exec')
TOKEN = os.getenv('KBH_API_TOKEN', 'KBH_BILLDESK_2026')
PORT = int(os.getenv('PORT', '5000'))

app = Flask(__name__)


# One background BillDesk run at a time. Render uses one web worker by default,
# so this in-memory state is sufficient for the mobile dashboard.
JOB_LOCK = threading.Lock()
JOB = {
    "running": False,
    "month": "",
    "mode": "",
    "startedAt": None,
    "finishedAt": None,
    "counts": {"PAID": 0, "ALREADY": 0, "NOT PAID": 0, "ERROR": 0},
    "error": "",
}


def _run_nonpaid_job(month):
    try:
        counts = asyncio.run(run_update(month, "3"))
        with JOB_LOCK:
            JOB["counts"] = counts
            JOB["running"] = False
            JOB["finishedAt"] = time.time()
            JOB["error"] = ""
    except Exception as exc:
        with JOB_LOCK:
            JOB["running"] = False
            JOB["finishedAt"] = time.time()
            JOB["error"] = str(exc)




def api_get(params):
    req = Request(API_URL + '?' + urlencode(params), headers={'User-Agent': 'KBH-BillDesk-Web/1.0'})
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8-sig'))


def api_post(payload):
    body = json.dumps(payload).encode('utf-8')
    req = Request(API_URL, data=body, headers={'Content-Type': 'application/json', 'User-Agent': 'KBH-BillDesk-Web/1.0'}, method='POST')
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8-sig'))


@app.get('/')
def index():
    return render_template('index.html')


@app.get('/api/months')
def months():
    try:
        return jsonify(api_get({'action': 'months'}))
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 502


@app.get('/api/students')
def students():
    month = request.args.get('month', '').strip()
    if not month:
        return jsonify(ok=False, error='Month is required'), 400
    try:
        return jsonify(api_get({'action': 'students', 'month': month, 'token': TOKEN}))
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 502


@app.post('/api/update')
def update():
    data = request.get_json(silent=True) or {}
    allowed = ['month','rollNo','status','paymentDate','amount','paymentRef','transactionId','retryCount','error']
    payload = {k: data.get(k, '') for k in allowed}
    payload.update(action='update', token=TOKEN)
    if not payload['month'] or not payload['rollNo']:
        return jsonify(ok=False, error='Month and Roll No are required'), 400
    try:
        return jsonify(api_post(payload))
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 502




@app.post('/api/update-nonpaid')
def update_nonpaid():
    month = (request.get_json(silent=True) or {}).get("month", "").strip()
    if not month:
        return jsonify(ok=False, error="Month is required"), 400

    with JOB_LOCK:
        if JOB["running"]:
            return jsonify(ok=False, error="An automatic update is already running", job=JOB), 409
        JOB["running"] = True
        JOB["month"] = month
        JOB["mode"] = "NOT PAID ONLY"
        JOB["startedAt"] = time.time()
        JOB["finishedAt"] = None
        JOB["counts"] = {"PAID": 0, "ALREADY": 0, "NOT PAID": 0, "ERROR": 0}
        JOB["error"] = ""

    threading.Thread(target=_run_nonpaid_job, args=(month,), daemon=True).start()
    return jsonify(ok=True, message="NOT PAID update started", job=JOB)


@app.get('/api/update-nonpaid/status')
def update_nonpaid_status():
    with JOB_LOCK:
        return jsonify(ok=True, job=dict(JOB))


@app.get('/health')
def health():
    return jsonify(ok=True, app='KBH BillDesk Mobile Dashboard')


if __name__ == '__main__':
    print(f'KBH BillDesk Mobile Dashboard: http://127.0.0.1:{PORT}')
    app.run(host='0.0.0.0', port=PORT, debug=False)
