"""HTTP の層の守り。応答のヘッダー、本文の大きさの上限、接続元の判定。"""
import ipaddress
import json
import os

from fastapi import Request

from . import auth

# この API が画面も配る手元の開発用。本番の画面は Firebase Hosting が配り、そのヘッダーは firebase.json にある。
# 文字はすべて textContent で入れ、外部のスクリプトも読まないので、最も厳しい形にできる。
# Trusted Types を必須にして、innerHTML などに文字列を渡す書き方そのものをブラウザに拒否させる。
# 許すポリシーは mushitori だけで、Service Worker の登録（web/offline.js）にだけ使う。
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self'",
        "connect-src 'self'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "require-trusted-types-for 'script'",
        "trusted-types mushitori",
    ]
)

BASE_HEADERS = {
    "content-security-policy": CONTENT_SECURITY_POLICY,
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    # Google ログインのポップアップが、開いた側に結果を返せるようにする
    "cross-origin-opener-policy": "same-origin-allow-popups",
    "cross-origin-resource-policy": "same-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()",
}
# トークン、コード、生徒の結果を返すので、APIの応答はどこにも保存させない
API_CACHE_CONTROL = "no-store"
HSTS = "max-age=63072000; includeSubDomains"


class SecurityHeaders:
    """すべての応答にセキュリティヘッダーを付ける ASGI ミドルウェア。"""

    def __init__(self, app, https_only: bool) -> None:
        self.app = app
        self.https_only = https_only

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_api = scope["path"].startswith("/v1/")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                extra = dict(BASE_HEADERS)
                if is_api:
                    extra["cache-control"] = API_CACHE_CONTROL
                if self.https_only:
                    extra["strict-transport-security"] = HSTS
                # 同じ名前のヘッダーは上書きし、実装を明かす server ヘッダーは消す
                replaced = {name.encode("latin-1") for name in extra} | {b"server"}
                headers = [(name, value) for name, value in message.get("headers", []) if name.lower() not in replaced]
                headers += [(name.encode("latin-1"), value.encode("latin-1")) for name, value in extra.items()]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodyTooLarge(Exception):
    pass


class BodyLimit:
    """本文の大きさを、ハンドラーが読み込む前に制限する ASGI ミドルウェア。

    Content-Length を見て先に断り、宣言がない（chunked）ときは受け取りながら数える。
    """

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared is not None:
            try:
                too_large = int(declared) > self.max_bytes
            except ValueError:
                too_large = True
            if too_large:
                return await _reject(send, 413, "本文が大きすぎます")
        received = 0
        started = False

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except BodyTooLarge:
            if not started:
                await _reject(send, 413, "本文が大きすぎます")


async def _reject(send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii"))],
        }
    )
    await send({"type": "http.response.body", "body": body})


def trusted_proxy_hops() -> int:
    """X-Forwarded-For のうち、右から何番目までを信用するか。

    Cloud Run は受け取った X-Forwarded-For の右端に接続元を足すので、右端の1つだけが信用できる。
    それより左は送り手が自由に書ける。Cloud Run の上では K_SERVICE が必ず設定されるので、既定で1にする。
    """
    value = os.environ.get("TRUSTED_PROXY_HOPS")
    if value is None:
        return 1 if os.environ.get("K_SERVICE") else 0
    return max(0, min(int(value), 5))


def client_address(request: Request) -> str:
    hops = trusted_proxy_hops()
    address = request.client.host if request.client else ""
    if hops:
        forwarded = [part.strip() for value in request.headers.getlist("x-forwarded-for") for part in value.split(",") if part.strip()]
        if len(forwarded) >= hops:
            address = forwarded[-hops]
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return "unknown"
    if parsed.version == 4:
        return str(parsed)
    if parsed.ipv4_mapped is not None:
        return str(parsed.ipv4_mapped)
    # IPv6 は1つの回線に /64 がまるごと割り当てられるので、/64 単位で数える
    return str(ipaddress.ip_network(f"{parsed}/64", strict=False))


def forwarded_count(request: Request) -> int:
    """X-Forwarded-For の項目数。アドレスは残さず、何段の中継を通ったかだけを監査ログに出す。

    Firebase Hosting を通すと項目が増える見込みで、TRUSTED_PROXY_HOPS を決める手がかりにする。
    """
    return sum(len([part for part in value.split(",") if part.strip()]) for value in request.headers.getlist("x-forwarded-for"))


def client_key(request: Request) -> str:
    """接続元を、保存や記録に使える形（鍵付きハッシュ）にする。生のアドレスは残さない。"""
    return auth.keyed_hash(auth.PURPOSE_CLIENT, client_address(request))[:32]
