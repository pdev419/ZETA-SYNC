from __future__ import annotations

import ssl
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TLSPaths:
    ca_cert: Path
    node_cert: Path
    node_key: Path


def build_server_ssl_context(paths: TLSPaths) -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(certfile=str(paths.node_cert), keyfile=str(paths.node_key))
    ctx.load_verify_locations(cafile=str(paths.ca_cert))
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = False
    return ctx


def build_client_ssl_context(paths: TLSPaths) -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.load_cert_chain(certfile=str(paths.node_cert), keyfile=str(paths.node_key))
    ctx.load_verify_locations(cafile=str(paths.ca_cert))
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = False
    return ctx
