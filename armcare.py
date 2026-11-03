"""ArmCare exams (the "Daily Log" CSV that ArmCare exports) stored per pitcher, plus the numbers the workload pages show from them.

Only the exam measurements are kept. Email, birth date, weight, height, country and the other identity columns in the export are
dropped on read and never written to disk. Coach-only: nothing here is ever put on a shared (public) profile."""
import csv
import datetime
import json
import os
import re

import github_sync
import store

DIR = os.path.join(store.DATA_DIR, 'armcare')
URL = 'https://lab.armcare.com/players/dashboard'   # the team's ArmCare dashboard (coaches sign in there)
ARM_DROP_PCT = 10        # latest Arm Score this far (%) under the pitcher's own earlier average gets a "check in" flag
MIN_BASE = 3             # earlier exams needed before that average means anything
GROUPS = (('ir', 'IRTARM', 'Internal rotation'), ('er', 'ERTARM', 'External rotation'), ('st', 'STARM', 'Scaption'), ('gr', 'GTARM', 'Grip'))
TYPES = {'fresh_quick': 'Fresh (quick)', 'fresh_full': 'Fresh (full)', 'post': 'Post-throwing'}


def _num(v):
    try:
        s = str(v).strip()
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def _txt(v):
    s = (v or '').strip()
    return s or None


def _date(s):
    s = (s or '').strip()
    for fmt in ('%m/%d/%Y', '%Y-%m-%d', '%m/%d/%y'):
        try:
            return datetime.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _kind(t):
    t = (t or '').lower()
    if 'post' in t:
        return 'post'
    if 'full' in t:
        return 'fresh_full'
    return 'fresh_quick' if 'fresh' in t or 'quick' in t else None


def _exam(r):
    """One CSV row -> a compact exam dict, or None when the row has no usable name, date or exam type."""
    d, kind = _date(r.get('Exam Date')), _kind(r.get('Exam Type'))
    if not d or not kind:
        return None
    e = {'date': d, 'type': kind, 'time': (r.get('Time') or '').strip()}
    if kind == 'post':
        e.update(post_total=_num(r.get('Total Strength Post')), loss=_num(r.get('Post Strength Loss')), pct_fresh=_num(r.get('Total %Fresh')),
                 activity=_txt(r.get('Post- Throwing Activity')), pitches=_num(r.get('Post- Pitch Count')), high_intent=_num(r.get('Post- High Intent Throws')),
                 minutes=_num(r.get('Post- Throwing Time')), rpe=_num(r.get('Post-RPE')))
        for k, p in ((g[0], g[1]) for g in GROUPS):
            e[k + '_fresh'] = _num(r.get(f'{p} %Fresh'))
    else:
        e.update(arm_score=_num(r.get('Arm Score')), total=_num(r.get('Total Strength')), balance=_num(r.get('Shoulder Balance')), velo=_num(r.get('Velo')),
                 svr=_num(r.get('SVR')), rpe=_num(r.get('Fresh- RPE')), feels=_txt(r.get('Fresh- Arm Feels')), last_outing=_txt(r.get('Fresh- Last Outing')))
        for k, p, _l in GROUPS:
            e[k] = _num(r.get(f'{p} Strength'))
            e[k + '_rec'] = _txt(r.get(f'{p} Recovery'))
    e = {k: v for k, v in e.items() if v is not None and v != ''}
    return e if (e.get('arm_score') is not None or e.get('total') is not None or e.get('post_total') is not None or e.get('pct_fresh') is not None) else None


def parse(path):
    """-> [{'first','last','name','exams':[...]}] one entry per athlete in the file, in file order."""
    with open(path, newline='', encoding='utf-8-sig', errors='replace') as f:
        rows = list(csv.DictReader(f))
    if not rows or not {'Exam Date', 'Exam Type', 'First Name', 'Last Name'} <= set(rows[0]):
        raise ValueError("This doesn't look like an ArmCare Daily Log export (no Exam Date / Exam Type / name columns).")
    by = {}
    for r in rows:
        first, last = (r.get('First Name') or '').strip(), (r.get('Last Name') or '').strip()
        e = _exam(r)
        if not (first or last) or not e:
            continue
        a = by.setdefault((first.lower(), last.lower()), {'first': first, 'last': last, 'name': f'{first} {last}'.strip(), 'exams': []})
        a['exams'].append(e)
    return list(by.values())


_MONTHS = '(January|February|March|April|May|June|July|August|September|October|November|December)'


def parse_pdf(path):
    """One ArmCare "Player Report" PDF (a single fresh exam) -> [athlete] like parse(). Adds what the CSV doesn't carry: the individualized
    pitch count (daily max, required rest by pitches thrown, early-season limits) and the peer percentiles."""
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        pages = [(pg.extract_text() or '') for pg in pdf.pages]
    t1, rest = pages[0] if pages else '', '\n'.join(pages[1:])
    allt = t1 + '\n' + rest
    m = re.search(r'(Fresh|Post)\s+exam\s*-\s*(Quick|Full)?', t1, re.I)
    if not m or 'PLAYER REPORT' not in t1.upper():
        raise ValueError("This PDF doesn't look like an ArmCare player report.")
    if m.group(1).lower() == 'post':
        raise ValueError("Post-throwing PDFs aren't supported yet. Use the CSV export for those.")
    kind = 'fresh_full' if (m.group(2) or '').lower() == 'full' else 'fresh_quick'
    dm = re.search(_MONTHS + r'\s+(\d{1,2}),\s+(\d{4})', t1)
    nm = re.search(r'(?:Quick|Full)\s*\n\s*([^\n]+?)\s*\n\s*AGE', t1)
    if not dm or not nm:
        raise ValueError("Couldn't find the exam date or the player's name in this PDF.")
    date = datetime.datetime.strptime(f'{dm.group(1)} {dm.group(2)} {dm.group(3)}', '%B %d %Y').date().isoformat()
    parts = nm.group(1).split()
    first, last = ' '.join(parts[:-1]), parts[-1]

    def g(pat, text=t1, grp=1, flags=0):
        x = re.search(pat, text, flags)
        return _num(x.group(grp)) if x else None
    e = {'date': date, 'type': kind, 'arm_score': g(r'Arm Score\s+([\d.]+)'), 'recovery_score': g(r'Recovery Score\s+(-?[\d.]+)'),
         'total': g(r'^\s*([\d.]+)\s+\d+(?:\.\d+)?\s*mph', flags=re.M), 'velo': g(r'^\s*[\d.]+\s+(\d+(?:\.\d+)?)\s*mph', flags=re.M)}
    sb = re.search(r'([\d.]+)\s+>=\s*[\d.]+\s+>=\s*[\d.]+\s+[\d.]+\s*-\s*[\d.]+\s+([\d.]+)\s+IR\s+([\d.]+)\s*lbs', t1)
    if sb:
        e['svr'], e['balance'], e['ir'] = _num(sb.group(1)), _num(sb.group(2)), _num(sb.group(3))
    e['er'] = g(r'\bER\s+([\d.]+)\s*lbs')
    e['st'] = g(r'Scaption Strength\s+([\d.]+)', rest)
    e['gr'] = g(r'Grip Strength\s+([\d.]+)', rest) or g(r'([\d.]+)\s+[\d.]+\s+\d+\s+[\d.]+\s+[\d.]+\s+\d+\s*\n\s*Grip Strength', rest)
    e['daily_max'] = g(r'Required Rest \(Pitches\)\s*\n\s*(\d+)')
    rt = re.search(r'0 Days Rest[^\n]*\n(?:[^\n]*\n){0,2}?\s*(-\s+[\d+\- ]+)\n', t1) or re.search(r'\n\s*(-\s+\d+[\d+\- ]*)\n', t1)
    if rt:
        toks = rt.group(1).split()
        if len(toks) == 6:
            e['rest'] = toks
    em = re.search(r'1st Outing\s+2nd Outing\s+3rd Outing\s*\n[^\n]*\n\s*(\d+)\s+(\d+)\s+(\d+)', t1)
    if em:
        e['early_max'] = [int(em.group(i)) for i in (1, 2, 3)]
    peers = re.findall(r'([\d.]+)\s+Percentile\s+(\d+)%', rest)
    for k, p in zip(('arm', 'velo', 'svr'), peers):
        e[f'peer_{k}'], e[f'pct_{k}'] = _num(p[0]), _num(p[1])
    e = {k: v for k, v in e.items() if v is not None}
    if e.get('arm_score') is None and e.get('total') is None:
        raise ValueError("Couldn't read the Arm Score from this PDF.")
    return [{'first': first, 'last': last, 'name': f'{first} {last}', 'exams': [e]}]


def combine(batches):
    """Merges the athletes from several files into one list (same name = same athlete)."""
    by = {}
    for aths in batches:
        for a in aths:
            k = (a['first'].lower(), a['last'].lower())
            if k in by:
                by[k]['exams'].extend(a['exams'])
            else:
                by[k] = {**a, 'exams': list(a['exams'])}
    return list(by.values())


def rest_days(rest, pitches):
    """Days of rest ArmCare's table asks for after `pitches` thrown, or None when the table has no box for that count."""
    for days, tok in enumerate(rest or []):
        m = re.fullmatch(r'(\d+)(?:-(\d+)|(\+))?', tok.strip())
        if not m:
            continue
        lo = int(m.group(1))
        hi = float('inf') if m.group(3) else int(m.group(2) or m.group(1))
        if lo <= pitches <= hi:
            return days
    return None


def _norm(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def match(athletes, candidates):
    """candidates = {slug: display name}. Sets each athlete's 'slug' to the pitcher with the same name ('' when there is none)."""
    idx = {}
    for slug, name in candidates.items():
        idx[_norm(name)] = slug
    for a in athletes:
        a['slug'] = idx.get(_norm(a['first'] + a['last'])) or idx.get(_norm(a['last'] + a['first'])) or ''
    return athletes


def _path(slug):
    return os.path.join(DIR, f'{slug}.json')


def load(slug):
    try:
        with open(_path(slug), encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get('exams'), list) else {'exams': []}
    except Exception:
        return {'exams': []}


def _key(e):
    return (e.get('date'), e.get('type'), e.get('total') if e.get('total') is not None else e.get('post_total'))


def save(slug, name, exams):
    """Merges exams into the pitcher's file. An exam already stored (same date, type and total) is not duplicated; a CSV and a PDF of the
    same exam are combined, each filling in what the other lacks. Returns how many exams were new."""
    d = load(slug)
    idx = {_key(e): e for e in d['exams']}
    new = 0
    for e in exams:
        have = idx.get(_key(e))
        if have is None:
            d['exams'].append(e)
            idx[_key(e)] = e
            new += 1
        else:
            for k, v in e.items():
                if have.get(k) in (None, '') and v not in (None, ''):
                    have[k] = v
    d['name'] = name
    d['exams'].sort(key=lambda e: (e['date'], 0 if e['type'] != 'post' else 1, e.get('time') or ''))
    os.makedirs(DIR, exist_ok=True)
    text = json.dumps(d, separators=(',', ':'), ensure_ascii=False)
    with open(_path(slug), 'w', encoding='utf-8') as f:
        f.write(text)
    github_sync.put_file(f'data/armcare/{slug}.json', text.encode('utf-8'))
    return new


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def summary(slug, as_of=None):
    """What the pages show for one pitcher on or before `as_of` (ISO date), or None when there is no ArmCare data."""
    exams = [e for e in load(slug)['exams'] if not as_of or e['date'] <= as_of]
    if not exams:
        return None
    quick = [e for e in exams if e['type'] == 'fresh_quick' and e.get('arm_score') is not None]
    full = [e for e in exams if e['type'] == 'fresh_full' and e.get('arm_score') is not None]
    series, kind = (quick, 'quick') if quick else (full, 'full')
    out = {'exams': exams, 'series': series, 'kind': kind, 'latest': series[-1] if series else None, 'base': None, 'delta': None, 'flag': False, 'watch': [], 'post': None}
    if series:
        prior = [e['arm_score'] for e in series[:-1]]
        if len(prior) >= MIN_BASE:
            out['base'] = _mean(prior)
            out['delta'] = (series[-1]['arm_score'] - out['base']) / out['base'] * 100
            out['flag'] = out['delta'] <= -ARM_DROP_PCT
        out['watch'] = [lab for k, _p, lab in GROUPS if (series[-1].get(k + '_rec') or 'normal').lower() != 'normal']
    posts = [e for e in exams if e['type'] == 'post' and e.get('pct_fresh') is not None]
    out['post'] = posts[-1] if posts else None
    out['posts'] = posts
    lim = [e for e in exams if e.get('daily_max')]
    out['limit'] = lim[-1] if lim else None          # the newest exam that carries ArmCare's individualized pitch count
    return out


def line_svg(points, base=None, w=560, h=190):
    """points = [(iso date, value)] oldest first. A plain line chart; `base` draws a dashed line at the pitcher's own earlier average."""
    if len(points) < 2:
        return ''
    vals = [v for _d, v in points] + ([base] if base else [])
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.15, 2)
    lo, hi = lo - pad, hi + pad
    L, R, T, B = 38, 12, 12, 26
    ds = [datetime.date.fromisoformat(d) for d, _v in points]
    span = max((ds[-1] - ds[0]).days, 1)
    X = lambda d: L + (d - ds[0]).days / span * (w - L - R)
    Y = lambda v: T + (hi - v) / (hi - lo) * (h - T - B)
    s = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px;display:block;" role="img" aria-label="Arm Score over time">']
    for i in range(4):
        v = lo + (hi - lo) * i / 3
        s.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#eceeed"/><text x="{L - 6}" y="{Y(v) + 4:.1f}" font-size="11" fill="#6b7680" text-anchor="end">{v:.0f}</text>')
    if base:
        s.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(base):.1f}" y2="{Y(base):.1f}" stroke="#98a3a9" stroke-dasharray="5 4"/>')
    s.append('<polyline fill="none" stroke="var(--accent,#5c97a8)" stroke-width="2.5" points="' + ' '.join(f'{X(d):.1f},{Y(v):.1f}' for d, (_dd, v) in zip(ds, points)) + '"/>')
    for d, (iso, v) in zip(ds, points):
        s.append(f'<circle cx="{X(d):.1f}" cy="{Y(v):.1f}" r="4.5" fill="var(--accent,#5c97a8)" stroke="#fff" stroke-width="1.5"><title>{d.strftime("%b %-d, %Y")}: {v:.1f}</title></circle>')
    s.append(f'<text x="{L}" y="{h - 6}" font-size="11" fill="#6b7680">{ds[0].strftime("%b %-d, %Y")}</text><text x="{w - R}" y="{h - 6}" font-size="11" fill="#6b7680" text-anchor="end">{ds[-1].strftime("%b %-d, %Y")}</text></svg>')
    return ''.join(s)
