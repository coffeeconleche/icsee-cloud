"""Exercise the actual local HTTP routes, using no camera, SDK, or account."""
import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest

from icsee_cloud.viewer import serve


class FakeView:
    port = 0

    def __init__(self):
        self.stop = threading.Event()
        self.qualities = []

    def status(self):
        return {'camera': 'Fixture camera', 'status': 'Connecting'}

    def request_quality(self, quality):
        self.qualities.append(quality)
        return 202, {'quality': quality, 'switching': True}

    def request_stop(self):
        self.stop.set()


@contextmanager
def running_server():
    view = FakeView()
    server = serve(view)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', view
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_bundled_frontend_and_asset_routes_are_available_with_cache_queries():
    with running_server() as (url, view):
        for path, kind in [('/', 'text/html'), ('/static/app.css', 'text/css'),
                           ('/static/app.js', 'text/javascript'), ('/static/icons.svg', 'image/svg+xml')]:
            with urllib.request.urlopen(url + path + '?v=fixture', timeout=5) as response:
                assert response.status == 200
                assert response.headers.get_content_type() == kind
                assert response.headers['X-Content-Type-Options'] == 'nosniff'
                assert "default-src 'self'" in response.headers['Content-Security-Policy']
                assert response.read()
        assert not view.stop.is_set()


@pytest.mark.parametrize('path', ['/static/../config.py', '/static/%2e%2e/.env', '/static/unknown.js', '/.env'])
def test_unlisted_assets_cannot_expose_configuration_or_source(path):
    with running_server() as (url, view):
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url + path, timeout=5)
        assert error.value.code == 404


def test_existing_status_and_control_api_still_works():
    with running_server() as (url, view):
        with urllib.request.urlopen(url + '/status?fresh=1', timeout=5) as response:
            assert json.load(response)['camera'] == 'Fixture camera'
        request = urllib.request.Request(url + '/quality', data=b'{"quality":"high"}',
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 202
        assert view.qualities == ['high']
        request = urllib.request.Request(url + '/stop', method='POST')
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
        assert view.stop.is_set()
