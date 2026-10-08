import os, json, asyncio, threading, time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from flask import Flask, jsonify, request, render_template
from billdesk_google_agent import run_update

API_URL = os.getenv('KBH_API_URL', 'https://script.google.com/macros/s/AKfycbwaRv7MJoPudhwA3c71hSqlOwUjFu-8_Ssn43fuAMWnIcD1TfGYqmPf1fNb1Z_HCPmQ/exec')
TOKEN = os.getenv('KBH_API_TOKEN', 'KBH_BILLDESK_2026')
PORT = int(os.getenv('PORT', '5000'))
JOB_STALE_SECONDS = int(os.getenv('KBH_JOB_STALE_SECONDS', '1200'))

app = Flask(__name__)
JOB_LOCK = threading.Lock()
JOB = {
    'running': False,
    'month': '',
    'mode': '',
    'startedAt': None,
    'finishedAt': None,
    'heartbeatAt': None,
    'total': 0,
    'processed': 0,
    'current': '',
    'counts': {'PAID': 0, 'ALREADY': 0, 'NOT PAID': 0, 'ERROR': 0},
    'results': [],
    'error': '',
}


def api_get(params):
    req = Request(API_URL + '?' + urlencode(params), headers={'User-Agent': 'KBH-BillDesk-Web/2.0'})
    with urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8-sig'))


def api_post(payload):
    body = json.dumps(payload).encode('utf-8')
    req = Request(API_URL, data=body, headers={'Content-Type': 'application/json', 'User-Agent': 'KBH-BillDesk-Web/2.0'}, method='POST')
    with urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8-sig'))


def _progress(event):
    now = time.time()
    with JOB_LOCK:
        JOB['heartbeatAt'] = now
        kind = event.get('event')
        if kind == 'started':
            JOB['total'] = int(event.get('total', 0))
            JOB['processed'] = 0
            JOB['current'] = ''
        elif kind == 'checking':
            JOB['current'] = str(event.get('rollNo', ''))
        elif kind == 'result':
            JOB['processed'] = max(JOB['processed'], int(event.get('index', 0)))
            JOB['current'] = str(event.get('rollNo', ''))
            status = str(event.get('status', 'ERROR')).upper()
            if status == 'PAID':
                JOB['counts']['PAID'] += 1
            elif status == 'NOT PAID':
                JOB['counts']['NOT PAID'] += 1
            elif status == 'ALREADY':
                JOB['counts']['ALREADY'] += 1
            else:
                JOB['counts']['ERROR'] += 1
            item = {
                'rollNo': event.get('rollNo', ''),
                'status': status,
                'amount': event.get('amount', ''),
                'paymentDate': event.get('paymentDate', ''),
                'paymentRef': event.get('paymentRef', ''),
                'error': event.get('error', ''),
            }
            JOB['results'].insert(0, item)
            JOB['results'] = JOB['results'][:40]
        elif kind == 'completed':
            JOB['heartbeatAt'] = now


def _run_nonpaid_job(month):
    try:
        counts = asyncio.run(run_update(month, '3', progress_callback=_progress))
        with JOB_LOCK:
            # Use the agent's final counts as the authoritative totals.
            JOB['counts'] = counts
            JOB['running'] = False
            JOB['finishedAt'] = time.time()
            JOB['heartbeatAt'] = JOB['finishedAt']
            JOB['current'] = ''
            JOB['error'] = ''
    except Exception as exc:
        with JOB_LOCK:
            JOB['running'] = False
            JOB['finishedAt'] = time.time()
            JOB['heartbeatAt'] = JOB['finishedAt']
            JOB['error'] = str(exc)


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
    month = (request.get_json(silent=True) or {}).get('month', '').strip()
    if not month:
        return jsonify(ok=False, error='Month is required'), 400

    # Read the selected sheet before starting so the UI can immediately show 128/128,
    # 50/50, etc. and so the job is guaranteed to use the selected month.
    try:
        sheet_data = api_get({'action': 'students', 'month': month, 'token': TOKEN})
        if not sheet_data.get('ok'):
            return jsonify(ok=False, error=sheet_data.get('error', 'Could not read selected Google Sheet')), 502
        selected = sheet_data.get('students', []) or []
        targets = [s for s in selected if str(s.get('status', '')).strip().upper() in {'NOT PAID', 'NOT_PAID', 'NOTPAID'}]
    except Exception as e:
        return jsonify(ok=False, error=f'Could not read {month}: {e}'), 502

    with JOB_LOCK:
        if JOB['running']:
            # If a real job is already running, don't start a duplicate BillDesk run.
            # Return its live state so the browser can simply attach to it.
            return jsonify(ok=False, error='An automatic update is already running', job=dict(JOB)), 409

        now = time.time()
        JOB.update({
            'running': True,
            'month': month,
            'mode': 'NOT PAID ONLY',
            'startedAt': now,
            'finishedAt': None,
            'heartbeatAt': now,
            'total': len(targets),
            'processed': 0,
            'current': '',
            'counts': {'PAID': 0, 'ALREADY': 0, 'NOT PAID': 0, 'ERROR': 0},
            'results': [],
            'error': ''
        })

    if not targets:
        with JOB_LOCK:
            JOB['running'] = False
            JOB['finishedAt'] = time.time()
            JOB['heartbeatAt'] = JOB['finishedAt']
        return jsonify(ok=True, message=f'No NOT PAID students found for {month}', job=dict(JOB))

    threading.Thread(target=_run_nonpaid_job, args=(month,), daemon=True, name='kbh-billdesk-update').start()
    return jsonify(ok=True, message=f'NOT PAID update started for {month}', job=dict(JOB))


@app.get('/api/update-nonpaid/status')
def update_nonpaid_status():
    with JOB_LOCK:
        snapshot = dict(JOB)
        heartbeat = JOB.get('heartbeatAt')
        snapshot['stale'] = bool(JOB['running'] and heartbeat and (time.time() - heartbeat > JOB_STALE_SECONDS))
        if snapshot['stale']:
            snapshot['staleSeconds'] = int(time.time() - heartbeat)
        return jsonify(ok=True, job=snapshot)


@app.post('/api/update-nonpaid/reset')
def reset_nonpaid():
    # This endpoint only clears a genuinely stale UI lock. It does NOT silently
    # create a second job while a healthy job is making progress.
    with JOB_LOCK:
        heartbeat = JOB.get('heartbeatAt')
        if not JOB['running']:
            return jsonify(ok=True, message='No running job', job=dict(JOB))
        if heartbeat and time.time() - heartbeat <= JOB_STALE_SECONDS:
            return jsonify(ok=False, error='Update is still active; wait for it to finish', job=dict(JOB)), 409
        JOB['running'] = False
        JOB['error'] = 'Previous update was reset because no progress was received for too long.'
        JOB['finishedAt'] = time.time()
        return jsonify(ok=True, message='Stale update lock cleared. Start a new update.', job=dict(JOB))


@app.get('/health')
def health():
    return jsonify(ok=True, app='KBH BillDesk Mobile Dashboard')


if __name__ == '__main__':
    print(f'KBH BillDesk Mobile Dashboard: http://127.0.0.1:{PORT}')
    app.run(host='0.0.0.0', port=PORT, debug=False)
