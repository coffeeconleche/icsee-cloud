"""Serve the bundled local interface without a frontend build or external CDN."""
from importlib.resources import files

ASSETS = {
    'app.css': 'text/css; charset=utf-8',
    'app.js': 'text/javascript; charset=utf-8',
    'icons.svg': 'image/svg+xml',
    'favicon.svg': 'image/svg+xml',
    'lucide-LICENSE.txt': 'text/plain; charset=utf-8',
}


def frontend_asset(path):
    if path == '/':
        name, content_type = 'index.html', 'text/html; charset=utf-8'
    elif path.startswith('/static/') and path[8:] in ASSETS:
        name = path[8:]
        content_type = ASSETS[name]
    else:
        return None
    return files('icsee_cloud').joinpath('web', name).read_bytes(), content_type
