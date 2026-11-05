"""Pitch counts and rest from the sessions already stored, with the ArmCare numbers (armcare.py) alongside.
Counts are TRACKED pitches only: what was uploaded. Throwing that nobody uploaded (long toss, untracked bullpens) is not in them."""
import datetime

import armcare
import outings as outings_mod
import team as team_mod

WINDOWS = (7, 14, 30)


def _d(s):
    return datetime.date.fromisoformat(str(s)[:10])


def log(slug):
    """[(date, pitches)] oldest first, one entry per day that has stored pitches."""
    by = {}
    for o in outings_mod.outings(slug):
        by[str(o['date'])[:10]] = by.get(str(o['date'])[:10], 0) + len(o['rows'])
    return sorted(by.items())


def windows(entries, as_of):
    """Pitch totals over the last 7 / 14 / 30 days (as_of included), this calendar year, and the most recent outing on or before as_of."""
    as_of = _d(as_of)
    upto = [(d, n) for d, n in entries if _d(d) <= as_of]
    res = {f'd{w}': sum(n for d, n in upto if (as_of - _d(d)).days < w) for w in WINDOWS}
    res['year'] = sum(n for d, n in upto if _d(d).year == as_of.year)
    res['last'] = None
    if upto:
        d, n = upto[-1]
        res['last'] = {'date': d, 'pitches': n, 'days': (as_of - _d(d)).days}
    return res


def bars_svg(entries, as_of, w=560, h=150, keep=14):
    """Pitches per outing, most recent `keep` outings up to as_of."""
    ent = [(d, n) for d, n in entries if _d(d) <= _d(as_of)][-keep:]
    if not ent:
        return ''
    top = max(n for _d_, n in ent) or 1
    L, B, T = 8, 24, 16
    slot = (w - 2 * L) / len(ent)
    bw = min(slot * 0.62, 38)
    s = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px;display:block;" role="img" aria-label="Pitches per outing">']
    for i, (d, n) in enumerate(ent):
        x = L + slot * i + (slot - bw) / 2
        bh = (h - B - T) * n / top
        s.append(f'<rect x="{x:.1f}" y="{h - B - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" fill="var(--accent,#5c97a8)"><title>{_d(d).strftime("%b %-d, %Y")}: {n} pitches</title></rect>'
                 f'<text x="{x + bw / 2:.1f}" y="{h - B - bh - 4:.1f}" font-size="11" font-weight="700" fill="#22303a" text-anchor="middle">{n}</text>'
                 f'<text x="{x + bw / 2:.1f}" y="{h - 8}" font-size="10" fill="#6b7680" text-anchor="middle">{_d(d).strftime("%-m/%-d")}</text>')
    s.append('</svg>')
    return ''.join(s)


def limit_status(w, arm):
    """ArmCare's individualized pitch limit set against the last outing: {'max', 'exam', 'over', 'need', 'left'} or None. `need` is the rest days its
    table asks for after that many pitches (None when the table has no box for the count) and `left` how many of those days are still to go."""
    lim = (arm or {}).get('limit')
    if not lim:
        return None
    res = {'max': int(lim['daily_max']), 'exam': lim['date'], 'over': False, 'need': None, 'left': None, 'rest': lim.get('rest')}
    last = (w or {}).get('last')
    if last:
        res['over'] = last['pitches'] > res['max']
        res['need'] = armcare.rest_days(lim.get('rest'), last['pitches'])
        if res['need'] is not None:
            res['left'] = max(res['need'] - last['days'], 0)
    return res


def card(slug, as_of=None):
    """The workload + arm score block for one pitcher's profile (coach view), or None when there is nothing to show."""
    as_of = as_of or datetime.date.today().isoformat()
    ent = log(slug)
    arm = armcare.summary(slug, as_of)
    if not ent and not arm:
        return None
    w = windows(ent, as_of) if ent else None
    line = armcare.line_svg([(e['date'], e['arm_score']) for e in arm['series']], arm['base']) if arm and arm['series'] else ''
    return {'w': w, 'bars': bars_svg(ent, as_of) if ent else '', 'arm': arm, 'line': line, 'as_of': as_of, 'lim': limit_status(w, arm)}


def team_rows(program, as_of):
    """One row per pitcher with stored pitches or ArmCare exams: windows, last outing, arm summary. Sorted by last name."""
    import store
    rows, seen = [], set()
    for slug, bio, _outs in team_mod._pitchers(program, None):
        seen.add(slug)
        rows.append(_row(slug, bio.get('name', slug), as_of))
    for slug, bio in store.list_players_view().items():          # ArmCare data for a pitcher with no stored pitches yet
        if slug not in seen and (bio.get('program') or 'shepherds') == program and armcare.load(slug)['exams']:
            rows.append(_row(slug, bio.get('name', slug), as_of))
    return sorted(rows, key=lambda r: r['name'].split()[-1].lower())


def _row(slug, name, as_of):
    ent = log(slug)
    wd, arm = (windows(ent, as_of) if ent else None), armcare.summary(slug, as_of)
    return {'slug': slug, 'name': name, 'w': wd, 'arm': arm, 'lim': limit_status(wd, arm)}
