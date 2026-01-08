from __future__ import annotations
import ssl
from typing import Optional

def build_server_ssl_context(ca_cert_path: str, cert_path: str, key_path: str) -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    ctx.load_verify_locations(cafile=ca_cert_path)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = False
    return ctx

def build_client_ssl_context(ca_cert_path: str, cert_path: str, key_path: str) -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_cert_path)
    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    ctx.check_hostname = False
    return ctx

def extract_node_id_from_ssl_object(sslobj: ssl.SSLObject) -> Optional[str]:
    """
    Extract node_id from certificate CN.
    For production: use SAN and strict parsing.
    """
    cert = sslobj.getpeercert()
    if not cert:
        return None
    subject = cert.get("subject", [])
    for tup in subject:
        for key, value in tup:
            if key == "commonName":
                return value
    return None
