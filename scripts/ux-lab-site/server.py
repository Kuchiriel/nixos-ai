#!/usr/bin/env python3
"""Site lab com estado servidor (verificação independente do browser)."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE = {"clicks": 0, "fills": {}, "last": "aguardando"}

PAGE = """<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>JARVIS Lab</title></head>
<body>
<h1>JARVIS Lab</h1>
<p id="status">aguardando</p>
<button id="go" onclick="fetch('/clicked',{method:'POST'}).then(()=>{document.getElementById('status').textContent='clicado'})">Clique aqui</button>
<br><br>
<input id="nome" type="text" placeholder="digite">
<button id="ok" onclick="fetch('/filled/'+encodeURIComponent(document.getElementById('nome').value),{method:'POST'}).then(()=>{document.getElementById('status').textContent='ola '+document.getElementById('nome').value})">OK</button>
</body>
</html>"""


class H(BaseHTTPRequestHandler):
    def _send(self, body, ctype="text/html"):
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/state":
            self._send(json.dumps(STATE), "application/json")
        elif self.path == "/reset":
            STATE.update(clicks=0, fills={}, last="aguardando")
            self._send('{"ok": true}', "application/json")
        else:
            self._send(PAGE)

    def do_POST(self):
        if self.path == "/clicked":
            STATE["clicks"] += 1
            STATE["last"] = "clicado"
        elif self.path.startswith("/filled/"):
            from urllib.parse import unquote
            v = unquote(self.path[len("/filled/"):])
            STATE["fills"]["nome"] = v
            STATE["last"] = f"ola {v}"
        self._send('{"ok": true}', "application/json")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8931), H).serve_forever()
