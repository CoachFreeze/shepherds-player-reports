"""
Subscription plans, built so that nothing changes for current coaches.

Every program has a plan (default 'pilot' = full access). The checks below are wired into the app already,
but they only bite when enforcement is switched on (env SHEPSAVANT_ENFORCE_PLANS=on). Until then every
program gets every feature, whatever plan it is on, so pilots are never affected. Plans are set by the admin at
/admin/plans, stored in data/plans.json and committed to GitHub like the other settings.

Usage tracking (logins, uploads, views, downloads, stat customizing) is kept in data/usage.json to show which features
coaches actually use. It is pushed to GitHub at most once a day so it survives redeploys without causing commit spam.
"""
import datetime
import json
import os
import time

import github_sync
import store

PLANS_PATH = os.path.join(store.DATA_DIR, 'plans.json')
USAGE_PATH = os.path.join(store.DATA_DIR, 'usage.json')

# None = unlimited. history = how many recent outings feed the player profile.
PLANS = {
    'pilot':   {'label': 'Pilot (free trial)', 'max_players': None, 'max_coaches': None, 'max_assistants': 5, 'history': 10, 'download': True,  'custom_stats': True,  'roster_upload': True, 'hitting': True, 'scouting': True},
    'free':    {'label': 'Free',               'max_players': 5,    'max_coaches': 1, 'max_assistants': 0,    'history': 3,  'download': False, 'custom_stats': False, 'roster_upload': False, 'hitting': False, 'scouting': False},
    'team':    {'label': 'Team',               'max_players': None, 'max_coaches': 3, 'max_assistants': 1,    'history': 10, 'download': True,  'custom_stats': True,  'roster_upload': False, 'hitting': True, 'scouting': False},
    'program': {'label': 'Program',            'max_players': None, 'max_coaches': 10, 'max_assistants': 5,   'history': 10, 'download': True,  'custom_stats': True,  'roster_upload': True, 'hitting': True, 'scouting': True},
}
DEFAULT_PLAN = 'pilot'
FEATURE_NAMES = {'download': 'Download-to-send outing reports', 'custom_stats': 'Customizable player stats',
                 'roster_upload': 'Team roster upload', 'hitting': 'Hitting profiles and team hitting dashboard', 'scouting': 'Opponent scouting (hitters and pitchers from games and scrimmages)', 'max_players': 'More players', 'max_coaches': 'More coach logins'}


def enforcing():
    return (os.environ.get('SHEPSAVANT_ENFORCE_PLANS') or '').lower() in ('on', '1', 'true', 'yes')


def _load(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save(path, data, repo_path=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(data, indent=1, sort_keys=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    if repo_path:
        github_sync.put_file(repo_path, text.encode('utf-8'))


def all_plans():
    return _load(PLANS_PATH)


def plan_info(program):
    """{'plan': key, 'trial_ends': 'YYYY-MM-DD' or '', 'note': str} (defaults to the pilot plan)."""
    e = all_plans().get(program or '') or {}
    key = e.get('plan') if e.get('plan') in PLANS else DEFAULT_PLAN
    return {'plan': key, 'trial_ends': e.get('trial_ends') or '', 'note': e.get('note') or ''}


def set_plan(program, plan, trial_ends='', note=''):
    if plan not in PLANS:
        return 'Unknown plan.'
    d = all_plans()
    d[program] = {**{k: v for k, v in (d.get(program) or {}).items() if k.startswith('flag_')},
                  'plan': plan, 'trial_ends': (trial_ends or '').strip(), 'note': (note or '').strip()[:200]}
    _save(PLANS_PATH, d, 'data/plans.json')
    return None


def effective_plan(program):
    """The plan whose limits apply right now. An expired pilot falls back to 'free' (only when enforcing)."""
    info = plan_info(program)
    if info['plan'] == 'pilot' and info['trial_ends']:
        try:
            if datetime.date.fromisoformat(info['trial_ends']) < datetime.date.today():
                return 'free'
        except ValueError:
            pass
    return info['plan']


def limit(program, feature):
    """Value of a plan limit/feature for a program; everything is unrestricted unless enforcement is on."""
    if not enforcing() or not program:
        return PLANS['pilot'][feature]
    return PLANS[effective_plan(program)][feature]


def allowed(program, feature):
    return bool(limit(program, feature))


def can_add_players(program, new_count):
    """-> (ok, message). Counts the program's current players."""
    cap = limit(program, 'max_players')
    if cap is None:
        return True, ''
    have = sum(1 for p in store.list_players().values() if p.get('program') == program)
    if have + new_count > cap:
        return False, f'Your plan includes up to {cap} players ({have} on the roster, {new_count} new in this file).'
    return True, ''


def can_add_coach(program):
    """Head-coach logins for a program (assistants are counted separately, see can_add_assistant)."""
    cap = limit(program, 'max_coaches')
    if cap is None:
        return True, ''
    have = sum(1 for c in store.list_coaches().values() if c.get('program') == program and c.get('role') != 'assistant')
    return (have < cap), f'Your plan includes up to {cap} coach login{"s" if cap != 1 else ""}.'


def assistant_cap(program):
    return limit(program, 'max_assistants') or 0


def assistant_count(program):
    return sum(1 for c in store.list_coaches().values() if c.get('program') == program and c.get('role') == 'assistant')


def can_add_assistant(program):
    """-> (ok, message). Assistant coaches are the head coach's helpers: none on the lowest plan, one on the middle, five on the top."""
    cap = assistant_cap(program)
    if cap <= 0:
        return False, 'Your plan includes the head coach login only. Contact the ShepSavant admin to add assistant coaches.'
    if assistant_count(program) >= cap:
        return False, f'Your plan includes up to {cap} assistant coach{"es" if cap != 1 else ""}, and all are in use. Remove one to add another.'
    return True, ''


def trial_note(program):
    """Short line for the coach's Account page, e.g. 'Pilot (free trial), full access until Mar 31, 2027'."""
    info = plan_info(program)
    label = PLANS[info['plan']]['label']
    if info['plan'] == 'pilot' and info['trial_ends']:
        try:
            d = datetime.date.fromisoformat(info['trial_ends'])
            return f"{label}, full access until {d.strftime('%b %-d, %Y')}"
        except ValueError:
            pass
    return label


# --- usage tracking ---------------------------------------------------------

_last_push = [0.0]
MAX_EVENTS = 6000


def track(event, user, program=None, **meta):
    """Records one usage event. Never raises: tracking must not be able to break a page."""
    try:
        d = _load(USAGE_PATH) or {}
        ev = d.setdefault('events', [])
        ev.append({'t': int(time.time()), 'u': user, 'p': program or '', 'e': event, **meta})
        del ev[:-MAX_EVENTS]
        os.makedirs(os.path.dirname(USAGE_PATH), exist_ok=True)
        text = json.dumps(d, separators=(',', ':'))
        with open(USAGE_PATH, 'w', encoding='utf-8') as f:
            f.write(text)
        if time.time() - _last_push[0] > 86400 and github_sync.enabled():     # at most one commit a day
            _last_push[0] = time.time()
            github_sync.put_file('data/usage.json', text.encode('utf-8'))
    except Exception as exc:
        print(f'WARNING: usage not tracked: {exc}')


def summary(days=30):
    """Per program: coaches, players, last login, and event counts over the last N days."""
    ev = (_load(USAGE_PATH) or {}).get('events', [])
    cutoff = time.time() - days * 86400
    players = store.list_players()
    coaches = store.list_coaches()
    progs = {}
    def row(p):
        return progs.setdefault(p, {'program': p, 'label': store.program_label(p), 'coaches': 0, 'assistants': 0, 'players': 0, 'last_login': 0,
                                    'logins': 0, 'uploads': 0, 'views': 0, 'downloads': 0, 'customized': 0, 'active_users': set()})
    for p, _l in store.list_programs():
        row(p)
    for k in all_plans():
        if k not in store.DEMO_PROGRAMS:
            row(k)
    for c in coaches.values():
        if c.get('program'):
            r_ = row(c['program'])
            r_['assistants' if c.get('role') == 'assistant' else 'coaches'] += 1
    for pl in players.values():
        if pl.get('program') and pl['program'] not in store.DEMO_PROGRAMS:
            row(pl['program'])['players'] += 1
    for x in ev:
        if not x.get('p') or x['p'] not in progs:
            continue
        r = progs[x['p']]
        if x['e'] == 'login':
            r['last_login'] = max(r['last_login'], x['t'])
        if x['t'] < cutoff:
            continue
        r['active_users'].add(x['u'])
        key = {'login': 'logins', 'upload': 'uploads', 'view': 'views', 'download': 'downloads', 'customize': 'customized'}.get(x['e'])
        if key:
            r[key] += 1
    out = []
    for r in progs.values():
        r['active'] = len(r.pop('active_users'))
        r['last_login_s'] = time.strftime('%b %-d', time.localtime(r['last_login'])) if r['last_login'] else 'never'
        r['plan'] = plan_info(r['program'])
        out.append(r)
    return sorted(out, key=lambda r: r['label'].lower())


def events(program=None, days=30, users=None, limit=200):
    """Recent usage events, newest first, optionally limited to one program or a set of usernames."""
    ev = (_load(USAGE_PATH) or {}).get('events', [])
    cutoff = time.time() - days * 86400
    out = [x for x in ev if x.get('t', 0) >= cutoff and (not program or x.get('p') == program) and (users is None or x.get('u') in users)]
    out.sort(key=lambda x: -x.get('t', 0))
    return out[:limit]


def flags():
    """Things worth a look: failed-login bursts, heavy downloading, and logins nobody has used in 60 days."""
    now = time.time()
    ev = (_load(USAGE_PATH) or {}).get('events', [])
    fails, dls, last = {}, {}, {}
    for x in ev:
        u = x.get('u')
        if x['e'] == 'login':
            last[u] = max(last.get(u, 0), x['t'])
        if now - x['t'] <= 86400:
            if x['e'] == 'login_fail':
                fails[u] = fails.get(u, 0) + 1
            elif x['e'] == 'download':
                dls[u] = dls.get(u, 0) + 1
    out = []
    for u, n in fails.items():
        if n >= 5:
            out.append({'kind': 'Failed logins', 'user': u, 'detail': f'{n} wrong passwords in the last 24 hours'})
    for u, n in dls.items():
        if n >= 15:
            out.append({'kind': 'Heavy downloading', 'user': u, 'detail': f'{n} downloads in the last 24 hours'})
    for u, c in store.list_coaches().items():
        if c.get('active') is False:
            continue
        seen = last.get(u, 0)
        if (now - seen > 60 * 86400) if seen else (now - _created_ts(c) > 60 * 86400):
            out.append({'kind': 'Inactive login', 'user': u, 'detail': 'no login in 60+ days' if seen else 'has never logged in'})
    return out


def _created_ts(c):
    try:
        return datetime.datetime.fromisoformat(c.get('created', '')).timestamp()
    except ValueError:
        return time.time()


def flag(program, name):
    return bool((all_plans().get(program) or {}).get('flag_' + name))


def set_flag(program, name, on):
    d = all_plans()
    e = dict(d.get(program) or {'plan': plan_info(program)['plan'], 'trial_ends': '', 'note': ''})
    e['flag_' + name] = bool(on)
    d[program] = e
    _save(PLANS_PATH, d, 'data/plans.json')
