"""Generate a development signing certificate for Moadian SDK work.

Mirrors the structure of the vendor's own sample cert (TaxCollectData.Sample/cert1.crt):
the X.509 subject serialNumber carries the taxpayer's شناسه ملی, which must match the
`tins` field of invoices signed with it.

NOT usable against the real tax API -- the organization validates the chain against
Iranian intermediate CAs. Local development and mock-server testing only.
"""

import datetime
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _write_private(path: Path, data: bytes) -> None:
    """Write key material at 0o600 from the moment the file exists.

    `write_bytes()` followed by `chmod()` leaves a window in which the
    unencrypted PKCS#8 key sits at the umask default (0o644 on a typical
    developer box) and any local process can read it. `os.open` with the mode
    argument closes that window: the permissions are set by the creating
    syscall. `O_TRUNC` still re-uses the mode of a *pre-existing* file, so an
    already-loose file is tightened explicitly afterwards.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.chmod(path, 0o600)


def generate(out_dir: Path, national_id: str, common_name: str, org: str, days: int):
    out_dir.mkdir(parents=True, exist_ok=True)

    # The org's own certs are RSA-2048; JWS here is RS256.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "IR"),
        # This is the binding the tax org cares about: must equal invoice `tins`.
        x509.NameAttribute(NameOID.SERIAL_NUMBER, national_id),
    ])

    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)  # self-issued, as the vendor's sample effectively is
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,  # nonRepudiation -- what a signing cert asserts
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    # PKCS#8 PEM, unencrypted -- the format Pkcs8SignatoryFactory expects.
    key_path = out_dir / "privatekey.pem"
    _write_private(
        key_path,
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )

    cert_path = out_dir / "certificate.crt"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    pub_path = out_dir / "publickey.pem"
    pub_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    return key_path, cert_path, pub_path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dev-certs")
    paths = generate(
        out_dir=out,
        national_id="14003778990",   # same شناسه ملی the SDK samples use as `tins`
        common_name="Moadian Dev",
        org="Moadian Framework Development",
        days=825,
    )
    for p in paths:
        print(f"  {p}")
