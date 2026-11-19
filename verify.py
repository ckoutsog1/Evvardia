"""Run end-to-end HTTP and CSV checks with an isolated synthetic database."""
from concurrent.futures import ThreadPoolExecutor
import csv
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parent

with tempfile.TemporaryDirectory() as directory:
    args = [sys.executable, str(ROOT / 'server.py'), '--db', str(Path(directory) / 'test.sqlite3')]
    first = subprocess.check_output(args + ['add', 'TEST-001'], text=True).strip()
    second = subprocess.check_output(args + ['add', 'TEST-002'], text=True).strip()
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    with subprocess.Popen(args + ['serve','--port',str(port)], stdout=subprocess.PIPE, text=True, env={**os.environ, 'EVVARDIA_GUIDANCE_ENABLED':'0'}) as process:
        try:
            assert process.stdout.readline().strip() == f'http://127.0.0.1:{port}'

            def request(route, payload=None, cookie='', code='TEST-001'):
                http = HTTPConnection('127.0.0.1', port, timeout=5)
                headers = {'Origin':f'http://127.0.0.1:{port}','Content-Type':'application/json',
                           'Cookie':cookie,'X-Study-Participant':code}
                http.request('GET' if payload is None else 'POST', route,
                             None if payload is None else json.dumps(payload), headers)
                result = http.getresponse()
                data = result.read().decode()
                token = result.getheader('Set-Cookie','').split(';')[0]
                http.close()
                return result.status, data, token

            assert 'Ατομικός κωδικός πρόσβασης' in request('/')[1]
            checkin = {'id':str(uuid4()), 'type':'checkin', 'day':'2026-11-18'}
            assert request('/event', checkin)[0] == 401
            assert request('/login', {'access_code':'invalid'})[0] == 401
            cookie = request('/login', {'access_code':first})[2]
            other_cookie = request('/login', {'access_code':second})[2]
            page = request('/',cookie=cookie)[1]
            assert 'content="TEST-001"' in page
            assert 'guidance-form' not in page and '/guidance.js' not in page
            assert request('/guidance.js')[0] == 404
            assert request('/guidance',{'topic':'after_shift'},cookie)[0] == 404
            assert request('/event',checkin,other_cookie)[0] == 403
            with ThreadPoolExecutor(max_workers=2) as pool:
                runs = list(pool.map(lambda _: request('/event',checkin,cookie), range(2)))
            assert sorted(reply[0] for reply in runs) == [200,201]
            assert all(json.loads(reply[1])['type'] == 'checkin_submitted' for reply in runs)
            updated = {**checkin,'id':str(uuid4())}
            assert json.loads(request('/event',updated,cookie)[1])['type'] == 'checkin_updated'
            assert request('/event',{**checkin,'day':'2026-11-17'},cookie)[0] == 409
            assert request('/event',{**updated,'scores':[1,2,3]},cookie)[0] == 400
            assert request('/event',checkin,other_cookie,'TEST-002')[0] == 201
            for kind in ('voice_attempted','voice_confirmed','support_path_opened','technical_error'):
                payload = {'id':str(uuid4()),'type':kind}
                if kind == 'technical_error':
                    payload['error'] = 'voice_recognition'
                assert request('/event',payload,cookie)[0] == 201
            assert request('/logout',{},cookie)[0] == 200
            assert request('/event',updated,cookie)[0] == 401
            output = Path(directory) / 'events.csv'
            subprocess.run(args + ['export',str(output)],check=True)
            with output.open(encoding='utf-8-sig',newline='') as stream:
                rows = list(csv.DictReader(stream))
            assert len(rows) == 7
            assert sum(row['event_type']=='checkin_submitted' for row in rows) == 2
            assert sum(row['event_type']=='checkin_updated' for row in rows) == 1
            print('Passed HTTP authentication, participant isolation, concurrent retry, update, event validation, logout and CSV export.')
        finally:
            process.terminate()
