"""An opponent's roster, uploaded by the coach who is scouting them (PDF, Excel or CSV, same readers as a team's own roster).
Private to the scouting program and kept per opponent, so it never touches another program's own roster. It fills height, weight and
class year on that opponent's scouted players and tells the scouting pages who is still on the team."""
import datetime
import json
import os

import github_sync
import roster as roster_mod
import store

PATH = os.path.join(store.DATA_DIR, 'scout_rosters.json')
MAX_PLAYERS = 200


def _load():
    try:
        with open(PATH, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def all_for(program):
    """{opp_slug: {'players': [...], 'source', 'updated', 'by'}}"""
    return _load().get(program) or {}


def get(program, opp):
    return all_for(program).get(opp)


def _write(d):
    body = json.dumps(d, separators=(',', ':'), ensure_ascii=False, sort_keys=True)
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    github_sync.atomic_write(PATH, body)
    github_sync.put_file('data/scout_rosters.json', body.encode('utf-8'))


def save(program, opp, players, source='', user=''):
    """The roster it replaces is kept as a dated snapshot (unless saved today, which is a correction)."""
    d = _load()
    today = datetime.date.today().isoformat()
    prev = (d.get(program) or {}).get(opp) or {}
    history = list(prev.get('history') or [])
    if prev.get('players') and prev.get('updated') != today:
        history.append({k: prev.get(k) for k in ('source', 'updated', 'by', 'players')})
    d.setdefault(program, {})[opp] = {'players': players[:MAX_PLAYERS], 'source': (source or '')[:120], 'updated': today, 'by': user, 'history': history[-6:]}
    _write(d)


def clear(program, opp):
    d = _load()
    (d.get(program) or {}).pop(opp, None)
    if not d.get(program):
        d.pop(program, None)
    _write(d)


def find(program, name, rosters=None):
    """(roster player, the roster record, opp_slug) for a name across this program's uploaded opponent rosters, or None."""
    rosters = rosters if rosters is not None else all_for(program)
    best = None
    for opp, rec in rosters.items():
        m = roster_mod.match_name(name, [(p['name'], p) for p in rec.get('players', [])])
        if m and (best is None or (m[1] == 'exact' and best[3] != 'exact')):
            best = (m[0], rec, opp, m[1])
    return best[:3] if best else None
