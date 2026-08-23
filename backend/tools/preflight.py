"""Check a real certificate end to end, before it is used to file anything.

Runs in three stages and stops at the first that fails, because a later stage
cannot be interpreted without the earlier one:

1. **Local** — do the certificate and key load, do they match, is the key 2048
   bits, and what کد ملی does the certificate carry? No network.
2. **Reachable** — ``GET /nonce``, which needs no certificate. Separates "this
   network cannot reach tax.gov.ir" from "the certificate was refused", two
   failures that otherwise look identical.
3. **Accepted** — one authenticated call. This is the moment of truth: it is the
   first time the organization judges the certificate, the chain, and whether
   the identity in it may act for this شناسه یکتای حافظه مالیاتی.

Nothing here submits an invoice or changes any state.

    .venv/bin/python tools/preflight.py --memory-id A11216
    .venv/bin/python tools/preflight.py --memory-id B22327 --environment production
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from moadian.client import MoadianClient  # noqa: E402
from moadian.config import Environment, Settings  # noqa: E402
from moadian.crypto import Pkcs8Signatory  # noqa: E402
from moadian.errors import MoadianError, TaxApiError, TransportError  # noqa: E402

OK, BAD, WARN = "PASS", "FAIL", "WARN"


def line(status: str, label: str, detail: str = "") -> None:
    print(f"  [{status:4}] {label}" + (f" — {detail}" if detail else ""))


def stage(title: str) -> None:
    print(f"\n{title}")


def local_checks(settings: Settings, environment: Environment, memory_id: str):
    """Everything answerable without touching the network."""
    stage(f"1. LOCAL — {environment.value} ({environment.label})")

    material = settings.signing_material(environment)
    try:
        cert_path, key_path = material.require()
    except MoadianError as exc:
        line(BAD, "configuration", str(exc))
        return None
    line(OK, "certificate path", str(cert_path))
    line(OK, "private key path", str(key_path))

    try:
        credentials = material.load()
    except MoadianError as exc:
        line(BAD, "load", str(exc))
        print(
            "\n  If the key is encrypted, set MOADIAN_KEY_PASSPHRASE.\n"
            "  If it came from a .pfx, extract it first — see the admin guide."
        )
        return None
    line(OK, "certificate parses", "")
    line(OK, "key matches certificate", "and is not expired")

    key = credentials.private_key
    size = key.key_size if isinstance(key, rsa.RSAPrivateKey) else 0
    # RC_TICS §2 requires 2048; anything else the organization will not accept.
    line(OK if size == 2048 else BAD, "key size", f"{size} bits (spec requires 2048)")

    cert = credentials.certificate
    not_after = cert.not_valid_after_utc
    days = (not_after - datetime.now(UTC)).days
    line(
        OK if days > 30 else (WARN if days > 0 else BAD),
        "validity",
        f"expires {not_after.date()} ({days} days)",
    )

    issuer = cert.issuer.rfc4514_string()
    self_signed = cert.issuer == cert.subject
    line(
        BAD if self_signed else OK,
        "issuer",
        "SELF-SIGNED — the organization will refuse this"
        if self_signed
        else issuer[:90],
    )

    national = credentials.national_id
    line(
        OK if national else BAD,
        "کد ملی in certificate",
        f"{national} (SERIALNUMBER)" if national else "SERIALNUMBER is absent",
    )
    common = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if common:
        line(OK, "subject CN", str(common[0].value))

    print(
        f"\n  This certificate will file as کد ملی {national}. It must match the\n"
        f"  `tins` on your invoices, and must hold send-permission for {memory_id}."
    )
    return credentials


async def network_checks(
    settings: Settings, environment: Environment, memory_id: str, credentials
) -> int:
    base_url = settings.base_url(environment)

    stage(f"2. REACHABLE — {base_url}")
    client = MoadianClient(
        base_url=base_url,
        client_id=memory_id,
        signatory=Pkcs8Signatory(credentials),
        timeout=settings.request_timeout_seconds,
    )
    async with client:
        try:
            nonce = await client.get_nonce()
        except TransportError as exc:
            line(BAD, "GET /nonce", str(exc))
            print(
                "\n  The service was not reached at all, so nothing can be said about\n"
                "  the certificate. Check the network first:\n"
                "    .venv/bin/python tools/check_connectivity.py"
            )
            return 1
        line(OK, "GET /nonce", f"expires {nonce.expDate}")

        stage("3. ACCEPTED — the first time the organization judges this certificate")
        try:
            info = await client.get_server_information()
        except TaxApiError as exc:
            line(BAD, "authenticated call", f"HTTP {exc.status_code}")
            for code, message in exc.errors:
                print(f"         {code}: {message}")
            print(
                "\n  The certificate was reached but refused. The usual causes:\n"
                "    · it has not been uploaded to کارپوشه for this fiscal memory\n"
                "      (RC_TICS §2 — عضویت و ثبت نام, بارگذاری گواهی امضاء);\n"
                "    · the کد ملی in the certificate has no send-permission for it;\n"
                "    · this شناسه یکتا belongs to the other environment."
            )
            return 1
        except MoadianError as exc:
            line(BAD, "authenticated call", str(exc))
            return 1
        line(OK, "authenticated call", f"{len(info.publicKeys)} server key(s) returned")

        try:
            fiscal = await client.get_fiscal_information(memory_id)
        except TaxApiError as exc:
            line(WARN, f"fiscal memory {memory_id}", "; ".join(c for c, _ in exc.errors))
            print("\n  Authentication worked, so the certificate is accepted. This")
            print("  memory id may belong to the other environment, or not to you.")
            return 1
        line(OK, f"fiscal memory {memory_id}", str(getattr(fiscal, "nameTrade", "")))

    print(
        "\n  Ready. The certificate is accepted and the fiscal memory answers.\n"
        "  Next: issue one invoice in the UI, اعتبارسنجی it, then ارسال."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-id", required=True, help="شناسه یکتای حافظه مالیاتی")
    parser.add_argument("--environment", default="sandbox", help="sandbox | production")
    parser.add_argument("--offline", action="store_true", help="stage 1 only")
    args = parser.parse_args()

    settings = Settings()
    environment = Environment.parse(args.environment)

    print("Moadian preflight — reads your configured credentials, sends no invoice")
    if environment.is_production:
        print("  ** PRODUCTION — filings in this environment are real **")

    credentials = local_checks(settings, environment, args.memory_id)
    if credentials is None:
        return 1
    if args.offline:
        return 0
    return asyncio.run(network_checks(settings, environment, args.memory_id, credentials))


if __name__ == "__main__":
    raise SystemExit(main())
