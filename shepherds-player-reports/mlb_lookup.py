"""
Resolves an MLB player name to {id, position, photo, url} for display on a
report -- id/photo/url come from the MLB Stats API + image CDN, cached to
disk so repeat lookups (the same comp surfacing for multiple players) don't
re-hit the network.

In this dev sandbox, outbound requests to statsapi.mlb.com are blocked, so a
lookup here simply falls back to a name-only entry (no photo/link) -- the
same graceful degradation the original comps.py used. Once deployed
somewhere with normal internet access (Render, Fly.io, etc.) this resolves
for real automatically; nothing else about the code changes.
"""
import json
import os
import re
import unicodedata
import requests

BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BUILD_DIR, 'data', 'mlb_id_cache.json')

HEADSHOT_TMPL = (
    'https://img.mlbstatic.com/mlb-photos/image/upload/'
    'w_213,d_people:generic:headshot:silo:current.png,q_auto:best,f_auto/v1/people/{id}/headshot/67/current'
)
SAVANT_TMPL = 'https://baseballsavant.mlb.com/savant-player/{slug}-{id}'


def savant_slug(name):
    ascii_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    ascii_name = ascii_name.replace('.', '')
    return re.sub(r'[^a-zA-Z0-9]+', '-', ascii_name).strip('-').lower()


def _load_cache():
    if not os.path.exists(CACHE_PATH):
        return {}
    with open(CACHE_PATH) as f:
        return json.load(f)


def _save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, 'w') as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def resolve(name):
    """Returns {'name', 'position', 'photo', 'url'} -- photo/url are None if
    the lookup couldn't complete (no network, player not found, etc.)."""
    cache = _load_cache()
    if name in cache:
        return cache[name]

    entry = {'name': name, 'position': None, 'photo': None, 'url': None}
    try:
        resp = requests.get(
            'https://statsapi.mlb.com/api/v1/people/search',
            params={'names': name}, timeout=4,
        )
        resp.raise_for_status()
        people = resp.json().get('people', [])
        if people:
            p = people[0]
            pid = p['id']
            entry['position'] = (p.get('primaryPosition') or {}).get('abbreviation')
            entry['photo'] = HEADSHOT_TMPL.format(id=pid)
            entry['url'] = SAVANT_TMPL.format(slug=savant_slug(name), id=pid)
    except requests.RequestException:
        pass  # no network reachable here (e.g. this dev sandbox) -- degrade gracefully

    cache[name] = entry
    _save_cache(cache)
    return entry


def search(query, limit=8):
    """Used by the coach-facing 'override this comp' search box. Searches the
    local reference pool first (always available, no network needed), then
    tries a live MLB name search to widen results when the network allows it."""
    import comps_engine as ce
    ref = ce._load_reference()
    query_l = query.lower().strip()
    results = []
    for pool in (ref['hitters'], ref['pitchers']):
        for cand in pool:
            if query_l in cand['name'].lower():
                results.append({'name': cand['name'], 'position': cand['position'], 'source': 'reference'})
    if len(results) < limit:
        try:
            resp = requests.get(
                'https://statsapi.mlb.com/api/v1/people/search',
                params={'names': query}, timeout=4,
            )
            resp.raise_for_status()
            for p in resp.json().get('people', [])[:limit]:
                nm = p.get('fullName')
                if nm and not any(r['name'] == nm for r in results):
                    results.append({'name': nm, 'position': (p.get('primaryPosition') or {}).get('abbreviation'), 'source': 'mlb_api'})
        except requests.RequestException:
            pass
    return results[:limit]
