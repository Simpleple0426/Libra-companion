"""Portable Windows co-viewing client; Python standard library only."""
import ipaddress
import json
import re
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from subtitles import parse_subtitles

ROOT = Path(__file__).resolve().parent
PORT = 18765


def valid_backend(value):
    value = value.strip()
    url = urllib.parse.urlsplit(value)
    if (url.scheme not in {'http', 'https'} or not url.hostname
            or any(character.isspace() for character in value)
            or url.username or url.password or url.query or url.fragment
            or (url.port is not None and url.port <= 0)):
        raise ValueError('请填写完整 HTTPS 私人地址，或本地测试地址')
    path = url.path.rstrip('/')
    if path and not re.fullmatch(r'/connect/[A-Za-z0-9_-]{32,128}', path):
        raise ValueError('请粘贴完整私人连接地址，不要添加接口路径')
    if url.scheme == 'http':
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError:
            raise ValueError('公网服务必须使用 HTTPS') from None
        if path or not (address.is_loopback or address.is_private
                       or address in ipaddress.ip_network('100.64.0.0/10')):
            raise ValueError('公网服务及私人连接地址必须使用 HTTPS')
    return value.rstrip('/')


class Handler(BaseHTTPRequestHandler):
    settings = {}

    def log_message(self, *args):
        pass

    def send(self, code, content, mime='application/json; charset=utf-8'):
        if not isinstance(content, bytes):
            content = json.dumps(content, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def trusted(self):
        origin = f'http://127.0.0.1:{PORT}'
        return self.headers.get('Host') == f'127.0.0.1:{PORT}' and self.headers.get('Origin') == origin

    def do_GET(self):
        if self.headers.get('Host') != f'127.0.0.1:{PORT}':
            return self.send(403, {'error': 'Invalid host'})
        if self.path == '/':
            return self.send(200, (ROOT / 'index.html').read_bytes(), 'text/html; charset=utf-8')
        if self.path in {'/timeline.js', '/app.js'}:
            return self.send(200, (ROOT / self.path[1:]).read_bytes(), 'application/javascript; charset=utf-8')
        return self.send(404, {})

    def do_POST(self):
        if not self.trusted():
            return self.send(403, {'error': '请从本机陪看页面操作'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 2_100_000:
                return self.send(413, {'error': '请求过大'})
            body = json.loads(self.rfile.read(size))
            if self.path == '/subtitles':
                return self.send(200, {'cues': parse_subtitles(body['content'])})
            if self.path == '/settings':
                return self.send(200, {'backend': self.settings.get('backend', ''),
                                       'paired': bool(self.settings.get('token'))})
            if self.path == '/connect':
                selected = {'backend': valid_backend(body['backend']),
                            'token': body.get('token') or self.settings.get('token', '')}
                self.upstream('/status', None, selected)
                type(self).settings = selected
                return self.send(200, {'ready': True})
            if self.path not in {'/start', '/control', '/observe'}:
                return self.send(404, {})
            return self.send(200, self.upstream(self.path, body, dict(self.settings)))
        except urllib.error.HTTPError as error:
            return self.send(error.code, {'error': '后端拒绝请求，请检查连接码、会话状态或后端版本。'})
        except (urllib.error.URLError, TimeoutError, OSError):
            return self.send(502, {'error': '连接中断或响应超时，请检查网络和后端运行状态。'})
        except (ValueError, KeyError, TypeError):
            return self.send(400, {'error': '连接设置或画面数据无效，请检查输入。'})

    @staticmethod
    def upstream(path, body, settings):
        backend = valid_backend(settings['backend'])
        request = urllib.request.Request(backend + '/watch-together' + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + settings['token'], 'Content-Type': 'application/json'})
        # Local traffic bypasses proxies; public HTTPS uses normal proxy and
        # certificate verification settings.
        parsed = urllib.parse.urlsplit(backend)
        try:
            address = ipaddress.ip_address(parsed.hostname)
            local = address.is_loopback or address.is_private or address in ipaddress.ip_network('100.64.0.0/10')
        except ValueError:
            local = False
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if local else urllib.request.build_opener()
        with opener.open(request, timeout=600 if path == '/observe' else 10) as response:
            return json.load(response)


if __name__ == '__main__':
    settings_file = ROOT / 'connection.json'
    if settings_file.exists():
        Handler.settings = json.loads(settings_file.read_text(encoding='utf-8'))
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print('陪看页面已打开。结束使用后关闭此窗口。')
    webbrowser.open(f'http://127.0.0.1:{PORT}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
