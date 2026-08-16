# Moadian UI

RTL Persian interface over the backend API. Vite + React + TypeScript, no UI
framework — the whole thing is six screens and a stylesheet.

## Running

The backend must be up first; the dev server proxies `/api` to it, which keeps
the browser same-origin and means the invoice-signing API is never exposed
directly.

```bash
# terminal 1 — backend
cd backend
MOADIAN_MASTER_PASSPHRASE=... \
MOADIAN_CERTIFICATE_PATH=/secure/cert.crt \
MOADIAN_PRIVATE_KEY_PATH=/secure/key.pem \
.venv/bin/uvicorn moadian.api.app:app --port 8000

# terminal 2 — UI
cd frontend
npm install
npm run dev        # http://localhost:5173
```

## Screens

| Screen | What it is for |
|---|---|
| داشبورد | Counts per invoice state, recent invoices, certificate-expiry warning |
| صدور صورتحساب | Entry form, محاسبه مبالغ, اعتبارسنجی, ذخیره پیش‌نویس, ارسال |
| پیگیری ارسال‌ها | Sent ≠ confirmed — status per submission with the error detail |
| خریداران | Reusable buyers, scoped to one fiscal memory |
| کالا و خدمات | شناسه کالا/خدمت catalogue, one entry may be the form default |
| تنظیمات | Fiscal memories, signing-material status, connection test |

## Things that are deliberate

**One picker, not two.** The sidebar selects a *profile*, and environment comes
with it. A شناسه یکتای حافظه مالیاتی belongs to exactly one environment, so
offering environment and memory id as independent dropdowns would let an
operator point a sandbox identity at production.

**Production is visually distinct.** A banner and a coloured switcher, driven by
`is_production` from the API. Nobody should have to read a URL to know whether
the invoice they are about to file is real. The app also opens on a sandbox
profile when one exists, rather than whichever sorts first.

**The form is a projection of جدول ۱.** Required, optional and conditional come
from `/api/patterns/{n}/fields`, not from rules written here. A correction to the
obligation matrix changes the form with no frontend release, and the نوع اول /
نوع دوم differences come along for free.

**ارسال is disabled until اعتبارسنجی passes.** Submitting an invalid invoice
spends a tax id and a monotonic serial that cannot be reused, so the button
refuses rather than letting the tax service reject it ten seconds later.

**Wire field names are kept verbatim** in `api/types.ts` — `taxid`, `indatim`,
`tprdis`. Prettifying them would add a translation layer that is invisible when
it goes wrong. Persian labels come from the API, which reads them from جدول ۱.

**No key material, ever.** Nothing here uploads or displays a certificate or a
private key. The admin screen shows only *status* — which path the server has
configured, whether the file exists, and its permissions.
