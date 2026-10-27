"""Public, read-only share links for player profiles (recruiting). A link is an unguessable token; revoking it kills the link at once.
Stored in data/shares.json: {token: {'kind': 'pitcher'|'hitter', 'ref': slug or hitter key, 'program', 'by', 'created', 'active'}}."""
import os
import secrets
import time

import github_sync
import store

PATH = os.path.join(store.DATA_DIR, 'shares.json')


def _all():
    return store._load(PATH, {})


def _write(d):
    store._save(PATH, d)
    try:
        with open(PATH, 'rb') as f:
            github_sync.put_file('data/shares.json', f.read())
    except Exception as exc:
        print(f'WARNING: could not push shares.json: {exc}')


def get(token):
    s = _all().get(token or '')
    return s if s and s.get('active') else None


def for_ref(kind, ref):
    """(token, share) for the live link of this profile, else (None, None)."""
    for t, s in _all().items():
        if s.get('active') and s.get('kind') == kind and s.get('ref') == ref:
            return t, s
    return None, None


def create(kind, ref, program, by):
    t, s = for_ref(kind, ref)
    if t:
        return t
    d = _all()
    t = secrets.token_urlsafe(12)
    d[t] = {'kind': kind, 'ref': ref, 'program': program or '', 'by': by or '', 'created': int(time.time()), 'active': True}
    _write(d)
    return t


def revoke(kind, ref):
    d = _all()
    for t, s in d.items():
        if s.get('kind') == kind and s.get('ref') == ref and s.get('active'):
            s['active'] = False
            s['revoked'] = int(time.time())
    _write(d)
