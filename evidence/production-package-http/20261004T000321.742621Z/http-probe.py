"""Run inside an isolated deployable web image; synthetic configuration only."""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


opener = urllib.request.build_opener(NoRedirect())


def request(path, *, secure=True, host='localhost', data=None):
    headers = {'Host':host}
    if secure:
        headers['X-Forwarded-Proto'] = 'https'
    query = urllib.request.Request('http://127.0.0.1:8000'+path, data=data, headers=headers)
    try:
        response = opener.open(query, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    return response.status, response.headers, response.read(2*1024*1024)


def main():
    if os.getuid() != 10001 or os.getenv('STEWARDENCE_ISOLATED_QA') != '1':
        raise RuntimeError('Isolated non-root package qualification required')
    expected = json.loads(Path('/expected-source.json').read_bytes())
    actual = {}
    for folder in ['apps', 'src', 'templates', 'static', 'collector']:
        for file in (Path('/app')/folder).rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc':
                actual[file.relative_to('/app').as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    for name in ['manage.py', 'pyproject.toml', 'uv.lock']:
        actual[name] = hashlib.sha256((Path('/app')/name).read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError('Packaged image source differs from the pinned complete source subset')
    for _ in range(30):
        try:
            status, headers, body = request('/healthz',secure=False)
            if status == 200:
                break
        except urllib.error.URLError:
            pass
        time.sleep(.2)
    else:
        raise RuntimeError('Packaged Gunicorn did not become available')
    assert json.loads(body) == {'status':'ok'}
    status, headers, body = request('/readyz',secure=False)
    assert status == 200 and json.loads(body) == {'status':'ready'}
    status, headers, body = request('/',secure=False)
    assert status == 301 and headers['Location'] == 'https://localhost/'
    status, headers, body = request('/')
    assert status == 200 and b'Inventory AI usage' in body
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert headers['X-Frame-Options'] == 'DENY'
    assert 'max-age=3600' in headers['Strict-Transport-Security']
    styles = re.findall(rb'href="(/static/[^" ]+\.css)"',body)
    assert len(styles) >= 2
    manifest = json.loads(Path('/app/staticfiles/staticfiles.json').read_bytes())['paths']
    assets = []
    for key in ['agentledger.css','atlas.css','brand/atlas/reports.svg']:
        url = '/static/'+manifest[key]
        if key.endswith('.css'):
            assert url.encode() in styles
        status, headers, content = request(url)
        assert status == 200
        assert content == (Path('/app/staticfiles')/manifest[key]).read_bytes()
        assert 'max-age=315360000' in headers['Cache-Control']
        assets.append({'asset':key,'manifest_path':manifest[key],
                       'sha256':hashlib.sha256(content).hexdigest(),'status':status})
    status, headers, body = request('/accounts/login/')
    assert status == 200 and b'csrfmiddlewaretoken' in body
    cookie = headers.get('Set-Cookie','')
    for flag in ['Secure','HttpOnly','SameSite=Lax']:
        assert flag in cookie
    status, headers, body = request('/accounts/login/',data=b'email=synthetic%40example.invalid')
    assert status == 403
    status, headers, body = request('/',host='untrusted.example.invalid')
    assert status == 400
    from django.conf import settings
    assert not settings.DEBUG and not settings.FOUNDER_OFFER_ENABLED
    assert not settings.AUTOMATION_ENABLED and not settings.CORE_WORKFLOWS_ENABLED
    print(json.dumps({'qualification_passed':True,'uid':os.getuid(),
        'image_source_files_matched':len(actual),
        'image_source_manifest_sha256':hashlib.sha256(Path('/expected-source.json').read_bytes()).hexdigest(),
        'gunicorn_http':True,'production_settings':True,'database_readiness':True,
        'http_to_https_redirect':True,'secure_proxy_header_simulated':True,
        'csrf_rejection':True,'host_rejection':True,'static_manifest_assets':assets,
        'synthetic_only':True,'provider_requests':False,'production_touched':False,
        'limits':'Isolated deployable image and simulated trusted proxy header; not live ingress, real TLS, provider health or payment fulfillment.'}))


if __name__ == '__main__':
    import django
    django.setup()
    main()
