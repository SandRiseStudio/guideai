"""Ed25519 cryptographic signing — OSS Stub.

Full implementation moved to guideai-enterprise.
This module re-exports stubs from guideai.crypto for backward compatibility.
"""

from guideai.crypto import (
    AuditSigner,
    SignatureMetadata,
    SigningError,
    KeyNotLoadedError,
    InvalidSignatureError,
    generate_signing_key,
    load_signer_from_settings,
)

__all__ = [
    "AuditSigner",
    "SignatureMetadata",
    "SigningError",
    "KeyNotLoadedError",
    "InvalidSignatureError",
    "generate_signing_key",
    "load_signer_from_settings",
]
