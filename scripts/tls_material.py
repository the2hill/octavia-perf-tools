#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def write(path: pathlib.Path, content: str, mode: int = 0o600) -> None:
    path.write_text(content)
    path.chmod(mode)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate disposable TLS material for Octavia benchmarks")
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--backend-ip", action="append", default=[])
    ap.add_argument("--key-bits", type=int, default=2048)
    ap.add_argument("--ca-key-bits", type=int, default=4096)
    ap.add_argument("--days", type=int, default=3650)
    args = ap.parse_args()

    if not shutil.which("openssl"):
        raise SystemExit("openssl is required to generate benchmark TLS material")
    if not args.backend_ip:
        raise SystemExit("at least one --backend-ip is required")

    root = pathlib.Path(args.state_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for path in root.iterdir():
        if path.is_file():
            path.unlink()

    ca_key = root / "ca.key"
    ca_crt = root / "ca.crt"
    frontend_key = root / "frontend.key"
    frontend_csr = root / "frontend.csr"
    frontend_crt = root / "frontend.crt"
    frontend_p12 = root / "frontend.p12"
    backend_key = root / "backend.key"
    backend_csr = root / "backend.csr"
    backend_crt = root / "backend.crt"
    serial = root / "ca.srl"

    run("openssl", "genrsa", "-out", str(ca_key), str(args.ca_key_bits))
    run(
        "openssl", "req", "-x509", "-new", "-sha256", "-nodes",
        "-key", str(ca_key), "-days", str(args.days),
        "-subj", "/CN=octavia-perf-benchmark-ca",
        "-out", str(ca_crt),
    )

    run("openssl", "genrsa", "-out", str(frontend_key), str(args.key_bits))
    run(
        "openssl", "req", "-new", "-sha256", "-key", str(frontend_key),
        "-subj", "/CN=octavia-perf.local", "-out", str(frontend_csr),
    )
    frontend_ext = root / "frontend.ext"
    write(
        frontend_ext,
        "subjectAltName=DNS:octavia-perf.local\n"
        "extendedKeyUsage=serverAuth\n"
        "keyUsage=digitalSignature,keyEncipherment\n",
        0o644,
    )
    run(
        "openssl", "x509", "-req", "-sha256", "-in", str(frontend_csr),
        "-CA", str(ca_crt), "-CAkey", str(ca_key), "-CAcreateserial",
        "-days", str(args.days), "-extfile", str(frontend_ext),
        "-out", str(frontend_crt),
    )
    run(
        "openssl", "pkcs12", "-export", "-inkey", str(frontend_key),
        "-in", str(frontend_crt), "-certfile", str(ca_crt),
        "-passout", "pass:", "-out", str(frontend_p12),
    )

    run("openssl", "genrsa", "-out", str(backend_key), str(args.key_bits))
    run(
        "openssl", "req", "-new", "-sha256", "-key", str(backend_key),
        "-subj", "/CN=octavia-perf-backend", "-out", str(backend_csr),
    )
    san = ",".join(f"IP:{ip}" for ip in args.backend_ip)
    backend_ext = root / "backend.ext"
    write(
        backend_ext,
        f"subjectAltName={san}\n"
        "extendedKeyUsage=serverAuth\n"
        "keyUsage=digitalSignature,keyEncipherment\n",
        0o644,
    )
    run(
        "openssl", "x509", "-req", "-sha256", "-in", str(backend_csr),
        "-CA", str(ca_crt), "-CAkey", str(ca_key),
        "-CAserial", str(serial), "-days", str(args.days),
        "-extfile", str(backend_ext), "-out", str(backend_crt),
    )

    for path in (ca_key, frontend_key, backend_key, frontend_p12):
        path.chmod(0o600)
    for path in (ca_crt, frontend_crt, backend_crt):
        path.chmod(0o644)

    meta = {
        "backend_ips": args.backend_ip,
        "key_bits": args.key_bits,
        "ca_key_bits": args.ca_key_bits,
        "certificate_days": args.days,
        "ca_sha256": hashlib.sha256(ca_crt.read_bytes()).hexdigest(),
        "frontend_cert_sha256": hashlib.sha256(frontend_crt.read_bytes()).hexdigest(),
        "backend_cert_sha256": hashlib.sha256(backend_crt.read_bytes()).hexdigest(),
    }
    (root / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
