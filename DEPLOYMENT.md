# Evvardia deployment status

This repository contains the local research prototype. It runs on Python 3.10 or later with SQLite 3.38 or later, using the Python standard library.

## Local synthetic verification

Run these commands from the repository directory.

    python verify.py
    python server.py add TEST-001
    python server.py serve

The add command prints the access token once. Keep it outside source control.
Open http://127.0.0.1:8765 on the same computer.

To export synthetic events, use a new output filename.

    python server.py export events.csv

## Hospital deployment work remaining

The included HTTP server binds to the loopback interface. Its request-origin validation currently accepts only the local HTTP address. Hospital HTTPS hosting requires an explicit configured external origin, secure cookies, a production service configuration and verification behind the selected proxy. The current session expires after eight hours. Pending events survive while the page remains open. Reloading or closing the page can lose pending events.

The event database records usage actions and pseudonymous identifiers. Check-in scores and raw voice recordings are excluded from the event log. The personal overview reflects the current page session. A separate study registry is required for enrolment and the final assessment.

Before participant use, complete institutional hosting, database access and backup arrangements, account provisioning and revocation, browser testing and the site's human-support pathway. The two hospital sites are intended deployment locations. Installation is forthcoming.

LLM guidance is disabled by default. Enabling it requires a clinician-approved card catalogue and server-side configuration, documented in README.md. Public-demo specialist profiles and wearable inputs are simulated.
