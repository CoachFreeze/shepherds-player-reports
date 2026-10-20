"""Keeping the data clean: where each hitter belongs, and taking a whole CSV back out."""
import csv
import json
import os

import github_sync
import outings
import store

HITTER_PATH = os.path.join(store.DATA_DIR, 'hitter_overrides.json')
HIDDEN = '_hidden'
OPP_PREFIX = 'opp-'     # outing files for opposing pitchers: kept only so our own hitters' at-bats count; never shown as players


# ------------------------------------------------------------ hitter placement
def hitter_overrides():
    try:
        with open(HITTER_PATH, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def set_hitter_overrides(changes):
    """changes: {hitter key: program slug | HIDDEN | '' (clear)}. One write for the whole batch."""
    d = hitter_overrides()
    for k, v in changes.items():
        if v:
            d[k] = v
        else:
            d.pop(k, None)
    text = json.dumps(d, separators=(',', ':'), sort_keys=True)
    os.makedirs(os.path.dirname(HITTER_PATH), exist_ok=True)
    with open(HITTER_PATH, 'w', encoding='utf-8') as f:
        f.write(text)
    github_sync.put_file('data/hitter_overrides.json', text.encode('utf-8'))


# ------------------------------------------------------------ removing a CSV
def _outing_slugs():
    d = outings.OUTINGS_DIR
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith('.json')) if os.path.isdir(d) else []


def _purge(match, allowed=None):
    """Drops every stored pitch row for which match(row) is true. allowed(slug) limits which pitchers are touched.
    Returns {'rows': n, 'pitchers': [slugs touched], 'emptied': [slugs with nothing left]}."""
    total, touched, emptied = 0, [], []
    for slug in _outing_slugs():
        if allowed and not allowed(slug):
            continue
        data = outings.load(slug, real_only=True)
        n = 0
        for o in data['outings']:
            keep = [r for r in o['rows'] if not match(r)]
            n += len(o['rows']) - len(keep)
            o['rows'] = keep
        if not n:
            continue
        data['outings'] = [o for o in data['outings'] if o['rows']]
        total += n
        touched.append(slug)
        if data['outings']:
            outings._save(slug, data)
        else:
            outings.delete(slug)
            emptied.append(slug)
    return {'rows': total, 'pitchers': touched, 'emptied': emptied}


def remove_upload(upload_id, allowed=None):
    return _purge(lambda r: r.get('_upload') == upload_id, allowed)


def csv_uids(path):
    """The pitch ids a CSV would have stored (Full Swing files are translated first, exactly as on upload)."""
    import fullswing
    if fullswing.is_fullswing(path):
        rows, _ = fullswing.convert_rows(fullswing._read(path))
    else:
        with open(path, newline='', encoding='utf-8-sig', errors='ignore') as f:
            rows = list(csv.DictReader(f))
    return {outings._uid(r) for r in rows}


def remove_uids(uids, allowed=None):
    return _purge(lambda r: outings._uid(r) in uids, allowed)


def drop_empty_players(slugs):
    """Deletes player records for pitchers that have no data left. Returns the names removed."""
    names = []
    for s in slugs:
        p = store.get_real_player(s)
        if p and not outings.load(s, real_only=True)['outings']:
            names.append(p.get('name') or s)
            store.delete_player(s)
    return names


def store_opponent_rows(path, program, our_names, exclude=()):
    """Scrimmage / Game: every pitch thrown by someone who is not one of our checked pitchers is stored under an
    'opp-<name>' file tagged with our program. Those rows hold our hitters' at-bats; the pitcher never becomes a player."""
    import extract as e
    ours = {store.slugify(n) for n in our_names}
    ex = set(exclude)
    by = {}
    for r in e.load_trackman_rows(path):
        nm = (r.get('Pitcher') or '').strip()
        last, _, first = nm.partition(', ')
        disp = f'{first} {last}'.strip() if first else nm
        if not nm or store.slugify(disp) in ours or outings._uid(r) in ex or (r.get('PitchUID') or r.get('PitchNo')) in ex:
            continue
        by.setdefault(store.slugify(disp), []).append(r)
    n = 0
    for s, rows in by.items():
        slug = OPP_PREFIX + s
        outings.add_rows(slug, rows, live_ab=True)
        data = outings.load(slug, real_only=True)
        data['program'] = program
        outings._save(slug, data)
        n += len(rows)
    return n


def scouting_teams(path):
    """Team codes in a Trackman file for a scouting-only upload: {code: {'pitchers': n, 'batters': n}} (rows per side)."""
    import extract as e
    out = {}
    for r in e.load_trackman_rows(path):
        for col, k in (('PitcherTeam', 'pitchers'), ('BatterTeam', 'batters')):
            code = (r.get(col) or '').strip()
            if code:
                out.setdefault(code, {'pitchers': 0, 'batters': 0})[k] += 1
    return out


def store_scouting_rows(path, program, names):
    """Scouting-only upload: neither team is ours. names = {team code: team name}. Every pitcher goes into an 'opp-<name>' file tagged
    with our program (Opponent = his team); each row also records the batter's team (BatterTeamLabel) so those hitters are scouted too.
    Returns (rows stored, {team name: pitchers})."""
    import extract as e
    by, seen = {}, {}
    for r in e.load_trackman_rows(path):
        nm = (r.get('Pitcher') or '').strip()
        px = names.get((r.get('PitcherTeam') or '').strip())
        if not nm or not px:
            continue
        last, _, first = nm.partition(', ')
        disp = f'{first} {last}'.strip() if first else nm
        r = dict(r)
        r['BatterTeamLabel'] = names.get((r.get('BatterTeam') or '').strip(), '')
        by.setdefault((store.slugify(disp), px), []).append(r)
        seen.setdefault(px, set()).add(disp)
    n = 0
    prev = outings.CURRENT_OPPONENT
    try:
        for (s, px), rows in by.items():
            slug = OPP_PREFIX + s
            outings.CURRENT_OPPONENT = px
            outings.add_rows(slug, rows, live_ab=True)
            data = outings.load(slug, real_only=True)
            data['program'] = program
            outings._save(slug, data)
            n += len(rows)
    finally:
        outings.CURRENT_OPPONENT = prev
    return n, {k: sorted(v) for k, v in seen.items()}


# ------------------------------------------------------------ which team code is ours
TEAMCODE_PATH = os.path.join(store.DATA_DIR, 'team_codes.json')


def team_code(program):
    """The team code Trackman writes for this program (e.g. LON_DIR), learned from an earlier Game / Scrimmage upload."""
    try:
        with open(TEAMCODE_PATH, encoding='utf-8') as f:
            return (json.load(f) or {}).get(program)
    except Exception:
        return None


def set_team_code(program, code):
    try:
        with open(TEAMCODE_PATH, encoding='utf-8') as f:
            d = json.load(f) or {}
    except Exception:
        d = {}
    if not code or d.get(program) == code:
        return
    d[program] = code
    text = json.dumps(d, separators=(',', ':'), sort_keys=True)
    os.makedirs(os.path.dirname(TEAMCODE_PATH), exist_ok=True)
    with open(TEAMCODE_PATH, 'w', encoding='utf-8') as f:
        f.write(text)
    github_sync.put_file('data/team_codes.json', text.encode('utf-8'))


def guess_my_team(program, pitchers):
    """Which team code in this file is the program's? Saved code first, then whichever team's pitchers are already on the
    roster or already players of the program. Returns (code or None, {code: pitcher count})."""
    codes = {}
    for p in pitchers:
        if p.get('team'):
            codes[p['team']] = codes.get(p['team'], 0) + 1
    saved = team_code(program)
    if saved in codes:
        return saved, codes
    votes = {}
    for p in pitchers:
        if p.get('team') and (p.get('on_roster') is True or p.get('known')):
            votes[p['team']] = votes.get(p['team'], 0) + 1
    ranked = sorted(votes.items(), key=lambda kv: -kv[1])
    if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
        return ranked[0][0], codes
    return None, codes
