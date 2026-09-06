import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body=json.dumps(payload).encode();self.send_response(status);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)

    def do_GET(self):
        if self.path=="/v1/models": self.send_json({"data":[{"id":"mock-chat"},{"id":"mock-embedding"}]})
        else: self.send_json({"error":"not_found"},404)

    def do_POST(self):
        length=int(self.headers.get("Content-Length","0"));payload=json.loads(self.rfile.read(length) or b"{}")
        if self.path=="/v1/embeddings":
            values=payload.get("input",[]);values=[values] if isinstance(values,str) else values
            self.send_json({"data":[{"index":index,"embedding":[float(len(value)%11),float(sum(map(ord,value))%13),1.0]} for index,value in enumerate(values)]})
        elif self.path=="/v1/chat/completions":
            context="\n".join(str(item.get("content","")) for item in payload.get("messages",[]));answer="WORK_ONLY_TOKEN" if "WORK_ONLY_TOKEN" in context else "JAPANESE_ONLY_TOKEN" if "JAPANESE_ONLY_TOKEN" in context else "NO_GROUNDED_CONTEXT"
            self.send_json({"choices":[{"message":{"role":"assistant","content":answer}}],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}})
        else: self.send_json({"error":"not_found"},404)

    def log_message(self, *_): pass


ThreadingHTTPServer(("0.0.0.0",1234),Handler).serve_forever()
