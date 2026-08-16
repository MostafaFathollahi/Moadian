# Conformance vectors

Artifacts the test suite checks our wire format against. Nothing here is a
fixture we invented — each item comes from the organization's own documents.

| File | What it is |
|---|---|
| `RC_TICS_extracted.txt` | Extracted text of `Docs/دستورالعمل فنی اتصال به سامانه مودیان.pdf` (`RC_TICS.IS_v1.6`). RTL extraction mangles Persian prose, but base64 and JSON survive intact — which is all the vectors need. |
| `error_codes_extracted.txt` | Extracted text of `Docs/کدهای خطا.pdf`, the source for `moadian.errors.ERROR_CODES`. |
| `sample_keypair/` | The vendor's published sample signing keypair. See below. |
| `test_official_vector.py` | The canary: byte-exact reproduction of the JWS documented on p.13. |
| `poc_crypto.py`, `verify_official_vector.py` | The original standalone proofs, kept as readable references. |

## Why a private key is committed here

`sample_keypair/` holds `cert1.crt` and `privatekey1.pem` — a real, loadable RSA
keypair, committed on purpose, with a narrow `.gitignore` exception. That is
normally the wrong thing to do, so here is the reasoning.

**It is not a secret.** Both halves are printed verbatim in a public government
PDF: the certificate is the `x5c` of the worked example on p.13 of RC_TICS, and
the matching private key is printed in the appendix of the same document. It also
ships in the vendor's own `TaxCollectData.Sample`.

**It cannot be used against anything.** It expired on **2024-03-23**, it is
self-issued by the SDK vendor rather than by an Iranian intermediate CA, and the
organization validates signing certificates via OCSP and CRL against the issuing
CA. It authenticates to nothing.

**The canary needs it.** `test_official_vector.py` proves that `Pkcs8Signatory`
reproduces the officially documented token byte for byte — the one test that
checks our JWS against the organization's output rather than against our own
assumptions. Reproducing a signature requires the private key that made it.

**The alternative was worse.** This keypair was previously read out of `SDK/`,
which `.gitignore` excludes. So on every fresh clone and every CI runner the
fixture was absent, the test called `pytest.skip`, and **the suite reported green
with its most important test silently missing** — verified: `3 passed, 5 skipped`,
exit 0. A deliberate, documented, allowlisted copy is safer than an accidental
one, and the key was in any case already riding along inside
`RC_TICS_extracted.txt` where nobody had noticed it. That copy has since been
stripped, so exactly one lives here.

The lookup now **raises** instead of skipping. If the keypair goes missing the
suite goes red, which is the only behaviour that makes a canary worth having.

> **Never use this keypair for anything but the conformance test.** Real
> submission needs a certificate from an Iranian intermediate CA whose subject
> `SERIALNUMBER` matches a شناسه ملی with send-permission for your fiscal memory.
