import functools
import json
import os
import datetime
import re
from flask import g, Flask, Response, make_response, render_template, request, session, redirect, url_for, render_template_string, send_file, jsonify, abort

import github_sync
import plans
import store
import pipeline
import extract as e_mod
import mlb_lookup
import headshots
import hitting
import prs
import advanced
import stats as stats_mod
import team
import theme
import roster as roster_mod
import glossary
import overview
import outings as outings_mod
import fullswing
import uploadlog
import shares
import cleanup
import scouting
import scoutnotes
import gamenotes
import scoutplan
import pitchfx
import savant_components as sc_mod
import uuid

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-me')
if app.secret_key == 'dev-only-change-me' and not app.debug:
    print('WARNING: SECRET_KEY env var is not set -- using the insecure default. '
          'Set a real SECRET_KEY in your host\'s environment variables before sharing this URL.')

UPLOAD_DIR = os.path.join(store.DATA_DIR, 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)


# --- auth ---------------------------------------------------------------

def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('coach'):
            # Only GET pages can be returned to after logging in; a POST (e.g. a form submit from a
            # session that expired) would land on a GET and show "Method not allowed".
            nxt = request.path if request.method == 'GET' else (request.referrer or url_for('dashboard'))
            return redirect(url_for('login', next=nxt))
        return view(*args, **kwargs)
    return wrapped


def current_coach():
    return store.list_coaches().get(session.get('coach') or '')


def is_admin():
    c = current_coach()
    return bool(c) and c.get('role', 'admin') == 'admin'


def can_manage(slug):
    """Admins manage everyone; a program coach manages only players of his own program."""
    c = current_coach()
    if not c:
        return False
    if c.get('role', 'admin') == 'admin':
        return True
    if c.get('role') == 'player':
        return False
    p = store.get_player(slug)
    return bool(p) and p.get('program', 'shepherds') == c.get('program')


def is_demo_viewer():
    """A view-only login for the bundled sample program, safe to hand to a prospective coach."""
    c = current_coach()
    return bool(c) and bool(c.get('demo_view'))


def can_view(slug):
    """Public programs (Shepherds) are open to everyone; every other program is private to its own coaches and admins."""
    p = store.get_player(slug)
    if not p:
        return False
    c = current_coach()
    if p.get('program') in store.DEMO_PROGRAMS:          # the bundled sample program is for admins and its view-only logins
        return is_admin() or (is_demo_viewer() and c.get('program') == p.get('program'))
    if c and c.get('role') == 'player':                  # a player sees only himself
        return slug == c.get('player_slug')
    if c and c.get('role', 'admin') != 'admin':          # a signed-in program coach sees only his own program
        return can_manage(slug)
    if p.get('program', 'shepherds') in store.PUBLIC_PROGRAMS:
        return True
    return can_manage(slug)


def _upgrade(feature, detail=''):
    """Shown when a plan doesn't include something (only possible once plan enforcement is switched on)."""
    name = plans.FEATURE_NAMES.get(feature, feature)
    return (BULK_STYLE + f'<h1>{name}</h1><div class="card">{detail or "This is not included in your current plan."} '
            'Contact the ShepSavant admin to upgrade.</div><p><a href="' + home_url() + '">Back to the dashboard</a></p>'), 402


def _track(event, **meta):
    c = current_coach() or {}
    plans.track(event, session.get('coach') or '', c.get('program'), **meta)


def my_program():
    c = current_coach() or {}
    return c.get('program')


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('coach'):
            return redirect(url_for('login', next=request.path if request.method == 'GET' else url_for('dashboard')))
        if not is_admin():
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def is_assistant():
    c = current_coach()
    return bool(c) and c.get('role') == 'assistant'


def can_upload():
    """Admins and head coaches always; an assistant coach only while the head coach leaves uploading on."""
    c = current_coach()
    if not c:
        return False
    if c.get('role') == 'player' or c.get('demo_view'):
        return False
    return c.get('role') != 'assistant' or c.get('can_upload', True)


def is_player():
    c = current_coach()
    return bool(c) and c.get('role') == 'player'


def player_home():
    """The one page a player lands on: his pitcher profile, else his hitter profile."""
    c = current_coach() or {}
    if c.get('player_slug') and store.get_player(c['player_slug']):
        return url_for('player_overview', slug=c['player_slug'])
    hk = _player_hkey(c)
    return url_for('beta_hitter', key=hk) if hk else url_for('account')


def _player_hkey(c):
    if c.get('hitter_key'):
        return c['hitter_key']
    try:
        return hitting.hitter_key_for(c.get('player_name', ''), c.get('program'), include_demo=False)
    except Exception:
        return None


def head_required(view):
    """Head coach (or admin) only: managing logins, appearance, and removing data. Assistants get a plain 403."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if is_assistant() or is_player():
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def upload_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if session.get('coach') and is_player():
            abort(403)
        if session.get('coach') and not can_upload():
            return (BULK_STYLE + '<h1>Uploads are turned off</h1><div class="card">Your head coach has turned off uploading for assistant coaches. '
                    'Ask them to switch it back on from the Coaches page.</div><p><a href="' + home_url() + '">Back to the dashboard</a></p>'), 403
        return view(*args, **kwargs)
    return wrapped


LOGIN_PAGE = """
<!doctype html><title>Coach Login</title>
<style>
  body{font-family:Barlow,Arial,sans-serif;background:#f7f6f2;color:#22303a;display:flex;
       align-items:center;justify-content:center;height:100vh;margin:0;}
  form{background:#fff;border:1px solid #dcdfdc;border-radius:12px;padding:28px 26px;width:280px;}
  h1{font-size:18px;margin:0 0 16px;}
  input{width:100%;padding:9px 10px;margin-bottom:10px;border:1px solid #dcdfdc;border-radius:7px;box-sizing:border-box;}
  button{width:100%;padding:10px;border:none;border-radius:999px;background:#5c97a8;color:#fff;font-weight:600;cursor:pointer;}
  .error{color:#b33;font-size:13px;margin-bottom:10px;}
</style>
<form method="post">
  <h1>Player Reports &mdash; Coach Login</h1>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <input name="username" placeholder="Username" autofocus>
  <input name="password" type="password" placeholder="Password">
  <button type="submit">Log in</button>
  {% if site_public %}<div style="text-align:center;margin-top:12px;font-size:13px;">New here? <a href="{{ url_for('welcome_signup') }}">Start a free trial</a> &middot; <a href="{{ url_for('welcome') }}">About</a></div>{% endif %}
  <div style="font-size:11.5px;color:#76828a;margin-top:12px;line-height:1.45;">For authorized coaches and players only. Sign-ins and report downloads are logged, and printed or saved reports are marked with the name of the person they were prepared for.</div>
</form>
"""


_FOOTER_ENDPOINTS = {'view_outing', 'team_scouting_print', 'team_game_scorebook', 'team_game'}


@app.after_request
def prepared_for_footer(resp):
    """Every report page that can be printed or saved carries who it was prepared for, so a shared copy can be traced."""
    try:
        if (request.endpoint in _FOOTER_ENDPOINTS and session.get('coach') and resp.status_code == 200 and (resp.mimetype or '') == 'text/html'
                and not resp.direct_passthrough):
            c = current_coach() or {}
            who = (c.get('display_name') or session.get('coach')).replace('&', '&amp;').replace('<', '&lt;')
            import datetime as _d
            html = resp.get_data(as_text=True)
            bar = ('<div style="text-align:center;font:11px Arial,sans-serif;color:#8a949a;padding:14px 0 6px;">Prepared for ' + who + ', '
                   + _d.date.today().strftime('%B %-d, %Y') + '. For the use of this program only.</div>')
            k = html.rfind('</body>')
            resp.set_data(html[:k] + bar + html[k:] if k > -1 else html + bar)
    except Exception:
        pass
    return resp


_FAILS = {}      # (username, ip) -> [timestamps of recent wrong passwords]; per worker, best effort
_LOCK_AFTER, _LOCK_WINDOW = 6, 600


def _locked(key):
    import time
    now = time.time()
    recent = [t for t in _FAILS.get(key, []) if now - t < _LOCK_WINDOW]
    _FAILS[key] = recent
    return len(recent) >= _LOCK_AFTER


def _fail(key):
    import time
    _FAILS.setdefault(key, []).append(time.time())


_OPEN_ENDPOINTS = {'login', 'logout', 'account', 'static', 'school_logo', 'school_mark', 'brand_logo', 'watermark'}


@app.before_request
def staff_checks():
    """A login that was removed or turned off stops working at once, and a new or reset login must choose its own password first."""
    name = session.get('coach')
    if not name:
        return None
    c = store.list_coaches().get(name)
    if not c or not store.coach_active(name):
        session.pop('coach', None)
        return redirect(url_for('login'))
    if c.get('must_change') and request.endpoint not in _OPEN_ENDPOINTS:
        return redirect(url_for('account'))
    if c.get('role') != 'admin' and c.get('program') and plans.trial_expired(c['program']) and request.endpoint not in (_OPEN_ENDPOINTS | {'trial_ended'}):
        return redirect(url_for('trial_ended'))
    if c.get('demo_view'):
        return _demo_gate()
    if c.get('role') == 'player':
        return _player_gate(c)
    return None


_DEMO_BLOCKED = {'team_coaches', 'team_appearance', 'roster_page', 'upload_log_page', 'intake_bulk', 'intake_bulk_run', 'edit_profile', 'account', 'change_password',
                 'admin_status', 'hitters_sort', 'team_customize'}


def _demo_gate():
    """Demo viewers can only look: nothing that saves, uploads or manages gets through."""
    if request.endpoint in _OPEN_ENDPOINTS - {'account'} or request.endpoint == 'trial_ended':
        return None
    if request.method not in ('GET', 'HEAD') or request.endpoint in _DEMO_BLOCKED:
        abort(403)
    return None


_PLAYER_ENDPOINTS = {'pitch_clip', 'player_overview', 'player_outings', 'player_prs', 'hitter_prs', 'view_outing', 'beta_hitter', 'headshot', 'hitter_photo', 'glossary_page',
                     'account', 'change_password', 'logout', 'static', 'school_logo', 'school_mark', 'brand_logo', 'watermark', 'onboarding_done'}


def _player_gate(c):
    """A player can open only his own profile pages (pitching and hitting), his own reports and his account. Everything else
    (team pages, scouting, other players, uploads, editing, admin) is closed, whatever address he types."""
    ep, va = request.endpoint, request.view_args or {}
    ok = ep in _PLAYER_ENDPOINTS and request.method in ('GET', 'HEAD') or (ep == 'account' and request.method == 'POST')
    if ok and 'slug' in va and va['slug'] != c.get('player_slug'):
        ok = False
    if ok and ep in ('beta_hitter', 'hitter_photo', 'hitter_prs') and va.get('key') != _player_hkey(c):
        ok = False
    if ok and ep == 'beta_hitter' and request.args.get('side', 'all') not in ('all', 'L', 'R'):
        ok = False
    if ok:
        return None
    if request.method in ('GET', 'HEAD'):
        return redirect(player_home())
    abort(403)


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = store.resolve_username(request.form.get('username', '').strip())
        password = request.form.get('password', '')
        _prog = (store.list_coaches().get(username) or {}).get('program')
        _key = (username.lower(), request.remote_addr)
        if _locked(_key):
            error = 'Too many wrong passwords. Wait a few minutes and try again.'
        elif store.verify_coach(username, password) and not store.coach_active(username):
            error = 'This login has been turned off or has expired. Ask your head coach.'
        elif store.verify_coach(username, password):
            _FAILS.pop(_key, None)
            session['coach'] = username
            plans.track('login', username, _prog)
            if not request.args.get('next') and store.needs_first_upload(username):
                return redirect(url_for('intake_bulk') + '?welcome=1')
            return redirect(request.args.get('next') or url_for('dashboard'))
        else:
            _fail(_key)
            plans.track('login_fail', username[:40], _prog)
            error = 'Incorrect username or password.'
    return render_template_string(LOGIN_PAGE, error=error, site_public=marketing.is_public())


ACCOUNT_PAGE = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Account Settings</title>
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=Barlow:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  body{font-family:'Barlow',Arial,sans-serif;background:#f7f6f2;color:#22303a;margin:0;}
  .top{max-width:560px;margin:0 auto;padding:16px 16px 0;display:flex;justify-content:space-between;align-items:center;} .top a.back{color:#5c97a8;font-weight:600;font-size:13px;text-decoration:none;}
  .wrap{max-width:560px;margin:0 auto;padding:6px 16px 50px;}
  h1{font:700 30px 'Oswald',sans-serif;margin:8px 0 14px;}
  .card{background:#fff;border-radius:16px;box-shadow:0 1px 3px rgba(26,31,36,.08),0 6px 18px rgba(26,31,36,.06);padding:20px;margin-bottom:14px;}
  .card h2{font:700 15px 'Oswald',sans-serif;letter-spacing:.08em;text-transform:uppercase;margin:0 0 12px;}
  .id{display:flex;gap:14px;align-items:center;} .id .meta b{display:block;font-size:17px;} .id .meta span{color:#6b7680;font-size:13px;}
  label{font-size:13px;font-weight:600;display:block;margin-top:10px;}
  input[type=text],input[type=password]{width:100%;padding:10px 12px;margin-top:4px;border:1px solid #dcdfdc;border-radius:8px;box-sizing:border-box;font:500 15px 'Barlow',sans-serif;}
  button{margin-top:14px;padding:10px 22px;border:none;border-radius:999px;background:#5c97a8;color:#fff;font-weight:700;cursor:pointer;font-size:14px;}
  .msg{font-size:13px;margin:0 0 10px;padding:8px 12px;border-radius:8px;} .err{background:#f8e6e6;color:#9c3a3a;} .ok{background:#e4f2ea;color:#2a7a4b;}
  .ro{color:#6b7680;font-size:14px;margin-top:4px;}
</style></head><body>
<div class="top"><a class="back" href="{{ home_url }}">&larr; Back to {{ home_label }}</a>{% include '_usermenu.html' %}</div>
<div class="wrap"><h1>Account Settings</h1>
  <div class="card"><div class="id">{% if me.badge %}<span class="um-av big" style="background:{{ me.badge.bg }}"><img src="{{ url_for('school_logo', fname=me.badge.file) }}" alt=""></span>{% else %}<span class="um-av big"><b>{{ me.initials }}</b></span>{% endif %}
    <div class="meta"><b>{{ me.name }}</b><span>{{ me.label or ('Administrator' if me.is_admin else '') }}{% if me.is_admin and me.label %} &middot; Administrator{% endif %}</span></div></div>
    <div class="ro">Your logo comes from your program. Username: <b>{{ me.key }}</b></div>{% if plan_line %}<div class="ro">Plan: <b>{{ plan_line }}</b></div>{% endif %}</div>
  <div class="card"><h2>Profile</h2>
    {% if name_msg %}<div class="msg {{ 'ok' if name_ok else 'err' }}">{{ name_msg }}</div>{% endif %}
    <form method="post"><input type="hidden" name="form" value="name">
      <label>Display name</label><input type="text" name="display_name" value="{{ me.name }}" maxlength="60" required>
      <button type="submit">Save name</button></form></div>
  {% if first_login %}<div class="msg err" style="font-weight:600;">Welcome. Before you continue, choose your own password below. The one you were given is temporary.</div>{% endif %}
  <div class="card"><h2>Change password</h2>
    {% if pw_msg %}<div class="msg {{ 'ok' if pw_ok else 'err' }}">{{ pw_msg }}</div>{% endif %}
    <form method="post"><input type="hidden" name="form" value="password">
      <label>Current password</label><input type="password" name="current" required>
      <label>New password (8+ characters)</label><input type="password" name="new" required minlength="8">
      <label>Confirm new password</label><input type="password" name="confirm" required minlength="8">
      <button type="submit">Update password</button></form></div>
</div></body></html>
"""


def _nav_program():
    """The program whose pages the signed-in person is on: set by the route (g.theme_program), else the program in the URL, else the owner
    of the player being viewed, else a program coach's own program. None on pages that belong to no program (admin tools, glossary...)."""
    prog = getattr(g, 'theme_program', None)
    if not prog:
        va = request.view_args or {}
        prog = va.get('program')
        if not prog and va.get('slug'):
            prog = (store.get_player(va['slug']) or {}).get('program')
    if not prog and session.get('coach') and not is_admin():
        prog = my_program()
    return prog or None


def home_url():
    """Where "back to dashboard" goes: a program's Team Dashboard for coaches (and for admins inside a program), else the team list."""
    if session.get('coach') and is_player():
        return player_home()
    prog = _nav_program() if session.get('coach') else None
    return url_for('team_dashboard', program=prog) if prog else url_for('dashboard')


@app.context_processor
def inject_prs():
    def _dates(slug):
        try:
            ent = prs.for_pitcher(slug)
            return {} if not ent else {ev['date']: 1 for ev in ent['events']}
        except Exception:
            return {}
    def _new(kind, key):
        try:
            return prs.new_count(kind, key)
        except Exception:
            return 0
    return {'pr_new': _new, 'pr_dates': _dates}


# Every subject heading shows with each word capitalized (Top Exit Velocity), without touching the stored text.
_TITLE_CSS = 'h1,h2,h3,h4,.half-head,.phead,.fx-h,.g-t,.board h4,.card>.head,.sh,.sect-title{text-transform:capitalize;}'

@app.context_processor
def inject_theme():
    """School colors (see theme.py) plus back-link targets for whichever program's page this is. Pages with no program (admin tools,
    login) keep the default colors and link back to the team list."""
    prog = _nav_program() if session.get('coach') else None
    _pl = bool(session.get('coach')) and is_player()
    out = {'nav_program': None if _pl else prog, 'home_url': home_url(), 'home_label': 'my profile' if _pl else ('Team Dashboard' if prog else 'dashboard'),
           'pitchers_url': url_for('team_pitchers', program=prog) if prog else url_for('dashboard'),
           'hitters_url': url_for('team_hitters', program=prog) if prog else (url_for('beta_hitters') if is_admin() else url_for('dashboard')),
           'theme_css': _TITLE_CSS, 'theme_program': None}
    if _pl:
        out['pitchers_url'] = out['hitters_url'] = home_url()
    try:
        out['wm_url'] = _wm_url(prog) if (prog and not _pl) else None      # the team logo shown faintly in the dark page header
    except Exception:
        out['wm_url'] = None
    try:
        out['nav_hitting'] = bool(prog) and plans.allowed(prog, 'hitting')
    except Exception:
        out['nav_hitting'] = bool(prog)
    if prog:
        try:
            out['theme_css'] = theme.css(theme.for_program(prog)) + _TITLE_CSS
            out['theme_program'] = prog
        except Exception:
            pass
    return out


@app.context_processor
def inject_me():
    """Signed-in coach info for the profile circle/menu shown at the top of every page."""
    c = current_coach() if session.get('coach') else None
    if not c:
        return {}
    name = c.get('display_name') or session.get('coach')
    label = c.get('program_label') or (store.program_label(c['program']) if c.get('program') else None)
    _b = pipeline.school_badge_file(label, c.get('program')) if label else None
    parts = [w for w in name.split() if w]
    initials = (parts[0][:1] + (parts[-1][:1] if len(parts) > 1 else '')).upper() or '?'
    return {'me': {'name': name, 'key': session.get('coach'), 'label': label, 'is_admin': is_admin(), 'initials': initials, 'program': c.get('program') if c.get('role', 'admin') != 'admin' else None,
                   'badge': {'file': _b[0], 'bg': _b[1]} if _b else None,
                   'is_head': c.get('role', 'admin') not in ('assistant', 'player'), 'is_player': c.get('role') == 'player', 'is_assistant': c.get('role') == 'assistant', 'can_upload': can_upload(),
                   'must_change': bool(c.get('must_change')), 'demo_view': bool(c.get('demo_view')),
                   'trial_left': plans.trial_days_left(c.get('program')) if c.get('role', 'admin') != 'admin' else None}}


_MENU_PAGES = {'edit_profile', 'admin_status', 'admin_old_reports', 'hitters_sort', 'admin_coaches', 'view_report', 'intake', 'intake_bulk', 'intake_bulk_run',
               'intake_lbsu', 'intake_lbsu_confirm', 'edit_comps'}


@app.after_request
def add_profile_menu(resp):
    """Pages built outside the dashboard templates (upload, edit profile, admin, Shepherds reports) still get the
    profile circle/menu in the top-right corner, so navigation is the same everywhere."""
    try:
        if (request.endpoint in _MENU_PAGES and session.get('coach') and resp.status_code == 200
                and (resp.mimetype or '') == 'text/html' and not resp.direct_passthrough
                and 'Content-Disposition' not in resp.headers):
            html = resp.get_data(as_text=True)
            i = html.lower().find('<body')
            j = (html.find('>', i) + 1) if i > -1 else 0       # pages without a <body> tag: put it at the very top
            if 'class="bhero"' not in html:                     # the upload pages carry their own menu in the dark header
                box = ('<style>.um-fixed{position:fixed;top:12px;right:14px;z-index:9999;} @media print{.um-fixed{display:none;}}</style>'
                       '<div class="um-fixed">' + render_template('_usermenu.html', **inject_me()) + '</div>')
                resp.set_data(html[:j] + box + html[j:])
    except Exception as exc:
        print(f'WARNING: profile menu not added: {exc}')
    return resp


@app.route('/account', methods=['GET', 'POST'])
@login_required
def account():
    ctx = {}
    if request.method == 'POST':
        if request.form.get('form') == 'name':
            err = store.set_display_name(session['coach'], request.form.get('display_name', ''))
            ctx.update(name_msg=err or 'Name updated.', name_ok=not err)
        else:
            new = request.form.get('new', '')
            if new != request.form.get('confirm', ''):
                err = 'New passwords do not match.'
            else:
                err = store.change_password(session['coach'], request.form.get('current', ''), new)
            ctx.update(pw_msg=err or 'Password updated.', pw_ok=not err)
    _c = current_coach() or {}
    ctx['first_login'] = bool(_c.get('must_change'))
    ctx['plan_line'] = plans.trial_note(_c['program']) if _c.get('program') else ''
    return render_template_string(ACCOUNT_PAGE, **ctx, **inject_me())


@app.route('/account/password')
@login_required
def change_password():
    return redirect(url_for('account'))


@app.route('/onboarding/done', methods=['POST'])
@login_required
def onboarding_done():
    store.set_coach_flag(session['coach'], 'toured', True)
    return ('', 204)


@app.route('/logout')
def logout():
    session.pop('coach', None)
    return redirect(url_for('login'))


# --- dashboard (public -- players view this, no login needed) -----------

_SUFFIXES = {'jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv'}


def _split_name(name):
    parts = name.split()
    if len(parts) < 2:
        return name, ''
    k = 2 if parts[-1].lower() in _SUFFIXES and len(parts) > 2 else 1
    return ' '.join(parts[-k:]), ' '.join(parts[:-k])


def _player_pos(p):
    r = p.get('roles') or {}
    return (r.get('pitch') or {}).get('position') or (r.get('hit') or {}).get('position')


def _build_groups():
    players = store.list_players_view() if is_admin() else store.list_players()
    priv = {}
    for slug, p in players.items():
        if not can_view(slug):
            continue
        p = dict(p)
        _b = pipeline.school_badge_file(p.get('school'), p.get('program'))
        p['badge'] = {'file': _b[0], 'bg': _b[1]} if _b else None
        p['can_edit'] = can_manage(slug) and not store.is_demo(slug)
        p['has_photo'] = headshots.exists(slug)
        p['photo_v'] = int(os.path.getmtime(headshots.path(slug))) if p['has_photo'] else 0
        last, first = _split_name(p['name'])
        pos = _player_pos(p)
        priv.setdefault(p.get('program', 'shepherds'), []).append((slug, p, url_for('player_overview', slug=slug), last, first, pos))   # Shepherds is built exactly like every other team; can_view() keeps it admin-only
    key = lambda t: (t[3].lower(), t[4].lower())
    groups = [(k, store.program_label(k), sorted(v, key=key)) for k, v in sorted(priv.items(), key=lambda kv: store.program_label(kv[0]))]
    for tk in store.list_teams():                      # teams added by hand that have no players yet
        if tk not in priv and is_admin():
            groups.append((tk, store.program_label(tk), []))
    if 'shepherds' not in priv:
        groups.append(('shepherds', 'Shepherds', []))
    return groups


def _tour_next_player(groups):
    for _pk, _l, plist in groups:
        if plist and _pk != 'shepherds':
            return url_for('player_overview', slug=plist[0][0]) + '?tour=player'
    return ''


def _team_tiles(groups):
    """Admin home: one tile per team/program, with its logo, player count and coach count."""
    coaches = store.list_coaches().values()
    tiles = []
    for pk, label, plist in groups:
        if not plist and pk == 'shepherds':
            continue
        _b = pipeline.school_badge_file(label, pk)
        tiles.append({'key': pk, 'label': label, 'players': len(plist),
                      'coaches': sum(1 for c in coaches if c.get('program') == pk),
                      'badge': {'file': _b[0], 'bg': _b[1]} if _b else None,
                      'brand': pk == 'shepherds', 'demo': pk in store.DEMO_PROGRAMS,
                      'search': label.lower()})
    # real programs first (A-Z), then Shepherds, then the sample program
    tiles.sort(key=lambda t: (t['demo'], t['brand'], t['label'].lower()))
    return tiles


@app.route('/admin/teams/add', methods=['POST'])
@admin_required
def admin_add_team():
    slug, err = store.add_team(request.form.get('name'))
    if err:
        return redirect(url_for('dashboard', team_msg=err))
    return redirect(url_for('team_dashboard', program=slug))


@app.route('/')
def dashboard():
    if not session.get('coach'):
        return redirect(url_for('welcome') if marketing.is_public() else url_for('login'))
    groups = _build_groups()
    if is_admin():
        return render_template('dashboard.html', mode='teams', tiles=_team_tiles(groups), groups=[], team_label=None, team_msg=request.args.get('team_msg'),
                               is_coach=True, is_admin=True, coach_key=session.get('coach') or '', tour_next=_tour_next_player(groups))
    if my_program() and not store.needs_first_upload(session.get('coach')) and not request.args.get('tour'):
        return redirect(url_for('team_dashboard', program=my_program()))
    return render_template('dashboard.html', mode='players', groups=[(l, p) for _, l, p in groups], team_label=None, tiles=[],
                           is_coach=True, is_admin=False, coach_key=session.get('coach') or '',
                           first_upload=store.needs_first_upload(session.get('coach')), tour_next=_tour_next_player(groups))


def _team_ok(program):
    """Admins can open any team; a program coach only his own."""
    if is_admin():
        return
    if not session.get('coach') or program != my_program():
        abort(404)


def _team_players_page(program, page_title, pitchers_only=False):
    groups = [g for g in _build_groups() if g[0] == program]
    if not groups:
        abort(404)
    if pitchers_only:      # hitters who never pitched belong on the Hitters page only
        groups = [(k, l, [t for t in pl if not t[1].get('roles') or (t[1].get('roles') or {}).get('pitch')]) for k, l, pl in groups]
    return render_template('dashboard.html', mode='players', groups=[(l, p) for _, l, p in groups], team_label=groups[0][1], tiles=[],
                           is_coach=True, is_admin=is_admin(), coach_key=session.get('coach') or '', tour_next=_tour_next_player(groups),
                           team_program=program, page_title=page_title)


@app.route('/team/<program>')
@login_required
def team_view(program):
    _team_ok(program)
    return redirect(url_for('team_dashboard', program=program))


_PSTAT_SKIP = {'bf', 'ip', 'pitches'}     # estimates that read as real box-score numbers; everything else the pitching stats module computes is shown


_STAT_ABBR = {
    # hitting
    'avg_ev': 'Avg EV', 'max_ev': 'Max EV', 'ev90': 'EV90', 'hard_hit_pct': 'HH%', 'sweet_spot_pct': 'SwSp%', 'xba': 'xBA', 'avg_la': 'LA',
    'score': 'SDR', 'qab_pct': 'QAB%', 'chase_pct': 'Chase%', 'zone_swing_pct': 'Z-Swing%', 'swing_pct': 'Swing%', 'whiff_pct': 'Whiff%', 'zone_contact_pct': 'Z-Con%',
    'brl_pct': 'Brl%', 'gb_pct': 'GB%', 'ld_pct': 'LD%', 'fb_pct': 'Fly%', 'pu_pct': 'PU%', 'pull_pct': 'Pull%', 'avg_bs': 'Avg BS', 'max_bs': 'Max BS',
    'sq_pct': 'Sq%', 'avg_smash': 'Smash', 'ev_gap': 'EV Gap', 'bip': 'BIP',
    # pitching
    'hits': 'H', 'walks': 'BB', 'hbp': 'HBP', 'ks': 'K', 'strike_pct': 'Str%', 'ball_pct': 'Ball%', 'fps_pct': 'FPS%', 'zone_pct': 'Zone%',
    'edge_pct': 'oZone%', 'ahead_pct': 'Ahead%', 'twostrike_pct': 'Putaway%', 'csw_pct': 'CSW%', 'zswing_pct': 'Z-Swing%', 'zcontact_pct': 'Z-Con%',
    'ocontact_pct': 'O-Con%', 'contact_pct': 'Con%', 'cs_pct': 'CS%', 'foul_pct': 'Foul%', 'hh_pct': 'HH%', 'top_velo': 'Top Velo',
    'fb_velo': 'FB Velo', 'fb_top': 'FB Top', 'fb_spin': 'FB Spin', 'fb_ivb': 'FB IVB', 'fb_hb': 'FB HB', 'fb_vaa': 'FB VAA', 'avg_spin': 'Spin',
    'max_spin': 'Max Spin', 'velo_gap': 'Velo Gap', 'ext': 'Ext', 'rel_h': 'RelH', 'rel_s': 'RelS', 'rel_h_sd': 'RelH SD', 'rel_s_sd': 'RelS SD',
    'arsenal': 'Arsenal',
}


def _last_first(name):
    """'Michael Chang' -> 'Chang, Michael' (a trailing Jr./III stays with the last name)."""
    parts = (name or '').split()
    if len(parts) < 2:
        return name or ''
    k = 1
    if parts[-1].strip('.').lower() in ('jr', 'sr', 'ii', 'iii', 'iv', 'v') and len(parts) > 2:
        k = 2
    return ' '.join(parts[-k:]) + ', ' + ' '.join(parts[:-k])


def _pct_num(txt):
    try:
        return float(re.sub(r'[^0-9.\-]', '', str(txt)))
    except Exception:
        return None


def _jersey_lookup(program):
    """name -> jersey number from the team roster (Team roster page). Empty until numbers are entered; the tables show a placeholder."""
    try:
        r = roster_mod.load(program) or {}
        pl = [(x['name'], x) for x in r.get('players', [])]
    except Exception:
        pl = []

    def look(name):
        try:
            m = roster_mod.match_name(name, pl) if pl else None
            return str((m[0] or {}).get('number') or '') if m else ''
        except Exception:
            return ''
    return look


_PITCH_LINEUP = [  # (stat id, header, hover text "Full name: definition", section)
    ('gp', 'GP', 'Games Played: outings with data.', 'Volume'),
    ('ip', 'IP', 'Innings Pitched: outs recorded (tagged outs + strikeouts) / 3. Estimate.', 'Volume'),
    ('pitches', 'TP', 'Total Pitches thrown.', 'Volume'),
    ('balls', 'Balls', 'Balls: pitches called balls (hit-by-pitch included).', 'Volume'),
    ('strikes', 'Strikes', 'Strikes: called, swinging, foul and in-play pitches.', 'Volume'),
    ('hits', 'H', 'Hits allowed: pitches tagged single, double, triple or home run.', 'Volume'),
    ('ks', 'K', 'Strikeouts: swinging or called strike three (estimate).', 'Volume'),
    ('walks', 'BB', 'Walks: balls thrown with 3 balls already in the count (estimate).', 'Volume'),
    ('hbp', 'HBP', 'Hit By Pitch: pitches that hit the batter.', 'Volume'),
    ('strike_pct', 'Str%', 'Strike %: strikes / pitches.', 'Command'),
    ('zone_pct', 'Zone%', 'Zone %: pitches in the strike zone / pitches with location.', 'Command'),
    ('fps_pct', 'FPS%', 'First Pitch Strike %: strikes on 0-0 pitches.', 'Command'),
    ('ahead_pct', 'Ahead%', 'Ahead in Count %: pitches thrown with more strikes than balls.', 'Command'),
    ('whiff_pct', 'Whiff%', 'Whiff %: swinging strikes / swings.', 'Swing and Miss'),
    ('chase_pct', 'Chase%', 'Chase %: swings at pitches outside the zone / pitches outside the zone.', 'Swing and Miss'),
    ('csw_pct', 'CSW%', 'Called + Swinging Strike %: (called strikes + whiffs) / pitches.', 'Swing and Miss'),
    ('swing_pct', 'Swing%', 'Swing %: swings / pitches.', 'Swing and Miss'),
    ('bip', 'BIP', 'Balls In Play: pitches put in play.', 'Contact Allowed'),
    ('avg_ev', 'Avg EV', 'Average Exit Velocity on balls in play (mph).', 'Contact Allowed'),
    ('contact_pct', 'Contact%', 'Contact %: fouls + balls in play / swings.', 'Contact Allowed'),
    ('hh_pct', 'HH%', 'Hard-Hit %: balls in play at 95+ mph.', 'Contact Allowed'),
    ('gb_pct', 'GB%', 'Ground Ball %: launch angle under 10 degrees.', 'Contact Allowed'),
    ('ld_pct', 'LD%', 'Line Drive %: launch angle 10-25 degrees.', 'Contact Allowed'),
    ('fb_pct', 'Fly%', 'Fly Ball %: launch angle 25-50 degrees.', 'Contact Allowed'),
    ('pu_pct', 'PU%', 'Pop-Up %: launch angle over 50 degrees.', 'Contact Allowed'),
    ('fb_use', 'FB%', 'Fastball usage % (includes Cutter and Sinker): share of all pitches.', 'Arsenal'),
    ('fb_k', 'FBk%', 'Fastball Strike % (includes Cutter and Sinker): strikes / fastballs thrown.', 'Arsenal'),
    ('cb_use', 'CB%', 'Curveball usage % (includes Slurve): share of all pitches.', 'Arsenal'),
    ('cb_k', 'CBk%', 'Curveball Strike % (includes Slurve): strikes / curveballs thrown.', 'Arsenal'),
    ('sl_use', 'SL%', 'Slider usage % (includes Sweeper): share of all pitches.', 'Arsenal'),
    ('sl_k', 'SLk%', 'Slider Strike % (includes Sweeper): strikes / sliders thrown.', 'Arsenal'),
    ('ch_use', 'CH%', 'Changeup usage % (includes Splitter): share of all pitches.', 'Arsenal'),
    ('ch_k', 'CHk%', 'Changeup Strike % (includes Splitter): strikes / changeups thrown.', 'Arsenal'),
]


def _stat_table(program, side):
    """Columns + rows for the sortable team stat tables. side = 'pitching' | 'hitting'. Each cell is (text, number-for-sorting)."""
    cols, rows = [], []
    jersey = _jersey_lookup(program)
    if side == 'pitching':
        D = team.pitching_data(program)
        for pl in D['players']:
            v = dict(pl['v'])
            v['gp'] = (str(pl['sessions']), '')
            rows.append({'name': pl['name'], 'key': pl['key'], 'disp': _last_first(pl['name']), 'jersey': jersey(pl['name']), 'url': url_for('player_overview', slug=pl['key']), 'n': pl['n'],
                         'cells': {i: (v[i][0], _pct_num(v[i][0])) for i, _a, _d, _g in _PITCH_LINEUP if i in v and v[i][0] not in (None, '', '—', '-', '–')}})
        for i, ab, d, g in _PITCH_LINEUP:
            cols.append({'id': i, 'label': ab, 'abbr': ab, 'group': g, 'def': d})
    else:
        D = team.hitting_data(program, True)
        for pl in D['players']:
            cells = {}
            for i, (lab, grp, d, kind) in team.HIT_CATALOG.items():
                if i == 'pitches':
                    continue
                v = pl['s'].get(i)
                if v is None:
                    continue
                cells[i] = (team._fmt_hit(kind, v), v)
            rows.append({'name': pl['name'], 'key': pl['key'], 'disp': _last_first(pl['name']), 'jersey': jersey(pl['name']), 'url': url_for('beta_hitter', key=pl['key']), 'n': pl['n'], 'cells': cells})
        for i, (lab, grp, d, kind) in team.HIT_CATALOG.items():
            if i == 'pitches':
                continue
            cols.append({'id': i, 'label': lab, 'abbr': _STAT_ABBR.get(i, lab), 'group': grp, 'def': d})
    # xwOBA / xERA / FIP are always calculated (cached) but only shown for players past the sample minimums; admins can add ?preview=1
    preview = is_admin() and request.args.get('preview') == '1'
    adv = advanced.table(program)['p' if side == 'pitching' else 'h']
    ADV = [('xwoba', 'xwOBA (est.)', 'Expected weighted on-base average from exit velocity, launch angle, walks, HBP and strikeouts. Estimated from our own batted-ball model, not Statcast.' if side == 'hitting' else 'Expected wOBA allowed, from the contact quality, walks, HBP and strikeouts a pitcher gave up. Estimated from our own batted-ball model, not Statcast.', lambda v: f'{v:.3f}'.lstrip('0'))]
    if side == 'pitching':
        ADV += [('xera', 'xERA (est.)', 'Expected ERA, converted from xwOBA allowed (MLB run environment). An estimate.', lambda v: f'{v:.2f}'),
                ('fip', 'FIP (est.)', 'Fielding Independent Pitching: (13 HR + 3 (BB+HBP) - 2 K) / IP + 3.10. Innings and results come from the tagged data, so it is an estimate.', lambda v: f'{v:.2f}')]
    for r in rows:
        v = adv.get(r['key'])
        vals = ({k: v[k] for k in ('xwoba', 'xera', 'fip') if v and v.get(k) is not None} if preview else advanced.released('p' if side == 'pitching' else 'h', v))
        for sid, lab, d, fmt in ADV:
            if sid in vals:
                r['cells'][sid] = (fmt(vals[sid]), vals[sid])
    for sid, lab, d, fmt in ADV:
        if any(sid in r['cells'] for r in rows):
            cols.append({'id': sid, 'label': lab, 'abbr': lab.split(' ')[0], 'group': 'Run value', 'def': d})
    used = {i for r in rows for i in r['cells']}
    cols = [c for c in cols if c['id'] in used]
    order = list(dict.fromkeys(c['group'] for c in cols))
    cols.sort(key=lambda c: order.index(c['group']))      # keep each group together (the sort is stable)
    groups = []
    for c in cols:
        if groups and groups[-1]['name'] == c['group']:
            groups[-1]['n'] += 1
        else:
            groups.append({'name': c['group'], 'n': 1})
    rows.sort(key=lambda r: r['disp'].lower())
    return cols, groups, rows


def _colsets(side):
    """This coach's saved column sets for one stat sheet: {'sets': {name: [stat ids]}, 'active': name or ''}."""
    c = (current_coach() or {}).get('col_sets') or {}
    d = c.get(side) or {}
    return {'sets': d.get('sets') or {}, 'active': d.get('active') or ''}


@app.route('/team/<program>/<side>/colsets', methods=['POST'])
@login_required
def save_colsets(program, side):
    _team_ok(program)
    if side not in ('pitching', 'hitting'):
        abort(404)
    data = request.get_json(silent=True) or {}
    sets = {}
    for name, ids in (data.get('sets') or {}).items():
        name = re.sub(r'\s+', ' ', str(name)).strip()[:40]
        if name and isinstance(ids, list):
            sets[name] = [str(i)[:40] for i in ids][:80]
        if len(sets) >= 12:
            break
    active = str(data.get('active') or '')
    me = session.get('coach')
    cs = dict((current_coach() or {}).get('col_sets') or {})
    cs[side] = {'sets': sets, 'active': active if active in sets else ''}
    store.update_coach(me, col_sets=cs)
    return jsonify(ok=True)


@app.route('/team/<program>/pitchers')
@login_required
def team_pitchers(program):
    _team_ok(program)
    if request.args.get('view') == 'cards':
        return _team_players_page(program, 'Pitchers', pitchers_only=True)
    cols, groups, rows = _stat_table(program, 'pitching')
    return render_template('team_stats.html', side='pitching', title='Pitchers', cols=cols, groups=groups, rows=rows, program=program,
                           team_label=store.program_label(program), colsets=_colsets('pitching'))


@app.route('/team/<program>/hitters')
@login_required
def team_hitters(program):
    _team_ok(program)
    if not plans.allowed(program, 'hitting'):
        return _upgrade('hitting')
    if request.args.get('view') == 'cards':
        rows = [r for r in hitting.list_hitters() if r['program'] == program]
        rows.sort(key=lambda r: r['name'].split()[-1].lower())
        return render_template('team_hitters.html', rows=rows, program=program, team_label=store.program_label(program))
    cols, groups, rows = _stat_table(program, 'hitting')
    return render_template('team_stats.html', side='hitting', title='Hitters', cols=cols, groups=groups, rows=rows, program=program,
                           team_label=store.program_label(program), colsets=_colsets('hitting'))


@app.route('/team/<program>/dashboard')
@login_required
def team_dashboard(program):
    _team_ok(program)
    cfg = team.load(program)
    P = team.pitching_data(program)
    H = team.hitting_data(program, True) if plans.allowed(program, 'hitting') else None
    def half(side, D, ids):
        tiles = [D['tiles'][i] for i in ids if i in D['tiles']]
        return {'side': side, 'D': D, 'tiles': tiles, 'goals': team.goal_rows(program, side, D['tiles']),
                'picker': team.stat_picker(side, ids), 'metrics': team.goal_metric_options(side)}
    halves = [half('pitching', P, cfg['pitching_stats'])]
    if H is not None:
        halves.append(half('hitting', H, cfg['hitting_stats']))
    sessions = sorted(set(P['sessions']) | set(H['sessions'] if H else []))
    return render_template('team_dashboard.html', program=program, team_label=store.program_label(program), halves=halves,
                           last_session=sessions[-1] if sessions else None, is_coach=True, is_admin=is_admin(), pr_recent=[r for r in prs.program_recent(program, days=30, limit=200) if r['kind'] != 'h' or plans.allowed(program, 'hitting')],
                           wm_url=_wm_url(program),
                           coach_key=session.get('coach') or '', th=theme.for_program(program), th_default=theme.default_pair(program))


@app.route('/team/<program>/personal-bests')
@login_required
def team_prs(program):
    _team_ok(program)
    rows = prs.program_recent(program, days=30, limit=200)
    if not plans.allowed(program, 'hitting'):
        rows = [r for r in rows if r['kind'] != 'h']
    days = []
    for r in rows:
        if not days or days[-1]['date'] != r['date']:
            days.append({'date': r['date'], 'label': overview._long_date(r['date']), 'rows': []})
        days[-1]['rows'].append({**r, 'url': url_for('player_overview', slug=r['key']) if r['kind'] == 'p' else url_for('beta_hitter', key=r['key'])})
    return render_template('team_prs.html', program=program, team_label=store.program_label(program), days=days, total=len(rows),
                           is_coach=True, is_admin=is_admin(), coach_key=session.get('coach') or '',
                           th=theme.for_program(program), th_default=theme.default_pair(program))


@app.route('/team/<program>/swing-decisions')
@login_required
def team_swing_decisions(program):
    _team_ok(program)
    if not plans.allowed(program, 'hitting'):
        return _upgrade('hitting')
    return render_template('team_swing_decisions.html', program=program, team_label=store.program_label(program),
                           D=team.swing_decision_page_data(program), th=theme.for_program(program))


@app.route('/team/<program>/customize', methods=['POST'])
@login_required
def team_customize(program):
    _team_ok(program)
    side = 'hitting' if request.form.get('side') == 'hitting' else 'pitching'
    if side == 'hitting' and not plans.allowed(program, 'hitting'):
        abort(403)
    team.set_stats(program, side, request.form.getlist('stat'))
    return redirect(url_for('team_dashboard', program=program) + f'#{side}')


def _wm_url(program):
    src = theme.watermark_source(program)
    if not src:
        return None
    try:
        v = int(os.path.getmtime(src[1])) if src[0] != 'school' else 0
    except OSError:
        v = 0
    return url_for('watermark', program=program, v=v)


APPEARANCE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Appearance Settings</title>
<style>{{ theme_css|safe }}</style>
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=Barlow:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{ --ink:#22303a; --teal:var(--accent,#5c97a8); --muted:#6b7680; --line:#dde2e5; }
  *{box-sizing:border-box;} body{background:#f7f6f2;color:var(--ink);font-family:'Barlow',sans-serif;margin:0;padding-bottom:50px;}
  .hero{background:var(--brand,#22303a);padding:34px 16px 28px;border-bottom:3px solid var(--teal);position:relative;overflow:hidden;} .wrap{max-width:860px;margin:0 auto;padding:0 16px;} .hero .wrap{padding:0;position:relative;}
  .hero .wm{position:absolute;right:0;top:50%;transform:translateY(-50%);height:118%;max-height:140px;max-width:300px;width:auto;opacity:.2;pointer-events:none;object-fit:contain;} .hero .wrap>*:not(.wm){position:relative;z-index:1;}
  .eyebrow{font:600 12px 'Oswald',sans-serif;letter-spacing:.16em;text-transform:uppercase;color:var(--accent-on-dark,#5c97a8);margin:0 0 8px;}
  h1{font:700 40px 'Oswald',sans-serif;margin:0 0 6px;color:#fff;} .sub{color:#c9d3d8;font-size:14.5px;margin:0;}
  .back{display:inline-block;margin:18px 0 6px;font:700 13px Barlow,sans-serif;color:var(--accent-ink,#5c97a8);text-decoration:none;}
  h2{font:700 24px 'Oswald',sans-serif;margin:26px 0 10px;} .card{background:#fff;border-radius:14px;box-shadow:0 1px 3px rgba(26,31,36,.08);padding:18px 20px;}
  .note{font-size:13.5px;color:var(--muted);line-height:1.55;margin:0 0 12px;} .msg{background:#e4f4ec;color:#1f7a50;border-radius:10px;padding:10px 14px;margin:14px 0 0;font-size:14px;} .msg.err{background:#fbe8e5;color:#a63a2c;}
  .row{display:flex;gap:18px;align-items:center;flex-wrap:wrap;} .row label{font:600 12px 'Barlow',sans-serif;color:var(--muted);display:flex;align-items:center;gap:8px;}
  input[type=color]{width:42px;height:32px;border:1px solid var(--line);border-radius:8px;padding:2px;background:#fff;}
  .btn{border:0;background:var(--accent,#5c97a8);color:var(--on-accent,#fff);font:700 14px 'Barlow',sans-serif;border-radius:999px;padding:10px 20px;cursor:pointer;} .btn.ghost{background:#eef1f0;color:var(--ink);}
  .prev{border-radius:12px;background:var(--brand,#22303a);height:120px;position:relative;overflow:hidden;margin:0 0 14px;} .prev img{position:absolute;right:16px;top:50%;transform:translateY(-50%);max-height:92px;max-width:240px;opacity:.2;object-fit:contain;} .prev b{position:absolute;left:18px;top:50%;transform:translateY(-50%);font:700 26px 'Oswald',sans-serif;color:#fff;}
  @media (max-width:520px){h1{font-size:32px;}}
</style></head><body>
<div class="hero"><div class="wrap">{% if wm_url %}<img class="wm" src="{{ wm_url }}" alt="">{% endif %}<div style="position:absolute;top:-14px;right:0;z-index:2;">{% include '_usermenu.html' %}</div>
  <p class="eyebrow">{{ team_label }}</p><h1>Appearance Settings</h1><p class="sub">Colors and the logo shown in your dashboard header.</p></div></div>
<div class="wrap">
  <a class="back" href="{{ url_for('team_dashboard', program=program) }}">&larr; Team Dashboard</a>
  {% if msg %}<div class="msg {{ 'err' if err }}">{{ msg }}</div>{% endif %}
  <h2>Team colors</h2>
  <form class="card" method="post" action="{{ url_for('team_theme', program=program) }}"><p class="note">{% if th.source == 'custom' %}Using your custom colors.{% elif th.source == 'logo' %}Pulled from your school logo.{% elif th.source == 'school' %}Your school's colors.{% else %}Default colors.{% endif %} They show on the dashboards, player pages and outing reports.</p>
    <div class="row"><label>Header <input type="color" name="brand" value="{{ th.brand }}"></label><label>Accent <input type="color" name="accent" value="{{ th.accent }}"></label>
    <button class="btn" type="submit">Save colors</button>{% if th.source == 'custom' %}<button class="btn ghost" type="submit" name="reset" value="1">Reset to school colors</button>{% endif %}</div></form>
  <h2>Header logo</h2>
  <div class="card"><p class="note">Shown faintly in the top right of your Team Dashboard header. A PNG with a transparent background looks best, in white or a light color so it reads on your header. A solid white box around the logo is removed automatically.</p>
    <div class="prev"><b>Team Dashboard</b>{% if wm_url %}<img src="{{ wm_url }}" alt="">{% endif %}</div>
    <p class="note">{% if kind == 'custom' %}Using the logo you uploaded.{% elif kind == 'builtin' %}Using the built-in logo for {{ team_label }}.{% elif kind == 'school' %}Using the school logo.{% else %}No logo yet.{% endif %}</p>
    <form method="post" action="{{ url_for('team_logo', program=program) }}" enctype="multipart/form-data" class="row"><input type="file" name="logo" accept="image/png,image/jpeg,image/webp" required><button class="btn" type="submit">{{ 'Replace logo' if kind == 'custom' else 'Upload logo' }}</button>
      {% if kind == 'custom' %}<button class="btn ghost" type="submit" name="remove" value="1" formnovalidate>Remove my logo</button>{% endif %}</form></div>
</div></body></html>"""


@app.route('/team/<program>/appearance')
@login_required
@head_required
def team_appearance(program):
    _team_ok(program)
    src = theme.watermark_source(program)
    g.theme_program = program
    return render_template_string(APPEARANCE_PAGE, program=program, team_label=store.program_label(program), th=theme.for_program(program),
                                  wm_url=_wm_url(program), kind=src[0] if src else None, msg=request.args.get('msg'), err=bool(request.args.get('err')))


def _clean_logo(raw):
    """Image bytes -> transparent PNG bytes (max 900px, a solid white box around the logo removed). Raises on a bad image."""
    import io
    from PIL import Image, ImageDraw
    im = Image.open(io.BytesIO(raw))
    if im.format not in ('PNG', 'JPEG', 'WEBP'):
        raise ValueError('format')
    im = im.convert('RGBA')
    im.thumbnail((900, 900))
    w, h = im.size
    px = im.load()
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        r, g_, b, al = px[seed]
        if al > 200 and min(r, g_, b) > 235:
            ImageDraw.floodfill(im, seed, (255, 255, 255, 0), thresh=40)
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return buf.getvalue()


@app.route('/team/<program>/appearance/logo', methods=['POST'])
@login_required
@head_required
def team_logo(program):
    _team_ok(program)
    back = lambda m, err=False: redirect(url_for('team_appearance', program=program, msg=m, **({'err': 1} if err else {})))
    path = theme.custom_logo_path(program)
    if request.form.get('remove'):
        if os.path.exists(path):
            os.remove(path)
            github_sync.delete_file(f'data/logos/{program}.png')
        return back('Your logo was removed.')
    f = request.files.get('logo')
    if not f or not f.filename:
        return back('Choose an image first.', True)
    raw = f.read(3 * 1024 * 1024 + 1)
    if len(raw) > 3 * 1024 * 1024:
        return back('That image is over 3 MB. Please use a smaller one.', True)
    try:
        data = _clean_logo(raw)
    except Exception:
        return back('That file could not be read as a PNG, JPG or WebP image.', True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as out:
        out.write(data)
    github_sync.put_file(f'data/logos/{program}.png', data)
    return back('Logo saved.')


@app.route('/team/<program>/theme', methods=['POST'])
@login_required
@head_required
def team_theme(program):
    _team_ok(program)
    d = team.load(program)
    if request.form.get('reset'):
        d.pop('theme', None)
    else:
        brand, accent = request.form.get('brand', ''), request.form.get('accent', '')
        if theme._valid(brand) and theme._valid(accent):
            d['theme'] = {'brand': brand.lower(), 'accent': accent.lower()}
    team.save(program, d)
    return redirect(url_for('team_appearance', program=program, msg='Colors saved.'))


@app.route('/team/<program>/goals', methods=['POST'])
@login_required
def team_goals(program):
    _team_ok(program)
    f = request.form
    side = 'hitting' if f.get('side') == 'hitting' else 'pitching'
    if side == 'hitting' and not plans.allowed(program, 'hitting'):
        abort(403)
    act = f.get('action')
    if act == 'add':
        team.add_goal(program, f)
    elif act == 'delete':
        team.delete_goal(program, f.get('id', ''))
    elif act in ('toggle', 'progress'):
        team.update_goal(program, f.get('id', ''), f)
    return redirect(url_for('team_dashboard', program=program) + f'#goals-{side}')


@app.route('/brand-logo/<fname>')
def brand_logo(fname):
    path = os.path.join(pipeline.APP_DIR, 'assets', 'brand', os.path.basename(fname))
    if os.path.basename(fname) != 'shepsavant_logo.png' or not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype='image/png', max_age=86400)


def _date_range(dates, extra=None, empty=False):
    """Model for templates/_daterange.html from ?frm= / ?to= (ISO dates) and the list of dates the player has data for."""
    import datetime as _dt
    from urllib.parse import urlencode
    def _iso(v):
        try:
            return _dt.date.fromisoformat((v or '')[:10]).isoformat()
        except ValueError:
            return None
    frm, to = _iso(request.args.get('frm')), _iso(request.args.get('to'))
    if frm and to and frm > to:
        frm, to = to, frm
    ds = sorted(d for d in dates if d)
    today = _dt.date.today()
    extra = dict(extra or {})
    def qs(f, t):
        q = {k: v for k, v in extra.items() if v}
        if f:
            q['frm'] = f
        if t:
            q['to'] = t
        return urlencode(q)
    presets = [('All', None, None), ('Last 7 days', (today - _dt.timedelta(days=7)).isoformat(), None), ('Last 30 days', (today - _dt.timedelta(days=30)).isoformat(), None)]
    if ds:
        yr = ds[-1][:4]
        presets.append((f'{yr} season', f'{yr}-01-01', f'{yr}-12-31'))
    return {'frm': frm, 'to': to, 'min': ds[0] if ds else '', 'max': ds[-1] if ds else '', 'empty': empty, 'extra': extra, 'presets': presets, 'qs': qs}


@app.route('/player/<slug>')
def player_overview(slug):
    if not session.get('coach'):
        return redirect(url_for('login', next=request.path))
    bio = store.get_player(slug)
    if not bio or not can_view(slug):
        abort(404)
    return _pitcher_page(slug, bio)


def _share_ctx(kind, ref, program):
    """What the Share panel on a coach's profile page needs, or None when this viewer can't share it."""
    if is_player() or is_demo_viewer() or not session.get('coach'):
        return None
    if not (is_admin() or program == my_program()):
        return None
    t, s = shares.for_ref(kind, ref)
    return {'url': url_for('public_share', token=t, _external=True) if t else '', 'active': bool(t),
            'post': url_for('share_pitcher', slug=ref) if kind == 'pitcher' else url_for('share_hitter', key=ref)}


def _pitcher_page(slug, bio, public=False, token=None):
    can_retag = (not public) and can_manage(slug) and not store.is_demo(slug) and not is_player()
    _dr = _date_range([o['date'] for o in outings_mod.outings(slug)])
    b = overview.build(slug, bio, retag=can_retag, frm=_dr['frm'], to=_dr['to']) if (_dr['frm'] or _dr['to']) else None
    if (_dr['frm'] or _dr['to']) and not b:
        _dr = _date_range([o['date'] for o in outings_mod.outings(slug)], empty=True)
        _dr['frm'] = _dr['to'] = None
    b = b or overview.build(slug, bio, retag=can_retag)
    if not b:
        abort(404)
    if not public and not store.is_demo(slug):
        _track('view', slug=slug)
    last, first = _split_name(bio['name'])
    has_photo = headshots.exists(slug)
    _b = pipeline.school_badge_file(bio.get('school'), bio.get('program'))
    badge = {'file': _b[0], 'bg': _b[1]} if _b else None
    css = re.sub(r'@font-face\s*\{[^}]*\}', '', pipeline.CSS)
    hitter_url = None      # two-way player: a hitter profile exists for the same person (same program) -> Hitter / Pitcher switch
    _prog = bio.get('program')
    if not public and _prog and not store.is_demo(slug) and (is_admin() or (_prog == my_program() and plans.allowed(_prog, 'hitting'))):
        _hk = hitting.hitter_key_for(bio['name'], _prog)
        hitter_url = url_for('beta_hitter', key=_hk) if _hk else None
    return render_template('player_overview.html', dr=_dr, public=public, photo_src=(url_for('public_share_photo', token=token) if public else None),
                           share=(None if public else _share_ctx('pitcher', slug, _prog)), share_team=store.program_label(_prog) if (public and _prog) else '',
                           can_retag=can_retag, retag_types=[l for l, _ in outings_mod.RETAG_TYPES], pr_ent=(None if public else prs.for_pitcher(slug)), b=b, bio=bio, slug=slug, css=css, hitter_url=hitter_url, has_photo=has_photo, badge=badge,
                           photo_v=int(os.path.getmtime(headshots.path(slug))) if has_photo else 0,
                           initials=(first[:1] + last[:1]).upper(), pos=_player_pos(bio), is_coach=(not public) and bool(session.get('coach')) and not is_player(), can_edit=(not public) and can_manage(slug), is_demo=store.is_demo(slug),
                           tour_next='' if public else ((url_for('view_outing', slug=slug, date=b['log'][0]['id']) + '?tour=report') if b.get('log') else ''))


@app.route('/player/<slug>/share', methods=['POST'])
@login_required
def share_pitcher(slug):
    bio = store.get_player(slug)
    if not bio or not can_view(slug) or not can_manage(slug) or store.is_demo(slug) or is_player() or is_demo_viewer():
        abort(404)
    if request.form.get('action') == 'revoke':
        shares.revoke('pitcher', slug)
    else:
        shares.create('pitcher', slug, bio.get('program'), session.get('coach'))
    return redirect(url_for('player_overview', slug=slug) + '#share')


@app.route('/hitter/<key>/share', methods=['POST'])
@login_required
def share_hitter(key):
    h = hitting.hitter_profile(key, include_demo=False)
    if not h or h.get('opp_slug') or h['demo'] or is_player() or is_demo_viewer() or not (is_admin() or h['program'] == my_program()):
        abort(404)
    if request.form.get('action') == 'revoke':
        shares.revoke('hitter', key)
    else:
        shares.create('hitter', key, h['program'], session.get('coach'))
    return redirect(url_for('beta_hitter', key=key) + '#share')


@app.route('/s/<token>')
def public_share(token):
    """The public, read-only profile behind a share link. No sign-in; the token is the key, and revoking it ends access."""
    s = shares.get(token)
    if not s:
        abort(404)
    if s['kind'] == 'pitcher':
        bio = store.get_player(s['ref'])
        if not bio or store.is_demo(s['ref']):
            abort(404)
        resp = make_response(_pitcher_page(s['ref'], bio, public=True, token=token))
    else:
        _d = _date_range([])
        h = hitting.hitter_profile(s['ref'], include_demo=False, vs=request.args.get('vs', 'all'), frm=_d['frm'], to=_d['to'])
        if not h or h['demo'] or h.get('opp_slug'):
            abort(404)
        resp = make_response(_hitter_render(s['ref'], h, public=True, token=token))
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    resp.headers['Cache-Control'] = 'private, no-store'
    resp.headers['Referrer-Policy'] = 'no-referrer'
    return resp


@app.route('/s/<token>/photo')
def public_share_photo(token):
    s = shares.get(token)
    if not s:
        abort(404)
    if s['kind'] == 'pitcher':
        slug = s['ref']
    else:
        h = hitting.hitter_profile(s['ref'], include_demo=False)
        slug = (h or {}).get('bio', {}).get('photo_slug')
    if not slug or not headshots.exists(slug):
        abort(404)
    resp = send_file(headshots.path(slug), mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'private, max-age=600'
    return resp


@app.route('/clip/<int:pid>/<code>/<int:year>')
def pitch_clip(pid, code, year):
    """Redirects to a playable Baseball Savant clip of this MLB pitcher's pitch type in that season (looked up once, then remembered)."""
    import arsenal_comps as _ac
    import savant_clips
    ids = {str(r['id']) for r in _ac.load_reference()[0]}          # only pitchers in our comparison data: keeps this from being a free Savant proxy
    if str(pid) not in ids or code not in savant_clips.CODES or not (2015 <= year <= 2035):
        abort(404)
    resp = redirect(savant_clips.resolve(pid, code, year))
    resp.headers['Cache-Control'] = 'private, max-age=3600'
    return resp


@app.route('/player/<slug>/outings')
def player_outings(slug):
    if not session.get('coach'):
        return redirect(url_for('login', next=request.path))
    bio = store.get_player(slug)
    if not bio or not can_view(slug):
        abort(404)
    log = overview.all_outings_log(slug, bio)
    if not log:
        abort(404)
    _b = pipeline.school_badge_file(bio.get('school'), bio.get('program'))
    return render_template('player_outings.html', bio=bio, slug=slug, log=log, can_edit=can_manage(slug), is_demo=store.is_demo(slug),
                           is_coach=bool(session.get('coach')) and not is_player(), has_photo=headshots.exists(slug),
                           badge={'file': _b[0], 'bg': _b[1]} if _b else None, g_prog=bio.get('program'))


@app.route('/player/<slug>/personal-bests')
def player_prs(slug):
    if not session.get('coach'):
        return redirect(url_for('login', next=request.path))
    bio = store.get_player(slug)
    if not bio or not can_view(slug):
        abort(404)
    ent = prs.for_pitcher(slug)
    _b = pipeline.school_badge_file(bio.get('school'), bio.get('program'))
    last, first = _split_name(bio['name'])
    return render_template('player_prs.html', name=bio['name'], ent=ent, history=_pr_history(ent), back_url=url_for('player_overview', slug=slug),
                           photo=url_for('headshot', slug=slug) if headshots.exists(slug) else None, badge={'file': _b[0], 'bg': _b[1]} if _b else None,
                           initials=(first[:1] + last[:1]).upper(), is_coach=bool(session.get('coach')) and not is_player())


def _pr_history(ent):
    if not ent:
        return []
    return [{'who': '', 'label': ev['label'], 'disp': ev['disp'], 'prev_disp': ev['prev_disp'], 'date': ev['date']}
            for ev in sorted(ent['events'], key=lambda x: (x['date'], x['label']), reverse=True)]


@app.route('/hitter/<key>/personal-bests')
@login_required
def hitter_prs(key):
    h = hitting.hitter_profile(key)
    if not h or h.get('opp_slug') or (h['demo'] and not is_admin()):
        abort(404)
    if not is_admin() and (h['program'] != my_program() or not plans.allowed(h['program'], 'hitting')):
        abort(404)
    g.theme_program = h['program']
    bio = h['bio']
    nm = h['name'].split()
    ent = prs.for_hitter(key)
    return render_template('player_prs.html', name=h['name'], ent=ent, history=_pr_history(ent), back_url=url_for('beta_hitter', key=key),
                           photo=hphoto(bio), badge=sbadge(bio.get('program'), bio.get('school')), initials=((nm[0][:1] + nm[-1][:1]).upper() if nm else ''),
                           is_coach=bool(session.get('coach')) and not is_player())


@app.route('/report/<slug>/outing/<date>')
def view_outing(slug, date):
    if not session.get('coach'):
        return redirect(url_for('login', next=request.path))
    bio = store.get_player(slug)
    html = overview.outing_report_html(slug, date, bio) if bio and can_view(slug) else None
    if not html:
        abort(404)
    if request.args.get('download'):
        if not plans.allowed(bio.get('program'), 'download'):
            return _upgrade('download')
        _track('download', slug=slug)
        fname = re.sub(r'[^A-Za-z0-9]+', '_', bio['name']).strip('_') + f'_{date}_outing_report.html'
        return Response(html, mimetype='text/html', headers={'Content-Disposition': f'attachment; filename="{fname}"'})
    _bar = ('<style>.ss-back{position:fixed;top:10px;left:10px;z-index:100;background:#fff;color:#22303a;font:700 13px Arial,sans-serif;'
            'text-decoration:none;border:1px solid #cfd6d9;border-radius:999px;padding:7px 14px;box-shadow:0 2px 8px rgba(26,31,36,.18);}'
            '@media print{.ss-back{display:none}}</style><a class="ss-back" href="' + url_for('player_overview', slug=slug) + '">&larr; Back to '
            + re.sub(r'<[^>]*>', '', (bio.get('name') or 'profile')).replace('&', '&amp;').replace('<', '') + '</a>')
    _k = re.search(r'<body[^>]*>', html)
    html = html[:_k.end()] + _bar + html[_k.end():] if _k else _bar + html
    if request.args.get('tour') == 'report':
        _t = render_template('_tour.html', tour_stage='report', tour_next=url_for('dashboard'), coach_key=session.get('coach') or '')
        k = html.rfind('</body>')
        html = html[:k] + _t + html[k:] if k > -1 else html + _t
    return html


@app.route('/beta/hitters')
@admin_required
def beta_hitters():
    rows = hitting.list_hitters()
    return render_template('beta_hitters.html', real=[r for r in rows if not r['demo']], demo=[r for r in rows if r['demo']])


@app.route('/beta/hitter/<key>')
@login_required
def beta_hitter_old(key):
    return redirect(url_for('beta_hitter', key=key))


# ----------------------------------------------------------------- scouting (premium)
def _scouting_ok(program):
    _team_ok(program)
    if not plans.allowed(program, 'scouting'):
        return _upgrade('scouting')
    return None


def _game_decorate(m, program):
    """Adds display names and arsenal graphics to a built game model."""
    import gamereport as gr
    flip = gr._flip
    for p in m['pas']:
        p['display'] = flip(p['batter'])
        p['pitcher_display'] = flip(p['pitcher'])
    for side in ('us', 'opp'):
        for s in m['teams'][side]['slots']:
            s['display'] = flip(s['name'])
            s['sub_for_display'] = flip(s['sub_for']) if s.get('sub_for') else ''
    return m


@app.route('/team/<program>/games')
@login_required
def team_games(program):
    _team_ok(program)
    if not plans.allowed(program, 'hitting'):
        return _upgrade('hitting')
    import gamereport as gr
    import datetime as _dt
    g.theme_program = program
    out = []
    for gid, gm in gr.collect(program).items():
        m = gr.build(gm['rows'])
        d = _dt.date.fromisoformat(gm['date'])
        out.append({'gid': gid, 'opp': gm['opp'], 'date': gm['date'], 'date_pretty': d.strftime('%a %b %-d, %Y'), 'n': gm['n'],
                    'us': m['score']['us'], 'them': m['score']['opp'], 'partial': not (m['pitchers']['us'] and m['pitchers']['opp']),
                    'logo': _opp_logo_url(program, store.slugify(gm['opp']) or 'unlabeled', gm['opp'])})
    out.sort(key=lambda x: x['date'], reverse=True)
    return render_template('games.html', program=program, team_label=store.program_label(program), games=out)


@app.route('/team/<program>/catchers')
@login_required
def team_catchers(program):
    _team_ok(program)
    import catcher
    g.theme_program = program
    B = catcher.build(program)
    cs = sorted(B['catchers'].values(), key=lambda c: -c['n'])
    return render_template('catchers.html', program=program, team_label=store.program_label(program), catchers=cs, team_call=B['team_call'])


@app.route('/team/<program>/catchers/<key>')
@login_required
def team_catcher(program, key):
    _team_ok(program)
    import catcher
    g.theme_program = program
    B = catcher.build(program)
    c = B['catchers'].get(key)
    if not c:
        abort(404)
    return render_template('catcher_profile.html', program=program, team_label=store.program_label(program), c=c, team_call=B['team_call'],
                           zone_svg=catcher.zone_svg(c['recv']['points']), res_ids=catcher.RESULT_IDS)


@app.route('/team/<program>/game/<gid>/notes', methods=['POST'])
@login_required
def team_game_notes(program, gid):
    _team_ok(program)
    side = request.form.get('side', '')
    if side not in ('us', 'opp'):
        abort(400)
    gamenotes.save(program, f'{gid}--{side}', request.form.get('text', ''), (current_coach() or {}).get('display_name') or session.get('coach') or '')
    if request.headers.get('X-Requested-With') == 'fetch':
        return ('', 204)
    return redirect(url_for('team_game_scorebook', program=program, gid=gid) + f'#notes-{side}')



@app.route('/team/<program>/game/<gid>/analysis')
@login_required
def team_game(program, gid):
    _team_ok(program)
    if not plans.allowed(program, 'hitting'):
        return _upgrade('hitting')
    import gamereport as gr
    import datetime as _dt
    gm = gr.collect(program).get(gid)
    if not gm:
        abort(404)
    g.theme_program = program
    m = _game_decorate(gr.build(gm['rows']), program)
    for side in ('us', 'opp'):
        for p in m['pitchers'][side]:
            p['ars'], p['prev_n'] = None, 0
            if p['np'] >= 8:
                ars, pn = gr.arsenal(p, gm['date'], program, 'us' if side == 'us' else 'opp')
                p['ars'], p['prev_n'] = gr.arsenal_svg(ars), pn
    d = _dt.date.fromisoformat(gm['date'])
    tl = store.program_label(program)
    complete = bool(m['pitchers']['us'] and m['pitchers']['opp']) and all(v is not None for v in m['linescore']['us'] + m['linescore']['opp'])
    return render_template('game_report.html', m=m, program=program, team_label=tl, opp=gm['opp'], date_pretty=d.strftime('%A, %B %-d, %Y'),
                           n_pitches=gm['n'], complete=complete, gid=gid, abbr=gr.ABBR, logo=_opp_logo_url(program, store.slugify(gm['opp']) or 'unlabeled', gm['opp']),
                           order=[('us', tl), ('opp', gm['opp'])], maxpa={s: max([x['pa_n'] for x in m['teams'][s]['slots']] or [1]) for s in ('us', 'opp')},
                           back_url=url_for('team_games', program=program))



@app.route('/team/<program>/game/<gid>')
@login_required
def team_game_scorebook(program, gid):
    _team_ok(program)
    if not plans.allowed(program, 'hitting'):
        return _upgrade('hitting')
    import gamereport as gr
    import datetime as _dt
    gm = gr.collect(program).get(gid)
    if not gm:
        abort(404)
    g.theme_program = program
    m = _game_decorate(gr.build(gm['rows']), program)
    tl = store.program_label(program)
    sheets = []
    hits = {s: sum(1 for p in m['teams'][s]['pas'] if p['result'] in gr.HITS) for s in ('us', 'opp')}
    errs = {s: sum(1 for p in m['teams']['opp' if s == 'us' else 'us']['pas'] if p['result'] == 'Error') for s in ('us', 'opp')}
    names = {'us': tl, 'opp': gm['opp']}
    for side, nm, other in (('us', tl, gm['opp']), ('opp', gm['opp'], tl)):
        sb = gr.scorebook(m, side)
        pas = m['teams'][side]['pas']
        newp, prev = {}, None
        for p in pas:
            if prev is not None and p['pitcher'] != prev:
                newp[p['seq']] = p['pitcher']
            prev = p['pitcher']
        phs = {e['pas'][0]['seq'] for r in sb['rows'] for e in r['ents'][1:] if e['pas']}
        for r in sb['rows']:
            r['cells'] = [(gr.cell2(p, newp[p['seq']] if p['seq'] in newp else '', p['result'] is not None and p['outs'] + p['outs_made'] >= 3, p['seq'] in phs) if p else '') for p in r['cells']]
            for ent in r['ents']:
                sides = {p['side'] for p in ent['pas'] if p['side']}
                ent['hand'] = 'S' if len(sides) > 1 else (next(iter(sides)) if sides else '')
        staff, letters = gr.staff_table(m, side)
        home = m['us_home'] if side == 'us' else not m['us_home']
        sheets.append({'side': side, 'team': nm, 'vs': other, 'half': 'HOME' if home else 'AWAY', 'sb': sb, 'staff': staff, 'note': gamenotes.get(program, f'{gid}--{side}'), 'note_key': f'{gid}--{side}', 'letters': letters,
                       'runs': m['score'][side],
                       'ab': sum(r['ab'] for r in sb['rows']), 'h': sum(r['h'] for r in sb['rows']), 'rbi': sum(r['rbi'] for r in sb['rows']),
                       'bb': sum(r['bb'] for r in sb['rows']), 'k': sum(r['k'] for r in sb['rows'])})
    m['hits'], m['errs'] = hits, errs
    d = _dt.date.fromisoformat(gm['date'])
    return render_template('game_scorebook.html', m=m, sheets=sheets, gid=gid, program=program, team_label=tl, opp=gm['opp'], date_pretty=d.strftime('%A, %B %-d, %Y'),
                           back_url=url_for('team_games', program=program), analysis_url=url_for('team_game', program=program, gid=gid), order=[('us', tl), ('opp', gm['opp'])])



@app.route('/team/<program>/scouting')
@login_required
def team_scouting(program):
    blocked = _scouting_ok(program)
    if blocked:
        return blocked
    opps = sorted(scouting.opponents(program).values(), key=lambda s: (s['dates'][-1] if s['dates'] else ''), reverse=True)
    for o in opps:
        o['logo'] = _opp_logo_url(program, o['slug'], o['label'])
        o['initials'] = ''.join(w[0] for w in o['label'].split()[:3]).upper()
    return render_template('scouting.html', program=program, team_label=store.program_label(program), opps=opps, opp=None)


def _scout_opp(program, opp):
    """The opponent dict for the scouting pages (None -> 404), with logo and note flags filled in."""
    o = scouting.opponents(program).get(opp)
    if not o:
        abort(404)
    o['logo'] = _opp_logo_url(program, o['slug'], o['label'])
    o['custom'] = os.path.exists(_opp_logo_path(program, o['slug']))
    _nt = scoutnotes.all_for(program)
    for x in o['hitters']:
        x['noted'] = bool((_nt.get(x['key']) or {}).get('t'))
    for x in o['pitchers']:
        x['noted'] = bool((_nt.get('p--' + x['slug']) or {}).get('t'))
    return o


@app.route('/team/<program>/scouting/<opp>')
@login_required
def team_scouting_opp(program, opp):
    """Scouting Team Dashboard for one opponent: their pitchers and hitters side by side, like a team's own dashboard."""
    blocked = _scouting_ok(program)
    if blocked:
        return blocked
    o = _scout_opp(program, opp)
    D = scouting.team_data(program, opp)
    cfg = D['cfg']
    halves = []
    for side, ids in (('pitching', cfg['pitching_stats']), ('hitting', cfg['hitting_stats'])):
        d = D[side]
        halves.append({'side': side, 'D': d, 'tiles': [d['tiles'][i] for i in ids if i in d['tiles']]})
    sessions = sorted(set(D['pitching']['sessions']) | set(D['hitting']['sessions']))
    return render_template('scout_team.html', program=program, team_label=store.program_label(program), opp=o, halves=halves,
                           last_session=sessions[-1] if sessions else None,
                           defense=scouting.defense_data(program, opp) if is_admin() else [])   # Defensive Positioning is admin-only while in beta


@app.route('/team/<program>/scouting/<opp>/pitchers')
@login_required
def team_scouting_pitchers(program, opp):
    blocked = _scouting_ok(program)
    if blocked:
        return blocked
    return render_template('scouting.html', program=program, team_label=store.program_label(program), opps=[], opp=_scout_opp(program, opp), view='pitchers')


@app.route('/team/<program>/scouting/<opp>/hitters')
@login_required
def team_scouting_hitters(program, opp):
    blocked = _scouting_ok(program)
    if blocked:
        return blocked
    return render_template('scouting.html', program=program, team_label=store.program_label(program), opps=[], opp=_scout_opp(program, opp), view='hitters')


@app.route('/team/<program>/scouting/<opp>/print')
@login_required
def team_scouting_print(program, opp):
    blocked = _scouting_ok(program)
    if blocked:
        return blocked
    o = scouting.opponents(program).get(opp)
    if not o:
        abort(404)
    import stats as stats_mod
    g.theme_program = program
    notes = scoutnotes.all_for(program)
    hit = []
    raw_all = hitting.collect_scouting(program)
    for x in o['hitters']:
        raw = raw_all.get(x['key'])
        if not raw:
            continue
        ps = raw['pitches']
        for p in ps:
            p['label'] = stats_mod._pt_label(p['pitch_type']) if p.get('pitch_type') else 'Unknown'
        bats = {p['side'] for p in ps if p.get('side')}
        bt = next(iter(bats)) if len(bats) == 1 else None
        rep = scoutplan.hitter_report(ps, bats=bt if bt in ('L', 'R') else None)
        hit.append({'name': x['name'], 'bats': bt, 'r': rep, 'note': (notes.get(x['key']) or {}).get('t')})
    pit = []
    for x in o['pitchers']:
        data = outings_mod.load(x['slug'], real_only=True)
        rows = [r for oo in data.get('outings', []) for r in oo['rows'] if (store.slugify(r.get('Opponent') or '') or 'unlabeled') == opp]
        if not rows:
            continue
        for r in rows:
            r['Pitcher'] = x['name']
        rep = scoutplan.pitcher_report(scoutplan.prep_pitcher(rows))
        pit.append({'name': x['name'], 'throws': x['throws'], 'r': rep, 'n': x['n'], 'note': (notes.get('p--' + x['slug']) or {}).get('t')})
    return render_template('scout_book.html', program=program, team_label=store.program_label(program), opp=o,
                           logo=_opp_logo_url(program, o['slug'], o['label']), hit=hit, pit=pit,
                           back_url=url_for('team_scouting_opp', program=program, opp=opp))



def _opp_logo_path(program, opp):
    return os.path.join(store.DATA_DIR, 'logos', 'opp', f'{program}--{opp}.png')


def _opp_own_logo(program, opp_slug):
    """Path of the logo to use for an opponent: the coach's upload for this opponent, else the logo that team uses on its own
    dashboard when it is a team in the app (their uploaded or built-in logo), else None (the school library is the fallback)."""
    p = _opp_logo_path(program, opp_slug)
    if os.path.exists(p):
        return p
    src = theme.watermark_source(opp_slug)
    return src[1] if src and src[0] in ('custom', 'builtin') else None


def _opp_logo_url(program, opp_slug, label):
    """URL of the opponent's logo (a coach's upload, that team's own logo, else the school library), or None."""
    p = _opp_own_logo(program, opp_slug)
    if p:
        return url_for('scouting_logo', program=program, opp=opp_slug, v=int(os.path.getmtime(p)))
    if pipeline.school_badge_file(label, None):
        return url_for('scouting_logo', program=program, opp=opp_slug, label=label)
    return None


@app.route('/team/<program>/scouting/<opp>/logo')
@login_required
def scouting_logo(program, opp):
    blocked = _scouting_ok(program)
    if blocked:
        return blocked
    p = _opp_own_logo(program, opp)
    if p:
        resp = send_file(p, mimetype='image/png')
        resp.headers['Cache-Control'] = 'private, max-age=3600'
        return resp
    o = scouting.opponents(program).get(opp)
    b = pipeline.school_badge_file((o or {}).get('label') or request.args.get('label', ''), None)
    if not b:
        abort(404)
    return school_mark(b[0]) if request.args.get('mark') else school_logo(b[0])


@app.route('/team/<program>/scouting/<opp>/logo', methods=['POST'])
@login_required
def scouting_logo_save(program, opp):
    blocked = _scouting_ok(program)
    if blocked:
        return blocked
    back = redirect(url_for('team_scouting_opp', program=program, opp=opp))
    p = _opp_logo_path(program, opp)
    if request.form.get('remove'):
        if os.path.exists(p):
            os.remove(p)
            github_sync.delete_file(f'data/logos/opp/{program}--{opp}.png')
        return back
    f = request.files.get('logo')
    raw = f.read(3 * 1024 * 1024 + 1) if f and f.filename else b''
    if not raw or len(raw) > 3 * 1024 * 1024:
        return back
    try:
        data = _clean_logo(raw)
    except Exception:
        return back
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as out:
        out.write(data)
    github_sync.put_file(f'data/logos/opp/{program}--{opp}.png', data)
    return back


@app.route('/scouting/notes', methods=['POST'])
@login_required
def scout_notes_save():
    prog = request.form.get('program', '')
    blocked = _scouting_ok(prog)
    if blocked:
        return blocked
    key = request.form.get('key', '')
    ok = key.startswith(f'scout--{prog}--') or (key.startswith('p--') and outings_mod.load(key[3:], real_only=True).get('program') == prog)
    if not ok:
        abort(400)
    scoutnotes.save(prog, key, request.form.get('text', ''), (current_coach() or {}).get('display_name') or session.get('coach') or '')
    back = request.form.get('back', '')
    return redirect(back if back.startswith('/') and not back.startswith('//') else url_for('team_scouting', program=prog))


def _initials(name):
    w = [x for x in re.split(r'\s+', name or '') if x]
    return ((w[0][:1] + w[-1][:1]) if len(w) > 1 else (w[0][:2] if w else '')).upper()


@app.route('/scouting/pitcher/<slug>')
@login_required
def scouting_pitcher(slug):
    if not slug.startswith(cleanup.OPP_PREFIX):
        abort(404)
    data = outings_mod.load(slug, real_only=True)
    prog = data.get('program')
    if not prog or not data.get('outings'):
        abort(404)
    blocked = _scouting_ok(prog)
    if blocked:
        return blocked
    want = request.args.get('opp')
    rows = [r for o in data['outings'] for r in o['rows'] if not want or (store.slugify(r.get('Opponent') or '') or 'unlabeled') == want]
    if not rows:
        abort(404)
    nm = scouting._flip(rows[0].get('Pitcher')) if rows else slug
    opp = next((r.get('Opponent') for r in rows if r.get('Opponent')), 'Unlabeled opponent')
    opp_slug = store.slugify(opp) or 'unlabeled'
    for r in rows:
        r['Pitcher'] = nm
    meta, tm = e_mod.pitcher_trackman_summary(rows, nm)
    for t_ in tm:
        t_['color'] = e_mod.MINI_PITCH_COLORS.get(t_['type'], '#555')
    ps = scoutplan.prep_pitcher(rows)
    rep = scoutplan.pitcher_report(ps)
    colors = {t_['type']: t_['color'] for t_ in tm}
    fb = next((t_ for t_ in tm if any(k in t_['type'].lower() for k in ('seam', 'sinker'))), None)
    css = re.sub(r'@font-face\s*\{[^}]*\}', '', pipeline.CSS)
    g.theme_program = prog
    return render_template('scout_pitcher.html', name=nm, opp=opp, r=rep, css=css, initials=_initials(nm), logo=_opp_logo_url(prog, opp_slug, opp),
                           throws=(meta.get('throws') or '')[:1].upper(), arsenal=tm, fb_velo=(fb or {}).get('velo'),
                           top_velo=max([t_['top_velo'] for t_ in tm if t_.get('top_velo')] or [0]) or None,
                           dates=sorted({(r.get('Date') or '')[:10] for r in rows if r.get('Date')}),
                           location_html=sc_mod.location_heatmap_html(tm, width=340, uid='loc'),
                           effect=pitchfx.effectiveness(rows, [t_['type'] for t_ in tm], colors),
                           program=prog, note_key='p--' + slug, note=scoutnotes.get(prog, 'p--' + slug), back_url=url_for('team_scouting_pitchers', program=prog, opp=opp_slug))


def _scout_hitter_page(key, h):
    prog = h['program']
    raw = hitting.collect_scouting(prog).get(key)
    if not raw:
        abort(404)
    ps = raw['pitches']
    import stats as stats_mod
    for p in ps:
        p['label'] = stats_mod._pt_label(p['pitch_type']) if p.get('pitch_type') else 'Unknown'
    bats = h['bio'].get('bats')
    rep = scoutplan.hitter_report(ps, bats=bats if bats in ('L', 'R') else None)
    opp = h['opponent']
    return render_template('scout_hitter.html', h=h, r=rep, zone_svg=scoutplan.zone_map_svg(rep['cells'], bats=bats if bats in ('L', 'R') else None),
                           initials=_initials(h['name']), logo=_opp_logo_url(prog, h['opp_slug'], opp), program=prog, note_key=key,
                           note=scoutnotes.get(prog, key), back_url=url_for('team_scouting_hitters', program=prog, opp=h['opp_slug']))


@app.route('/hitter/<key>')
@login_required
def beta_hitter(key):
    _dr0 = _date_range([])
    h = hitting.hitter_profile(key, side=request.args.get('side', 'all'), vs=request.args.get('vs', 'all'), frm=_dr0['frm'], to=_dr0['to'])
    if not h or h['demo'] and not (is_admin() or is_demo_viewer()):
        abort(404)
    if not is_admin() and (h['program'] != my_program() or not plans.allowed(h['program'], 'hitting')):   # a coach sees only his own program's hitters
        abort(404)
    if h.get('opp_slug') and not plans.allowed(h['program'], 'scouting'):
        return _upgrade('scouting')
    g.theme_program = h['program']
    if h.get('opp_slug'):
        return _scout_hitter_page(key, h)
    return _hitter_render(key, h)


def _hitter_render(key, h, public=False, token=None):
    g.theme_program = h['program']
    css = re.sub(r'@font-face\s*\{[^}]*\}', '', pipeline.CSS)
    _ps = h['bio']['photo_slug']
    _dr = _date_range(h['dates'], {'vs': h['vs'] if h['vs'] != 'all' else '', 'side': request.args.get('side') if request.args.get('side') in ('L', 'R') else ''}, empty=h.get('range_empty', False))
    def hurl(vs=None):
        if public:
            return url_for('public_share', token=token, vs=vs, frm=_dr['frm'], to=_dr['to'])
        return url_for('beta_hitter', key=key, vs=vs, frm=_dr['frm'], to=_dr['to'])
    return render_template('beta_hitter.html', dr=_dr, public=public, hurl=hurl, photo_src=(url_for('public_share_photo', token=token) if public and _ps else None),
                           share=(None if public else _share_ctx('hitter', key, h['program'])), share_team=store.program_label(h['program']) if public else '',
                           pr_ent=(None if public else prs.for_hitter(key)), h=h, css=css, can_edit=((not public) and not h['demo'] and not h.get('opp_slug') and not is_player() and (is_admin() or h['program'] == my_program())),
                           photo_v=int(os.path.getmtime(headshots.path(_ps))) if _ps else 0,
                           **({'hitters_url': url_for('team_scouting_opp', program=h['program'], opp=h['opp_slug']), 'scouting': True} if h.get('opp_slug') else {}))



def _roster_program():
    """A program coach works on his own roster; an admin picks the program (form field or ?program=)."""
    if is_admin():
        newp = (request.values.get('new_program') or '').strip()
        if newp:
            return store.program_slug(newp)
        return request.values.get('program') or 'long_beach_state'
    return my_program()


def _roster_matches(prog, players):
    """For each parsed roster row: is he already on the dashboard, a batter in the data, or new."""
    existing = [(b.get('name', ''), (s, b)) for s, b in store.list_players().items() if b.get('program', 'shepherds') == prog]
    batters = hitting.batter_names()
    out = []
    for p in players:
        st, link, note = 'new', None, None
        m = roster_mod.match_name(p['name'], existing)
        if m:
            st, link = 'player', m[0][0]
            note = m[2] if m[1] == 'likely' else None
        else:
            hb = roster_mod.match_name(p['name'], batters)
            if hb:
                st, link = 'hitter', hb[0]
                note = hb[2] if hb[1] == 'likely' else None
        warn = []
        if not (p.get('bats') and p.get('throws')):
            warn.append('no bats/throws')
        if not p.get('position'):
            warn.append('no position')
        out.append({'p': p, 'status': st, 'link': link, 'note': note, 'warn': warn})
    return out


@app.route('/roster', methods=['GET', 'POST'])
@login_required
@upload_required
def roster_page():
    prog = _roster_program()
    if not prog:
        abort(403)
    if not plans.allowed(prog, 'roster_upload'):
        return _upgrade('roster_upload')
    ctx = {'programs': ([('shepherds', store.program_label('shepherds'))] + store.list_programs()) if is_admin() else None, 'prog': prog, 'prog_label': store.program_label(prog),
           'saved': request.args.get('saved'), 'preview': None, 'error': None, 'token': None, 'source': None}
    if request.method == 'POST':
        f = request.files.get('roster_file')
        if not f or not f.filename:
            ctx['error'] = 'Choose a roster file (PDF, Excel or CSV).'
        else:
            try:
                players = roster_mod.parse_file(f.filename, f.read())
                import uuid
                token = uuid.uuid4().hex
                with open(os.path.join(UPLOAD_DIR, f'roster_{token}.json'), 'w', encoding='utf-8') as fh:
                    json.dump({'program': prog, 'source': f.filename, 'players': players}, fh)
                ctx.update(preview=_roster_matches(prog, players), token=token, source=f.filename)
            except Exception as exc:
                ctx['error'] = f"Couldn't read that roster: {exc}"
    cur = roster_mod.load(prog)
    ctx['current'] = None
    if cur:
        ctx['current'] = {'n': len(cur['players']), 'source': cur.get('source'), 'updated': cur.get('updated'),
                          'rows': _roster_matches(prog, cur['players'])}
    return render_template('roster.html', **ctx)


@app.route('/roster/save', methods=['POST'])
@login_required
@upload_required
def roster_save():
    prog = _roster_program()
    if not prog or not plans.allowed(prog, 'roster_upload'):
        abort(403)
    token = re.sub(r'[^a-f0-9]', '', request.form.get('token', ''))
    path = os.path.join(UPLOAD_DIR, f'roster_{token}.json')
    if not token or not os.path.exists(path):
        abort(400)
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    keep = [p for i, p in enumerate(data['players']) if request.form.get(f'inc_{i}')]
    season = request.form.get('season', '').strip() or None
    roster_mod.save(prog, keep, source=data.get('source'), season=season)
    n = roster_mod.apply_to_players(prog, keep, store.list_players())
    if n:
        store.sync_to_github()
    try:
        os.remove(path)
    except OSError:
        pass
    _track('roster', players=len(keep))
    return redirect(url_for('roster_page', program=prog if is_admin() else None, saved=f'{len(keep)}:{n}'))


@app.route('/glossary')
@login_required
def glossary_page():
    return render_template('glossary.html', sections=glossary.sections(is_admin()))


@app.route('/school-logo/<fname>')
def school_logo(fname):
    path = os.path.join(pipeline.APP_DIR, 'assets', 'schools', os.path.basename(fname))
    if not os.path.exists(path):
        abort(404)
    resp = send_file(path)
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp


_MARKS = {}


@app.route('/watermark/<program>')
@login_required
def watermark(program):
    """The header logo for a team: the coach's own upload, else the built-in one, else the school logo with its white backing removed."""
    _team_ok(program)
    src = theme.watermark_source(program)
    if not src:
        abort(404)
    kind, ref = src
    if kind == 'school':
        return school_mark(ref)
    resp = send_file(ref, mimetype='image/png')
    resp.headers['Cache-Control'] = 'private, max-age=3600'
    return resp


@app.route('/school-mark/<fname>')
def school_mark(fname):
    """The school logo with any solid white/near-white backing keyed out, so it can sit on a coloured header at low opacity."""
    fname = os.path.basename(fname)
    if fname not in _MARKS:
        path = os.path.join(pipeline.APP_DIR, 'assets', 'schools', fname)
        if not os.path.exists(path):
            abort(404)
        import io
        from PIL import Image, ImageDraw
        im = Image.open(path).convert('RGBA')
        w, h = im.size
        px = im.load()
        for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            r, g, b, al = px[seed]
            if al > 200 and min(r, g, b) > 235:          # opaque white corner = a backing, not part of the mark
                ImageDraw.floodfill(im, seed, (255, 255, 255, 0), thresh=40)
        buf = io.BytesIO()
        im.save(buf, 'PNG')
        _MARKS[fname] = buf.getvalue()
    resp = Response(_MARKS[fname], mimetype='image/png')
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp


@app.route('/headshot/<slug>')
def headshot(slug):
    if not headshots.exists(slug) or not can_view(slug):
        abort(404)
    resp = send_file(headshots.path(slug), mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'private, max-age=3600' if (store.get_player(slug) or {}).get('program', 'shepherds') not in store.PUBLIC_PROGRAMS else 'public, max-age=86400'
    return resp


EDIT_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Edit Profile</title>
<style>body{font-family:Barlow,Arial,sans-serif;background:#f7f6f2;color:#22303a;max-width:560px;margin:0 auto;padding:24px 16px 60px;} h1{font-family:Oswald,Arial,sans-serif;margin:6px 0 2px;}
label{display:block;font-weight:600;font-size:13px;margin:14px 0 4px;} input[type=text],input[type=number],select{width:100%;padding:9px 10px;border:1px solid #dcdfdc;border-radius:7px;box-sizing:border-box;font:inherit;}
.row{display:flex;gap:10px;} .row>div{flex:1;} .btns{margin-top:22px;display:flex;gap:10px;align-items:center;} button{padding:11px 24px;border:none;border-radius:999px;background:#5c97a8;color:#fff;font-weight:600;cursor:pointer;font-size:14px;}
a{color:#6b7680;font-size:13px;} .ph{width:96px;height:96px;border-radius:50%;object-fit:cover;background:#cfd8dc;display:block;} .msg{background:#f6dede;color:#9c3a3a;padding:10px 14px;border-radius:8px;margin:12px 0;}</style></head><body>
<a href="{{ url_for('player_overview', slug=slug) }}">&larr; Back to {{ p.name }}</a><h1>Edit Profile</h1>
{% if err %}<div class="msg">{{ err }}</div>{% endif %}
<form method="post" enctype="multipart/form-data">
<label>Headshot</label>{% if has_photo %}<img class="ph" src="{{ url_for('headshot', slug=slug) }}?v={{ v }}" alt="">{% endif %}
<input type="file" name="photo" accept="image/*">{% if has_photo %}<label style="font-weight:400;"><input type="checkbox" name="remove_photo" value="1"> Remove current headshot</label>{% endif %}
<label>Full name</label><input type="text" name="name" value="{{ p.name }}" required>
<div class="row"><div><label>School</label><input type="text" name="school" value="{{ p.school or '' }}"></div><div><label>Class of</label><input type="number" name="grad_year" value="{{ p.grad_year or '' }}"></div></div>
<div class="row"><div><label>Position</label><select name="position">{% for o in ['RHP','LHP','INF','OF','C','TWP'] %}<option value="{{ o }}" {{ 'selected' if pos == o }}>{{ o }}</option>{% endfor %}</select></div></div>
<div class="row"><div><label>Height (ft)</label><input type="number" name="ft" value="{{ ((p.height_in or 0)//12)|int or '' }}"></div><div><label>(in)</label><input type="number" name="inch" value="{{ ((p.height_in or 0)%12)|int if p.height_in else '' }}"></div><div><label>Weight (lb)</label><input type="number" name="wt" value="{{ p.weight_lbs|int if p.weight_lbs else '' }}"></div></div>
<div class="btns"><button type="submit">Save changes</button><a href="{{ url_for('player_overview', slug=slug) }}">Cancel</a></div></form></body></html>"""


@app.template_global()
def hphoto(bio):
    """URL of a hitter's headshot (his own, or the shared one of his pitcher profile), or None."""
    if not bio or not bio.get('photo_slug'):
        return None
    if bio['photo_kind'] == 'player':
        return url_for('headshot', slug=bio['photo_slug'])
    return url_for('hitter_photo', key=bio['photo_slug'][2:])


@app.template_global()
def sbadge(program, label=None):
    b = pipeline.school_badge_file(label or store.program_label(program), program)
    return {'file': b[0], 'bg': b[1]} if b else None


@app.route('/hitter-photo/<key>')
@login_required
def hitter_photo(key):
    """Headshot of a hitter who has no pitcher profile (two-way players share the pitcher headshot instead)."""
    slug = f'h_{key}'
    prog = (hitting._load_json(hitting.HITTER_BIOS_PATH).get(key) or {}).get('program')
    if not headshots.exists(slug) or not prog or not (is_admin() or prog == my_program()):
        abort(404)
    resp = send_file(headshots.path(slug), mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'private, max-age=3600'
    return resp


def _hitter_for_edit(key):
    h = hitting._collect(True).get(key)
    if not h or h['demo'] or not (is_admin() or h['program'] == my_program()):
        abort(404)
    return h


HITTER_EDIT_PAGE = EDIT_PAGE.replace("background:#5c97a8;color:#fff", "background:var(--accent,#5c97a8);color:var(--on-accent,#fff)").replace("{{ url_for('player_overview', slug=slug) }}", "{{ url_for('beta_hitter', key=key) }}").replace(
    "<title>Edit Profile</title>", "<title>Edit Profile</title><style>{{ theme_css|safe }}</style>").replace(
    "src=\"{{ url_for('headshot', slug=slug) }}?v={{ v }}\"", "src=\"{{ photo_url }}?v={{ v }}\"").replace(
    "{% for o in ['RHP','LHP','INF','OF','C','TWP'] %}", "{% for o in ['INF','OF','C','DH','UTL','TWP'] %}").replace(
    "<label>Full name</label><input type=\"text\" name=\"name\" value=\"{{ p.name }}\" required>",
    "<label>Name</label><input type=\"text\" value=\"{{ p.name }}\" disabled>").replace(
    "<div class=\"row\"><div><label>School</label><input type=\"text\" name=\"school\" value=\"{{ p.school or '' }}\"></div>",
    "<div class=\"row\"><div><label>School</label><input type=\"text\" value=\"{{ p.school or '' }}\" disabled></div>").replace(
    "<div class=\"row\"><div><label>Position</label>",
    "<div class=\"row\"><div><label>Bats</label><select name=\"bats\">{% for o in ['R','L','S'] %}<option value=\"{{ o }}\" {{ 'selected' if p.bats == o }}>{{ o }}</option>{% endfor %}</select></div><div><label>Throws</label><select name=\"throws\">{% for o in ['R','L'] %}<option value=\"{{ o }}\" {{ 'selected' if p.throws == o }}>{{ o }}</option>{% endfor %}</select></div><div><label>Position</label>").replace(
    "<div class=\"btns\">", "<div class=\"row\"><div><label>Jersey #</label><input type=\"number\" name=\"number\" value=\"{{ p.number or '' }}\"></div></div>\n<div class=\"btns\">")


RETAG_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Retag Pitches</title>
<style>{{ theme_css|safe }}</style>
<style>body{font-family:Barlow,Arial,sans-serif;background:#f7f6f2;color:#22303a;max-width:760px;margin:0 auto;padding:24px 16px 80px;} h1{font-family:Oswald,Arial,sans-serif;margin:6px 0 2px;}
a{color:var(--accent-ink,#6b7680);font-size:13px;} p.s{color:#6b7680;font-size:13.5px;margin:4px 0 14px;line-height:1.45;}
.card{background:#fff;border-radius:14px;box-shadow:0 1px 3px rgba(26,31,36,.08),0 6px 18px rgba(26,31,36,.06);padding:14px 16px;margin:12px 0;}
.tabs a{display:inline-block;margin:0 6px 6px 0;padding:5px 12px;border-radius:999px;background:#eef1f0;color:#55626b;text-decoration:none;font-weight:600;} .tabs a.on{background:var(--accent,#5c97a8);color:var(--on-accent,#fff);}
table{width:100%;border-collapse:collapse;font-size:13.5px;} th{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:#76828a;text-align:left;padding:6px 6px;border-bottom:1px solid #e6e9e8;} td{padding:6px;border-bottom:1px solid #f0f2f1;}
td.n{font-variant-numeric:tabular-nums;} select{padding:6px 8px;border:1px solid #dcdfdc;border-radius:7px;font:inherit;background:#fff;} tr.ch td{background:#fbf3e0;} .was{font-size:11.5px;color:#8a6212;}
.bulk{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13.5px;} button{padding:10px 22px;border:none;border-radius:999px;background:var(--accent,#5c97a8);color:var(--on-accent,#fff);font-weight:700;cursor:pointer;font-size:14px;} button.g{background:#eef1f0;color:#22303a;padding:7px 14px;font-size:13px;}
.bar{position:sticky;bottom:0;background:linear-gradient(transparent,#f7f6f2 30%);padding:18px 0 4px;} .ok{background:#e4f2ea;color:#2a7a4b;padding:10px 14px;border-radius:10px;margin:10px 0;font-size:14px;}</style></head><body>
<a href="{{ url_for('player_overview', slug=slug) }}">&larr; Back to {{ p.name }}</a><h1>Retag Pitches</h1>
<p class="s">Fix a pitch Trackman tagged wrong. Every report, chart and stat for {{ p.name }} updates right away, and the original tag is kept so any change can be undone. A correction stays put even if the same CSV is uploaded again.</p>
{% if saved is not none %}<div class="ok">{{ saved }} pitch{{ '' if saved == 1 else 'es' }} updated.</div>{% endif %}
<div class="tabs">{% for o in outs %}<a href="{{ url_for('retag_pitches', slug=slug, date=o.id) }}" class="{{ 'on' if o.id == date }}">{{ o.label }}</a>{% endfor %}</div>
{% if rows %}<form method="post">
<div class="card bulk"><b>Change all</b><select id="bf">{% for l, v in types %}<option>{{ l }}</option>{% endfor %}</select><b>to</b><select id="bt">{% for l, v in types %}<option>{{ l }}</option>{% endfor %}</select><button type="button" class="g" id="ba">Apply to this outing</button></div>
<div class="card"><table><tr><th>#</th><th>Velo</th><th>Spin</th><th>IVB / HB</th><th>Pitch type</th></tr>
{% for r in rows %}<tr class="{{ 'ch' if r.was }}"><td class="n">{{ loop.index }}</td><td class="n">{{ r.velo }}</td><td class="n">{{ r.spin }}</td><td class="n">{{ r.mv }}</td>
<td><select name="t_{{ r.uid }}" data-orig="{{ r.cur }}">{% for l, v in types %}<option {{ 'selected' if l == r.cur }}>{{ l }}</option>{% endfor %}{% if r.cur not in type_labels %}<option selected>{{ r.cur }}</option>{% endif %}</select>{% if r.was %}<div class="was">was {{ r.was }}</div>{% endif %}</td></tr>{% endfor %}</table></div>
<div class="bar"><button type="submit">Save changes</button></div></form>
<script>document.getElementById('ba').onclick=function(){var f=document.getElementById('bf').value,t=document.getElementById('bt').value;document.querySelectorAll('td select').forEach(function(s){if(s.value===f)s.value=t;});};</script>
{% else %}<p class="s">No pitches for this outing.</p>{% endif %}</body></html>"""


@app.route('/player/<slug>/retag', defaults={'date': None}, methods=['GET', 'POST'])
@app.route('/player/<slug>/retag/<date>', methods=['GET', 'POST'])
@login_required
def retag_pitches(slug, date):
    """Coaches (their own players) and admins can correct pitch-type tags; stored on the outing rows (see outings.retag)."""
    if not can_manage(slug) or store.is_demo(slug):
        abort(403)
    p = store.get_player(slug)
    if not p:
        abort(404)
    outs = outings_mod.outings(slug)
    if not outs:
        abort(404)
    date = outings_mod.iso_date(date) if date else outs[0]['id']
    if request.method == 'POST':
        ch = {k[2:]: v for k, v in request.form.items() if k.startswith('t_')}
        n = outings_mod.retag(slug, date, ch, who=session.get('coach') or '')
        return redirect(url_for('retag_pitches', slug=slug, date=date, saved=n))
    o = next((x for x in outs if x['id'] == date), None)
    if not o:
        abort(404)
    def f1(v, d=1):
        try:
            return f"{float(v):.{d}f}"
        except Exception:
            return '–'
    rows = [{'uid': outings_mod._uid(r), 'cur': outings_mod.label_for(r.get('TaggedPitchType')),
             'was': outings_mod.label_for(r['OrigTaggedPitchType']) if r.get('OrigTaggedPitchType') else '',
             'velo': f1(r.get('RelSpeed')), 'spin': f1(r.get('SpinRate'), 0),
             'mv': f"{f1(r.get('InducedVertBreak'))} / {f1(r.get('HorzBreak'))}"} for r in o['rows']]
    saved = request.args.get('saved', type=int)
    outs = [{'id': x['id'], 'label': overview._long_date(x['id'])} for x in outs]
    return render_template_string(RETAG_PAGE, p=p, slug=slug, outs=outs, date=date, rows=rows, types=outings_mod.RETAG_TYPES,
                                  type_labels=[l for l, _ in outings_mod.RETAG_TYPES], saved=saved)


@app.route('/player/<slug>/retag/pmp', methods=['POST'])
@login_required
def retag_from_pmp(slug):
    """Retag one or many pitches picked on the Pitch Movement Profile. Body: {"label": "Slider", "pitches": [{"date": "2026-10-09", "uid": "..."}, ...]}."""
    if not can_manage(slug) or store.is_demo(slug) or is_player():
        abort(403)
    d = request.get_json(silent=True) or {}
    label = d.get('label')
    if label not in dict(outings_mod.RETAG_TYPES):
        return jsonify({'ok': False, 'error': 'Pick a pitch type.'}), 400
    by_date = {}
    for p in (d.get('pitches') or [])[:500]:
        if isinstance(p, dict) and p.get('uid') and p.get('date'):
            by_date.setdefault(outings_mod.iso_date(p['date']), {})[str(p['uid'])] = label
    n = 0
    for date, ch in by_date.items():
        n += outings_mod.retag(slug, date, ch, who=session.get('coach') or '')
    return jsonify({'ok': True, 'changed': n})


@app.route('/hitter/<key>/edit', methods=['GET', 'POST'])
@login_required
def hitter_edit(key):
    h = _hitter_for_edit(key)
    g.theme_program = h['program']
    _sides = {p['side'] for p in h['pitches'] if p['side']}
    bio = hitting._bio(key, h, hitting._players_index(), 'S' if len(_sides) > 1 else (next(iter(_sides)) if _sides else None))
    pitcher_slug = bio['pitcher_slug']
    photo_slug = pitcher_slug or f'h_{key}'
    if request.method == 'POST':
        f = request.form
        def num(x):
            try:
                return float(x) if x not in (None, '') else None
            except Exception:
                return None
        ft, inch, wt, no = num(f.get('ft')), num(f.get('inch')), num(f.get('wt')), num(f.get('number'))
        height = int(ft * 12 + (inch or 0)) if ft else None
        fields = {'program': h['program'], 'position': f.get('position') or None, 'bats': f.get('bats') or None, 'throws': f.get('throws') or None,
                  'height_in': height, 'weight_lbs': int(wt) if wt else None, 'grad_year': int(num(f.get('grad_year'))) if num(f.get('grad_year')) else None,
                  'number': int(no) if no else None}
        hitting.save_bio(key, {k: v for k, v in fields.items() if v is not None or k in ('height_in', 'weight_lbs', 'grad_year', 'number')})
        if f.get('remove_photo'):
            headshots.delete(photo_slug)
        up = request.files.get('photo')
        if up and up.filename:
            try:
                headshots.save(photo_slug, up)
            except Exception as exc:
                return f"Couldn't read that image: {exc}", 400
        return redirect(url_for('beta_hitter', key=key))
    has = headshots.exists(photo_slug)
    p = dict(bio, school=bio['school'])
    ph = url_for('headshot', slug=photo_slug) if pitcher_slug else url_for('hitter_photo', key=key)
    return render_template_string(HITTER_EDIT_PAGE, p=p, key=key, has_photo=has, pos=bio['position'], photo_url=ph, v=int(os.path.getmtime(headshots.path(photo_slug))) if has else 0, err=None)


@app.route('/player/<slug>/stats', methods=['POST'])
@login_required
def save_stats(slug):
    if not can_manage(slug):
        abort(403)
    _p = store.get_player(slug) or {}
    if not plans.allowed(_p.get('program'), 'custom_stats'):
        return _upgrade('custom_stats')
    _track('customize', slug=slug)
    ids = [i for i in (request.form.get('order') or '').split(',') if i][:40]
    if request.form.get('reset'):
        ids = []
    store.set_stat_ids(slug, ids)
    return redirect(url_for('player_overview', slug=slug) + '#stats')


@app.route('/player/<slug>/edit', methods=['GET', 'POST'])
@login_required
def edit_profile(slug):
    if not can_manage(slug) or store.is_demo(slug):
        abort(403)
    p = store.get_player(slug)
    if not p:
        abort(404)
    err = None
    if request.method == 'POST':
        f = request.form
        gy = f.get('grad_year', '').strip()
        ft, inch = _num_or_none(f.get('ft')), _num_or_none(f.get('inch'))
        new_slug, err = store.update_profile(
            slug, name=f.get('name', '').strip(), school=f.get('school', '').strip() or None,
            grad_year=int(gy) if gy.isdigit() else None, position=f.get('position') or None,
            height_in=(ft * 12 + (inch or 0)) if ft else None, weight_lbs=_num_or_none(f.get('wt')))
        if not err:
            if f.get('remove_photo'):
                headshots.delete(new_slug)
            ph = request.files.get('photo')
            if ph and ph.filename:
                try:
                    headshots.save(new_slug, ph)
                except Exception as exc:
                    err = f"Saved, but couldn't read that image: {exc}"
            if not err:
                return redirect(url_for('player_overview', slug=new_slug))
        p = store.get_player(slug) or p
    has = headshots.exists(slug)
    return render_template_string(EDIT_PAGE, p=p, slug=slug, err=err, pos=_player_pos(p), has_photo=has,
                                  v=int(os.path.getmtime(headshots.path(slug))) if has else 0)


COACHES_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Coach Logins</title>
<style>body{font-family:Barlow,Arial,sans-serif;background:#f7f6f2;color:#22303a;max-width:640px;margin:0 auto;padding:24px 16px 60px;} h1{font-family:Oswald,Arial,sans-serif;margin:6px 0 10px;}
.card{background:#fff;border:1px solid #dcdfdc;border-radius:10px;padding:12px 14px;margin:10px 0;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;} small{color:#6b7680;}
label{display:block;font-weight:600;font-size:13px;margin:12px 0 4px;} input,select{width:100%;padding:9px 10px;border:1px solid #dcdfdc;border-radius:7px;box-sizing:border-box;font:inherit;}
button{padding:10px 22px;border:none;border-radius:999px;background:#5c97a8;color:#fff;font-weight:600;cursor:pointer;margin-top:16px;} button.del{background:#fff;color:#9c3a3a;border:1px solid #dcdfdc;margin:0;padding:6px 14px;font-size:12.5px;} a{color:#6b7680;font-size:13px;}
.msg{background:#e3ecdf;color:#3f6b42;padding:10px 14px;border-radius:8px;margin:10px 0;} .err{background:#f6dede;color:#9c3a3a;}</style></head><body>
<a href="{{ url_for('dashboard') }}">&larr; Dashboard</a><h1>Coach Logins</h1>
{% if msg %}<div class="msg {{ 'err' if err }}">{{ msg }}</div>{% endif %}
{% for u, c in coaches.items() %}<div class="card"><div><b>{{ c.display_name }}</b> <small>({{ u }})</small><br><small>{{ 'Demo viewer -- view-only, sample data' if c.get('demo_view') else 'Admin -- full access' if c.get('role','admin') == 'admin' else ('Assistant coach -- ' ~ (c.get('program_label') or c.get('program')) if c.get('role') == 'assistant' else (c.get('program_label') or c.get('program')) ~ ' coach -- only sees and edits their own program') }}</small></div>
{% if u != me %}<form method="post" action="{{ url_for('admin_coach_delete', username=u) }}" onsubmit="return confirm('Remove this login?');" style="margin:0;"><button class="del">Remove</button></form>{% endif %}</div>{% endfor %}
<h2 style="font-family:Oswald,Arial,sans-serif;margin-top:28px;">Add a login <small>(or reset a password: reuse the username)</small></h2>
<form method="post"><label>Username</label><input name="username" required autocomplete="off"><label>Display name</label><input name="display_name" required>
<label>Password</label><input name="password" type="text" required autocomplete="off" minlength="8">
<label>Access</label><select name="role"><option value="program">Program coach (sees only their own program)</option><option value="demo">Demo viewer (view-only, sample data only; safe to share)</option><option value="admin">Admin (everything)</option></select>
<label>Program / school <small>(program coaches only -- coaches with the same name share players)</small></label><input name="program_label" list="progs" placeholder="e.g. Long Beach State"><datalist id="progs">{% for s, l in programs %}<option value="{{ l }}">{% endfor %}</datalist>
<button type="submit">Save login</button></form></body></html>"""


STATUS_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Save Status</title>
<style>body{font-family:Barlow,Arial,sans-serif;background:#f7f6f2;color:#22303a;max-width:680px;margin:0 auto;padding:24px 16px 60px;} h1{font-family:Oswald,Arial,sans-serif;} .card{background:#fff;border-radius:12px;padding:14px 16px;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,.08);}
.ok{color:#2f7a4a;font-weight:700;} .bad{color:#b03a3a;font-weight:700;} small{color:#6b7680;} button{padding:10px 20px;border:none;border-radius:999px;background:#5c97a8;color:#fff;font-weight:600;cursor:pointer;} a{color:#5c97a8;font-size:13px;} code{background:#eef1f1;padding:1px 5px;border-radius:4px;}</style></head><body>
<a href="{{ url_for('dashboard') }}">&larr; Dashboard</a><h1>Save Status</h1>
<div class="card">Automatic GitHub saving: {% if on %}<span class="ok">ON</span> <small>repo <code>{{ repo }}</code>, branch <code>{{ branch }}</code></small>{% else %}<span class="bad">OFF</span><br><small>The Render environment variables <code>SHEPSAVANT_GITHUB_TOKEN</code> and <code>SHEPSAVANT_GITHUB_REPO</code> are missing, so edits only last until the next deploy.</small>{% endif %}</div>
<form method="post" action="{{ url_for('admin_status_test') }}"><button>Test save now</button></form>
<p style="margin-top:18px;"><a href="{{ url_for('admin_old_reports') }}">Old Shepherds reports</a></p>
<div class="card"><b>Recent saves (since the last restart)</b>{% if not log %}<br><small>None yet. Edit a profile or upload a CSV, then reload this page.</small>{% endif %}
{% for l in log|reverse %}<div style="margin-top:8px;">{{ l.when }} &middot; <code>{{ l.what }}</code> &middot; {% if l.ok %}<span class="ok">saved</span>{% else %}<span class="bad">FAILED</span>{% endif %}<br><small>{{ l.detail }}</small></div>{% endfor %}</div>
<p><small>If a save shows FAILED, the change only exists on the running server and will be lost at the next deploy. Send me the message shown.</small></p></body></html>"""


@app.route('/admin/plans', methods=['GET', 'POST'])
@admin_required
def admin_plans():
    msg = None
    if request.method == 'POST':
        prog = request.form.get('program', '')
        err = plans.set_plan(prog, request.form.get('plan', ''), request.form.get('trial_ends', ''), request.form.get('note', ''))
        msg = err or f'Saved plan for {store.program_label(prog)}.'
    return render_template('admin_plans.html', rows=plans.summary(30), plans=plans.PLANS, enforcing=plans.enforcing(), msg=msg)


JOIN_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Create your login</title>
<style>body{font-family:Barlow,Arial,sans-serif;background:#f7f6f2;color:#22303a;margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center;}
form{background:#fff;padding:28px;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,.1);width:min(360px,92vw);} h1{font-family:Oswald,Arial,sans-serif;font-size:24px;margin:0 0 6px;} p{color:#6b7680;font-size:13.5px;margin:0 0 14px;}
input{width:100%;padding:10px;margin:6px 0;border:1px solid #dcdfdc;border-radius:7px;box-sizing:border-box;font:inherit;} button{width:100%;padding:11px;margin-top:10px;border:none;border-radius:999px;background:#5c97a8;color:#fff;font-weight:700;cursor:pointer;font-size:15px;}
.error{color:#b33;font-size:13px;margin-bottom:8px;} small{color:#8a949a;display:block;margin-top:12px;line-height:1.45;}</style></head><body>
<form method="post"><h1>Welcome, {{ name }}</h1><p>{{ team }} invited you to see your own data. Choose a username and password.</p>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
<input name="username" placeholder="Username (letters and numbers)" value="{{ username }}" autocomplete="off" required minlength="3">
<input name="password" type="password" placeholder="Password (8+ characters)" required minlength="8" autocomplete="new-password">
<input name="confirm" type="password" placeholder="Confirm password" required minlength="8" autocomplete="new-password">
<button type="submit">Create login</button>
<small>This login shows only your own profile and reports, until {{ until }}. Sign-ins and downloads are logged. Please do not share your login.</small></form></body></html>"""


@app.route('/join/<token>', methods=['GET', 'POST'])
def join(token):
    inv = store.get_invite(token)
    if not inv:
        return render_template_string(LOGIN_PAGE, error='This invite link is invalid or has expired. Ask your head coach for a new one.'), 404
    import datetime as _d
    until = _d.date.fromisoformat(inv['season_end']).strftime('%B %-d, %Y')
    error, username = None, ''
    if request.method == 'POST':
        username = re.sub(r'[^a-z0-9_.-]', '', request.form.get('username', '').strip().lower())
        pw = request.form.get('password', '')
        if len(username) < 3:
            error = 'Pick a username of at least 3 letters or numbers.'
        elif username in store.list_coaches():
            error = 'That username is taken. Try another.'
        elif len(pw) < 8:
            error = 'Use a password of at least 8 characters.'
        elif pw != request.form.get('confirm', ''):
            error = 'The passwords do not match.'
        else:
            store.add_player_login(username, inv['name'], pw, inv)
            store.use_invite(token)
            plans.track('player_join', username, inv['program'])
            session.clear()
            session['coach'] = username
            return redirect(player_home())
    return render_template_string(JOIN_PAGE, name=inv['name'].split()[0] if inv['name'] else '', team=store.program_label(inv['program']), until=until, error=error, username=username)


# --- Public website (/welcome): admin-only until SHEPSAVANT_SITE_PUBLIC=on --------------------------------------------------
import marketing

_SIGNUPS = {}      # ip -> [timestamps]; per worker, best effort


def _site_gate():
    """Only administrators can open the site until it is switched on for everyone."""
    if marketing.is_public() or (session.get('coach') and is_admin()):
        return None
    return redirect(url_for('login'))


@app.route('/welcome')
def welcome():
    return _site_gate() or render_template('site_home.html', **marketing.context('home'))


@app.route('/welcome/features')
def welcome_features():
    return _site_gate() or render_template('site_features.html', **marketing.context('features'))


@app.route('/welcome/plans')
def welcome_plans():
    return _site_gate() or render_template('site_plans.html', **marketing.context('plans'))


@app.route('/welcome/signup', methods=['GET', 'POST'])
def welcome_signup():
    blocked = _site_gate()
    if blocked:
        return blocked
    if session.get('coach') and not is_admin():
        return redirect(home_url())
    f = {k: ' '.join(request.form.get(k, '').split()) for k in ('name', 'email', 'school', 'username')}
    f['username'] = f['username'].lower()
    error = None
    if request.method == 'POST':
        import time as _t
        now = _t.time()
        ip = request.remote_addr or '?'
        recent = [t for t in _SIGNUPS.get(ip, []) if now - t < 3600]
        _SIGNUPS[ip] = recent
        u = re.sub(r'[^a-z0-9_.-]', '', f['username'])
        pslug = store.program_slug(f['school'])
        pw = request.form.get('password', '')
        existing = store.list_coaches()
        if request.form.get('website'):                                   # hidden field: only bots fill it
            return redirect(url_for('welcome'))
        if len(recent) >= 5:
            error = 'Too many sign-ups from this connection. Try again later.'
        elif not f['name'] or not f['school'] or not pslug:
            error = 'Enter your name and your school or program.'
        elif not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', f['email']):
            error = 'Enter a valid email address.'
        elif len(u) < 3 or u != f['username']:
            error = 'Pick a username of at least 3 letters or numbers (no spaces).'
        elif u.lower() in {x.lower() for x in existing}:
            error = 'That username is taken. Try another.'
        elif any((c.get('email') or '').lower() == f['email'].lower() for c in existing.values()):
            error = 'That email already has an account. Log in instead.'
        elif len(pw) < 8:
            error = 'Use a password of at least 8 characters.'
        elif pw != request.form.get('confirm', ''):
            error = 'The passwords do not match.'
        elif not request.form.get('agree'):
            error = 'Please confirm the checkbox to continue.'
        elif pslug in store.ADMIN_ONLY_PROGRAMS or pslug in store.DEMO_PROGRAMS or any(c.get('program') == pslug for c in existing.values()) \
                or pslug in {p for p, _ in store.list_programs()}:
            error = 'A team with that name already exists. Ask your head coach to add you as an assistant, or use a more specific name.'
        else:
            _SIGNUPS.setdefault(ip, []).append(now)
            store.add_coach(u, f['name'], pw, role='program', program=pslug, program_label=f['school'], push=False)
            store.update_coach(u, email=f['email'], signup=True, created=datetime.date.today().isoformat())
            end = plans.start_trial(pslug)
            plans.track('signup', u, pslug, email=f['email'])
            session.clear()
            session['coach'] = u
            return redirect(url_for('intake_bulk') + '?welcome=1')
    return render_template('site_signup.html', f=f, error=error, **marketing.context('signup'))


@app.route('/trial-ended')
@login_required
def trial_ended():
    return render_template('site_trial_ended.html', **marketing.context('plans'))


@app.route('/team/<program>/coaches', methods=['GET', 'POST'])
@login_required
@head_required
def team_coaches(program):
    _team_ok(program)
    c = current_coach() or {}
    head = session['coach'] if c.get('role', 'admin') != 'admin' else None
    msg, err = None, False
    invite_url = None
    f = request.form
    if request.method == 'POST':
        act = f.get('action', '')
        target = f.get('username', '')
        t = store.list_coaches().get(target)
        if act == 'add':
            u = re.sub(r'[^a-z0-9_.-]', '', f.get('username', '').strip().lower())
            name = ' '.join(f.get('display_name', '').split())
            ok, why = plans.can_add_assistant(program)
            if not ok:
                msg, err = why, True
            elif len(u) < 3 or not name or len(f.get('password', '')) < 8:
                msg, err = 'A username (3+ characters), a name and a temporary password of 8+ characters are required.', True
            elif u in store.list_coaches():
                msg, err = 'That username is already taken. Pick another.', True
            else:
                store.add_assistant(u, name, f['password'], program, store.program_label(program), head or session['coach'], can_upload=bool(f.get('can_upload')))
                plans.track('coach_add', session['coach'], program, target=u)
                msg = f'Added {name}. Give them the username "{u}" and the temporary password. They choose their own at first login.'
        elif act == 'players_switch' and is_admin():
            plans.set_flag(program, 'players', f.get('value') == '1')
            msg = 'Player logins ' + ('enabled' if f.get('value') == '1' else 'disabled') + ' for this program.'
        elif act == 'p_invite':
            if not plans.flag(program, 'players'):
                abort(404)
            kind, _, ref = f.get('who', '').partition(':')
            slug = hkey = name = None
            if kind == 'p' and (store.get_player(ref) or {}).get('program') == program:
                slug, name = ref, store.get_player(ref)['name']
                hkey = hitting.hitter_key_for(name, program, include_demo=False)
            elif kind == 'h':
                hh = hitting._collect(False).get(ref)
                if hh and hh['program'] == program:
                    hkey, name = ref, hitting.display_name(hh['name'])
            if not name:
                msg, err = 'Pick a player from the list.', True
            else:
                token = store.create_invite(program, name, slug, hkey, session['coach'], f.get('season_end') or None)
                invite_url = url_for('join', token=token, _external=True)
                msg = f'Invite link for {name} (works once, for {store.INVITE_DAYS} days):'
        elif act in ('p_active', 'p_remove', 'p_extend'):
            tp = store.list_coaches().get(target)
            if not tp or tp.get('role') != 'player' or tp.get('program') != program:
                msg, err = 'That player was not found.', True
            elif act == 'p_remove':
                store.delete_coach(target)
                plans.track('coach_remove', session['coach'], program, target=target)
                msg = f'Removed {tp["display_name"]}.'
            elif act == 'p_extend':
                store.update_coach(target, expires=f.get('season_end') or store.default_season_end(), active=True)
                msg = f'{tp["display_name"]} can log in until {f.get("season_end") or store.default_season_end()}.'
            else:
                store.update_coach(target, active=(f.get('value') == '1'))
                msg = f'{tp["display_name"]} {"can log in again" if f.get("value") == "1" else "has been turned off"}.'
        elif not t or t.get('role') != 'assistant' or t.get('program') != program:
            msg, err = 'That assistant was not found.', True
        elif act == 'uploads':
            on = f.get('value') == '1'
            store.update_coach(target, can_upload=on)
            plans.track('coach_uploads', session['coach'], program, target=target, on=on)
            msg = f'Uploading turned {"on" if on else "off"} for {t["display_name"]}.'
        elif act == 'active':
            on = f.get('value') == '1'
            if on and not t.get('active', True) and not plans.can_add_assistant(program)[0] and plans.assistant_count(program) > plans.assistant_cap(program):
                msg, err = 'Your plan has no room for another active assistant.', True
            else:
                store.update_coach(target, active=on)
                plans.track('coach_active', session['coach'], program, target=target, on=on)
                msg = f'{t["display_name"]} {"can log in again" if on else "has been turned off"}.'
        elif act == 'reset':
            if len(f.get('password', '')) < 8:
                msg, err = 'The temporary password needs 8+ characters.', True
            else:
                store.reset_password(target, f['password'])
                plans.track('coach_reset', session['coach'], program, target=target)
                msg = f'Temporary password set for {t["display_name"]}. They will choose a new one at next login.'
        elif act == 'remove':
            store.delete_coach(target)
            plans.track('coach_remove', session['coach'], program, target=target)
            msg = f'Removed {t["display_name"]}.'
    assistants = store.program_assistants(program)
    names = set(assistants) | set(store.program_heads(program))
    import time as _t
    last = {}
    for x in plans.events(program, 90, names, 2000):
        if x['e'] == 'login':
            last.setdefault(x['u'], x['t'])
    log = plans.events(program, 30, names, 40)
    ok_add, why_add = plans.can_add_assistant(program)
    players_on = plans.flag(program, 'players')
    players, choices = {}, []
    if players_on or is_admin():
        players = store.program_players(program)
        names |= set(players)
        for x in plans.events(program, 90, set(players), 2000):
            if x['e'] == 'login':
                last.setdefault(x['u'], x['t'])
        taken = {c.get('player_name') for c in players.values()}
        seen = set()
        for s, b in store.list_players().items():
            if b.get('program') == program and not store.is_demo(s) and b['name'] not in taken:
                choices.append(('p:' + s, b['name'])); seen.add(b['name'].lower())
        for k, hh in hitting._collect(False).items():
            nm = hitting.display_name(hh['name'])
            if hh['program'] == program and nm.lower() not in seen and nm not in taken:
                choices.append(('h:' + k, nm))
        choices.sort(key=lambda x: x[1].lower())
    log = plans.events(program, 30, names, 40)
    return render_template('team_coaches.html', players_on=players_on, players=players, choices=choices, invite_url=invite_url, season_end=store.default_season_end(), is_admin=is_admin(), program=program, team_label=store.program_label(program), heads=store.program_heads(program), assistants=assistants,
                           cap=plans.assistant_cap(program), count=plans.assistant_count(program), can_add=ok_add, why=why_add, last=last, log=log,
                           msg=msg, err=err, now=_t.time())


@app.route('/admin/activity')
@admin_required
def admin_activity():
    import time as _t
    log = plans.events(None, 14, None, 150)
    for x in log:
        x['when'] = _t.strftime('%b %d %H:%M', _t.gmtime(x['t'])) + ' UTC'
    signups = sorted(((u, c) for u, c in store.list_coaches().items() if c.get('signup')), key=lambda t: t[1].get('created', ''), reverse=True)
    trials = {c.get('program'): plans.plan_info(c.get('program'))['trial_ends'] for _u, c in signups}
    return render_template('admin_activity.html', flags=plans.flags(), log=log, coaches=store.list_coaches(), signups=signups, trials=trials, plans_expired=plans.trial_expired)


@app.route('/admin/status')
@admin_required
def admin_status():
    import github_sync
    return render_template_string(STATUS_PAGE, on=github_sync.enabled(), repo=github_sync.GITHUB_REPO, branch=github_sync.GITHUB_BRANCH, log=github_sync.LOG)


@app.route('/admin/backups', methods=['GET', 'POST'])
@admin_required
def admin_backups():
    import backup
    import time as _t
    msg = ''
    if request.method == 'POST':
        ok, msg = backup.run_backup(force_push=True)
        msg = ('Backed up: ' if ok else 'Backup failed: ') + msg
    rows = [dict(b, when=_t.strftime('%b %d, %Y %H:%M', _t.gmtime(b['mtime'])) + ' UTC', kb=b['size'] // 1024) for b in backup.list_backups()]
    return render_template_string(BACKUPS_PAGE, rows=rows, msg=msg, log=list(reversed(backup.LOG)), branch=backup.BACKUP_BRANCH)


@app.route('/admin/backups/<name>')
@admin_required
def admin_backup_download(name):
    import backup
    if not re.fullmatch(r'shepsavant-\d{4}-\d{2}-\d{2}\.zip', name) or not os.path.exists(os.path.join(backup.BACKUP_DIR, name)):
        abort(404)
    return send_file(os.path.join(backup.BACKUP_DIR, name), as_attachment=True, download_name=name)


BACKUPS_PAGE = """
<title>Backups</title><body style="font-family:system-ui,sans-serif;max-width:760px;margin:30px auto;padding:0 16px;color:#22303a;">
<h1>Data backups</h1>
<p>The whole data folder (players, rosters, outings, coaches, logs) is zipped automatically once a day and the newest 14 are kept. When GitHub sync is on, a copy also goes to the <b>{{ branch }}</b> branch once a week (and whenever you press the button), which does not redeploy the site. Backups kept on the server disappear if Render resets the server, so the GitHub copy is the one that survives.</p>
{% if msg %}<p style="background:#eef6f0;padding:10px 14px;border-radius:8px;">{{ msg }}</p>{% endif %}
<form method="post"><button type="submit" style="padding:9px 16px;border-radius:999px;border:0;background:#22303a;color:#fff;font-weight:700;cursor:pointer;">Back up now</button></form>
<table style="border-collapse:collapse;width:100%;margin-top:16px;font-size:14px;">
{% for r in rows %}<tr style="border-bottom:1px solid #e3e8e6;"><td style="padding:8px 0;"><a href="{{ url_for('admin_backup_download', name=r.name) }}">{{ r.name }}</a></td><td>{{ r.when }}</td><td style="text-align:right;">{{ r.kb }} KB</td></tr>
{% else %}<tr><td style="color:#6b7680;padding:10px 0;">No backups yet. The first one runs shortly after the site starts, or press the button.</td></tr>{% endfor %}</table>
{% if log %}<h3>Recent runs</h3>{% for l in log %}<div style="font-size:13px;color:{{ '#2f6b3a' if l.ok else '#a33' }};">{{ l.when }}: {{ l.detail }}</div>{% endfor %}{% endif %}
<p style="margin-top:22px;"><a href="{{ url_for('admin_status') }}">GitHub sync status</a></p>
</body>
"""


UPLOADS_PAGE = """
<title>Upload log</title><h1>Upload log</h1>
<p>Every CSV uploaded{% if not admin %} for {{ prog_label }}{% endif %}, newest first.</p>
{% if admin %}<form method="get" style="margin:0 0 12px;"><select name="program" onchange="this.form.submit()"><option value="">All programs</option>{% for slug, lab in programs %}<option value="{{ slug }}" {{ 'selected' if slug == sel }}>{{ lab }}</option>{% endfor %}</select></form>{% endif %}
{% if rows %}<div class="card" style="overflow-x:auto;"><table style="border-collapse:collapse;width:100%;font-size:14px;">
<tr style="text-align:left;color:#6b7680;"><th style="padding:6px 10px;">Uploaded</th><th style="padding:6px 10px;">File</th><th style="padding:6px 10px;">Type</th>{% if admin %}<th style="padding:6px 10px;">Program</th>{% endif %}<th style="padding:6px 10px;">By</th><th style="padding:6px 10px;">Rows</th><th style="padding:6px 10px;">Players</th><th></th></tr>
{% for e in rows %}<tr style="border-top:1px solid #eceeed;vertical-align:top;"><td style="padding:6px 10px;white-space:nowrap;">{{ e.when }}</td><td style="padding:6px 10px;">{{ e.file }}</td><td style="padding:6px 10px;">{{ e.source }}</td>{% if admin %}<td style="padding:6px 10px;">{{ e.plabel }}</td>{% endif %}<td style="padding:6px 10px;">{{ e.user }}</td><td style="padding:6px 10px;">{{ e.rows }}</td><td style="padding:6px 10px;">{{ e.players|join(', ') }}</td>
<td style="padding:6px 10px;white-space:nowrap;">{% if e.removed %}<span style="color:#98a3a9;">Removed</span>{% elif e.id %}<form method="post" action="{{ url_for('upload_remove') }}" onsubmit="return confirm('Remove every pitch from {{ e.file }}? This cannot be undone.');" style="margin:0;"><input type="hidden" name="id" value="{{ e.id }}"><button style="background:none;border:0;color:#a63a2c;font:600 13px Barlow,sans-serif;cursor:pointer;padding:0;">Remove data</button></form>{% endif %}</td></tr>{% endfor %}
</table></div>{% else %}<div class="card">No uploads logged yet. Uploads from now on will appear here.</div>{% endif %}
{% if message %}<div class="card" style="color:#2a7a4b;">{{ message }}</div>{% endif %}
<div class="card"><b>Remove a CSV that isn't listed above</b>
<p style="font-size:13px;color:#6b7680;">For files uploaded before this log existed: choose the same CSV again and every pitch it contributed is taken back out. Pitchers left with no data are removed too. Nothing else is touched.</p>
<form method="post" action="{{ url_for('upload_remove_file') }}" enctype="multipart/form-data" onsubmit="return confirm('Remove every pitch in this file from the data? This cannot be undone.');"><input type="file" name="csv" accept=".csv" required> <button type="submit" style="background:#a63a2c;">Remove this file's data</button></form></div>
<p><a href="{{ home }}">Back to the dashboard</a></p>
"""


def _own_pitcher(slug):
    """Admins may touch any pitcher's data; a program coach only his own program's."""
    if is_admin():
        return True
    if slug.startswith(cleanup.OPP_PREFIX):
        return outings_mod.load(slug, real_only=True).get('program') == my_program()
    p = store.get_real_player(slug)
    return bool(p) and p.get('program') == my_program()


def _removal_message(res, gone):
    msg = f"Removed {res['rows']} pitch{'es' if res['rows'] != 1 else ''}"
    if gone:
        msg += ' and the pitcher record' + ('s' if len(gone) > 1 else '') + ' for ' + ', '.join(gone)
    return msg + '.' if res['rows'] else 'No matching pitches were found, so nothing changed.'


@app.route('/uploads/remove', methods=['POST'])
@login_required
@head_required
def upload_remove():
    uid = request.form.get('id', '')
    entry = next((e for e in uploadlog.entries() if e.get('id') == uid), None) if uid else None
    if not entry or (not is_admin() and entry.get('program') != my_program()):
        abort(404)
    with github_sync.batch('Remove an uploaded CSV'):
        res = cleanup.remove_upload(uid, allowed=_own_pitcher)
        gone = cleanup.drop_empty_players([s for s in entry.get('new_players') or [] if s in res['pitchers']] if res['rows'] else [])
        uploadlog.mark_removed(uid)
    return redirect(url_for('upload_log_page', msg=_removal_message(res, gone)))


@app.route('/uploads/remove-file', methods=['POST'])
@login_required
@head_required
def upload_remove_file():
    f = request.files.get('csv')
    if not f or not f.filename:
        return redirect(url_for('upload_log_page', msg='Choose a CSV file first.'))
    path = os.path.join(UPLOAD_DIR, 'rm_' + os.path.basename(f.filename))
    f.save(path)
    try:
        uids = cleanup.csv_uids(path)
    except Exception as exc:
        return redirect(url_for('upload_log_page', msg=f"Couldn't read that file: {exc}"))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    with github_sync.batch('Remove a CSV from the data'):
        res = cleanup.remove_uids(uids, allowed=_own_pitcher)
        gone = cleanup.drop_empty_players(res['emptied'])
    return redirect(url_for('upload_log_page', msg=_removal_message(res, gone)))


SORT_PAGE = """
<title>Sort hitters</title><h1>Sort hitters</h1>
<p>Hitters are picked up from the pitches your pitchers faced, so an opposing team's hitters can land on your dashboard. Move each one to the right team, or hide opponents so they stay out of every dashboard. Their pitch data is kept.</p>
{% if message %}<div class="card" style="color:#2a7a4b;">{{ message }}</div>{% endif %}
<form method="get" style="margin:0 0 10px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
{% if admin %}<select name="program" onchange="this.form.submit()"><option value="">All teams</option>{% for slug, lab in programs %}<option value="{{ slug }}" {{ 'selected' if slug == sel }}>{{ lab }}</option>{% endfor %}</select>{% endif %}
<label style="font-size:14px;"><input type="checkbox" name="offroster" value="1" {{ 'checked' if offroster }} onchange="this.form.submit()"> Only hitters not on the team roster</label>
<input id="q" type="search" placeholder="Search hitters…" style="padding:8px 12px;border:1px solid #dde2e5;border-radius:999px;" oninput="var v=this.value.toLowerCase();document.querySelectorAll('tr.h').forEach(function(r){r.style.display=r.dataset.n.indexOf(v)>-1?'':'none';});"></form>
<form method="post" action="{{ url_for('hitters_sort_save') }}"><input type="hidden" name="back" value="{{ request.full_path }}">
<div class="card" style="overflow-x:auto;"><table style="border-collapse:collapse;width:100%;font-size:14px;">
<tr style="text-align:left;color:#6b7680;"><th style="padding:6px 10px;">Hitter</th><th style="padding:6px 10px;">Pitches</th><th style="padding:6px 10px;">Now on</th><th style="padding:6px 10px;">On roster</th><th style="padding:6px 10px;">Move to</th></tr>
{% for r in rows %}<tr class="h" data-n="{{ r.name|lower }}" style="border-top:1px solid #eceeed;{{ 'background:#faf6ee;' if r.hidden }}">
<td style="padding:6px 10px;font-weight:600;">{{ r.name }}</td><td style="padding:6px 10px;">{{ r.n }}</td>
<td style="padding:6px 10px;">{{ 'Hidden' if r.hidden else r.plabel }}</td>
<td style="padding:6px 10px;">{{ 'Yes' if r.on_roster else 'No' }}</td>
<td style="padding:6px 10px;"><input type="hidden" name="cur_{{ r.key }}" value="{{ r.cur }}"><select name="to_{{ r.key }}">
<option value="" {{ 'selected' if not r.cur }}>Automatic ({{ r.auto_label }})</option>
{% for slug, lab in r.options %}<option value="{{ slug }}" {{ 'selected' if r.cur == slug }}>{{ lab }}</option>{% endfor %}
<option value="_hidden" {{ 'selected' if r.cur == '_hidden' }}>Hide (opponent / not ours)</option></select></td></tr>{% endfor %}
</table>{% if not rows %}<p>No hitters to sort.</p>{% endif %}</div>
{% if rows %}<button type="submit">Save changes</button>{% endif %}</form>
<p><a href="{{ home }}">Back to the dashboard</a></p>
"""


@app.route('/hitters/sort')
@admin_required
def hitters_sort():
    admin = is_admin()
    sel = request.args.get('program') if admin else my_program()
    if not admin and not sel:
        abort(403)
    offroster = bool(request.args.get('offroster'))
    progs = store.list_programs()
    if admin:
        progs = progs + [('shepherds', store.program_label('shepherds'))]
    rows = []
    for key, h in hitting._collect(False, include_hidden=True).items():
        auto = h.get('auto_program') or h['program']
        eff = None if h.get('hidden') else h['program']
        if sel and sel not in (eff, auto):
            continue
        if offroster and h.get('on_roster'):
            continue
        cur = cleanup.hitter_overrides().get(key, '')
        rows.append({'key': key, 'name': hitting.display_name(h['name']), 'n': len(h['pitches']), 'hidden': bool(h.get('hidden')),
                     'plabel': store.program_label(eff) if eff else '', 'on_roster': h.get('on_roster'), 'cur': cur,
                     'auto_label': store.program_label(auto), 'options': progs if admin else []})
    rows.sort(key=lambda r: (r['on_roster'] or False, r['hidden'], r['name'].split()[-1].lower()))
    return render_template_string(BULK_STYLE + SORT_PAGE, rows=rows, admin=admin, programs=progs, sel=sel or '', offroster=offroster,
                                  home=home_url(), message=request.args.get('msg'))


@app.route('/hitters/sort', methods=['POST'])
@admin_required
def hitters_sort_save():
    admin = is_admin()
    allowed_keys = {k for k, h in hitting._collect(False, include_hidden=True).items()
                    if admin or (h.get('auto_program') or h['program']) == my_program()}
    valid = {s for s, _ in store.list_programs()} | {'shepherds', cleanup.HIDDEN, ''}
    changes = {}
    for k, v in request.form.items():
        if not k.startswith('to_'):
            continue
        key = k[3:]
        if key not in allowed_keys or v == request.form.get('cur_' + key, ''):
            continue
        if v not in valid or (not admin and v not in ('', cleanup.HIDDEN)):
            continue
        changes[key] = v
    if changes:
        with github_sync.batch('Sort hitters'):
            cleanup.set_hitter_overrides(changes)
    back = request.form.get('back', '')
    base = url_for('hitters_sort')
    q = back.split('?', 1)[1].rstrip('?') if '?' in back else ''
    q = '&'.join(x for x in q.split('&') if x and not x.startswith('msg='))
    return redirect(base + '?' + (q + '&' if q else '') + 'msg=' + (f'Saved {len(changes)} change{"s" if len(changes) != 1 else ""}.' if changes else 'Nothing to change.'))


@app.route('/uploads')
@login_required
def upload_log_page():
    import datetime
    admin = is_admin()
    sel = request.args.get('program') if admin else None
    prog = None if (admin and not sel) else (sel if admin else my_program())
    if not admin and not prog:
        abort(403)
    rows = []
    for e in uploadlog.entries(prog):
        t = datetime.datetime.fromtimestamp(e['t'], datetime.timezone(datetime.timedelta(hours=-7))).strftime('%b %-d, %Y %-I:%M %p')
        rows.append({**e, 'when': t, 'plabel': store.program_label(e.get('program')) if e.get('program') else '', 'prs': (prs.upload_events(e) if not e.get('removed') else [])})
    progs = [(p, store.program_label(p)) for p in sorted({e.get('program') for e in uploadlog.entries() if e.get('program')})]
    return render_template('upload_log.html', rows=rows, admin=admin, programs=progs, sel=sel or '', home=home_url(), message=request.args.get('msg'),
                                  prog_label=store.program_label(prog) if prog else '')


OLD_REPORTS_PAGE = """
<title>Old Shepherds reports</title><h1>Old Shepherds reports</h1>
<p>Shepherds players now get the same live dashboards and outing reports as every other team, built from their uploaded sessions. These are the original static report files made before that, and nothing links to them anymore.</p>
{% if message %}<div class="card" style="color:#2a7a4b;">{{ message }}</div>{% endif %}
{% if files %}<div class="card"><b>{{ files|length }} file{{ 's' if files|length != 1 }} will be deleted:</b><ul>{% for slug, suffix in files %}<li>{{ slug }}{{ suffix }}</li>{% endfor %}</ul>
<p style="font-size:13px;color:#6b7680;">Player profiles, outings, headshots and everything for other teams are not touched.</p>
<form method="post"><button type="submit" style="background:#a63a2c;">Delete these old reports</button></form></div>
{% else %}<div class="card">No old Shepherds report files are left.</div>{% endif %}
<p><a href="{{ url_for('admin_status') }}">&larr; Save status</a></p>"""


@app.route('/admin/old-reports', methods=['GET', 'POST'])
@admin_required
def admin_old_reports():
    message = None
    if request.method == 'POST':
        n = store.delete_legacy_shepherds_reports()
        message = f'Deleted {n} old report file{"s" if n != 1 else ""}.'
    return render_template_string(BULK_STYLE + OLD_REPORTS_PAGE, files=[(s_, suf) for s_, suf, _p in store.legacy_shepherds_reports()], message=message)


@app.route('/admin/status/test', methods=['POST'])
@admin_required
def admin_status_test():
    store.sync_to_github()
    return redirect(url_for('admin_status'))


@app.route('/admin/coaches', methods=['GET', 'POST'])
@admin_required
def admin_coaches():
    msg, err = None, False
    if request.method == 'POST':
        f = request.form
        u = re.sub(r'[^a-z0-9_.-]', '', f.get('username', '').strip().lower())
        if not u or len(f.get('password', '')) < 8 or not f.get('display_name', '').strip():
            msg, err = 'Username, name and a password of at least 8 characters are required.', True
        else:
            if f.get('role') == 'demo':
                store.add_coach(u, f['display_name'].strip(), f['password'], role='program', program='demo_university', program_label='Demo University (sample)', push=True, demo_view=True)
                return render_template_string(COACHES_PAGE, coaches=store.list_coaches(), me=session.get('coach'), err=False, programs=store.list_programs(),
                                              msg=f'Demo login "{u}" saved (view-only, sample data only). Share the username and password with them.')
            role = 'admin' if f.get('role') == 'admin' else 'program'
            label = ' '.join(f.get('program_label', '').split())
            pslug = store.program_slug(label)
            if role == 'program' and (not pslug or pslug in store.ADMIN_ONLY_PROGRAMS):
                msg, err = 'Enter the coach\'s program or school name (e.g. Long Beach State).', True
            elif role == 'program' and u not in store.list_coaches() and not plans.can_add_coach(pslug)[0]:
                msg, err = plans.can_add_coach(pslug)[1] + ' Change their plan on the Plans & usage page first.', True
            else:
                store.add_coach(u, f['display_name'].strip(), f['password'], role=role,
                                program=pslug if role == 'program' else None, program_label=label if role == 'program' else None, push=True)
                msg = f'Saved login "{u}". Share the username and password with them.'
    return render_template_string(COACHES_PAGE, coaches=store.list_coaches(), me=session.get('coach'), msg=msg, err=err, programs=store.list_programs())


@app.route('/admin/coaches/<username>/delete', methods=['POST'])
@admin_required
def admin_coach_delete(username):
    if username != session.get('coach'):
        store.delete_coach(username)
    return redirect(url_for('admin_coaches'))


@app.route('/player/<slug>/headshot', methods=['POST'])
@login_required
def upload_headshot(slug):
    if not can_manage(slug):
        abort(403)
    if not store.get_player(slug):
        abort(404)
    f = request.files.get('photo')
    if f and f.filename:
        try:
            headshots.save(slug, f)
        except Exception as exc:
            return f"Couldn't read that image: {exc}", 400
    return redirect(url_for('player_overview', slug=slug))


@app.route('/player/<slug>/delete', methods=['POST'])
@login_required
@head_required
def delete_player_route(slug):
    if not can_manage(slug) or store.is_demo(slug):
        abort(403)
    prog = (store.get_player(slug) or {}).get('program')
    if not store.delete_player(slug):
        abort(404)
    return redirect(url_for('team_pitchers', program=prog) if prog else url_for('dashboard'))


@app.route('/player/<slug>/rename', methods=['POST'])
@login_required
def rename_player_route(slug):
    if not can_manage(slug):
        abort(403)
    prog = (store.get_player(slug) or {}).get('program')
    new_slug, err = store.rename_player(slug, request.form.get('name', ''))
    if err:
        return err, 400
    return redirect(url_for('player_overview', slug=new_slug) if new_slug else (url_for('team_pitchers', program=prog) if prog else url_for('dashboard')))


@app.route('/admin/backup/players.json')
@admin_required
def backup_players():
    """Downloads the live roster data (bios, comps, 60 times) as a plain
    JSON file. Render's free tier resets this file to whatever's committed
    in the GitHub repo every time new code is pushed -- download this after
    adding or changing players, then drag-and-drop it into the repo's
    data/ folder (same as any other file update) so the current roster
    survives the next code deploy instead of resetting to an old snapshot."""
    return send_file(store.PLAYERS_PATH, as_attachment=True, download_name='players.json')


@app.route('/report/<slug>/<role>')
def view_report(slug, role):
    if not session.get('coach'):
        return redirect(url_for('login', next=request.path))
    if not can_view(slug):
        abort(404)
    if role not in ('pitching', 'hitting', 'trackman'):
        abort(404)
    if role == 'trackman':
        return redirect(url_for('player_overview', slug=slug))
    filename = f'{slug}_trackman_mini.html' if role == 'trackman' else f'{slug}_{role}.html'
    path = os.path.join(pipeline.REPORTS_DIR, filename)
    if not os.path.exists(path):
        abort(404)
    return send_file(path)


# --- intake form (coach-only) --------------------------------------------

INTAKE_PAGE = """
<!doctype html><title>New Player Intake</title>
<style>
  body{font-family:Barlow,Arial,sans-serif;background:#f7f6f2;color:#22303a;max-width:560px;margin:0 auto;padding:28px 16px 60px;}
  h1{font-family:Oswald,Arial,sans-serif;}
  label{display:block;font-weight:600;font-size:13px;margin:14px 0 4px;}
  input[type=text],input[type=number]{width:100%;padding:9px 10px;border:1px solid #dcdfdc;border-radius:7px;box-sizing:border-box;}
  .row{display:flex;gap:10px;} .row > div{flex:1;}
  button{margin-top:20px;padding:11px 22px;border:none;border-radius:999px;background:#5c97a8;color:#fff;font-weight:600;cursor:pointer;}
  .msg{padding:10px 14px;border-radius:8px;margin-bottom:14px;}
  .msg.ok{background:#e3ecdf;color:#3f6b42;} .msg.err{background:#f6dede;color:#9c3a3a;}
  .top{display:flex;justify-content:space-between;align-items:center;}
  .top a{color:#6b7680;font-size:13px;}
  fieldset{border:1px solid #dcdfdc;border-radius:10px;margin-top:16px;}
</style>
<div class="top"><h1>New Player Intake</h1><a href="{{ url_for('logout') }}">Log out ({{ coach }})</a></div>
{% if message %}<div class="msg {{ 'ok' if ok else 'err' }}">{{ message }}</div>{% endif %}
<form method="post" enctype="multipart/form-data">
  <label>Full name</label><input type="text" name="name" required>
  <div class="row">
    <div><label>School</label><input type="text" name="school"></div>
    <div><label>Graduation year</label><input type="number" name="grad_year"></div>
  </div>
  <div class="row">
    <div><label>Pitching position (leave blank if N/A)</label><input type="text" name="position_pitch" placeholder="RHP, LHP"></div>
    <div><label>Hitting position (leave blank if N/A)</label><input type="text" name="position_hit" placeholder="INF, OF, C"></div>
  </div>
  <div><label>60 time (seconds, hitters only -- leave blank if N/A)</label>
    <input type="number" step="0.01" min="0" name="sixty_yd_time" placeholder="e.g. 6.85">
    <p style="font-size:12.5px;color:#6b7680;margin:4px 0 0;">Used to fill in the 60 Yard Dash and Sprint Speed lines on the Running panel. Can be added or changed later from the Edit Comps page without re-uploading.</p>
  </div>
  <fieldset style="padding:12px 14px;">
    <label style="margin-top:0;">Full Swing export (.xlsx)</label>
    <input type="file" name="xlsx_file" accept=".xlsx" required>
    <p style="font-size:12.5px;color:#6b7680;">The workbook must include this player's rows on the Master and Totals tabs.</p>
  </fieldset>
  <fieldset style="padding:12px 14px;">
    <label style="margin-top:0;">Trackman export (.csv, pitchers only -- optional)</label>
    <input type="file" name="trackman_file" accept=".csv">
    <p style="font-size:12.5px;color:#6b7680;">If this player's school gives him a Trackman report, attach its CSV here to fill in real Pitch Movement Profile and Spin Direction numbers instead of the sample placeholder values. Leave blank if he doesn't have one -- everything else still works the same.</p>
  </fieldset>
  <button type="submit">Generate report(s)</button>
</form>
<p style="margin-top:28px;"><a href="{{ url_for('intake_bulk') }}">Adding Trackman pitchers? Upload a .CSV &rarr;</a></p>
<p style="margin-top:10px;"><a href="{{ home_url }}">&larr; Back to {{ home_label }}</a></p>
<p style="margin-top:10px;font-size:12.5px;"><a href="{{ url_for('backup_players') }}">Download current roster data (players.json)</a> -- after adding players, upload this file into the GitHub repo's <code>data/</code> folder so the roster survives the next code update.</p>
"""


@app.route('/intake', methods=['GET', 'POST'])
@admin_required
def intake():
    message, ok = None, True
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        school = request.form.get('school', '').strip() or None
        grad_year = request.form.get('grad_year', '').strip()
        grad_year = int(grad_year) if grad_year.isdigit() else None
        position_pitch = request.form.get('position_pitch', '').strip() or None
        position_hit = request.form.get('position_hit', '').strip() or None
        roles_needed = [r for r, pos in (('pitch', position_pitch), ('hit', position_hit)) if pos]
        if not roles_needed:
            roles_needed = ['pitch', 'hit']  # if neither position given, try both

        sixty_yd_time = request.form.get('sixty_yd_time', '').strip()
        try:
            sixty_yd_time = float(sixty_yd_time) if sixty_yd_time else None
        except ValueError:
            sixty_yd_time = None

        f = request.files.get('xlsx_file')
        tm_f = request.files.get('trackman_file')
        if not name or not f or not f.filename:
            message, ok = 'Name and a Full Swing export file are required.', False
        else:
            xlsx_path = os.path.join(UPLOAD_DIR, f'{store.slugify(name)}_{f.filename}')
            f.save(xlsx_path)
            trackman_path = None
            if tm_f and tm_f.filename:
                trackman_path = os.path.join(UPLOAD_DIR, f'{store.slugify(name)}_trackman_{tm_f.filename}')
                tm_f.save(trackman_path)
            try:
                slug, results = pipeline.process_upload(
                    xlsx_path, name, school, grad_year, position_pitch, position_hit, roles_needed,
                    sixty_yd_time=sixty_yd_time, trackman_path=trackman_path,
                )
                if results:
                    links = ', '.join(f"{role}" for role, _ in results)
                    message = f'Generated: {links} for {name}. View on the dashboard below.'
                else:
                    message, ok = f"{name} wasn't found on the Totals tab for the role(s) requested — check the name matches exactly.", False
            except Exception as exc:
                message, ok = f'Something went wrong processing that file: {exc}', False

    return render_template_string(INTAKE_PAGE, message=message, ok=ok, coach=store.coach_display_name(session['coach']))


# --- Long Beach State intake (coach-only) --------------------------------
# Separate, lighter-weight form for a pitcher who only has a Trackman
# session -- no Full Swing export required. Produces the scoped
# movement/spin/velo-only report (pipeline.render_trackman_mini) instead of
# the full Pitching Report, and tags the player 'long_beach_state' so he
# shows in that group on the dashboard instead of under Shepherds.

LBSU_INTAKE_PAGE = """
<!doctype html><title>New Player Intake &mdash; Long Beach State</title>
<style>
  body{font-family:Barlow,Arial,sans-serif;background:#f7f6f2;color:#22303a;max-width:560px;margin:0 auto;padding:28px 16px 60px;}
  h1{font-family:Oswald,Arial,sans-serif;font-size:22px;}
  label{display:block;font-weight:600;font-size:13px;margin:14px 0 4px;}
  input[type=text],input[type=number]{width:100%;padding:9px 10px;border:1px solid #dcdfdc;border-radius:7px;box-sizing:border-box;}
  .row{display:flex;gap:10px;} .row > div{flex:1;}
  button{margin-top:20px;padding:11px 22px;border:none;border-radius:999px;background:#5c97a8;color:#fff;font-weight:600;cursor:pointer;}
  .msg{padding:10px 14px;border-radius:8px;margin-bottom:14px;}
  .msg.ok{background:#e3ecdf;color:#3f6b42;} .msg.err{background:#f6dede;color:#9c3a3a;}
  .top{display:flex;justify-content:space-between;align-items:center;}
  .top a{color:#6b7680;font-size:13px;}
  fieldset{border:1px solid #dcdfdc;border-radius:10px;margin-top:16px;padding:12px 14px;}
</style>
<div class="top"><h1>New Player Intake &mdash; Long Beach State</h1><a href="{{ url_for('logout') }}">Log out ({{ coach }})</a></div>
{% if message %}<div class="msg {{ 'ok' if ok else 'err' }}">{{ message }}</div>{% endif %}
<form method="post" enctype="multipart/form-data">
  <label>Full name</label><input type="text" name="name" required>
  <p style="font-size:12.5px;color:#6b7680;margin:2px 0 0;">Must match the pitcher's name in the Trackman CSV (either "First Last" or "Last, First" works).</p>
  <div class="row">
    <div><label>School</label><input type="text" name="school"></div>
    <div><label>Graduation year</label><input type="number" name="grad_year"></div>
  </div>
  <label>Pitching position</label><input type="text" name="position_pitch" placeholder="RHP, LHP">
  <label>Height <span style="font-weight:400;color:#6b7680;">(used for the arm-slot graphic)</span></label>
  <div class="row">
    <div><input type="number" name="height_ft" min="4" max="7" placeholder="feet"></div>
    <div><input type="number" name="height_in" min="0" max="11" step="0.5" placeholder="inches"></div>
    <div><input type="number" name="weight_lbs" min="80" max="400" placeholder="weight (lbs)"></div>
  </div>
  <fieldset>
    <label style="margin-top:0;">Trackman export (.csv)</label>
    <input type="file" name="trackman_file" accept=".csv" required>
    <label style="font-weight:600;font-size:13px;display:block;margin-top:12px;"><input type="checkbox" name="live_ab" value="1"> Game / Live AB session (adds the Outing Summary; leave unchecked for bullpens)</label>
    <p style="font-size:12.5px;color:#6b7680;">Builds a Pitch Movement Profile, Spin Direction, and velocity report straight from this session. No Full Swing data behind it, so season stats, percentiles, and comps aren't part of this report.</p>
  </fieldset>
  <button type="submit">Generate report</button>
</form>
<p style="margin-top:28px;"><a href="{{ url_for('intake') }}">&larr; Back to Shepherds intake</a></p>
<p style="margin-top:10px;"><a href="{{ home_url }}">&larr; Back to {{ home_label }}</a></p>
"""


def _num_or_none(v):
    try:
        return float(v) if v not in (None, '') else None
    except ValueError:
        return None


BULK_STYLE = """<style>body{font-family:Barlow,Arial,sans-serif;background:#f7f6f2;color:#22303a;max-width:820px;margin:0 auto;padding:28px 16px 60px;}
h1{font-family:Oswald,Arial,sans-serif;} .card{background:#fff;border:1px solid #dcdfdc;border-radius:10px;padding:12px 14px;margin:12px 0;}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:end;} .row label{font-size:12px;font-weight:600;display:block;} .row input[type=text],.row input[type=number]{padding:7px 8px;border:1px solid #dcdfdc;border-radius:6px;}
.flag{color:#9c3a3a;font-size:12.5px;margin:4px 0 0 22px;} .tag{font-size:11px;background:#e3ecdf;color:#3f6b42;border-radius:999px;padding:2px 8px;margin-left:6px;}
button{margin-top:14px;padding:11px 22px;border:none;border-radius:999px;background:#5c97a8;color:#fff;font-weight:600;cursor:pointer;}</style>"""

BULK_UPLOAD_PAGE = BULK_STYLE + """
<title>Upload a .CSV</title>{% set hero_title = 'Upload a .CSV' %}{% include '_bulk_hero.html' %}{% if welcome %}<div class="card" style="border-left:5px solid #5c97a8;"><h2 style="margin:0 0 6px;font-family:Oswald,Arial,sans-serif;">Welcome{% if welcome_name %}, {{ welcome_name }}{% endif %}!</h2>
<p style="margin:0 0 8px;">Let's start by adding your first session. It takes about a minute.</p>
<ol style="margin:0;padding-left:20px;line-height:1.6;"><li>Export a session from your tracking system as a <b>CSV</b>.</li><li>Choose that file in the matching box below and tap <b>Read file</b>.</li><li>On the next screen, confirm each player and add class year, height and weight if you have them. Then tap <b>Generate all reports</b>.</li></ol>
<p style="margin:8px 0 0;color:#6b7680;font-size:14px;">Right after, we'll give you a quick tour of your player dashboard and outing reports.</p></div>{% endif %}
<p>Choose your Trackman file. Everyone in it is picked up automatically.</p>
{% if message %}<div class="card" style="color:#9c3a3a;">{{ message }}</div>{% endif %}
<form method="post" enctype="multipart/form-data">{% if programs %}<p><label style="font-weight:600;">Upload to: <select name="program">{% for s, l in programs %}<option value="{{ s }}" {{ 'selected' if s == prog }}>{{ l }}</option>{% endfor %}</select></label></p>{% endif %}
<div class="card"><label style="font-weight:700;font-size:16px;display:block;margin-bottom:6px;">What kind of session is this?</label>
<select name="session_type" required style="padding:9px 12px;border:1px solid #dde2e5;border-radius:10px;font:600 15px Barlow,sans-serif;"><option value="" disabled selected>Choose one…</option><option>Bullpen</option><option>Intrasquad</option><option>Scrimmage</option><option>Game</option><option value="Scouting">Scouting only (two other teams)</option></select>
<div id="opp-row" style="display:none;margin-top:12px;"><label style="font-weight:600;font-size:14px;">Opponent <span style="font-weight:400;color:#6b7680;">(optional)</span><br><input type="text" name="opponent" list="opp-list" placeholder="e.g. UCLA" autocomplete="off" style="margin-top:4px;padding:9px 12px;border:1px solid #dde2e5;border-radius:10px;font:500 15px Barlow,sans-serif;width:260px;max-width:100%;"></label><datalist id="opp-list">{% for o in opponents %}<option value="{{ o }}">{% endfor %}</datalist></div>
<script>(function(){var s=document.querySelector('select[name=session_type]'),r=document.getElementById('opp-row');function f(){r.style.display=(s.value==='Scrimmage'||s.value==='Game')?'block':'none';}s.addEventListener('change',f);f();})();</script>
<div style="color:#6b7680;font-size:13px;margin-top:8px;line-height:1.5;"><b>Bullpen</b>: pitching only, no hitters are added. <b>Intrasquad</b>: everyone in the file is on your team. <b>Scouting only</b>: a file between two other programs; both teams go into Scouting and nothing is added to your dashboards. <b>Scrimmage / Game</b>: you pick your pitchers on the next screen. Hitters facing them are treated as the opponent and left out, and your own hitters are picked up from the opposing pitchers' pitches.</div></div>
{% for sid, lab, note in sources %}<div class="card"><label style="font-weight:700;font-size:16px;display:block;margin-bottom:6px;">{{ lab }} CSV</label><input type="file" name="file_{{ sid }}" accept=".csv"><div style="color:#6b7680;font-size:13px;margin-top:6px;">{{ note }}</div></div>{% endfor %}
<button type="submit">Read file</button></form>
<p><a href="{{ home_url }}">&larr; {{ home_label|capitalize }}</a></p>"""

UPLOAD_SOURCES = [('trackman', 'Trackman', 'Per-pitch export from a Trackman session.'),
                  ('fullswing', 'Full Swing', 'Per-pitch export from a Full Swing session.'),
                  ('yakkertech', 'Yakkertech', 'Per-pitch export from a Yakkertech session.'),
                  ('rapsodo', 'Rapsodo', 'Per-pitch export from a Rapsodo session.')]
_SOURCES_READY = {'trackman', 'fullswing'}

BULK_REVIEW_PAGE = BULK_STYLE + """
<title>Review Pitchers</title>{% set hero_title = 'Review pitchers' %}{% include '_bulk_hero.html' %}
<p>{{ pitchers|length }} pitchers found. Fill in height/weight for the arm-angle badge (optional), uncheck anyone to skip, and review any flagged pitches.</p>
<form method="post" enctype="multipart/form-data" action="{{ url_for('intake_bulk_run') }}">
<input type="hidden" name="path" value="{{ path }}"><input type="hidden" name="program" value="{{ prog }}">
<input type="hidden" name="session_type" value="{{ session_type }}"><p style="font-weight:600;margin:0 0 8px;">Session type: {{ session_type }}{% if session_type in ('Scrimmage', 'Game') %} <span style="font-weight:400;color:#6b7680;">&mdash; check only your own pitchers. Everyone else is treated as the opponent.</span>{% endif %}</p>
{% if session_type in ('Scrimmage', 'Game') %}<div class="card" style="margin-top:10px;"><div class="row">
  {% if codes %}<div><label>Which team is yours in this file?</label><select id="myteam" name="my_team"><option value="" {{ 'selected' if not my_team }} disabled>Choose…</option>{% for code, n in codes.items() %}<option value="{{ code }}" {{ 'selected' if code == my_team }}>{{ code }} ({{ n }} pitchers)</option>{% endfor %}</select></div>{% endif %}
  <div><label>Opponent</label><input type="text" name="opponent" value="{{ opponent }}" placeholder="e.g. UCLA" style="width:220px;"></div></div>
  {% if codes %}<p style="font-size:13px;color:#6b7680;margin:8px 0 0;">Pitchers on your team are checked below and the other team's are left out. Your choice is remembered for next time.</p>{% endif %}</div>
{% else %}<input type="hidden" name="opponent" value="">{% endif %}
<div class="row" style="margin-top:10px;"><div><label>School</label><input type="text" name="school" value="{{ prog_label }}"></div></div>
{% for p in pitchers %}{% set i = loop.index0 %}
<div class="card">
  <label style="font-weight:700;font-size:16px;"><input type="checkbox" name="inc_{{ i }}" value="1" data-team="{{ p.team }}" {% if my_team and p.team %}{{ 'checked' if p.team == my_team else '' }}{% else %}{{ '' if p.on_roster is sameas false else 'checked' }}{% endif %}> <input type="text" name="name_{{ i }}" value="{{ p.name }}" style="font-weight:600;"> {{ p.throws }}HP &middot; {{ p.n }} pitches{% if p.known %}<span class="tag">already on roster</span>{% endif %}{% if p.on_roster is sameas true %}<span class="tag" style="background:#e4f2ea;color:#2a7a4b;">on team roster</span>{% elif p.on_roster is sameas false %}<span class="tag" style="background:#fbf0d9;color:#8a6212;">not on team roster</span>{% endif %}</label>
  <input type="hidden" name="csv_{{ i }}" value="{{ p.csv_name }}"><input type="hidden" name="throws_{{ i }}" value="{{ p.throws }}">
  <div class="row" style="margin-top:8px;">
    <div><label>Class of</label><input type="number" name="grad_{{ i }}" value="{{ p.bio.get('grad_year') or '' }}" style="width:80px;"></div>
    <div><label>Height (ft)</label><input type="number" name="ft_{{ i }}" value="{{ ((p.bio.get('height_in') or 0)//12)|int or '' }}" style="width:70px;"></div>
    <div><label>(in)</label><input type="number" name="in_{{ i }}" value="{{ ((p.bio.get('height_in') or 0)%12)|int if p.bio.get('height_in') else '' }}" style="width:70px;"></div>
    <div><label>Weight (lb)</label><input type="number" name="wt_{{ i }}" value="{{ p.bio.get('weight_lbs') or '' }}" style="width:80px;"></div>
    <div><label>Headshot (optional)</label><input type="file" name="photo_{{ i }}" accept="image/*" style="max-width:210px;font-size:12px;"></div>
  </div>
  {% for f in p.flagged %}<div class="flag">Pitch #{{ f.pitch_no }} ({{ f.type }}{% if f.velo %}, {{ '%.0f'|format(f.velo) }} mph{% endif %}) &mdash; {{ f.reasons[0] }}<br>
    <select name="fl_{{ f.uid }}" style="margin-left:0;">
      <option value="out" selected>Leave this pitch out</option><option value="keep">Keep it with {{ p.name }}</option>
      {% for q in pitchers if q.csv_name != p.csv_name %}<option value="move:{{ q.csv_name }}">Move to {{ q.name }}</option>{% endfor %}
    </select></div>{% endfor %}
</div>{% endfor %}
<button type="submit">Generate all reports</button></form>
<script>(function(){var s=document.getElementById('myteam');if(!s)return;s.addEventListener('change',function(){document.querySelectorAll('input[data-team]').forEach(function(b){if(b.dataset.team)b.checked=(b.dataset.team===s.value);});var o=document.querySelector('input[name=opponent]'),codes=[].slice.call(s.options).map(function(x){return x.value;}).filter(Boolean),other=codes.filter(function(x){return x!==s.value;});if(o&&other.length===1&&(!o.value||codes.indexOf(o.value)>-1))o.value=other[0];});})();</script>"""


SCOUT_REVIEW_PAGE = BULK_STYLE + """
<title>Scouting upload</title>{% set hero_title = 'Scouting only' %}{% include '_bulk_hero.html' %}
<p>Name the teams in this file. Both teams' hitters and pitchers go into Scouting, private to {{ prog_label }}. Nothing is added to your own dashboards.</p>
<form method="post" action="{{ url_for('intake_bulk_run') }}">
<input type="hidden" name="path" value="{{ path }}"><input type="hidden" name="program" value="{{ prog }}"><input type="hidden" name="session_type" value="Scouting">
{% for code, c in codes %}<div class="card"><div class="row"><div><label>Team code in the file</label><input type="text" name="tcode_{{ loop.index0 }}" value="{{ code }}" readonly style="width:160px;background:#f2f4f3;"></div>
<div><label>Team name</label><input type="text" name="tname_{{ loop.index0 }}" value="{{ pretty(code) }}" required style="width:260px;"></div></div>
<p style="font-size:13px;color:#6b7680;margin:8px 0 0;">{{ c.pitchers }} pitches thrown by this team &middot; {{ c.batters }} swings and takes by its hitters</p></div>{% endfor %}
<button type="submit">Add to Scouting</button></form><p><a href="{{ url_for('intake_bulk') }}">&larr; Back</a></p>"""


def _pretty_team(code):
    s = (code or '').replace('_', ' ').strip()
    return s.upper() if len(s) <= 5 else s.title()


def _target_program():
    """A program coach always uploads to his own program; an admin picks one (default Long Beach State)."""
    if is_admin():
        return request.form.get('program') or 'long_beach_state'
    return my_program()


def _safe_theme_css(prog):
    try:
        return theme.css(theme.for_program(prog))
    except Exception:
        return ''


def _safe_wm(prog):
    try:
        return _wm_url(prog)
    except Exception:
        return None


def _bulk_ctx(prog):
    return {'sources': [x for x in UPLOAD_SOURCES if x[0] == 'trackman'], 'programs': ([('shepherds', store.program_label('shepherds'))] + store.list_programs()) if is_admin() else None, 'prog': prog, 'prog_label': store.program_label(prog), 'theme_css': _safe_theme_css(prog), 'wm_url': _safe_wm(prog), 'nav_hitting': plans.allowed(prog, 'hitting'),
            'opponents': sorted({e_.get('opponent') for e_ in uploadlog.entries(prog) if e_.get('opponent')})}


def _first_upload_done(results, was_first):
    """True when this upload is a new program coach's first and it added at least one pitcher (starts the dashboard tour)."""
    return bool(was_first) and any(o for _, _, o in results)


def _after_upload(results, was_first, prog=None):
    if _first_upload_done(results, was_first):
        store.set_coach_flag(session['coach'], 'uploaded_first', True)
        return redirect(url_for('dashboard') + '?tour=dash&first=1')
    if prog:                                   # straight to the team the file was uploaded to
        return redirect(url_for('team_dashboard', program=prog))
    return redirect(url_for('dashboard'))


def _archive_csv(path, prog):
    """Keeps the original CSV in the repo under data/csv/<program>/<upload date>_<name>.csv, so each team's
    files stay together. Best-effort: a failure never blocks the upload."""
    try:
        import datetime
        base = os.path.basename(path)
        base = base[5:] if base.startswith('bulk_') else base
        safe = re.sub(r'[^A-Za-z0-9._-]+', '_', base)
        with open(path, 'rb') as fh:
            github_sync.put_file(f'data/csv/{prog}/{datetime.date.today().isoformat()}_{safe}', fh.read())
    except Exception as exc:
        print(f'WARNING: could not archive CSV: {exc}')


SESSION_TYPES = ('Bullpen', 'Intrasquad', 'Scrimmage', 'Game', 'Scouting')


def _session_type():
    v = (request.form.get('session_type') or '').strip().title()
    return v if v in SESSION_TYPES else 'Intrasquad'


def _opponent():
    return re.sub(r'\s+', ' ', (request.form.get('opponent') or '').strip())[:60] if _session_type() in ('Scrimmage', 'Game') else ''


@app.route('/intake/bulk', methods=['GET', 'POST'])
@login_required
@upload_required
def intake_bulk():
    if request.method == 'GET':
        _wel = bool(request.args.get('welcome')) or store.needs_first_upload(session.get('coach'))
        return render_template_string(BULK_UPLOAD_PAGE, message=None, welcome=_wel, welcome_name=(current_coach() or {}).get('display_name', ''),
                                      **_bulk_ctx((request.args.get('program') if is_admin() and request.args.get('program') else None) or my_program() or 'long_beach_state'))
    src, f = None, None
    for sid, _l, _n in UPLOAD_SOURCES:
        _f = request.files.get(f'file_{sid}')
        if _f and _f.filename:
            src, f = sid, _f
            break
    if request.form.get('session_type', '') not in SESSION_TYPES:
        return render_template_string(BULK_UPLOAD_PAGE, message='Choose the session type (Bullpen, Intrasquad, Scrimmage or Game) first.', **_bulk_ctx(_target_program()))
    if f is None:
        f = request.files.get('trackman_file')
        src = 'trackman' if f and f.filename else None
    if not f or not f.filename:
        return render_template_string(BULK_UPLOAD_PAGE, message='Choose a CSV file in one of the boxes.', **_bulk_ctx(_target_program()))
    if src not in _SOURCES_READY:
        _lab = {sid: l for sid, l, _n in UPLOAD_SOURCES}[src]
        return render_template_string(BULK_UPLOAD_PAGE, message=f"{_lab} files can't be read yet. Nothing was uploaded. Support is being added.", **_bulk_ctx(_target_program()))
    fname = 'bulk_' + os.path.basename(f.filename)
    path = os.path.join(UPLOAD_DIR, fname)
    f.save(path)
    try:
        if fullswing.is_fullswing(path):          # Full Swing Live-at-Bat export: translate to the row shape the intake reads
            fullswing.convert_file(path)
        prog = _target_program()
        pitchers = pipeline.pitchers_in_trackman(path, program=prog)
    except Exception as exc:
        return render_template_string(BULK_UPLOAD_PAGE, message=f"Couldn't read that file: {exc}", **_bulk_ctx(_target_program()))
    if not pitchers:
        return render_template_string(BULK_UPLOAD_PAGE, message='No pitchers found in that file.', **_bulk_ctx(_target_program()))
    _st = _session_type()
    if _st == 'Scouting':
        if not plans.allowed(prog, 'scouting'):
            return _upgrade('scouting')
        tc = cleanup.scouting_teams(path)
        if len(tc) < 2:
            return render_template_string(BULK_UPLOAD_PAGE, message="That file doesn't name two teams (PitcherTeam / BatterTeam), so it can't be used for scouting. Trackman files do; Full Swing files don't.", **_bulk_ctx(prog))
        return render_template_string(SCOUT_REVIEW_PAGE, codes=sorted(tc.items(), key=lambda kv: -(kv[1]['pitchers'] + kv[1]['batters']))[:2], path=fname, pretty=_pretty_team, **_bulk_ctx(prog))
    my_team, codes = cleanup.guess_my_team(prog, pitchers) if _st in ('Scrimmage', 'Game') else (None, {})
    _others = [k for k in codes if k != my_team]
    _opp = _opponent() or (_others[0] if my_team and len(_others) == 1 else '')
    return render_template_string(BULK_REVIEW_PAGE, pitchers=pitchers, path=fname, session_type=_st, opponent=_opp,
                                  codes=codes if len(codes) >= 2 else {}, my_team=my_team, **_bulk_ctx(prog))


def _scouting_run(path, f):
    prog = _target_program()
    if not prog:
        abort(403)
    if not plans.allowed(prog, 'scouting'):
        return _upgrade('scouting')
    names, i = {}, 0
    while f'tcode_{i}' in f:
        nm = re.sub(r'\s+', ' ', (f.get(f'tname_{i}') or '').strip())[:60]
        if nm:
            names[f[f'tcode_{i}']] = nm
        i += 1
    if len(set(names.values())) < 2:
        return BULK_STYLE + '<h1>Name both teams</h1><div class="card">Each team needs its own name.</div><p><a href="' + url_for('intake_bulk') + '">Back</a></p>'
    with github_sync.batch(f'Scouting upload for {store.program_label(prog)}'):
        _upload_id = uuid.uuid4().hex[:10]
        outings_mod.CURRENT_UPLOAD, outings_mod.CURRENT_SESSION = _upload_id, 'Scouting'
        try:
            n, seen = cleanup.store_scouting_rows(path, prog, names)
        finally:
            outings_mod.CURRENT_UPLOAD = outings_mod.CURRENT_SESSION = None
        if n:
            _archive_csv(path, prog)
            _bn = os.path.basename(path)
            uploadlog.record(session.get('coach') or '', prog, _bn[5:] if _bn.startswith('bulk_') else _bn, 'Trackman · Scouting', n,
                             [p for ps in seen.values() for p in ps], upload_id=_upload_id, opponent=' vs '.join(sorted(set(names.values()))))
            plans.track('upload', session.get('coach') or '', prog, players=0, rows=n)
    if not n:
        return BULK_STYLE + '<h1>Nothing added</h1><div class="card">No pitches with those team names were found.</div><p><a href="' + url_for('intake_bulk') + '">Back</a></p>'
    return redirect(url_for('team_scouting', program=prog))


@app.route('/intake/bulk/run', methods=['GET', 'POST'])
@login_required
@upload_required
def intake_bulk_run():
    if request.method == 'GET':
        return redirect(url_for('intake_bulk'))
    f = request.form
    path = os.path.join(UPLOAD_DIR, os.path.basename(f.get('path', '')))
    if not os.path.exists(path):
        abort(400)
    if _session_type() == 'Scouting':
        return _scouting_run(path, f)
    reassign, drop = {}, set()
    for k, v in f.items():
        if k.startswith('fl_'):
            uid = k[3:]
            if v == 'out':
                drop.add(uid)
            elif v.startswith('move:'):
                reassign[uid] = v[5:]
    prog = _target_program()
    if not prog:
        abort(403)
    specs, i, photos, skipped = [], 0, {}, []
    while f'csv_{i}' in f:
        _ex = store.get_real_player(store.slugify(f.get(f'name_{i}', '').strip()))
        _blocked = bool(_ex) and _ex.get('program', 'shepherds') != prog
        if f.get(f'inc_{i}') and _blocked:
            skipped.append(f.get(f'name_{i}', '').strip())
        if f.get(f'inc_{i}') and not _blocked:
            ft, inch = _num_or_none(f.get(f'ft_{i}')), _num_or_none(f.get(f'in_{i}'))
            gy = f.get(f'grad_{i}', '').strip()
            specs.append({'name': f.get(f'name_{i}', '').strip(), 'school': f.get('school') or None,
                          'grad_year': int(gy) if gy.isdigit() else None, 'throws': f.get(f'throws_{i}'),
                          'height_in': (ft * 12 + (inch or 0)) if ft else None,
                          'weight_lbs': _num_or_none(f.get(f'wt_{i}')), 'exclude_uids': list(drop)})
            ph = request.files.get(f'photo_{i}')
            if ph and ph.filename:
                photos[specs[-1]['name']] = ph
        i += 1
    _new = [s_ for s_ in specs if not store.get_real_player(store.slugify(s_['name']))]
    _ok, _msg = plans.can_add_players(prog, len(_new))
    if not _ok:
        return _upgrade('max_players', _msg)
    _was_first = store.needs_first_upload(session.get('coach'))
    with github_sync.batch(f'Upload to {store.program_label(prog)}'):      # one commit for the whole upload (a commit per file restarted the site mid-request)
        _upload_id = uuid.uuid4().hex[:10]
        _before = set(store.list_players())
        _stype = _session_type()
        if _stype in ('Scrimmage', 'Game') and (request.form.get('my_team') or '').strip():
            cleanup.set_team_code(prog, request.form['my_team'].strip())
        outings_mod.CURRENT_UPLOAD, outings_mod.CURRENT_SESSION, outings_mod.CURRENT_OPPONENT = _upload_id, _stype, _opponent()
        try:
            results = pipeline.process_trackman_bulk(path, specs, live_ab=(_stype != 'Bullpen') or fullswing.is_converted(path), reassign=reassign, program=prog)
            if _stype in ('Scrimmage', 'Game'):          # the opposing pitchers' pitches carry your hitters' at-bats
                cleanup.store_opponent_rows(path, prog, {s_['name'] for s_ in specs}, exclude=drop)
        finally:
            outings_mod.CURRENT_UPLOAD = outings_mod.CURRENT_SESSION = outings_mod.CURRENT_OPPONENT = None
        try:
            _ros = roster_mod.load(prog)
            if _ros and roster_mod.apply_to_players(prog, _ros['players'], store.list_players()):
                store.sync_to_github()
        except Exception as exc:
            print(f'WARNING: roster details not applied: {exc}')
        if any(out for _, _, out in results):
            _archive_csv(path, prog)
            try:
                _n = max(0, sum(1 for _ in open(path, encoding='utf-8', errors='ignore')) - 1)
            except Exception:
                _n = 0
            plans.track('upload', session.get('coach') or '', prog, players=sum(1 for _, _, o in results if o), rows=_n)
            _bn = os.path.basename(path)
            uploadlog.record(session.get('coach') or '', prog, _bn[5:] if _bn.startswith('bulk_') else _bn,
                             ('Full Swing' if fullswing.is_converted(path) else 'Trackman') + ' · ' + _stype + (f' vs {_opponent()}' if _opponent() else ''), _n, [n for n, _, o in results if o],
                             upload_id=_upload_id, opponent=_opponent(), new_players=[s_ for _, s_, o in results if o and s_ not in _before])
        for name, slug, out in results:
            if out and name in photos:
                try:
                    headshots.save(slug, photos[name])
                except Exception as exc:
                    print(f'WARNING: headshot for {name} not saved: {exc}')
    if skipped and not _first_upload_done(results, _was_first):
        return (BULK_STYLE + '<h1>Done</h1><div class="card">Skipped (a player with that name already belongs to another program): <b>' + ', '.join(skipped).replace('<', '') +
                '</b>. Everyone else was added.</div><p><a href="' + home_url() + '">Go to the dashboard</a></p>')
    return _after_upload(results, _was_first, prog)


REVIEW_PAGE = """
<!doctype html><title>Check these pitches</title>
<style>body{font-family:Barlow,Arial,sans-serif;background:#f7f6f2;color:#22303a;max-width:640px;margin:0 auto;padding:28px 16px 60px;}
h1{font-family:Oswald,Arial,sans-serif;} .p{background:#fff;border:1px solid #dcdfdc;border-radius:10px;padding:10px 14px;margin:10px 0;}
.p label{display:block;font-weight:600;} .p small{display:block;color:#9c3a3a;margin:3px 0 0 24px;}
button{margin:8px 8px 0 0;padding:11px 22px;border:none;border-radius:999px;background:#5c97a8;color:#fff;font-weight:600;cursor:pointer;} button.alt{background:#5c97a8;}</style>
<h1>Some pitches under {{ name }} look off</h1>
<p>These may belong to a different pitcher (a mis-tagged name in the export). Checked pitches will be left out of the report.</p>
<form method="post" action="{{ url_for('intake_lbsu_confirm') }}">
  {% for k in ['name','school','grad_year','position_pitch','height_in','weight_lbs','path','live_ab'] %}<input type="hidden" name="{{ k }}" value="{{ {'name':name,'school':school,'grad_year':grad_year,'position_pitch':position_pitch,'height_in':height_in,'weight_lbs':weight_lbs,'path':path,'live_ab':live_ab}[k] }}">{% endfor %}
  {% for f in flagged %}<div class="p"><label><input type="checkbox" name="exclude" value="{{ f.uid }}" checked> Pitch #{{ f.pitch_no }} &middot; {{ f.type }}{% if f.velo %} &middot; {{ '%.1f'|format(f.velo) }} mph{% endif %}{% if f.batter %} &middot; vs {{ f.batter }}{% endif %}</label>
    {% for r in f.reasons %}<small>{{ r }}</small>{% endfor %}</div>{% endfor %}
  <button type="submit">Generate report</button>
</form>
"""


@app.route('/intake/lbsu/confirm', methods=['GET', 'POST'])
@login_required
@upload_required
def intake_lbsu_confirm():
    if request.method == 'GET':
        return redirect(url_for('intake_lbsu'))
    f = request.form
    path = os.path.join(UPLOAD_DIR, os.path.basename(f.get('path', '')))
    if not os.path.exists(path):
        abort(400)
    gy = f.get('grad_year', '').strip()
    slug, out = pipeline.process_trackman_only(
        path, f['name'], f.get('school') or None, int(gy) if gy.isdigit() else None, f.get('position_pitch') or None,
        _num_or_none(f.get('height_in')), _num_or_none(f.get('weight_lbs')), exclude_uids=f.getlist('exclude'), live_ab=bool(f.get('live_ab')))
    if not out:
        return "That name wasn't found in the file.", 400
    return redirect(url_for('dashboard'))


@app.route('/intake/lbsu', methods=['GET', 'POST'])
@login_required
@upload_required
def intake_lbsu():
    return redirect(url_for('intake_bulk'))


# --- comps override API (coach-only) -------------------------------------

@app.route('/api/comps/search')
@admin_required
def api_comps_search():
    q = request.args.get('q', '')
    if len(q) < 2:
        return jsonify([])
    return jsonify(mlb_lookup.search(q))


@app.route('/api/comps/<slug>/<role>/<int:index>', methods=['POST'])
@admin_required
def api_comps_override(slug, role, index):
    data = request.get_json(force=True)
    name = data.get('name')
    position = data.get('position')
    if not name:
        return jsonify({'error': 'name required'}), 400
    store.override_comp(slug, role, index, name, position)
    pipeline.regenerate_role(slug, role)
    return jsonify({'ok': True})


@app.route('/api/comps/<slug>/<role>/<int:index>/unlock', methods=['POST'])
@admin_required
def api_comps_unlock(slug, role, index):
    store.unlock_comp(slug, role, index)
    pipeline.regenerate_role(slug, role)
    return jsonify({'ok': True})


# --- comps edit page (coach-only, simple form -- the published report card
#     itself stays untouched/pixel-perfect; this is a separate admin view) --

EDIT_COMPS_PAGE = """
<!doctype html><title>Edit Comps &mdash; {{ player.name }}</title>
<style>
  body{font-family:Barlow,Arial,sans-serif;background:#f7f6f2;color:#22303a;max-width:560px;margin:0 auto;padding:28px 16px 60px;}
  h1{font-family:Oswald,Arial,sans-serif;font-size:22px;}
  h2{font-family:Oswald,Arial,sans-serif;font-size:15px;color:#6b7680;text-transform:uppercase;letter-spacing:.06em;margin-top:28px;}
  .slot{display:flex;align-items:center;gap:8px;background:#fff;border:1px solid #dcdfdc;border-radius:8px;padding:10px 12px;margin-bottom:8px;}
  .slot .info{flex:1;}
  .slot .nm{font-weight:600;}
  .slot .tag{font-size:11px;padding:2px 7px;border-radius:999px;margin-left:6px;}
  .tag.auto{background:#e3e8ea;color:#22303a;}
  .tag.locked{background:#dce8f0;color:#355;}
  form.inline{display:flex;gap:6px;}
  input[type=text]{padding:6px 8px;border:1px solid #dcdfdc;border-radius:6px;width:150px;}
  button{padding:6px 12px;border:none;border-radius:999px;background:#5c97a8;color:#fff;font-weight:600;cursor:pointer;font-size:12.5px;}
  button.unlock{background:#5c97a8;}
  .top a{color:#6b7680;font-size:13px;}
</style>
<p class="top"><a href="{{ url_for('intake') }}">&larr; Back to intake</a></p>
<h1>{{ player.name }} &mdash; Players to Watch</h1>
{% if player.roles.get('hit') %}
<h2>60 Time / Sprint Speed</h2>
<form class="inline" method="post" action="{{ url_for('edit_sixty', slug=slug) }}">
  <input type="number" step="0.01" min="0" name="sixty_yd_time" placeholder="e.g. 6.85" value="{{ player.sixty_yd_time or '' }}">
  <button type="submit">Save</button>
</form>
<p style="font-size:12px;color:#6b7680;margin:6px 0 0;">Saving updates the Running panel on the hitting report immediately -- Sprint Speed (ft/s) and both percentiles are recalculated from this time.</p>
{% endif %}
{% for role, label in [('pitch','Pitching'), ('hit','Hitting')] %}
  {% if player.roles.get(role) %}
  <h2>{{ label }}</h2>
  {% for c in player.comps.get(role, []) %}
    <div class="slot">
      <div class="info">
        <span class="nm">{{ c.name or '(empty)' }}</span>
        <span class="tag {{ c.source }}">{{ c.source }}</span>
        {% if c.position %}<div style="font-size:12px;color:#6b7680;">{{ c.position }}</div>{% endif %}
      </div>
      <form class="inline" method="post" action="{{ url_for('edit_comps_override', slug=slug, role=role, index=loop.index0) }}">
        <input type="text" name="name" placeholder="Replace with...">
        <button type="submit">Save</button>
      </form>
      {% if c.source == 'locked' %}
      <form method="post" action="{{ url_for('edit_comps_unlock', slug=slug, role=role, index=loop.index0) }}">
        <button class="unlock" type="submit">Unlock</button>
      </form>
      {% endif %}
    </div>
  {% endfor %}
  {% endif %}
{% endfor %}
"""


@app.route('/edit/<slug>')
@admin_required
def edit_comps(slug):
    player = store.get_player(slug)
    if not player:
        abort(404)
    return render_template_string(EDIT_COMPS_PAGE, player=player, slug=slug)


@app.route('/edit/<slug>/<role>/<int:index>/override', methods=['POST'])
@admin_required
def edit_comps_override(slug, role, index):
    name = request.form.get('name', '').strip()
    if name:
        store.override_comp(slug, role, index, name)
        pipeline.regenerate_role(slug, role)
    return redirect(url_for('edit_comps', slug=slug))


@app.route('/edit/<slug>/<role>/<int:index>/unlock', methods=['POST'])
@admin_required
def edit_comps_unlock(slug, role, index):
    store.unlock_comp(slug, role, index)
    pipeline.regenerate_role(slug, role)
    return redirect(url_for('edit_comps', slug=slug))


@app.route('/edit/<slug>/sixty', methods=['POST'])
@admin_required
def edit_sixty(slug):
    raw = request.form.get('sixty_yd_time', '').strip()
    try:
        seconds = float(raw) if raw else None
    except ValueError:
        seconds = None
    if seconds is not None:
        store.set_sixty_yd_time(slug, seconds)
        pipeline.regenerate_role(slug, 'hit')
    return redirect(url_for('edit_comps', slug=slug))


store.lowercase_usernames()          # one-time tidy: every login name is lowercase
import backup as _backup
_backup.start()


if __name__ == '__main__':
    # Local dev only -- on Render (or any real host) gunicorn imports `app`
    # directly per the Procfile below and this block never runs, so debug
    # mode here never reaches a public deployment.
    port = int(os.environ.get('PORT', 5050))
    app.run(host='0.0.0.0', port=port, debug=True)
