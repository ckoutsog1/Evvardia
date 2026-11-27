# Central persistence candidate — synthetic testing only

27 November 2026. This change adds persistent answers to the existing local prototype. It does not deploy or certify a Windows Server installation. The public Sites demo is unchanged. Read this file in addition to the existing README and DEPLOYMENT notes, which describe the earlier event-only release.

## Local verification

Run with Python 3.10+ and SQLite 3.38+ (the existing prototype requirements):

```text
python verify.py
python verify_persistence.py
python server.py --db synthetic.sqlite3 add SYNTH-A001 --center A
python server.py --db synthetic.sqlite3 add SYNTH-B001 --center B
python server.py --db synthetic.sqlite3 add SYNTH-C001 --center C
python server.py --db synthetic.sqlite3 serve
```

Open http://127.0.0.1:8765 and enter the generated individual access secret, not the participant identifier. Use only synthetic responses. The three center codes are grouping fields, never shared passwords. Existing participants are retained by migration but have no assigned center; answer submissions for those accounts are refused until a separate, reviewed provisioning/migration process exists. Use new synthetic accounts for these tests.

The optional `verify_browser.py` requires Playwright and Chromium; those are test dependencies only. It uses Playwright's default executable unless `EVVARDIA_TEST_CHROMIUM` supplies an existing Chromium path. Browser verification was attempted but could not run: the installed Chromium launcher has no browser binary and downloading Playwright Chromium was blocked (HTTP 403). Browser and Windows execution remain pending.

## Stored data

- `/api/checkins`: date, all three 1–5 responses, immutable submission ID.
- `/api/bat`: T0/T4/T8, actual assessment date and 23 item responses (1–5 or null).
- `/api/records`: current responses of the authenticated participant only; there is no participant-selection query or researcher web endpoint.
- Participant and center are resolved from the server-side session and participant table. Client-supplied owner/center fields are rejected.
- SQLite response rows store UTC receipt time, instrument/app version and append-only revisions. Same-day check-ins share a logical key; BAT revisions share the participant/visit key.
- Retrying the same ID and identical content returns the original receipt. Reusing that ID with different content returns conflict. A write transaction serializes competing retries.
- BAT scores are computed on the server. Total requires all 23 items; each subscale requires its own complete items. Missing items remain null. There are no diagnostic thresholds or crisis predictions.
- The UI hydrates saved check-ins/BAT after login or reload. It acknowledges a save only after server commit. Unconfirmed submissions stay in the open tab with the same ID for explicit retry. Closing a tab can lose unconfirmed data; offline durable storage is not implemented.

## Export

```text
python server.py --db synthetic.sqlite3 export-responses responses.csv
```

The CSV includes **all revisions** and `is_current`. Filter `is_current=1` for current answers. Keep historical revisions for audit and time-specific analyses. For check-ins q01/q02/q03 mean exhaustion/sleep/workload respectively; for BAT they mean questionnaire item numbers. Always separate by `kind`; never treat the mixed columns as one scale. Higher sleep score means better sleep; higher exhaustion/workload means more burden.

Export includes participant/center, record ID, dates, versions, revision flags, raw values and BAT subscales/total. It excludes login secrets and hashes. Missing BAT totals are blank. Exports create new files and refuse to overwrite existing ones. There is no researcher web download route; exports currently require local administrative execution.

Existing event CSV remains separate. Counts for actual answer completion should use response rows, not event-only records: the answer commit and usage-event delivery are separate transactions. No existing event is converted into a score, and no simulated wearable value is written to the response store.

## Verified 27 November 2026

`verify.py`: existing authentication, isolation, concurrent retries, event updates/validation, logout and event CSV checks passed.

`verify_persistence.py`: migration from the old participant schema, A/B/C separation, rejected spoofing, concurrent duplicate requests, conflicting IDs, correction history, invalid values, forced database-write failure without acknowledgement, full/partial BAT scoring, response retention after process restart, logout and answer CSV checks passed using an isolated temporary synthetic database.

The Playwright browser workflow is provided but NOT verified. Browser launch/download failed in this environment; no end-to-end UI success is claimed. No real participants or records are included in source control.

## Work remaining before participant use

1. A production application runtime and HTTPS hosting as an approved Windows service; the existing standard-library HTTP server and loopback origin check remain local-only.
2. Reviewed database choice/migrations, encryption/access/backup/restore arrangements and verification on the actual server.
3. Study registry, consent/enrolment workflow, secure credential provisioning/revocation and role-specific researcher/local-coordinator access. There is no researcher dashboard or complete access lifecycle yet.
4. WHOQOL-BREF, SUS, demographics, final validated Greek instrument versions/instructions, visit windows, final analysis exports and database locking. The copied BAT item set retains the demo version identifier pending this review; this is not an approved questionnaire release for a live study.
5. Approved human-support contacts and removal/isolation of simulated specialist/wearable flows. LLM remains disabled by default.
6. Final acceptance tests, approvals, training and separate wearable integration if that study arm is activated.

Do not use this branch as a shortcut to collect real health data on the public demo or by exposing the local HTTP port.
