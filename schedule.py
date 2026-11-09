"""A program's season schedule (data/schedules/<program>.json), shown on the Game Reports page next to the games that have stored pitches."""
import json
import os

import store

DIR = os.path.join(store.DATA_DIR, 'schedules')


def load(program):
    """[{'date','time','at','opp','loc','tournament'}] in date order, or [] when the program has no schedule file."""
    try:
        with open(os.path.join(DIR, f'{store.program_slug(program)}.json'), encoding='utf-8') as f:
            d = json.load(f)
        games = [x for x in (d.get('games') if isinstance(d, dict) else d) or [] if isinstance(x, dict) and x.get('date')]
    except Exception:
        return []
    for g, i in zip(games, _ids(games)):
        g['_id'] = i
    return sorted(games, key=lambda x: x['date'])      # stable: same-day games keep their file (first-pitch) order


def _same_opp(a, b):
    a, b = store.slugify(a) or '', store.slugify(b) or ''
    return bool(a and b and (a == b or a in b or b in a))


def split(program, played):
    """played = [{'date','opp',...}] games that have stored pitches. -> (matches, open) where matches maps id(played game) -> its scheduled
    game and `open` is every scheduled game with no stored pitches yet. A game is matched on date + opponent; a lone game on a date with one
    scheduled game still matches when the opponent is spelled differently."""
    sched = load(program)
    free = list(range(len(sched)))
    matches = {}
    for p in sorted(played, key=lambda x: x['date']):
        hit = next((i for i in free if sched[i]['date'] == p['date'] and _same_opp(sched[i]['opp'], p['opp'])), None)
        if hit is None:
            day = [i for i in free if sched[i]['date'] == p['date']]
            if len(day) == 1:
                hit = day[0]
        if hit is not None:
            free.remove(hit)
            matches[id(p)] = sched[hit]
    return matches, [sched[i] for i in free]


# ---- coach edits (head coach only; saved back to the same file) ----------------------------------------------------------------------------
def _ids(games):
    """date|time|opponent|k, where k counts the identical games before it (a TBA doubleheader has two of them)."""
    seen, out = {}, []
    for g in games:
        base = f"{g.get('date', '')}|{g.get('time', '')}|{g.get('opp', '')}"
        out.append(f"{base}|{seen.get(base, 0)}")
        seen[base] = seen.get(base, 0) + 1
    return out


def sid(g):
    return g.get('_id', '')


def _file(program):
    return os.path.join(DIR, f'{store.program_slug(program)}.json')


def _raw(program):
    with open(_file(program), encoding='utf-8') as f:
        d = json.load(f)
    return d, (d.get('games') if isinstance(d, dict) else d)


def _write(program, d):
    import github_sync
    text = json.dumps(d, indent=1, ensure_ascii=False)
    github_sync.atomic_write(_file(program), text)
    github_sync.put_file(f'data/schedules/{store.program_slug(program)}.json', text.encode('utf-8'))


def update(program, game_id, **f):
    """Changes fields of one scheduled game (opp, time, loc, at, date). Returns the updated game, or None when it isn't found or a value is invalid."""
    import datetime
    import re
    try:
        d, games = _raw(program)
    except Exception:
        return None
    games = [x for x in games if isinstance(x, dict) and x.get('date')]
    g = next((x for x, i in zip(games, _ids(games)) if i == game_id), None)
    if g is None:
        return None
    clean = {}
    if f.get('date') is not None:
        try:
            clean['date'] = datetime.date.fromisoformat(str(f['date']).strip()).isoformat()
        except ValueError:
            return None
    for k, n in (('opp', 60), ('time', 20), ('loc', 120)):
        if f.get(k) is not None:
            v = re.sub(r'\s+', ' ', str(f[k]).strip())[:n]
            if k == 'opp' and not v:
                return None
            clean[k] = v
    if f.get('at') is not None:
        if f['at'] not in ('Home', 'Away', 'Neutral', ''):
            return None
        clean['at'] = f['at']
    g.update(clean)
    _write(program, d)
    return g


def remove(program, game_id):
    try:
        d, games = _raw(program)
    except Exception:
        return False
    ok = [x for x in games if isinstance(x, dict) and x.get('date')]
    hit = next((x for x, i in zip(ok, _ids(ok)) if i == game_id), None)
    if hit is None:
        return False
    games[:] = [x for x in games if x is not hit]
    _write(program, d)
    return True
