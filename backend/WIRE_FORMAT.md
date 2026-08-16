# Moadian v2 wire format — pinned facts

Everything here is derived from `Docs/دستورالعمل فنی اتصال به سامانه مودیان.pdf`
(`RC_TICS.IS_v1.6`) and verified empirically. **Where the .NET SDK under `SDK/`
disagrees with this document, this document wins** — the SDK adds headers the
spec does not define.

## Base URLs

| Environment | Base URL | Last observed |
|---|---|---|
| Sandbox (آزمایشی) | `https://sandboxrc.tax.gov.ir/requestsmanager` | 2026-08-16, `GET /nonce` → 200 in 251 ms |
| Production (عملیاتی) | `https://tp.tax.gov.ir/requestsmanager` | 2026-08-16, `GET /nonce` → 200 in 211 ms |

> **This column is a dated observation, not a live health check.** Reproduce it
> with `backend/tools/check_connectivity.py`, which needs no certificate. Note
> that a network can intercept these names: on 2026-08-15 `sandboxrc.tax.gov.ir`
> resolved to `198.18.0.54`, inside the RFC 2544 benchmarking range
> `198.18.0.0/15` — a sinkhole, not the real host — and every connection timed
> out. If the `live` tests fail, check that first; do not "fix" a live test by
> weakening it.

Established by the 2026-08-16 run against both environments, and relied on
elsewhere in this document:

- both hosts serve TLS 1.2 with a certificate issued by **Asseco Data Systems
  S.A.**, so the chain validates against the ordinary public trust store — no
  custom CA bundle is needed to *reach* the API. (This is unrelated to the
  signing certificate, which must come from an Iranian intermediate CA.)
- the nonce is `<uuid4>-<epochMillis>`, exactly as §Authentication describes, and
  differs on every call;
- **the granted TTL is the requested one plus 30 seconds.** Three observations
  agree: 20s → 50s, and 30s → ~60s on both environments. So `timeToLive` sets the
  margin *above* a fixed 30s floor rather than the lifetime itself. Treat the
  response `expDate` as authoritative regardless — this is an observation of
  current behaviour, not a documented contract.

All resources live under `{base}/api/v2/`. Build URLs by string join — **never**
`os.path.join`/`Path`, which mangles separators.

The legacy `/req/api/self-tsp/sync/GET_TOKEN` generation still routes but is
deprecated ("تا اطلاع ثانوی", RC_TICS p.5). Do not use it.

## Endpoints

| Purpose | Method | Path | Auth | Source |
|---|---|---|---|---|
| Random challenge | GET | `nonce?timeToLive=30` | **none** | RC_TICS |
| Server public keys | GET | `server-information` | yes | RC_TICS |
| Submit invoices | POST | `invoice` | yes | RC_TICS |
| Inquiry by time range | GET | `inquiry` | yes | RC_TICS |
| Inquiry by UID | GET | `inquiry-by-uid` | yes | RC_TICS |
| Inquiry by reference no. | GET | `inquiry-by-reference-id` | yes | RC_TICS |
| Invoice status (کارپوشه) | GET | `inquiry-invoice-status` | yes | RC_TICS |
| Taxpayer | GET | `taxpayer?economicCode=` | yes | RC_TICS |
| Fiscal memory info | GET | `fiscal-information?memoryId=` | yes | RC_TICS |
| Register payment | POST | `invoice-payment` | yes | RC_TICS §11 |
| Taxpayer info | GET | `taxpayer-info?economicCode=` | yes | **SDK only** ⚠ |
| Article-6 status | GET | `taxpayer-article6-status?economicCode=&vatValue=&period=` | yes | **SDK only** ⚠ |

> ⚠ **The last two rows are not attested by RC_TICS.IS_v1.6.** Neither path name
> appears anywhere in the PDF — grep `taxpayer-info` and `taxpayer-article6-status`
> against `tests/vectors/RC_TICS_extracted.txt` and both return zero hits, while
> `taxpayer`, `fiscal-information`, `inquiry-by-uid` and `invoice-payment` all hit.
> Their sole source is the .NET SDK:
>
> - `SDK/.../TaxCollectData.Library/Constants/PacketTypeConstants.cs:12-13` — the
>   two path constants;
> - `SDK/.../TaxCollectData.Library/Providers/RequestProvider.cs:126-140` — the
>   request builders, and the **only** source for the
>   `economicCode` + `vatValue` + `period` parameter triple and for the
>   `{"article6RemainStatus": bool}` response shape.
>
> Since this document declares that the PDF beats the SDK, these two cannot be
> carried as spec. Treat them as best-effort: the client implements them, the mock
> serves them, but a change in either is not a spec violation, and neither has been
> exercised against the live service.

## Authentication

Per-request challenge-response. **A token is single-use** — fetch a fresh nonce
for every call.

1. `GET /nonce` (unauthenticated) →
   `{"nonce": "<uuid>-<epochMillis>", "expDate": "<ISO8601 UTC>"}`
   `timeToLive` is in seconds, documented default 30, range 10–200. Observed
   behaviour is that the service grants **requested + 30s** (see §Base URLs), so
   the value you ask for is not the lifetime you get. Treat the response
   `expDate` as truth and never the requested value.
2. Build the JWS payload: `{"nonce": "...", "clientId": "<memoryId>"}`
3. Sign as a compact JWS (below).
4. Send `Authorization: Bearer <jws>` on the next request.

## JWS — auth token *and* invoice

The structure is identical for both; only the payload differs (RC_TICS §5-1-2,
§7-1-2). Protected header is **exactly these four keys**:

```json
{"crit":["sigT"],"sigT":"2024-03-06T13:05:50Z","x5c":["MIID..."],"alg":"RS256"}
```

- `alg` — `RS256`, i.e. RSASSA-PKCS1-v1_5 with SHA-256
- `x5c` — list, the signing certificate DER in **standard** base64 (not base64url),
  no PEM armour. Intermediate CA certs may be appended but are not required.
- `sigT` — signing time, `%Y-%m-%dT%H:%M:%SZ`, UTC
- `crit` — always exactly `["sigT"]`

> The .NET SDK additionally emits `typ: "jose"` and `cty: "text/plain"`. These are
> **not in the spec**; we omit them.

Signing input is `ASCII(BASE64URL(UTF8(header)) || '.' || BASE64URL(payload))`,
serialised compact as `header.payload.signature`.

Payload formatting is unconstrained — the documented example is pretty-printed
with CRLF and is accepted. Only header bytes matter for reproducibility.

### Certificate requirements

- Subject **`SERIALNUMBER`** must hold the کد ملی/شناسه ملی, and that identity
  must have send-permission for the `clientId` (fiscal memory) being used.
- Validity is checked against the issuing intermediate CA via **OCSP and CRL**.
  A self-signed certificate therefore *cannot* authenticate against the real API —
  dev certs are for local and mock testing only.

## JWE — invoice encryption

The signed invoice JWS becomes the plaintext of a compact JWE (RC_TICS §7-1-3):

- Key wrap: `RSA-OAEP-256` (OAEP, SHA-256, MGF1-SHA-256) against a public key from
  `GET /server-information`
- Content encryption: `A256GCM` — 256-bit CEK, 96-bit IV
- AAD is `ASCII(BASE64URL(protected header))`
- Protected header carries `kid` = the `id` of the chosen server key

Five segments: `protected.encrypted_key.iv.ciphertext.tag`

Cache server keys (the SDK refreshes hourly). If several are returned, any may be
used; record which `kid` was chosen.

## Invoice JSON

Shape is `{"header": {...}, "body": [...], "payments": [...], "extension": [...]}`
— full field list in `RC_IITP_IS_V7_9_1.pdf` §9-3 (p.97).

Serialisation rules for the bytes that get signed:

- **Omit null/unset fields entirely.** Confirmed by the doc's own p.20 example,
  which contains no nulls.
- Compact separators, no spaces.
- `ensure_ascii=False` — Persian text goes out as UTF-8, not `\uXXXX`.
- Field names are the wire names verbatim (`taxid`, `indatim`, `tprdis`). Never
  rename; a rename is invisible until the organization rejects the invoice.

## Submission envelope

`POST /invoice` takes a **list** of packets:

```json
[{"payload": "<JWE compact>",
  "header": {"requestTraceId": "<uuid>", "fiscalId": "<memoryId>"}}]
```

`requestTraceId` is the client-generated `uid` used later for inquiry. Response:
`{"timestamp": 0, "result": [{"uid", "packetType", "referenceNumber", "data"}]}`

Wait **≥10 seconds** after submission before inquiring; a status of `IN_PROGRESS`
means keep polling.

## TaxId (شماره منحصر به فرد مالیاتی)

```
taxid = upper( memoryId
              + hex(day_range).rjust(5,'0')
              + hex(serial).rjust(10,'0')
              + verhoeff_check_digit(control) )

day_range = floor(epoch_seconds(issue_datetime) / 86400)
control   = decimalise(memoryId) + str(day_range).rjust(6,'0')
                                 + str(serial).rjust(12,'0')
```

`decimalise` maps each character of `memoryId`: digits stay, letters become their
ordinal (`ord(ch)`, so `A` → `65`).

- **Pin the timezone to Asia/Tehran.** `day_range` is derived from a local-time
  epoch in the reference implementation, so a UTC host and a Tehran host disagree
  near midnight.
- `serial` must be **non-repeating** per fiscal memory — use a persisted monotonic
  counter, not a random draw (the SDK samples use `Random`, which can collide).
- `inno` (invoice serial) is `hex(serial).rjust(10,'0')`.

## Error envelope

```json
{"timestamp": 1786797257758,
 "requestTraceId": "2444eefb...",
 "errors": [{"code": "4100", "message": "متد درخواست ارسالی پشتیبانی نمی‌شود."}]}
```

Codes are catalogued in `Docs/کدهای خطا.pdf`.
