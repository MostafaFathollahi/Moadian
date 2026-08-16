"""Framework for issuing electronic invoices to Iran's سامانه مودیان, API v2.

Protocol facts are pinned in ../../WIRE_FORMAT.md. Where the bundled .NET SDK
disagrees with RC_TICS.IS_v1.6, the document wins.

The short path is :class:`InvoicePipeline`::

    async with MoadianClient(base_url=..., client_id=..., signatory=...) as client:
        pipeline = InvoicePipeline(client, signatory, "A11216",
                                   MonotonicSerialCounter(Path("instance/serial")))
        submissions = await pipeline.submit([invoice])
        results = await pipeline.await_results(submissions)

Everything below the pipeline stays usable on its own: ``moadian.crypto`` signs
and encrypts, ``moadian.client`` speaks HTTP, ``moadian.taxid`` builds tax ids.
``moadian.mock`` is deliberately not re-exported — it pulls in FastAPI and is a
test dependency, not a runtime one.
"""

from moadian.client import MoadianClient, build_packet, build_url, endpoints
from moadian.config import Profile, ProfileStore, Settings
from moadian.crypto import (
    JweEncryptor,
    Pkcs8Signatory,
    ServerKey,
    Signatory,
    SigningCredentials,
    canonical_json,
)
from moadian.errors import (
    ERROR_CODES,
    AuthenticationError,
    CertificateError,
    ConfigurationError,
    CryptographyError,
    InvalidTaxIdError,
    InvoiceValidationError,
    MoadianError,
    TaxApiError,
    TransportError,
    UnknownResponseError,
    describe,
)
from moadian.models import (
    ApiError,
    BatchResponse,
    ErrorEnvelope,
    InquiryResult,
    Invoice,
    InvoiceBodyItem,
    InvoiceHeader,
    InvoicePayment,
    InvoiceStatus,
    NonceResponse,
    Packet,
    PacketHeader,
    PaymentMethod,
    RequestStatus,
    ServerInformation,
    SubmitResult,
)
from moadian.pipeline import InvoicePipeline, InvoiceSubmission, MonotonicSerialCounter
from moadian.rules import (
    Obligation,
    RuleEngine,
    Severity,
    ValidationReport,
    Violation,
    recompute,
)
from moadian.taxid import TEHRAN, generate_tax_id, invoice_serial_hex

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # pipeline — the intended entry point
    "InvoicePipeline",
    "InvoiceSubmission",
    "MonotonicSerialCounter",
    # transport
    "MoadianClient",
    "build_packet",
    "build_url",
    "endpoints",
    # crypto
    "Pkcs8Signatory",
    "Signatory",
    "SigningCredentials",
    "JweEncryptor",
    "ServerKey",
    "canonical_json",
    # invoice models
    "Invoice",
    "InvoiceHeader",
    "InvoiceBodyItem",
    "InvoicePayment",
    "Packet",
    "PacketHeader",
    # response models
    "ApiError",
    "BatchResponse",
    "ErrorEnvelope",
    "InquiryResult",
    "NonceResponse",
    "ServerInformation",
    "SubmitResult",
    "InvoiceStatus",
    "PaymentMethod",
    "RequestStatus",
    # validation
    "RuleEngine",
    "ValidationReport",
    "Violation",
    "Severity",
    "Obligation",
    "recompute",
    # tax id
    "TEHRAN",
    "generate_tax_id",
    "invoice_serial_hex",
    # configuration
    "Settings",
    "Profile",
    "ProfileStore",
    # errors
    "MoadianError",
    "AuthenticationError",
    "CertificateError",
    "ConfigurationError",
    "CryptographyError",
    "InvalidTaxIdError",
    "InvoiceValidationError",
    "TaxApiError",
    "TransportError",
    "UnknownResponseError",
    "ERROR_CODES",
    "describe",
]
