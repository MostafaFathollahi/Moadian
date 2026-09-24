# Deploying on a single host

One process, one port, behind an SSH tunnel. The process holds the RSA key that
signs tax invoices, so it binds `127.0.0.1` and is never published.

## Which unit file

| | when |
|---|---|
| `moadian.service` | you have root. Installs to `/etc/systemd/system`. |
| `moadian.user.service` | you do not. A user unit plus `loginctl enable-linger`, which also starts at boot. |

Both run the same command. The user unit is not a downgrade in durability —
lingering is what makes a user manager start at boot rather than at first
login — but it is per account, and `systemctl --user` needs `XDG_RUNTIME_DIR`,
which a bare `ssh host systemctl --user …` has and a cron job may not.

## Steps

```bash
# 1. Code
git clone https://github.com/MostafaFathollahi/Moadian.git ~/Moadian

# 2. Backend
cd ~/Moadian/backend
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"

# 3. UI. Node 20 or newer — Vite 5 does not support 18 reliably.
cd ~/Moadian/frontend && npm ci && npm run build

# 4. Signing material, out of band. Never through the app: no endpoint
#    accepts a key, a path to one, or a passphrase, by construction.
sudo install -d -m 755 /secure/moadian
sudo install -o "$USER" -m 644 cert.crt /secure/moadian/cert.crt
sudo install -o "$USER" -m 600 key.pem  /secure/moadian/key.pem

# 5. Config
cd ~/Moadian/backend
cp .env.example .env && chmod 600 .env   # then fill it in — see below

# 6. Service (no root)
loginctl enable-linger "$USER"
mkdir -p ~/.config/systemd/user
cp ~/Moadian/deploy/moadian.user.service ~/.config/systemd/user/moadian.service
systemctl --user daemon-reload
systemctl --user enable --now moadian
```

## Verifying the certificate and key are a pair

Do this before the first filing. A mismatched pair signs perfectly well and is
refused by the organization — and by then a serial has been spent on an invoice
that cannot be reissued under the same number.

```bash
diff <(openssl x509 -in /secure/moadian/cert.crt -noout -pubkey) \
     <(openssl pkey -in /secure/moadian/key.pem -pubout) \
  && echo MATCH || echo MISMATCH
```

The same check runs at every startup and lands in the journal, and the admin
panel exposes it at `GET /api/signing-material/verify`.

Then the end-to-end version, which also proves the organization accepts the
certificate for this fiscal memory:

```bash
cd ~/Moadian/backend
./.venv/bin/python tools/preflight.py --memory-id <شناسه یکتای حافظه مالیاتی>
```

## `.env`: what actually has to be set

| key | consequence if wrong or unset |
|---|---|
| `MOADIAN_KEY_PASSPHRASE` | Required for an encrypted PKCS#8 key (`BEGIN ENCRYPTED PRIVATE KEY`). Unset, the service still starts and the UI still works — every signature fails. |
| `MOADIAN_MASTER_PASSPHRASE` | Unlocks the profile store. **Lose it and the stored profiles are unreadable.** Back it up somewhere other than this host. |
| `MOADIAN_APP_SECRET` | Signs this app's own session tokens, not tax packets. Unset means a random value per process, so every restart logs everyone out. |
| `MOADIAN_SEED_USERS` | Created once, at first start. Changing it never overwrites an existing user, so it cannot reset a password someone has since changed. |
| `MOADIAN_STATIC_DIR` | Unset, the API serves no UI and `/` is a 404. That is correct in development, where Vite serves it. |

Secrets go here and not in the unit file, which is world-readable.

## Reaching it

```bash
ssh -N -L 8000:127.0.0.1:8000 <host>   # then http://localhost:8000
```

## Egress

`sandboxrc.tax.gov.ir` and `tp.tax.gov.ir` are reachable from inside Iran.
A host outside it resolves both and then times out on port 443, which looks
exactly like a refused certificate until you test the TCP connect on its own:

```bash
getent hosts tp.tax.gov.ir
timeout 8 bash -c 'echo > /dev/tcp/tp.tax.gov.ir/443' && echo OPEN || echo BLOCKED
```

The client is a plain `httpx.AsyncClient` with `trust_env` at its default, so an
egress proxy needs no code change — add it to the unit and restart:

```ini
[Service]
Environment=HTTPS_PROXY=http://127.0.0.1:8888
Environment=NO_PROXY=127.0.0.1,localhost
```

`MOADIAN_SANDBOX_BASE_URL` and `MOADIAN_PRODUCTION_BASE_URL` exist for the same
job, but prefer the proxy: the URLs are pinned in `WIRE_FORMAT.md` and are the
one thing a misconfiguration can point at the wrong environment entirely.

## Operating

```bash
systemctl --user status moadian
journalctl --user -u moadian -f
systemctl --user restart moadian     # after editing .env
```

`.env` is read once, at startup. Nothing rereads it.

## Upgrading

```bash
cd ~/Moadian && git pull
./backend/.venv/bin/pip install -e "backend[dev]"
cd frontend && npm ci && npm run build
systemctl --user restart moadian
```

The record store migrates itself on open, in one transaction, and copies before
it deletes: an interrupted upgrade leaves the old schema intact. The invoice
serial counter is a plain file under `backend/instance` and is never reset —
`git pull` does not touch it, and nothing should.
