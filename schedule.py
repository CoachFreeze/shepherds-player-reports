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
