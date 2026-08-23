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
| خریداران | Reusable buyers, shared across fiscal memories; needs none to use |
| کالا و خدمات | شناسه کالا/خدمت catalogue, one entry may be the form default |
| تنظیمات | Fiscal memories, signing-material status, certificate/key match, connection test, users |
| راهنما | The user and admin guides, rendered from Docs/*.md |

## Authentication

Login is required; the token lives in `localStorage` and rides on every request.
A 401 anywhere clears the session, which is what routes the app back to the login
screen instead of leaving a blank page with an error on it.

Two roles. **تنظیمات** is admin-only and hidden from the sidebar otherwise —
though the backend enforces it regardless, since a hidden button is not a
permission. Admins get a users tab: create accounts, change roles, deactivate,
and sign one user or everyone out. Revoking all sessions hands the caller a fresh
token so an admin cannot lock themselves out doing it.

> The token in `localStorage` is a deliberate MVP trade-off: an XSS bug can read
> it, where an httpOnly cookie could not. Acceptable while this is single-operator
> on localhost or behind an authenticated proxy; revisit before exposing it wider.

## Typography

**Vazirmatn** (SIL OFL 1.1), bundled via `@fontsource-variable/vazirmatn` and
self-hosted — never a CDN. This app handles tax data and often runs on a machine
with no route to the public internet, so a third-party font request would be
both a privacy leak and a way for the whole interface to fall back to Tahoma the
day the CDN is unreachable. Three subsets ship, ~103 KB total, and the variable
weight means 100..900 costs one file.

`IRANSans` is deliberately **not** in the font stack. It is a commercial font;
naming it would mean the app renders correctly only on machines that happen to
have a licensed copy installed, and looks different everywhere else.

Tabular numerals are on globally. The money columns line up only if digit widths
are fixed, and Persian digits from `toLocaleString('fa-IR')` need the same
treatment as Latin ones.

## Things that are deliberate

**One picker, not two.** The sidebar selects a *profile*, and environment comes
with it. A شناسه یکتای حافظه مالیاتی belongs to exactly one environment, so
offering environment and memory id as independent dropdowns would let an
operator point a sandbox identity at production.

**The reference catalogues sit above the profile gate.** خریداران and
کالا و خدمات render whether or not a fiscal memory is selected, because neither
needs one: a شناسه ملی and a شناسه کالا/خدمت are issued nationally and mean the
same thing in both environments. They used to sit below it, which meant a
taxpayer still waiting on their شناسه یکتا could not enter a single customer —
the exact work that period is for. Only the dashboard, the entry form and the
submission history are gated, and those genuinely belong to one memory.

**Three themes, not a toggle.** `lib/theme.ts` writes `data-theme` on `<html>`,
and *not writing it* is the third state — "follow the system" — which the CSS
media query then answers. Every palette token is declared on bare `:root` as
well as in the dark blocks, so a viewer who picks dark on a light machine gets a
complete palette rather than a half-themed page. `main.tsx` applies the stored
choice before the first render, so there is no white flash.

**Form controls are themed by being form controls.** `color-scheme` is declared
per theme so the browser renders its own chrome — spin buttons, the caret,
scrollbars — to match, and inputs get their background from an element selector
rather than from `.field`. The invoice line table lays inputs straight into
`<td>`, and a `.field`-scoped rule left those with a white background under
`color: inherit`'s near-white text: 1.2:1, which is invisible.

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
private key. There is no field for one, no picker, and no path input — the admin
screen shows only *status*: which path the server has configured, whether the
file exists, and its permissions.

**The guides are imported, not retyped.** `HelpPanel` reads `docs/USER_GUIDE.md`
and `docs/ADMIN_GUIDE.md` with Vite's `?raw`, rendered by a ~150-line Markdown
subset in `lib/markdown.tsx`. Not a dependency: the guides are ours and written
in a known subset, and nothing is ever set as `innerHTML`, so there is no
sanitiser to get wrong either.
