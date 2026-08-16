"""Connectivity and conformance probe for both Moadian environments.

Run this from a network that can reach `tax.gov.ir` and paste the output back.
It needs **no certificate**: `GET /nonce` is the one unauthenticated resource, so
this establishes DNS, TLS, routing and the response contract before any
credential exists.

    cd backend
    .venv/bin/python tools/check_connectivity.py

Options:
    --environment sandbox|production|both   (default: both)
    --ttl N                                 request a nonce TTL, default 30
    --timeout S                             per-request timeout, default 20

Every check is read-only and sends at most a couple of requests per environment.
Nothing here submits an invoice or mutates state.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import ssl
import sys
import time
from datetime import UTC, datetime
from typing import Any

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))

from moadian.config import Environment  # noqa: E402

#: `<uuid4>-<epochMillis>` — WIRE_FORMAT.md "Authentication".
NONCE_RE = re.compile(r"^[0-9a-fA-F-]{36}-\d{13}$")

#: RFC 2544 benchmarking range. Resolving here means DNS is being sinkholed, not
#: that the service is down — worth calling out so it is not misread as an outage.
SINKHOLE_PREFIXES = ("198.18.", "198.19.", "0.0.0.0", "127.0.0.1")

OK, BAD, WARN = "PASS", "FAIL", "WARN"


def _line(status: str, label: str, detail: str = "") -> None:
    print(f"  [{status:4}] {label}" + (f" — {detail}" if detail else ""))


def resolve(host: str) -> tuple[str, list[str]]:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        return BAD, [f"DNS lookup failed: {exc}"]
    addresses = sorted({info[4][0] for info in infos})
    if any(a.startswith(SINKHOLE_PREFIXES) for a in addresses):
        return WARN, addresses
    return OK, addresses


def tls_probe(host: str, timeout: float) -> tuple[str, str]:
    """Confirm a TLS handshake completes and report the peer certificate's issuer."""
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                cert = tls.getpeercert() or {}
                issuer = dict(x[0] for x in cert.get("issuer", ()))  # type: ignore[misc]
                name = issuer.get("organizationName") or issuer.get("commonName") or "?"
                return OK, f"{tls.version()}, issued by {name}"
    except (TimeoutError, OSError, ssl.SSLError) as exc:
        return BAD, f"{type(exc).__name__}: {exc}"


def parse_exp_date(value: str) -> datetime | None:
    """The fractional part has been observed with more digits than fromisoformat takes."""
    text = value.rstrip("Z")
    if "." in text:
        whole, _, fraction = text.partition(".")
        text = f"{whole}.{fraction[:6]}"
    try:
        return datetime.fromisoformat(text).replace(tzinfo=UTC)
    except ValueError:
        return None


def check_environment(env: Environment, ttl: int, timeout: float) -> dict[str, Any]:
    base = env.base_url
    print(f"\n{env.value.upper()}  ({env.label})  {base}")

    report: dict[str, Any] = {"environment": env.value, "base_url": base, "checks": {}}

    status, addresses = resolve(env.host)
    report["checks"]["dns"] = {"status": status, "addresses": addresses}
    if status == WARN:
        _line(
            WARN,
            "DNS",
            f"{', '.join(addresses)} — inside the RFC 2544 sinkhole range; "
            "this network is intercepting the name, the service is not down",
        )
    elif status == BAD:
        _line(BAD, "DNS", addresses[0])
        return report
    else:
        _line(OK, "DNS", ", ".join(addresses))

    tls_status, tls_detail = tls_probe(env.host, timeout)
    report["checks"]["tls"] = {"status": tls_status, "detail": tls_detail}
    _line(tls_status, "TLS handshake", tls_detail)

    url = f"{base}/api/v2/nonce"
    started = time.monotonic()
    try:
        response = httpx.get(
            url, params={"timeToLive": ttl}, timeout=timeout, headers={"Accept": "*/*"}
        )
    except httpx.HTTPError as exc:
        report["checks"]["nonce"] = {"status": BAD, "error": f"{type(exc).__name__}: {exc}"}
        _line(BAD, "GET /nonce", f"{type(exc).__name__}: {exc}")
        return report
    elapsed_ms = round((time.monotonic() - started) * 1000)

    nonce_check: dict[str, Any] = {"http_status": response.status_code, "elapsed_ms": elapsed_ms}
    if response.status_code != 200:
        nonce_check["status"] = BAD
        nonce_check["body"] = response.text[:400]
        _line(BAD, "GET /nonce", f"HTTP {response.status_code} in {elapsed_ms} ms")
        print(f"         body: {response.text[:300]}")
        report["checks"]["nonce"] = nonce_check
        return report

    _line(OK, "GET /nonce", f"HTTP 200 in {elapsed_ms} ms")

    try:
        body = response.json()
    except json.JSONDecodeError:
        nonce_check["status"] = BAD
        _line(BAD, "nonce body", "not JSON")
        report["checks"]["nonce"] = nonce_check
        return report

    nonce, exp_date = body.get("nonce", ""), body.get("expDate", "")
    nonce_check["nonce_shape_ok"] = bool(NONCE_RE.match(nonce))
    _line(
        OK if nonce_check["nonce_shape_ok"] else BAD,
        "nonce shape",
        f"{nonce!r} " + ("matches <uuid>-<epochMillis>" if nonce_check["nonce_shape_ok"] else "DOES NOT match <uuid>-<epochMillis>"),
    )

    parsed = parse_exp_date(exp_date)
    if parsed is None:
        nonce_check["status"] = WARN
        _line(WARN, "expDate", f"unparseable: {exp_date!r}")
    else:
        granted = round((parsed - datetime.now(UTC)).total_seconds())
        nonce_check["ttl_requested"] = ttl
        nonce_check["ttl_granted_approx"] = granted
        nonce_check["status"] = OK
        note = f"asked {ttl}s, granted ~{granted}s"
        if abs(granted - ttl) > 5:
            note += "  (the service grants what it likes; expDate is authoritative)"
        _line(OK, "expDate", note)

    # Two nonces must differ — this is a single-use challenge.
    try:
        second = httpx.get(url, params={"timeToLive": ttl}, timeout=timeout).json().get("nonce")
        distinct = second != nonce
        nonce_check["distinct_across_calls"] = distinct
        _line(OK if distinct else BAD, "nonce is fresh per call", "" if distinct else "REPEATED")
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        _line(WARN, "second nonce", f"{type(exc).__name__}: {exc}")

    report["checks"]["nonce"] = nonce_check
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default="both", help="sandbox, production, or both")
    parser.add_argument("--ttl", type=int, default=30)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--json", action="store_true", help="also dump the raw report as JSON")
    args = parser.parse_args()

    if args.environment == "both":
        targets = list(Environment)
    else:
        targets = [Environment.parse(args.environment)]

    print("Moadian connectivity probe — unauthenticated, read-only")
    print(f"started {datetime.now(UTC).isoformat(timespec='seconds')}")

    reports = [check_environment(env, args.ttl, args.timeout) for env in targets]

    reachable = [
        r for r in reports if r["checks"].get("nonce", {}).get("http_status") == 200
    ]
    print(f"\n{len(reachable)}/{len(reports)} environment(s) answered a well-formed nonce.")
    if not reachable:
        print(
            "Nothing was reachable. If DNS showed a 198.18.x address, this network is\n"
            "intercepting tax.gov.ir — switch provider and re-run before reading\n"
            "anything into the result."
        )

    if args.json:
        print("\n--- raw report ---")
        print(json.dumps(reports, indent=2, ensure_ascii=False))

    return 0 if reachable else 1


if __name__ == "__main__":
    raise SystemExit(main())
