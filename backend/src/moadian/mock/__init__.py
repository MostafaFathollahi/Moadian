"""A local impersonation of the tax collection API, used as a correctness oracle.

The real API cannot be exercised without a CA-issued certificate; this app runs
the same server-side verification against a development one. See
``moadian.mock.server``.
"""

from moadian.mock.server import (
    MockState,
    NonceRecord,
    StoredSubmission,
    create_mock_app,
)

__all__ = ["create_mock_app", "MockState", "NonceRecord", "StoredSubmission"]
