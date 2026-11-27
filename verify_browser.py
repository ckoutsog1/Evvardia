"""Synthetic browser workflow; requires Playwright and a Chromium installation."""
from pathlib import Path
import os
import socket
import subprocess
import sys
import tempfile
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as directory:
    args=[sys.executable,str(ROOT/'server.py'),'--db',str(Path(directory)/'browser.sqlite3')]
    secret=subprocess.check_output(args+['add','BROWSER-001','--center','A'],text=True).strip()
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    process=subprocess.Popen(args+['serve','--port',str(port)],stdout=subprocess.PIPE,text=True,
                             env={**os.environ,'EVVARDIA_GUIDANCE_ENABLED':'0'})
    try:
        assert process.stdout.readline().strip()==f'http://127.0.0.1:{port}'
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=os.environ.get('EVVARDIA_TEST_CHROMIUM'),args=['--no-sandbox'])
            page=browser.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{port}')
            page.locator('input').fill(secret);page.locator('button[type=submit]').click()
            page.wait_for_function("document.querySelector('#response-status')?.textContent.includes('ολοκληρώθηκε')")
            for name,value in [('exhaustion','3'),('sleep','4'),('load','2')]:
                page.locator(f'input[name={name}][value="{value}"]').check()
            page.locator('#checkin button[type=submit]').click()
            page.wait_for_function("document.querySelector('#status').textContent.includes('αποθηκεύτηκαν')")
            for i in range(23):page.locator(f'select[name="bat-{i}"]').select_option('2')
            page.locator('#persistent-bat button[type=submit]').click()
            page.wait_for_function("document.querySelector('#persistent-bat-status').textContent.includes('2.00')")
            page.reload();page.wait_for_function("document.querySelector('#response-status')?.textContent.includes('ολοκληρώθηκε')")
            assert page.locator('select[name="bat-0"]').input_value()=='2'
            assert '3/5' in page.locator('#history').inner_text()
            # Lost acknowledgement: commit succeeds, first browser response is aborted.
            def lose_ack(route):
                response=route.fetch(); assert response.status==201;route.abort()
            page.route('**/api/checkins',lose_ack,times=1)
            page.locator('input[name=exhaustion][value="5"]').check()
            page.locator('#checkin button[type=submit]').click()
            page.wait_for_function("document.querySelector('#status').textContent.includes('fetch')")
            page.locator('#response-retry').click()
            page.wait_for_function("document.querySelector('#response-status').textContent.includes('εκκρεμείς απαντήσεις αποθηκεύτηκαν')")
            data=page.request.get(f'http://127.0.0.1:{port}/api/records').json()['records']
            checkin=next(r for r in data if r['kind']=='checkin')
            assert checkin['values']==[5,4,2] and checkin['revision']==2
            assert not errors,errors
            browser.close()
        print('PASS: Chromium login, check-in/BAT save, reload hydration, lost acknowledgement retry without duplicate, no JS errors.')
    finally:
        process.terminate();process.wait(timeout=5)
