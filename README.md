# سامانه مودیان — Moadian

Framework and web application for issuing electronic invoices (صورتحساب
الکترونیکی) to Iran's tax system, سامانه مودیان, API v2.

A Python library that speaks the protocol, a validation engine built from the
organization's own rule tables, an HTTP API, and a Persian RTL interface.

---

## Running it

Two processes: a FastAPI backend and a Vite dev server. The backend signs and
submits invoices, so keep it on `127.0.0.1` or behind an authenticated proxy.

### 1. Signing material

Place the certificate and private key on the server yourself — nothing about
them is ever accepted over HTTP.

```bash
mkdir -p /secure/moadian
cp cert.crt key.pem /secure/moadian/
chmod 600 /secure/moadian/key.pem
```

A CA-issued certificate from an Iranian intermediate authority is required for
the real service. For local work, generate a development pair:

```bash
cd backend
.venv/bin/python tools/gen_dev_cert.py /secure/moadian
```

That certificate authenticates to nothing — the organization validates the
chain via OCSP and CRL — but it exercises everything up to the point of sending.

### 2. Configuration

```bash
cd backend
cp .env.example .env      # then edit it
```

The four that matter:

| Variable | Purpose |
|---|---|
| `MOADIAN_CERTIFICATE_PATH` | Signing certificate, on the server |
| `MOADIAN_PRIVATE_KEY_PATH` | Private key, on the server, mode 600 |
| `MOADIAN_MASTER_PASSPHRASE` | Unlocks the encrypted profile store |
| `MOADIAN_APP_SECRET` | Signs this app's own session tokens |

`MOADIAN_SEED_USERS` creates the first account (default
`admin:admin1234:admin`). **Change that password after first login.**

### 3. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn moadian.api.app:app --host 127.0.0.1 --port 8000
```

### 4. Interface

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173
```

The dev server proxies `/api` to port 8000, so the browser stays same-origin.
For production, `npm run build` and serve `dist/` behind the same origin as the
API.

### 5. Check the connection

```bash
cd backend
.venv/bin/python tools/check_connectivity.py
```

Needs no certificate — `GET /nonce` is the one unauthenticated resource — so it
separates "the network cannot reach tax.gov.ir" from "the certificate was
refused" before either can be mistaken for the other.

---

## Documentation

| Document | For |
|---|---|
| [راهنمای کاربر](docs/USER_GUIDE.md) | Issuing, validating, sending and tracking invoices |
| [راهنمای مدیر سامانه](docs/ADMIN_GUIDE.md) | Setup, configuration, users, maintenance |
| [`backend/WIRE_FORMAT.md`](backend/WIRE_FORMAT.md) | The protocol, pinned and verified |
| [`backend/README.md`](backend/README.md) | Library architecture |
| [`frontend/README.md`](frontend/README.md) | Interface structure |

Both guides are also readable inside the app under **راهنما**, rendered from the
same Markdown files so they cannot drift apart.

---

## What is in here

| Path | What |
|---|---|
| `backend/src/moadian/crypto/` | JWS signing, JWE encryption, canonical JSON |
| `backend/src/moadian/taxid/` | Verhoeff checksum, شماره منحصر به فرد مالیاتی |
| `backend/src/moadian/rules/` | RC_IITP validation — جدول ۱ and the §8 formulas |
| `backend/src/moadian/client/` | All twelve v2 endpoints |
| `backend/src/moadian/mock/` | A mock service that verifies what we send |
| `backend/src/moadian/api/` | The HTTP surface |
| `backend/src/moadian/auth/` | Accounts, sessions, roles |
| `frontend/` | Persian RTL interface |
| `Docs/` | The organization's specifications |
| `SDK/` | The official .NET SDK — reference only, not a dependency |

---

## Correctness

The protocol is not guessed. Three independent checks stand behind it:

**The JWS is verified against the organization's own published token.**
RC_TICS p.13 prints a complete worked example — payload, signing time, and the
resulting token. Signing the same bytes with the same key reproduces it
character for character. If that test fails, the signature is wrong and
everything else is testing our assumptions back at us.

**The obligation matrix is double-sourced.** جدول ۱ was transcribed
mechanically from the PDF's cell grid, then compared against an independent OCR
of the same table: 102 rows, 1,632 cells, zero disagreements. That comparison
found a real defect the §8 anchors could not — a nested section the loader was
silently dropping.

**The mock service verifies rather than accepts.** It decrypts the JWE, checks
the JWS against the certificate in its own `x5c`, enforces the exact four-key
protected header, and rejects replayed nonces. A test that passes against it
produced bytes something actually validated.

```bash
cd backend
.venv/bin/pytest -m "not live"     # 493 tests, no network
.venv/bin/pytest -m live           # requires network access to the service
```

---

## Status

Working end to end against the mock and the sandbox's unauthenticated surface.
Not yet exercised against the live service with a real identity — that needs a
CA-issued certificate, which is the one thing no amount of code can substitute
for.

Known open questions are recorded where they matter: rounding tolerance in
`rules/arithmetic.py`, and the two SDK-only endpoints flagged in
`WIRE_FORMAT.md`.
