"""校内LAN版を教員PCで起動する。

    # apps/api で実行する。ネットがつながっているうちに1回だけ：クラウドの公開鍵を保存する
    .venv/bin/python scripts/lan.py --fetch-key https://mushitori-hackathon.web.app

    # 授業でネットが落ちたら：LAN だけで起動する（以後インターネットには接続しない）
    .venv/bin/python scripts/lan.py

初回の起動で、この PC 専用の秘密、保存ファイルの鍵、通信の暗号化に使う証明書を ~/.mushitori に作る。
フォルダは教員のアカウントだけが読める権限にする。
"""
import argparse
import datetime
import ipaddress
import json
import os
import secrets
import socket
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def private_file(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def lan_address() -> str:
    """この PC の校内LANのアドレス。UDP の connect はパケットを送らず、経路表を引くだけ。"""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("10.255.255.255", 1))
            address = probe.getsockname()[0]
        except OSError:
            address = "127.0.0.1"
    if not ipaddress.ip_address(address).is_private:
        raise SystemExit(f"{address} は私設アドレスではありません。校内LANにつないでから起動してください")
    return address


def ensure_certificate(folder: Path, address: str) -> tuple[Path, Path, str]:
    """この PC のアドレスに対する自己署名の証明書。生徒の端末には、学校の管理コンソールから信頼させる。"""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    cert_path, key_path = folder / "tls.crt", folder / "tls.key"
    # 生徒は LAN のアドレス、教員はこの PC（127.0.0.1）から開く
    wanted = {ipaddress.ip_address(address), ipaddress.ip_address("127.0.0.1")}
    if cert_path.exists() and key_path.exists():
        certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
        names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if wanted <= set(names.get_values_for_type(x509.IPAddress)):
            return cert_path, key_path, certificate.fingerprint(hashes.SHA256()).hex(":")
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"mushitori-lan {address}")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(item) for item in sorted(wanted, key=str)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    private_file(key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private_file(cert_path, certificate.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path, certificate.fingerprint(hashes.SHA256()).hex(":")


def fetch_key(base_url: str, folder: Path) -> None:
    if not base_url.startswith("https://"):
        raise SystemExit("公開鍵は https で取得してください")
    context = ssl.create_default_context()
    with urllib.request.urlopen(base_url.rstrip("/") + "/v1/package-key", timeout=15, context=context) as response:
        body = json.loads(response.read())
    pem = body["public_key_pem"]
    if "BEGIN PUBLIC KEY" not in pem:
        raise SystemExit("公開鍵の形が正しくありません")
    private_file(folder / "package-key.pem", pem.encode("ascii"))
    print(f"公開鍵を保存しました（{body['key_id']}）。以後はネットなしで起動できます。")


def main() -> None:
    parser = argparse.ArgumentParser(description="ムシトリの校内LAN版を起動する")
    parser.add_argument("--fetch-key", metavar="URL", help="クラウドの公開鍵を保存して終わる（ネットが必要）")
    parser.add_argument("--port", type=int, default=8443)
    args = parser.parse_args()

    folder = Path(os.environ.get("LAN_DATA_DIR") or Path.home() / ".mushitori")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    if args.fetch_key:
        fetch_key(args.fetch_key, folder)
        return

    secret_path = folder / "session.secret"
    if not secret_path.exists():
        private_file(secret_path, secrets.token_hex(32).encode("ascii"))
    address = lan_address()
    cert_path, key_path, fingerprint = ensure_certificate(folder, address)
    url = f"https://{address}:{args.port}"
    # クラウドにつながる設定は外す。残っていると起動を拒む（app/offline_api.py）
    for name in ("STORE_BACKEND", "SANDBOX_BACKEND", "MODEL_ARMOR_TEMPLATE", "PACKAGE_SIGNING_KEY", "PACKAGE_SIGNING_KMS_KEY", "GOOGLE_CLOUD_PROJECT"):
        os.environ.pop(name, None)
    os.environ.update(
        DEPLOY_MODE="lan",
        APP_ENV="lan",
        SERVE_WEB="1",
        AI_BACKEND="template",
        LAN_DATA_DIR=str(folder),
        LAN_PUBLIC_URL=url,
        SESSION_SECRET=secret_path.read_text().strip(),
        PACKAGE_PUBLIC_KEY_FILE=str(folder / "package-key.pem"),
    )
    if not (folder / "package-key.pem").exists():
        print("注意：クラウドの公開鍵がありません。ネットがあるうちに --fetch-key で保存してください。")
    print(f"生徒が開くアドレス：{url}")
    print(f"教員はこの PC で https://127.0.0.1:{args.port} を開いてください")
    print(f"証明書の指紋（SHA-256）：{fingerprint}")

    import uvicorn

    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=args.port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
        server_header=False,
        app_dir=str(ROOT),
    )


if __name__ == "__main__":
    main()
