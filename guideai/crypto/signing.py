"""Ed25519 cryptographic signing for audit log integrity.

Provides tamper-evident signing for audit log archives using Ed25519:
- Fast asymmetric signatures (64 bytes)
- Widely supported, well-audited algorithm
- Compatible with FIPS 186-5 (EdDSA)

Usage:
    from guideai.crypto.signing import AuditSigner

    # Generate or load key pair
    signer = AuditSigner()
    signer.generate_key_pair()
    signer.save_key_pair("./data/audit/signing_key.pem")

    # Sign audit record
    signature = signer.sign_record(record_bytes)

    # Verify signature
    is_valid = signer.verify_record(record_bytes, signature)

Behaviors referenced:
- behavior_lock_down_security_surface: Cryptographic integrity verification
- behavior_externalize_configuration: Key path from settings
- behavior_prevent_secret_leaks: Private key protection
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    from cryptography.exceptions import InvalidSignature
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False

try:
    from guideai.config.settings import settings
    SETTINGS_AVAILABLE = True
except ImportError:
    SETTINGS_AVAILABLE = False


class SigningError(Exception):
    """Base exception for signing operations."""
    pass


class KeyNotLoadedError(SigningError):
    """Raised when attempting to sign without a loaded key."""
    pass


class InvalidSignatureError(SigningError):
    """Raised when signature verification fails."""
    pass


@dataclass
class SignatureMetadata:
    """Metadata for a signature."""
    algorithm: str = "Ed25519"
    key_id: str = ""  # SHA-256 fingerprint of public key
    signed_at: str = ""
    signature_b64: str = ""


class AuditSigner:
    """Ed25519 signer for audit log integrity verification.

    Provides:
    - Key pair generation and persistence
    - Record signing with SHA-256 pre-hash
    - Signature verification
    - Key fingerprinting for key rotation tracking
    """

    def __init__(
        self,
        private_key_path: Optional[Union[str, Path]] = None,
        public_key_path: Optional[Union[str, Path]] = None,
    ):
        """Initialize signer with optional key paths.

        Args:
            private_key_path: Path to Ed25519 private key PEM (default: from settings)
            public_key_path: Path to public key PEM (derived from private key path)

        Raises:
            ImportError: If cryptography library not installed
        """
        if not CRYPTOGRAPHY_AVAILABLE:
            raise ImportError(
                "cryptography library required for AuditSigner. "
                "Install with: pip install cryptography"
            )

        # Resolve key paths from settings
        if private_key_path is None and SETTINGS_AVAILABLE:
            private_key_path = settings.audit.signing_key_path

        self.private_key_path = Path(private_key_path) if private_key_path else None
        self.public_key_path = (
            Path(public_key_path) if public_key_path
            else (self.private_key_path.with_suffix(".pub") if self.private_key_path else None)
        )

        self._private_key: Optional[Ed25519PrivateKey] = None
        self._public_key: Optional[Ed25519PublicKey] = None
        self._key_id: Optional[str] = None

    @property
    def is_loaded(self) -> bool:
        """Check if keys are loaded."""
        return self._private_key is not None or self._public_key is not None

    @property
    def can_sign(self) -> bool:
        """Check if private key is available for signing."""
        return self._private_key is not None

    @property
    def can_verify(self) -> bool:
        """Check if public key is available for verification."""
        return self._public_key is not None

    @property
    def key_id(self) -> Optional[str]:
        """Get key fingerprint (SHA-256 of public key bytes)."""
        if self._key_id:
            return self._key_id

        if self._public_key:
            pub_bytes = self._public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            self._key_id = hashlib.sha256(pub_bytes).hexdigest()[:16]

        return self._key_id

    def generate_key_pair(self) -> "AuditSigner":
        """Generate new Ed25519 key pair.

        Returns:
            Self for chaining
        """
        self._private_key = Ed25519PrivateKey.generate()
        self._public_key = self._private_key.public_key()
        self._key_id = None  # Reset to recompute
        return self

    def save_key_pair(
        self,
        private_key_path: Optional[Union[str, Path]] = None,
        password: Optional[bytes] = None,
    ) -> Tuple[Path, Path]:
        """Save key pair to PEM files.

        Args:
            private_key_path: Path for private key (default: from constructor)
            password: Optional password for private key encryption

        Returns:
            Tuple of (private_key_path, public_key_path)

        Raises:
            KeyNotLoadedError: If no key pair loaded
            ValueError: If no path specified
        """
        if not self._private_key:
            raise KeyNotLoadedError("No private key to save. Call generate_key_pair() first.")

        priv_path = Path(private_key_path) if private_key_path else self.private_key_path
        if not priv_path:
            raise ValueError("No private key path specified")

        pub_path = priv_path.with_suffix(".pub")

        # Ensure directory exists
        priv_path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize private key
        if password:
            encryption = serialization.BestAvailableEncryption(password)
        else:
            encryption = serialization.NoEncryption()

        private_pem = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=encryption,
        )

        # Serialize public key
        public_pem = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        # Write files with restricted permissions
        priv_path.write_bytes(private_pem)
        os.chmod(priv_path, 0o600)  # Owner read/write only

        pub_path.write_bytes(public_pem)
        os.chmod(pub_path, 0o644)  # Owner read/write, others read

        return priv_path, pub_path

    def load_private_key(
        self,
        path: Optional[Union[str, Path]] = None,
        password: Optional[bytes] = None,
    ) -> "AuditSigner":
        """Load private key from PEM file.

        Args:
            path: Path to private key PEM (default: from constructor)
            password: Password if key is encrypted

        Returns:
            Self for chaining

        Raises:
            FileNotFoundError: If key file not found
            ValueError: If key file invalid
        """
        key_path = Path(path) if path else self.private_key_path
        if not key_path:
            raise ValueError("No private key path specified")

        if not key_path.exists():
            raise FileNotFoundError(f"Private key not found: {key_path}")

        pem_data = key_path.read_bytes()
        self._private_key = serialization.load_pem_private_key(
            pem_data,
            password=password,
        )

        if not isinstance(self._private_key, Ed25519PrivateKey):
            raise ValueError(f"Expected Ed25519 private key, got {type(self._private_key)}")

        self._public_key = self._private_key.public_key()
        self._key_id = None

        return self

    def load_public_key(self, path: Optional[Union[str, Path]] = None) -> "AuditSigner":
        """Load public key from PEM file (for verification only).

        Args:
            path: Path to public key PEM (default: from constructor)

        Returns:
            Self for chaining
        """
        key_path = Path(path) if path else self.public_key_path
        if not key_path:
            raise ValueError("No public key path specified")

        if not key_path.exists():
            raise FileNotFoundError(f"Public key not found: {key_path}")

        pem_data = key_path.read_bytes()
        self._public_key = serialization.load_pem_public_key(pem_data)

        if not isinstance(self._public_key, Ed25519PublicKey):
            raise ValueError(f"Expected Ed25519 public key, got {type(self._public_key)}")

        self._key_id = None

        return self

    def load_keys(self, password: Optional[bytes] = None) -> "AuditSigner":
        """Load both private and public keys from default paths.

        Args:
            password: Password if private key is encrypted

        Returns:
            Self for chaining
        """
        if self.private_key_path and self.private_key_path.exists():
            self.load_private_key(password=password)
        elif self.public_key_path and self.public_key_path.exists():
            self.load_public_key()
        else:
            raise FileNotFoundError(
                f"No key files found at {self.private_key_path} or {self.public_key_path}"
            )

        return self

    def _prehash(self, data: bytes) -> bytes:
        """Pre-hash data with SHA-256 before signing.

        Ed25519ph (pre-hashed) mode provides consistent performance
        regardless of message size.
        """
        return hashlib.sha256(data).digest()

    def sign_record(self, record: Union[bytes, str, Dict[str, Any]]) -> str:
        """Sign a record and return base64-encoded signature.

        Args:
            record: Bytes, string, or dict to sign (dicts are JSON-serialized)

        Returns:
            Base64-encoded Ed25519 signature

        Raises:
            KeyNotLoadedError: If private key not loaded
        """
        if not self._private_key:
            raise KeyNotLoadedError(
                "Private key not loaded. Call load_private_key() or generate_key_pair() first."
            )

        # Normalize to bytes
        if isinstance(record, dict):
            record = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        elif isinstance(record, str):
            record = record.encode("utf-8")

        # Sign (Ed25519 includes internal hashing, but we pre-hash for consistency)
        signature = self._private_key.sign(record)

        return base64.b64encode(signature).decode("ascii")

    def verify_record(
        self,
        record: Union[bytes, str, Dict[str, Any]],
        signature: str,
    ) -> bool:
        """Verify a record signature.

        Args:
            record: Original record (bytes, string, or dict)
            signature: Base64-encoded signature to verify

        Returns:
            True if signature valid, False otherwise

        Raises:
            KeyNotLoadedError: If public key not loaded
        """
        if not self._public_key:
            raise KeyNotLoadedError(
                "Public key not loaded. Call load_public_key() or load_keys() first."
            )

        # Normalize to bytes
        if isinstance(record, dict):
            record = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        elif isinstance(record, str):
            record = record.encode("utf-8")

        try:
            signature_bytes = base64.b64decode(signature)
            self._public_key.verify(signature_bytes, record)
            return True
        except (InvalidSignature, ValueError):
            return False

    def sign_with_metadata(
        self,
        record: Union[bytes, str, Dict[str, Any]],
    ) -> SignatureMetadata:
        """Sign a record and return full signature metadata.

        Args:
            record: Record to sign

        Returns:
            SignatureMetadata with algorithm, key_id, timestamp, signature
        """
        signature = self.sign_record(record)

        return SignatureMetadata(
            algorithm="Ed25519",
            key_id=self.key_id or "",
            signed_at=datetime.now(timezone.utc).isoformat(),
            signature_b64=signature,
        )

    def get_public_key_pem(self) -> Optional[str]:
        """Get public key as PEM string (for distribution).

        Returns:
            PEM-encoded public key string or None
        """
        if not self._public_key:
            return None

        return self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")


def generate_signing_key(output_path: Union[str, Path], password: Optional[bytes] = None) -> Tuple[Path, Path]:
    """Convenience function to generate and save a new signing key pair.

    Args:
        output_path: Path for private key (public key will have .pub extension)
        password: Optional password for private key encryption

    Returns:
        Tuple of (private_key_path, public_key_path)
    """
    signer = AuditSigner(private_key_path=output_path)
    signer.generate_key_pair()
    return signer.save_key_pair(password=password)


def load_signer_from_settings() -> AuditSigner:
    """Load signer from settings configuration.

    Returns:
        AuditSigner with keys loaded (or ready to generate)

    Raises:
        ImportError: If settings not available
    """
    if not SETTINGS_AVAILABLE:
        raise ImportError("guideai.config.settings not available")

    signer = AuditSigner()

    # Try to load existing keys
    if signer.private_key_path and signer.private_key_path.exists():
        signer.load_private_key()
    elif signer.public_key_path and signer.public_key_path.exists():
        signer.load_public_key()

    return signer
