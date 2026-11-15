"""用 Chrome DevTools Protocol 跑 tests/ 下的冒烟测试页。

依次运行 smoke.html（全新安装 / 推荐功课 / 导入清洗）与
upgrade.html（老存档迁移、老用户不误入首次引导）。
不依赖第三方包：只用标准库实现最小的 WebSocket 客户端。
用法：python tests/cdp_smoke.py
"""
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_chrome():
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    raise SystemExit("没有找到 Chrome 或 Edge")


class WS:
    def __init__(self, url):
        # ws://127.0.0.1:port/devtools/page/ID
        rest = url.split("://", 1)[1]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=10)
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        req = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {hostport}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        if b"101" not in buf.split(b"\r\n", 1)[0]:
            raise RuntimeError("WebSocket 握手失败")
        self.buf = b""

    def send(self, obj):
        data = json.dumps(obj).encode()
        header = bytearray([0x81])  # FIN + text
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def _read_exact(self, n):
        out = b""
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise RuntimeError("WebSocket 连接已关闭")
            out += chunk
        return out

    def recv(self):
        while True:
            b1, b2 = self._read_exact(2)
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 8:
                raise RuntimeError("WebSocket 已关闭")
            if opcode == 9:  # ping
                self._send_frame(0x8A, payload)
                continue
            if opcode in (1, 2):
                return payload.decode("utf-8", "replace")

    def _send_frame(self, first, payload):
        header = bytearray([first])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def call(self, mid, method, params=None):
        self.send({"id": mid, "method": method, "params": params or {}})
        while True:
            msg = json.loads(self.recv())
            if msg.get("id") == mid:
                return msg


def run_page(chrome, page_name):
    """在全新 profile 里打开一个测试页，返回 (是否通过, 输出)。"""
    url = "file:///" + os.path.join(ROOT, "tests", page_name).replace("\\", "/")
    profile = tempfile.mkdtemp(prefix="xuefo-cdp-")
    proc = subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            "--allow-file-access-from-files",
            f"--user-data-dir={profile}",
            "--remote-debugging-port=0",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        port_file = os.path.join(profile, "DevToolsActivePort")
        port = None
        for _ in range(100):
            if os.path.exists(port_file):
                with open(port_file, "r", encoding="utf-8") as f:
                    port = f.read().splitlines()[0].strip()
                if port:
                    break
            time.sleep(0.1)
        if not port:
            raise SystemExit("Chrome 没有写出 DevToolsActivePort")

        targets = None
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                    targets = json.loads(r.read().decode())
                if targets:
                    break
            except Exception:
                pass
            time.sleep(0.1)
        if not targets:
            raise SystemExit("没有找到页面 target")

        page = next((t for t in targets if t.get("type") == "page"), targets[0])
        ws = WS(page["webSocketDebuggerUrl"])

        text = ""
        mid = 1
        for _ in range(40):
            time.sleep(0.25)
            res = ws.call(mid, "Runtime.evaluate", {
                "expression": "(document.getElementById('out')||{}).textContent||''",
                "returnByValue": True,
            })
            mid += 1
            text = (((res.get("result") or {}).get("result") or {}).get("value") or "")
            if "SMOKE OK" in text or "SMOKE FAILED" in text:
                break

        return ("SMOKE OK" in text), (text or "（没有拿到测试输出）")
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        shutil.rmtree(profile, ignore_errors=True)


def main():
    chrome = find_chrome()
    failed = 0
    for page in ("smoke.html", "upgrade.html"):
        print(f"--- {page} ---")
        ok, text = run_page(chrome, page)
        print(text)
        if not ok:
            failed += 1
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
