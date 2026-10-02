"""
Per-player asset intake: matches action photos, headshots, and coach's notes
to players by filename, using the convention:

    <slugified name>_action.<ext>     e.g. garcia_action.jpg
    <slugified name>_headshot.<ext>   e.g. garcia_headshot.png
    <slugified name>_notes.txt|.md    e.g. easton_steck_notes.txt

Images are inlined as base64 data URIs so every generated report stays a
single self-contained HTML file (no broken relative links if it's moved,
emailed, or reopened later). Name matching is fuzzy (difflib) so small
typos in a filename don't silently drop a player's assets.
"""
import os
import re
import glob
import base64
import difflib
import mimetypes

IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp')
NOTE_EXTS = ('.txt', '.md')


def slug(name):
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def _b64_image(path):
    mime, _ = mimetypes.guess_type(path)
    mime = mime or 'image/jpeg'
    with open(path, 'rb') as f:
        data = base64.b64encode(f.read()).decode('ascii')
    return f'data:{mime};base64,{data}'


def discover_asset_files(assets_dir):
    """Returns list of (filepath, basename_without_ext) for every candidate file."""
    if not os.path.isdir(assets_dir):
        return []
    files = []
    for ext in IMAGE_EXTS + NOTE_EXTS:
        files.extend(glob.glob(os.path.join(assets_dir, f'*{ext}')))
    return files


def _find_best_match(player_slug, candidate_slugs, cutoff=0.55):
    matches = difflib.get_close_matches(player_slug, candidate_slugs, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def get_player_assets(player_name, assets_dir):
    """
    Returns {'action_photo': data_uri|None, 'headshot': data_uri|None,
             'coach_notes': [paragraph, ...]|None,
             'matched': {'action':filename|None,'headshot':filename|None,'notes':filename|None}}
    """
    result = {'action_photo': None, 'headshot': None, 'coach_notes': None,
              'matched': {'action': None, 'headshot': None, 'notes': None}}
    files = discover_asset_files(assets_dir)
    if not files:
        return result

    player_slug = slug(player_name)

    # bucket files by suffix role, stripping the role suffix to get the player-slug part
    buckets = {'action': {}, 'headshot': {}, 'notes': {}}
    for path in files:
        base = os.path.basename(path)
        stem, ext = os.path.splitext(base)
        stem_l = stem.lower()
        for role, tag in (('action', '_action'), ('headshot', '_headshot'), ('notes', '_notes')):
            if stem_l.endswith(tag):
                name_part = stem_l[: -len(tag)]
                buckets[role][name_part] = path

    for role in ('action', 'headshot', 'notes'):
        candidates = list(buckets[role].keys())
        best = _find_best_match(player_slug, candidates)
        if best:
            path = buckets[role][best]
            result['matched'][role] = os.path.basename(path)
            if role == 'notes':
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read().strip()
                result['coach_notes'] = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
            else:
                key = 'action_photo' if role == 'action' else 'headshot'
                result[key] = _b64_image(path)

    return result
