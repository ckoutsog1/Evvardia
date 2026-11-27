"""Local research prototype. Run with Python 3.10+."""
import argparse
import csv
from datetime import date, datetime, timezone
from hashlib import sha256
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import sqlite3

import guidance
import research_store

GUIDANCE = None

EVENTS = {'checkin', 'voice_attempted', 'voice_confirmed', 'support_path_opened', 'technical_error'}
ERRORS = {'voice_start', 'voice_recognition'}
ROOT = Path(__file__).resolve().parent


def digest(value):
    return sha256(value.encode()).hexdigest()


def connect():
    db = sqlite3.connect(ARGS.db, timeout=10)
    db.execute('PRAGMA foreign_keys=ON')
    return db


def initialize():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS participant (
            code TEXT PRIMARY KEY, access_hash TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS session (
            token_hash TEXT PRIMARY KEY, code TEXT NOT NULL REFERENCES participant(code),
            expires INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS event (
            event_id TEXT NOT NULL, code TEXT NOT NULL REFERENCES participant(code),
            event_type TEXT NOT NULL, received_at_utc TEXT NOT NULL,
            checkin_date TEXT NOT NULL DEFAULT '', error_code TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (code, event_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS first_checkin
        ON event(code, checkin_date) WHERE event_type='checkin_submitted';
        """)

        research_store.initialize(db)


class App(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, status, content, mime='application/json', cookie=None):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(content)

    def json(self, status, payload, cookie=None):
        self.respond(status, json.dumps(payload).encode(), cookie=cookie)

    def participant(self, db):
        cookie = SimpleCookie(self.headers.get('Cookie', ''))
        token = cookie.get('evvardia_session')
        if not token:
            return None
        row = db.execute('SELECT code FROM session WHERE token_hash=? AND expires>unixepoch()',
                         (digest(token.value),)).fetchone()
        return row[0] if row else None

    def do_GET(self):
        if self.path == '/':
            with connect() as db:
                code = self.participant(db)
            page = 'index.html' if code else 'login.html'
            content = (ROOT / page).read_text(encoding='utf-8')
            if code:
                content = content.replace('__STUDY_PARTICIPANT__', code, 1)
                if GUIDANCE is None:
                    start = content.index('<!-- guidance-start -->')
                    end = content.index('<!-- guidance-end -->') + len('<!-- guidance-end -->')
                    content = content[:start] + content[end:]
            self.respond(200, content.encode(), 'text/html; charset=utf-8')
        elif self.path == '/api/records':
            with connect() as db:
                code = self.participant(db)
                if not code:
                    return self.json(401, {'error':'login_required'})
                data = research_store.records(db,code)
            return self.json(200, {'records':data})
        elif self.path in ('/persistence.js','/bat_items.js'):
            self.respond(200, (ROOT / self.path.lstrip('/')).read_bytes(), 'text/javascript; charset=utf-8')
        elif self.path == '/study.js' or (self.path == '/guidance.js' and GUIDANCE is not None):
            self.respond(200, (ROOT / self.path.lstrip('/')).read_bytes(), 'text/javascript; charset=utf-8')
        else:
            self.json(404, {'error': 'not_found'})

    def do_POST(self):
        if self.headers.get('Origin') != f'http://127.0.0.1:{ARGS.port}':
            return self.json(403, {'error': 'origin'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if self.headers.get_content_type() != 'application/json' or not 0 < size <= 4096:
                raise ValueError()
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            return self.json(400, {'error': 'invalid_request'})
        if self.path in ('/api/checkins','/api/bat'):
            return self.save_response(body)
        if self.path == '/guidance':
            return self.guidance_request(body)
        if self.path == '/login':
            return self.login(body)
        if self.path == '/event':
            return self.record(body)
        if self.path == '/logout':
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            token = cookie.get('evvardia_session')
            if token:
                with connect() as db:
                    db.execute('DELETE FROM session WHERE token_hash=?', (digest(token.value),))
            return self.json(200, {}, 'evvardia_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict')
        return self.json(404, {'error': 'not_found'})

    def save_response(self, body):
        try:
            with connect() as db:
                code = self.participant(db)
                if not code:
                    return self.json(401, {'error':'login_required'})
                if self.headers.get('X-Study-Participant') != code:
                    return self.json(403, {'error':'different_participant'})
                result = research_store.save(db,code,'checkin' if self.path=='/api/checkins' else 'bat23',body)
            # Acknowledge only after the transaction has committed.
            return self.json(200 if result['duplicate'] else 201,result)
        except research_store.Conflict as error:
            return self.json(409, {'error':str(error)})
        except (ValueError, TypeError, AttributeError):
            return self.json(400, {'error':'invalid_response'})
        except sqlite3.Error:
            return self.json(503, {'error':'storage_unavailable'})

    def guidance_request(self, body):
        if GUIDANCE is None:
            return self.json(404, {'error': 'not_found'})
        with connect() as db:
            code = self.participant(db)
        if not code:
            return self.json(401, {'error': 'login_required'})
        if self.headers.get('X-Study-Participant') != code:
            return self.json(403, {'error': 'different_participant'})
        topic = body.get('topic')
        if set(body) != {'topic'} or topic not in guidance.TOPICS:
            return self.json(400, {'error': 'invalid_topic'})
        return self.json(200, guidance.suggest(topic, GUIDANCE))

    def login(self, body):
        code = body.get('access_code')
        if not isinstance(code, str) or len(code) > 100:
            return self.json(400, {'error': 'invalid_request'})
        with connect() as db:
            row = db.execute('SELECT code FROM participant WHERE access_hash=?', (digest(code.strip()),)).fetchone()
            if not row:
                return self.json(401, {'error': 'invalid_code'})
            token = secrets.token_urlsafe(32)
            db.execute('DELETE FROM session WHERE expires<=unixepoch()')
            db.execute('INSERT INTO session VALUES (?, ?, unixepoch()+28800)', (digest(token), row[0]))
        return self.json(200, {}, f'evvardia_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800')

    def record(self, body):
        kind, event_id = body.get('type'), body.get('id')
        if not isinstance(kind, str) or kind not in EVENTS or not isinstance(event_id, str) or not re.fullmatch(r'[0-9a-f-]{36}', event_id):
            return self.json(400, {'error': 'invalid_event'})
        required = {'id','type'}
        if kind == 'checkin':
            required.add('day')
        if kind == 'technical_error':
            required.add('error')
        if set(body) != required:
            return self.json(400, {'error': 'invalid_fields'})
        day, error = body.get('day',''), body.get('error','')
        if kind == 'checkin':
            try:
                if date.fromisoformat(day).isoformat() != day:
                    raise ValueError()
            except (ValueError, TypeError):
                return self.json(400, {'error': 'invalid_date'})
        if kind == 'technical_error' and (not isinstance(error,str) or error not in ERRORS):
            return self.json(400, {'error': 'invalid_error'})
        with connect() as db:
            code = self.participant(db)
            if not code:
                return self.json(401, {'error': 'login_required'})
            if self.headers.get('X-Study-Participant') != code:
                return self.json(403, {'error': 'different_participant'})
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT event_type, checkin_date, error_code FROM event WHERE code=? AND event_id=?',
                             (code,event_id)).fetchone()
            if old:
                expected = {'checkin_submitted','checkin_updated'} if kind == 'checkin' else {kind}
                if old[0] in expected and old[1:] == (day,error):
                    return self.json(200, {'type':old[0], 'duplicate':True})
                return self.json(409, {'error':'event_id_conflict'})
            if kind == 'checkin':
                prior = db.execute("SELECT 1 FROM event WHERE code=? AND checkin_date=? AND event_type='checkin_submitted'",
                                   (code,day)).fetchone()
                kind = 'checkin_updated' if prior else 'checkin_submitted'
            at = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
            db.execute('INSERT INTO event VALUES (?,?,?,?,?,?)', (event_id,code,kind,at,day,error))
        self.json(201, {'type':kind, 'duplicate':False})


def main():
    global ARGS, GUIDANCE
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='study.sqlite3')
    cmds = parser.add_subparsers(dest='command', required=True)
    serve = cmds.add_parser('serve')
    serve.add_argument('--port', type=int, default=8765)
    participant = cmds.add_parser('add')
    participant.add_argument('code')
    participant.add_argument('--center', choices=['A','B','C'])
    responses = cmds.add_parser('export-responses')
    responses.add_argument('path')
    export = cmds.add_parser('export')
    export.add_argument('path')
    ARGS = parser.parse_args()
    initialize()
    if ARGS.command == 'serve':
        try:
            GUIDANCE = guidance.configuration()
        except (OSError, ValueError, KeyError) as error:
            parser.error(f'Invalid guidance configuration: {error}')
        httpd = ThreadingHTTPServer(('127.0.0.1', ARGS.port), App)
        print(f'http://127.0.0.1:{ARGS.port}', flush=True)
        httpd.serve_forever()
    elif ARGS.command == 'add':
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{2,31}', ARGS.code):
            parser.error('Use a synthetic code such as TEST-001.')
        secret = secrets.token_urlsafe(24)
        try:
            with connect() as db:
                db.execute('INSERT INTO participant(code,access_hash,center_id) VALUES (?,?,?)', (ARGS.code,digest(secret),ARGS.center))
        except sqlite3.IntegrityError:
            parser.error('Participant code already exists.')
        print(secret)
    elif ARGS.command == 'export-responses':
        with connect() as db, open(ARGS.path, 'x', newline='', encoding='utf-8-sig') as output:
            research_store.export(db,output)
    else:
        with connect() as db, open(ARGS.path, 'x', newline='', encoding='utf-8-sig') as output:
            writer = csv.writer(output)
            writer.writerow(['event_id','participant_code','event_type','received_at_utc','checkin_date','error_code'])
            writer.writerows(db.execute('SELECT * FROM event ORDER BY received_at_utc, rowid'))


if __name__ == '__main__':
    main()
