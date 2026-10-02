"""
Fixed brand/logo images supplied by the client (not per-player assets):
the Pitching and Coach's Notes section-header lockups, and the full
"shepsavant" wordmark+ball logo. Inlined as base64 data URIs, same
reasoning as fonts_embed.py, so every report stays a single
self-contained HTML file.
"""
import os
import base64

ASSETS_DIR = os.path.join(os.path.dirname(__file__), 'assets', 'brand')


def _data_uri(filename, mime='image/png'):
    path = os.path.join(ASSETS_DIR, filename)
    with open(path, 'rb') as f:
        data = base64.b64encode(f.read()).decode('ascii')
    return f'data:{mime};base64,{data}'


def build_brand_uris():
    return {
        'pitching_logo': _data_uri('pitching_header.png'),
        'batting_logo': _data_uri('batting_header.png'),
        'running_logo': _data_uri('running_header.png'),
        'coach_notes_logo': _data_uri('coach_notes_header.png'),
        'brand_logo': _data_uri('shepsavant_logo.png'),
    }
