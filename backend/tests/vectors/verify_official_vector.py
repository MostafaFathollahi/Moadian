"""Reproduce the official auth-token JWT from the tech guide (RC_TICS.IS_v1.6, p.13).

The doc publishes a complete worked example -- payload, sigT, and the resulting
compact JWS -- signed with the keypair shipped in TaxCollectData.Sample/.
RSASSA-PKCS1-v1_5 is deterministic, so a correct implementation must reproduce
the documented token byte for byte.

This is a conformance oracle that needs neither .NET nor a real certificate.
"""

import base64
import json
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate

GUIDE = Path("tech_guide.txt")
SAMPLE = Path(
    "/Users/llm_client/Desktop/Repos/Moadian/SDK/"
    "tax-collect-data-sdk-dotnet-tax-collect-data-sdk-2.0.32/TaxCollectData.Sample"
)


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def extract_documented_jwt(text: str) -> str:
    """Pull the example token out of the PDF text, which wraps it across lines."""
    start = text.index("eyJjcml0IjpbInNpZ1Qi")
    # The token runs until the following Persian prose. Keep only JWS-legal chars.
    chunk = text[start:start + 4000]
    stop = chunk.index("تکه")
    return re.sub(r"[^A-Za-z0-9_\-.]", "", chunk[:stop])


def main() -> int:
    doc_jwt = extract_documented_jwt(GUIDE.read_text())
    h_b64, p_b64, s_b64 = doc_jwt.split(".")

    header = json.loads(b64u_dec(h_b64))
    payload_bytes = b64u_dec(p_b64)

    print("Documented example (RC_TICS.IS_v1.6, p.13)")
    print(f"  header keys   {list(header)}")
    print(f"  alg           {header['alg']}")
    print(f"  sigT          {header['sigT']}")
    print(f"  crit          {header['crit']}")
    print(f"  payload       {payload_bytes!r}")

    # --- Does the sample certificate's public key verify the documented signature?
    cert = load_pem_x509_certificate((SAMPLE / "cert1.crt").read_bytes())
    embedded_der = base64.b64decode(header["x5c"][0])
    same_cert = embedded_der == cert.public_bytes(serialization.Encoding.DER)
    print(f"\n  x5c == TaxCollectData.Sample/cert1.crt: {same_cert}")

    cert.public_key().verify(
        b64u_dec(s_b64), f"{h_b64}.{p_b64}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    print("  documented signature verifies against cert1.crt  ✓")

    # --- Now re-sign the identical bytes with the shipped private key.
    private_key = serialization.load_pem_private_key(
        (SAMPLE / "privatekey1.pem").read_bytes(), password=None
    )
    signing_input = f"{h_b64}.{p_b64}".encode()
    our_sig = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    our_jwt = f"{h_b64}.{p_b64}.{b64u(our_sig)}"

    print(f"\n  our signature matches documented: {b64u(our_sig) == s_b64}")
    print(f"  full token matches documented:    {our_jwt == doc_jwt}")

    if our_jwt != doc_jwt:
        print("\n  MISMATCH", file=sys.stderr)
        return 1

    # --- Rebuild the header from scratch to confirm we produce identical bytes.
    rebuilt = json.dumps(
        {
            "crit": ["sigT"],
            "sigT": header["sigT"],
            "x5c": [base64.b64encode(embedded_der).decode()],
            "alg": "RS256",
        },
        separators=(",", ":"),
    ).encode()
    print(f"  header rebuilt byte-identical:    {b64u(rebuilt) == h_b64}")
    print("\n  Note: the documented payload is pretty-printed with CRLF, not compact —")
    print("  the server parses it as JSON, so payload formatting is not constrained.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
