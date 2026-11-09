#!/usr/bin/env python3
"""Route A runtime wrapper (Render / any runtime+upload PaaS).

- Downloads xray-core official release at runtime (if not present).
- Generates xray config from env: PORT (platform-given, public), UUID, WS_PATH.
- xray listens on 127.0.0.1:10000 (VLESS+WS).
- This process listens on $PORT: serves /sub (base64 subscription) and
  reverse-proxies the WS path to xray with a raw byte relay.
  Header reads are byte-at-a-time so no over-read bytes are lost (Sec.7 pitfall).
- Env: UUID (required), WS_PATH (default /ws), SUB_PATH (default /sub),
  NODE_NAME (default v2rayn-node), XRAY_VERSION (default v26.10.31).
"""
import os, sys, socket, threading, subprocess, urllib.request, zipfile, json, base64, uuid as uuidmod

PORT = int(os.environ.get("PORT", "10000"))
UUID = os.environ.get("UUID") or str(uuidmod.uuid4())
WS_PATH = os.environ.get("WS_PATH", "/ws")
SUB_PATH = os.environ.get("SUB_PATH", "/sub")
NODE_NAME = os.environ.get("NODE_NAME", "v2rayn-node")
XRAY_VERSION = os.environ.get("XRAY_VERSION", "v26.10.31")
HERE = os.path.dirname(os.path.abspath(__file__))
XRAY_BIN = os.path.join(HERE, "xray")

def ensure_xray():
    if os.path.exists(XRAY_BIN):
        return
    url = f"https://github.com/XTLS/Xray-core/releases/download/{XRAY_VERSION}/Xray-linux-64.zip"
    zpath = os.path.join(HERE, "Xray-linux-64.zip")
    print(f"[wrapper] downloading {url}", flush=True)
    urllib.request.urlretrieve(url, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extract("xray", HERE)
    os.chmod(XRAY_BIN, 0o755)
    os.remove(zpath)

def write_config():
    cfg = {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "port": 10000, "listen": "127.0.0.1", "protocol": "vless",
            "settings": {"clients": [{"id": UUID, "flow": ""}], "decryption": "none"},
            "streamSettings": {"network": "ws", "wsSettings": {"path": WS_PATH}}
        }],
        "outbounds": [{"protocol": "freedom", "tag": "direct"}]
    }
    p = os.path.join(HERE, "config.json")
    with open(p, "w") as f:
        json.dump(cfg, f)
    return p

def vless_url(host):
    import urllib.parse
    q = urllib.parse.urlencode({"encryption": "none", "security": "tls",
        "sni": host, "fp": "chrome", "type": "ws", "host": host, "path": WS_PATH})
    return f"vless://{UUID}@{host}:443?{q}#{urllib.parse.quote(NODE_NAME)}"

def relay(a, b):
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except OSError:
        pass
    finally:
        try: b.shutdown(socket.SHUT_WR)
        except OSError: pass

def handle(conn, host):
    try:
        # Read HTTP headers byte-at-a-time: no over-read past \r\n\r\n.
        buf = b""
        while not buf.endswith(b"\r\n\r\n"):
            chunk = conn.recv(1)
            if not chunk:
                return
            buf += chunk
            if len(buf) > 65536:
                return
        head = buf.decode("iso-8859-1", "replace")
        line = head.split("\r\n")[0]
        parts = line.split(" ")
        if len(parts) < 2:
            return
        path = parts[1].split("?")[0]
        if path == SUB_PATH:
            body = base64.urlsafe_b64encode(vless_url(host).encode()).decode().rstrip("=")
            resp = (f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                    f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n{body}").encode()
            conn.sendall(resp)
            return
        if path == WS_PATH:
            up = socket.create_connection(("127.0.0.1", 10000))
            up.sendall(buf)  # forward the exact handshake bytes
            t = threading.Thread(target=relay, args=(conn, up), daemon=True)
            t.start()
            relay(up, conn)
            return
        body = b"ok"
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\nConnection: close\r\n\r\n" + body)
    except OSError:
        pass
    finally:
        try: conn.close()
        except OSError: pass

def main():
    ensure_xray()
    cfg = write_config()
    xray = subprocess.Popen([XRAY_BIN, "run", "-c", cfg],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    host = os.environ.get("RENDER_EXTERNAL_HOSTNAME") or os.environ.get("PUBLIC_HOST") or "localhost"
    print(f"[wrapper] xray pid={xray.pid} uuid-set={'yes' if UUID else 'no'} ws={WS_PATH} sub={SUB_PATH}", flush=True)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(128)
    print(f"[wrapper] listening on {PORT}", flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn, host), daemon=True).start()

if __name__ == "__main__":
    main()
