"""Small in-memory cache for the heavy whole-program calculations (every hitter's stats, team dashboards, profile pages).

Results are kept per worker process and thrown away the moment any stored data file changes (an upload, a retag, a roster or
bio edit...), detected from file modification times, so a page can never show numbers older than the data on disk.
Set SHEPSAVANT_CACHE=off to switch it off entirely (every call computes fresh, exactly as before).
"""
import functools
import os
import threading

import store

_LOCK = threading.Lock()
_STATE = {'ver': None, 'mem': {}}
MAX_ENTRIES = 300
_SKIP = {'usage.json', 'upload_log.json', 'pitch_clips_cache.json'}       # these change on every page view / upload and feed none of the cached numbers
_DIRS = ('', 'outings', 'rosters', 'team', 'scouting')


def enabled():
    return (os.environ.get('SHEPSAVANT_CACHE') or '').lower() not in ('off', '0', 'false', 'no')


def data_version():
    """A fingerprint of every stored JSON data file (name, modified time, size)."""
    sig = []
    for sub in _DIRS:
        d = os.path.join(store.DATA_DIR, sub)
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for f in names:
            if f.endswith('.json') and f not in _SKIP:
                try:
                    st = os.stat(os.path.join(d, f))
                except OSError:
                    continue
                sig.append((sub, f, st.st_mtime_ns, st.st_size))
    for sub in ('headshots', 'logos'):               # photos feed the cached profile pages too
        d = os.path.join(store.DATA_DIR, sub)
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for f in names:
            try:
                st = os.stat(os.path.join(d, f))
            except OSError:
                continue
            sig.append((sub, f, st.st_mtime_ns, st.st_size))
    return hash(tuple(sig))


def get_or_compute(key, fn):
    if not enabled():
        return fn()
    ver = data_version()
    with _LOCK:
        if _STATE['ver'] != ver:
            _STATE['ver'], _STATE['mem'] = ver, {}
        mem = _STATE['mem']
        if key in mem:
            return mem[key]
    val = fn()
    with _LOCK:
        if _STATE['ver'] == ver:
            if len(_STATE['mem']) >= MAX_ENTRIES:
                _STATE['mem'].pop(next(iter(_STATE['mem'])))
            _STATE['mem'][key] = val
    return val


def memo(fn):
    """Cache fn(*args, **kwargs) until the stored data changes. Arguments must be hashable."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return get_or_compute((fn.__module__, fn.__qualname__, a, tuple(sorted(kw.items()))), lambda: fn(*a, **kw))
    wrapper.uncached = fn
    return wrapper
