# moadian

A Python framework for issuing electronic invoices to Iran's سامانه مودیان
(Moadian), **API v2** — `RC_TICS.IS_v1.6` for the transport, `RC_IITP_IS_V7_9_1`
for the invoice.

It does the whole submission: build the شماره منحصر به فرد مالیاتی, serialise
the invoice to the exact bytes the organization signs, wrap them in a JWS, seal
that in a JWE against the server's public key, mint a single-use bearer token
per request, POST the batch, and poll for the result.

**[`WIRE_FORMAT.md`](WIRE_FORMAT.md) is the authority on every protocol
question.** It records what the specification says, what was verified against
the live sandbox, and where the vendor's own .NET SDK disagrees with the
document. When this README and that file differ, that file is right.

---

## You need a CA-issued certificate. A self-signed one can never work.

This is the single fact that decides whether the framework can talk to the real
API at all, so it is here rather than in a footnote.

Authentication is a challenge-response: fetch a nonce, sign
`{"nonce": ..., "clientId": ...}`, present the compact JWS as a bearer token.
The organization then validates the signing certificate — and it does not stop
at "does this signature verify". It walks the chain to the issuing Iranian
intermediate CA and checks revocation status by **OCSP and CRL**.

A self-signed certificate has no issuing CA, so there is no OCSP responder to
ask and no CRL to fetch. The check does not fail because the certificate is
untrusted; it fails because there is nothing to check *against*. No
configuration flag, no local trust store, and no amount of correct
cryptography changes that. The same applies to the invoice JWS, which is
validated the same way after decryption.

Two further bindings the certificate carries:

- The subject **`SERIALNUMBER`** must hold the کد ملی/شناسه ملی of the
  taxpayer, and must match the invoice's `tins`. A mismatch is error `4103`.
- That identity must hold send-permission for the `clientId` (the شناسه یکتای
  حافظه مالیاتی) used at submission. Without it, transport error `04132`.

So: development certificates are for the mock server and the local test suite.
Get a certificate from an Iranian CA, register its public key in the کارپوشه,
and only then does the real endpoint answer anything but a rejection.

---

## Architecture

`src/moadian/`, src layout, installed as `moadian`. Each layer is usable on its
own; the pipeline is the thing that ties them together.

| Module | Responsibility |
|---|---|
| `pipeline` | `InvoicePipeline` — invoices in, submissions and results out. The intended entry point. |
| `client` | `MoadianClient`, one method per v2 resource; `NonceAuthenticator` mints one single-use token per call; `endpoints.build_url` joins URLs by string concatenation. |
| `crypto` | `canonical_json` (the signed bytes), `Pkcs8Signatory` (compact JWS, RS256), `JweEncryptor` (RSA-OAEP-256 + A256GCM), `SigningCredentials`. |
| `models` | Pydantic models for the invoice, the packet envelope, and every response. Field names are the wire names verbatim — `taxid`, `indatim`, `tprdis`. |
| `taxid` | `generate_tax_id` and its Verhoeff check digit, with `day_range` pinned to **Asia/Tehran**. |
| `config` | `Settings` (env-overridable, `MOADIAN_` prefix) and `ProfileStore`, an AES-GCM encrypted multi-profile credential file. |
| `errors` | One exception hierarchy under `MoadianError`, plus the transcribed error-code catalogue. |
| `mock` | An in-process FastAPI stand-in for the API that runs the *real* server-side checks. A correctness oracle, not a stub. |

Three design points worth knowing before reading the code:

- **`Signatory` is a Protocol.** `Pkcs8Signatory` signs with an in-process key;
  a PKCS#11 implementation for a hardware token drops in beside it without a
  base class.
- **Nothing is cached in `NonceAuthenticator`.** A nonce is consumed by the
  first request that presents it, so caching either the nonce or the token
  produces error `4102`.
- **`extra="forbid"` on invoice models, `extra="ignore"` on responses.** A
  misspelt invoice field would otherwise be signed and sent as an incomplete
  invoice; a new response field added between spec revisions should not break a
  working deployment.

---

## Install

Python 3.11+.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Generate a development certificate

For the mock server and the test suite only — see the CA section above.

```bash
.venv/bin/python tools/gen_dev_cert.py ../dev-certs
```

Writes `privatekey.pem` (PKCS#8, mode 0600), `certificate.crt` and
`publickey.pem`. The subject `SERIALNUMBER` is set to the شناسه ملی the SDK
samples use, `14003778990`; edit the call at the bottom of the script to use
your own. `dev-certs/` and every `*.pem`/`*.crt` are gitignored — the signing
key *is* the credential, and leaking it means someone else can issue invoices
as you.

---

## Submitting one invoice

```python
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from moadian import (
    Invoice, InvoiceBodyItem, InvoiceHeader,
    InvoicePipeline, MoadianClient, MonotonicSerialCounter,
    Pkcs8Signatory, SigningCredentials,
)

MEMORY_ID = "A11216"       # شناسه یکتای حافظه مالیاتی
NATIONAL_ID = "14003778990"  # must equal the certificate's subject SERIALNUMBER

credentials = SigningCredentials.from_files(
    "dev-certs/certificate.crt", "dev-certs/privatekey.pem"
)
credentials.assert_usable()
signatory = Pkcs8Signatory(credentials)

issued_at = datetime.now(UTC)
invoice = Invoice(
    header=InvoiceHeader(
        taxid="",                                    # left blank: the pipeline fills it in
        indatim=int(issued_at.timestamp() * 1000),   # epoch milliseconds
        inty=1, inp=1, ins=1, setm=2,                # نوع اول، الگوی ۱ (فروش)، اصلی، نقد
        tins=NATIONAL_ID, tinb="10100302746",
        tprdis=20000, tdis=500, tadis=19500,
        tvam=1755, todam=0, tbill=21255,
    ),
    body=[
        InvoiceBodyItem(
            sstid="2710000138624", sstt="سرسیلندر قطعات صنعت فولاد سازی",
            mu="164", am=2, fee=10000,
            prdis=20000, dis=500, adis=19500,
            vra=9, vam=1755, tsstam=21255,
        )
    ],
)


async def main() -> None:
    async with MoadianClient(
        base_url="https://sandboxrc.tax.gov.ir/requestsmanager",
        client_id=MEMORY_ID,
        signatory=signatory,
    ) as client:
        pipeline = InvoicePipeline(
            client, signatory, MEMORY_ID,
            MonotonicSerialCounter(Path("instance/serial")),
        )

        submissions = await pipeline.submit([invoice])
        for submission in submissions:
            print(submission.tax_id, submission.reference_number)

        # Waits the mandatory 10s, then polls until nothing is IN_PROGRESS.
        for result in await pipeline.await_results(submissions):
            print(result.referenceNumber, result.status, result.data)


asyncio.run(main())
```

`header.taxid` left empty means the pipeline generates one from the fiscal
memory, the next serial and the invoice's own `indatim`, and sets `inno` from
the same serial. Set it yourself and the pipeline leaves it alone. Input
invoices are never mutated — the assigned tax id comes back on the
`InvoiceSubmission`.

### About the serial

`MonotonicSerialCounter` is file-backed, fsynced, and guarded by an advisory
lock, because the serial goes into the tax id and **reuse produces a duplicate
شماره منحصر به فرد مالیاتی that no later request can undo**. The official
samples draw it from `Random`, which collides.

That durability stops at one host. A deployment spread over more than one
machine must replace the counter with something the machines share — a database
sequence or an allocation service — or two hosts will each issue serial 41.

---

## Tests

```bash
.venv/bin/pytest -m "not live" -q    # everything offline
.venv/bin/pytest -m live -q          # the two tests that hit the real sandbox
```

Use `-m "not live"` for ordinary runs: the `live` marker is registered in
`pyproject.toml` and is the only thing that touches the network. (Adding
`addopts = '-m "not live"'` under `[tool.pytest.ini_options]` makes that the
default for a bare `pytest`.)

| Suite | What it proves |
|---|---|
| `tests/unit/` | Crypto, tax id, models, config and the HTTP client at the level of bytes on the wire. `respx` stands in for the API. |
| `tests/integration/test_mock_roundtrip.py` | A full sign → encrypt → submit → inquire round trip against `moadian.mock`, which decrypts the JWE, verifies the JWS against the certificate in its own `x5c`, asserts the four-key protected header, and burns the nonce. |
| `tests/vectors/test_official_vector.py` | Reproduces the auth token printed in `RC_TICS.IS_v1.6` p.13 **byte for byte**, using the keypair from the official .NET SDK. The canary: if it fails, the JWS is wrong. Skips with a clear reason when the SDK sample files are not vendored. |
| `tests/integration/test_live_sandbox.py` | `GET /nonce` against the real sandbox (no certificate needed), and the documented rejection of a self-signed certificate. One request per test. |

The live rejection test is written to *record* the code and message the sandbox
returns rather than assume one. When a CA-issued certificate arrives it flips to
a positive test: same call, expect 200 and a `publicKeys` array.

---

## Things that are easy to get wrong

Each of these is enforced somewhere in the suite, and each is invisible until
the organization rejects an invoice.

- The JWS protected header is **exactly** `crit`, `sigT`, `x5c`, `alg`, in that
  order. The .NET SDK also sends `typ` and `cty`; the specification does not
  define them.
- `x5c` is **standard** base64 of the certificate DER — not base64url, no PEM
  armour. Every other field in a JOSE header is base64url, which is what makes
  this a real drift risk.
- The signed invoice JSON omits unset fields entirely, uses compact separators,
  and does **not** escape non-ASCII: Persian text travels as UTF-8, never as
  `\uXXXX`.
- `day_range` in the tax id is computed in **Asia/Tehran**. A UTC host and a
  Tehran host disagree near midnight, and the resulting tax id is wrong for
  exactly one day's worth of invoices.
- URLs are built by string concatenation. `os.path.join`/`pathlib` collapse the
  `//` in `https://`.
- Wait **at least 10 seconds** after `POST /invoice` before inquiring, and treat
  `IN_PROGRESS` as "poll again", never as "resend".

## Reference material

- `WIRE_FORMAT.md` — the pinned protocol facts. Start here.
- `tests/vectors/poc_crypto.py` — a standalone, verified reference for the JWS
  and JWE, in ~130 lines of `cryptography`.
- `tests/vectors/RC_TICS_extracted.txt` — extracted text of the technical guide.
  RTL extraction mangles prose; the JSON and base64 are exact.
- `../Docs/` — the source PDFs.
- `../SDK/` — the official .NET SDK, useful as a cross-check. `WIRE_FORMAT.md`
  wins on every disagreement.
