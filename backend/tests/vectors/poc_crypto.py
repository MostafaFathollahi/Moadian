"""Proof of concept: reproduce the SDK's JWS + JWE in Python, using only `cryptography`.

Mirrors JwsSignatory.cs (RS256, headers x5c/sigT/typ/crit/cty) and
JweEncryptor.cs (RSA-OAEP-256 + A256GCM compact, `kid` header).

Run: python3 poc_crypto.py dev-certs
"""

import base64
import datetime
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509 import load_pem_x509_certificate


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def canonical_json(obj) -> bytes:
    """Compact, non-ASCII-escaped, nulls omitted.

    Matches src/JsonSerializer.cs (DefaultIgnoreCondition = WhenWritingNull) plus
    UnsafeRelaxedJsonEscaping, which is what leaves Persian text unescaped.
    """
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if v is not None}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o

    return json.dumps(
        strip(obj), separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


# ---------------------------------------------------------------- JWS (sign)

def sign_jws(payload: bytes, private_key, cert) -> str:
    """Compact JWS, RS256, with the tax API's required protected headers."""
    # Exactly the four headers RC_TICS.IS_v1.6 specifies (§5-1-2 and §7-1-2), in the
    # order its worked examples use. The .NET SDK additionally sends typ:jose and
    # cty:text/plain; those are NOT in the spec, so we omit them.
    header = {
        "crit": ["sigT"],
        # "yyyy-MM-dd'T'HH:mm:ss'Z'", UTC
        "sigT": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # DER of the cert, base64 (standard, NOT base64url) -- per RFC 7515 x5c
        "x5c": [base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()],
        "alg": "RS256",
    }
    protected = b64u(json.dumps(header, separators=(",", ":")).encode())
    body = b64u(payload)
    signing_input = f"{protected}.{body}".encode()
    sig = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{protected}.{body}.{b64u(sig)}"


def verify_jws(token: str) -> dict:
    """Verify using the certificate embedded in the token's own x5c header."""
    protected_b64, body_b64, sig_b64 = token.split(".")
    header = json.loads(b64u_dec(protected_b64))
    embedded = load_pem_x509_certificate(
        b"-----BEGIN CERTIFICATE-----\n"
        + base64.b64encode(base64.b64decode(header["x5c"][0]))
        + b"\n-----END CERTIFICATE-----\n"
    )
    embedded.public_key().verify(
        b64u_dec(sig_b64),
        f"{protected_b64}.{body_b64}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return header


# ------------------------------------------------------------- JWE (encrypt)

def encrypt_jwe(plaintext: str, org_public_key, key_id: str) -> str:
    """Compact JWE: RSA-OAEP-256 key wrap + A256GCM content encryption."""
    header = {"alg": "RSA-OAEP-256", "enc": "A256GCM", "kid": key_id}
    protected = b64u(json.dumps(header, separators=(",", ":")).encode())

    cek = os.urandom(32)
    iv = os.urandom(12)

    encrypted_key = org_public_key.encrypt(
        cek,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    # AAD is the ASCII of the encoded protected header
    ct_and_tag = AESGCM(cek).encrypt(iv, plaintext.encode("utf-8"), protected.encode("ascii"))
    ciphertext, tag = ct_and_tag[:-16], ct_and_tag[-16:]

    return ".".join([protected, b64u(encrypted_key), b64u(iv), b64u(ciphertext), b64u(tag)])


def decrypt_jwe(token: str, org_private_key) -> str:
    """What the tax organization's server does on receipt."""
    protected, ek, iv, ct, tag = token.split(".")
    cek = org_private_key.decrypt(
        b64u_dec(ek),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return AESGCM(cek).decrypt(
        b64u_dec(iv), b64u_dec(ct) + b64u_dec(tag), protected.encode("ascii")
    ).decode("utf-8")


# ------------------------------------------------------------------- driver

if __name__ == "__main__":
    certs = Path(sys.argv[1] if len(sys.argv) > 1 else "dev-certs")

    private_key = serialization.load_pem_private_key(
        (certs / "privatekey.pem").read_bytes(), password=None
    )
    cert = load_pem_x509_certificate((certs / "certificate.crt").read_bytes())

    # A minimal پترن-۱ invoice, with unset optional fields left as None to
    # exercise the null-omission rule.
    invoice = {
        "header": {
            "taxid": "A11216000AB00000123C4",
            "indatim": 1755259200000,
            "inty": 1, "inp": 1, "ins": 1,
            "irtaxid": None, "scln": None,        # unset -> must not appear
            "tins": "14003778990",
            "tinb": "10100302746",
            "tprdis": 20000, "tdis": 500, "tadis": 19500,
            "tvam": 1755, "todam": 0, "tbill": 21255, "setm": 2,
        },
        "body": [{
            "sstid": "2710000138624",
            "sstt": "سرسیلندر قطعات صنعت فولاد سازی",
            "mu": "164", "am": 2, "fee": 10000,
            "prdis": 20000, "dis": 500, "adis": 19500,
            "vra": 9, "vam": 1755, "tsstam": 21255,
        }],
    }

    payload = canonical_json(invoice)
    assert b"irtaxid" not in payload, "null field leaked into signed payload"
    assert "سرسیلندر".encode() in payload, "Persian text was escaped"
    print(f"1. canonical JSON      {len(payload)} bytes, nulls omitted, Persian unescaped")

    # --- Sign, as the مودی
    jws = sign_jws(payload, private_key, cert)
    header = verify_jws(jws)
    print(f"2. JWS RS256           verified · {len(jws)} chars")
    print(f"   protected headers   {', '.join(header)}")
    print(f"   sigT                {header['sigT']}")

    # --- Encrypt to the organization. Stand in for the key that the real
    #     GET /server-information would hand back.
    org_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwe = encrypt_jwe(jws, org_key.public_key(), key_id="dev-key-1")
    print(f"3. JWE OAEP-256/A256GCM {len(jwe)} chars, 5 compact segments")

    # --- Decrypt + verify, as the organization's server would
    recovered_jws = decrypt_jwe(jwe, org_key)
    assert recovered_jws == jws
    verify_jws(recovered_jws)
    recovered = json.loads(b64u_dec(recovered_jws.split(".")[1]))
    assert recovered == json.loads(payload)
    print("4. server-side          decrypted, signature verified, invoice matches")
    print(f"\n   round trip intact: {recovered['body'][0]['sstt']}")
