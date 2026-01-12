from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


@dataclass(frozen=True)
class CAPaths:
    ca_key: Path
    ca_cert: Path


def sha256_fingerprint_from_cert_pem(pem_bytes: bytes) -> str:
    cert = x509.load_pem_x509_certificate(pem_bytes)
    der = cert.public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(der).hexdigest()


def ensure_cluster_ca(paths: CAPaths, validity_days: int = 3650, common_name: str = "ZETA-SYNC Cluster CA") -> None:
    paths.ca_key.parent.mkdir(parents=True, exist_ok=True)

    if paths.ca_key.exists() and paths.ca_cert.exists():
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ZETA-SYNC"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])

    now = dt.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=validity_days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    paths.ca_key.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    paths.ca_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def load_ca(paths: CAPaths) -> Tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = serialization.load_pem_private_key(paths.ca_key.read_bytes(), password=None)
    cert = x509.load_pem_x509_certificate(paths.ca_cert.read_bytes())
    return key, cert


def issue_node_cert(
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
    node_id: str,
    validity_days: int = 365,
) -> Tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ZETA-SYNC"),
        x509.NameAttribute(NameOID.COMMON_NAME, node_id),
    ])

    now = dt.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=validity_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(private_key=ca_key, algorithm=hashes.SHA256())
    )

    node_key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    node_cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return node_key_pem, node_cert_pem


def sign_csr(
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
    csr_pem: bytes,
    validity_days: int = 365,
) -> bytes:
    csr = x509.load_pem_x509_csr(csr_pem)
    now = dt.datetime.utcnow()

    cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(ca_cert.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=validity_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


def cert_subject_dict_from_cert_pem(cert_pem: bytes) -> Dict[str, Any]:
    cert = x509.load_pem_x509_certificate(cert_pem)
    out: Dict[str, Any] = {}
    for rdn in cert.subject.rdns:
        for attr in rdn:
            out[attr.oid._name] = attr.value
    return out


def common_name_from_cert_pem(cert_pem: bytes) -> Optional[str]:
    cert = x509.load_pem_x509_certificate(cert_pem)
    attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    return attrs[0].value if attrs else None
