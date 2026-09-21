"""Loopback HTTP boundary and per-process CSRF protection."""
import hmac
import json
import re
import secrets
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

SESSION_TOKEN = secrets.token_urlsafe(32)
MAX_BODY = 1024 * 1024


def require_loopback(host):
    if host not in {'127.0.0.1', 'localhost', '::1'}:
        raise ValueError('Paper Orbit only supports local loopback access.')


def allowed_request(handler):
    port = handler.server.server_address[1]
    allowed = {f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'}
    if handler.headers.get('Host', '') not in allowed:
        return False
    origin = handler.headers.get('Origin')
    if origin and origin not in {'http://' + host for host in allowed}:
        return False
    if handler.headers.get('Sec-Fetch-Site') == 'cross-site':
        return False
    return True


def valid_token(value):
    return isinstance(value,str) and hmac.compare_digest(value, SESSION_TOKEN)


def has_session(handler):
    if valid_token(handler.headers.get('X-Orbit-Token')):
        return True
    try:
        cookies = SimpleCookie(handler.headers.get('Cookie', ''))
        return 'orbit_session' in cookies and valid_token(cookies['orbit_session'].value)
    except Exception:
        return False


def secure_html(content):
    hidden = '<input type="hidden" name="_csrf" value="' + SESSION_TOKEN + '">'
    content = re.sub(r'(<form\b[^>]*>)', lambda match: match[0]+(hidden if re.search(r'''\bmethod\s*=\s*["']?post\b''',match[0],re.I) else ''), content, flags=re.I)
    bootstrap = '<script>(()=>{const token='+json.dumps(SESSION_TOKEN)+''';const nativeFetch=window.fetch.bind(window);window.fetch=(input,init={})=>{const url=new URL(typeof input==='string'?input:input.url,location.href);if(url.origin===location.origin){const headers=new Headers(init.headers||(input instanceof Request?input.headers:undefined));headers.set('X-Orbit-Token',token);init={...init,headers};}return nativeFetch(input,init);};})();</script>'''
    return content.replace('</head>', bootstrap+'</head>', 1)


def validate_ai_url(value):
    parts=urlsplit(value)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('AI endpoint must be HTTPS without credentials, query or fragment.')
    return value.rstrip('/')
