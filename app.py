import functools
import json
import os
import re
from flask import Flask, Response, render_template, request, session, redirect, url_for, render_template_string, send_file, jsonify, abort

import github_sync
import plans
import store
import pipeline
import extract as e_mod
import mlb_lookup
import headshots
import hitting
import team
import roster as roster_mod
import glossary
import overview

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
    p = store.get_player(slug)
    return bool(p) and p.get('program', 'shepherds') == c.get('program')


def can_view(slug):
    """Public programs (Shepherds) are open to everyone; every other program is private to its own coaches and admins."""
    p = store.get_player(slug)
    if not p:
        return False
    c = current_coach()
    if p.get('program') in store.DEMO_PROGRAMS:          # the bundled sample program is for admins only
        return is_admin()
    if c and c.get('role', 'admin') != 'admin':          # a signed-in program coach sees only his own program
        return can_manage(slug)
    if p.get('program', 'shepherds') in store.PUBLIC_PROGRAMS:
        return True
    return can_manage(slug)


def _upgrade(feature, detail=''):
    """Shown when a plan doesn't include something (only possible once plan enforcement is switched on)."""
    name = plans.FEATURE_NAMES.get(feature, feature)
    return (BULK_STYLE + f'<h1>{name}</h1><div class="card">{detail or "This is not included in your current plan."} '
            'Contact the ShepSavant admin to upgrade.</div><p><a href="' + url_for('dashboard') + '">Back to the dashboard</a></p>'), 402


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
</form>
"""


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if store.verify_coach(username, password):
            session['coach'] = username
            plans.track('login', username, (store.list_coaches().get(username) or {}).get('program'))
            if not request.args.get('next') and store.needs_first_upload(username):
                return redirect(url_for('intake_bulk') + '?welcome=1')
            return redirect(request.args.get('next') or url_for('dashboard'))
        error = 'Incorrect username or password.'
    return render_template_string(LOGIN_PAGE, error=error)


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
<div class="top"><a class="back" href="{{ url_for('dashboard') }}">&larr; Back to dashboard</a>{% include '_usermenu.html' %}</div>
<div class="wrap"><h1>Account Settings</h1>
  <div class="card"><div class="id">{% if me.badge %}<span class="um-av big" style="background:{{ me.badge.bg }}"><img src="{{ url_for('school_logo', fname=me.badge.file) }}" alt=""></span>{% else %}<span class="um-av big"><b>{{ me.initials }}</b></span>{% endif %}
    <div class="meta"><b>{{ me.name }}</b><span>{{ me.label or ('Administrator' if me.is_admin else '') }}{% if me.is_admin and me.label %} &middot; Administrator{% endif %}</span></div></div>
    <div class="ro">Your logo comes from your program. Username: <b>{{ me.key }}</b></div>{% if plan_line %}<div class="ro">Plan: <b>{{ plan_line }}</b></div>{% endif %}</div>
  <div class="card"><h2>Profile</h2>
    {% if name_msg %}<div class="msg {{ 'ok' if name_ok else 'err' }}">{{ name_msg }}</div>{% endif %}
    <form method="post"><input type="hidden" name="form" value="name">
      <label>Display name</label><input type="text" name="display_name" value="{{ me.name }}" maxlength="60" required>
      <button type="submit">Save name</button></form></div>
  <div class="card"><h2>Change password</h2>
    {% if pw_msg %}<div class="msg {{ 'ok' if pw_ok else 'err' }}">{{ pw_msg }}</div>{% endif %}
    <form method="post"><input type="hidden" name="form" value="password">
      <label>Current password</label><input type="password" name="current" required>
      <label>New password (8+ characters)</label><input type="password" name="new" required minlength="8">
      <label>Confirm new password</label><input type="password" name="confirm" required minlength="8">
      <button type="submit">Update password</button></form></div>
</div></body></html>
"""


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
                   'badge': {'file': _b[0], 'bg': _b[1]} if _b else None}}


_MENU_PAGES = {'edit_profile', 'admin_status', 'admin_coaches', 'view_report', 'intake', 'intake_bulk', 'intake_bulk_run',
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
            if True:
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
    shep, priv = [], {}
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
        if p.get('program', 'shepherds') not in store.ADMIN_ONLY_PROGRAMS:
            priv.setdefault(p['program'], []).append((slug, p, url_for('player_overview', slug=slug), last, first, pos))
        else:
            links = []
            if (p.get('roles') or {}).get('pitch'):
                links.append(('Pitching', url_for('view_report', slug=slug, role='pitching')))
            if (p.get('roles') or {}).get('hit'):
                links.append(('Hitting', url_for('view_report', slug=slug, role='hitting')))
            p['shep_links'] = links
            shep.append((slug, p, links[0][1] if links else '#', last, first, pos))
    key = lambda t: (t[3].lower(), t[4].lower())
    groups = [(k, store.program_label(k), sorted(v, key=key)) for k, v in sorted(priv.items(), key=lambda kv: store.program_label(kv[0]))]
    groups.append(('shepherds', 'Shepherds', sorted(shep, key=key)))
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


@app.route('/')
def dashboard():
    if not session.get('coach'):
        return redirect(url_for('login'))
    groups = _build_groups()
    if is_admin():
        return render_template('dashboard.html', mode='teams', tiles=_team_tiles(groups), groups=[], team_label=None,
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


def _team_players_page(program, page_title):
    groups = [g for g in _build_groups() if g[0] == program]
    if not groups:
        abort(404)
    return render_template('dashboard.html', mode='players', groups=[(l, p) for _, l, p in groups], team_label=groups[0][1], tiles=[],
                           is_coach=True, is_admin=is_admin(), coach_key=session.get('coach') or '', tour_next=_tour_next_player(groups),
                           team_program=program, page_title=page_title)


@app.route('/team/<program>')
@login_required
def team_view(program):
    _team_ok(program)
    return redirect(url_for('team_dashboard', program=program))


@app.route('/team/<program>/pitchers')
@login_required
def team_pitchers(program):
    _team_ok(program)
    return _team_players_page(program, 'Pitcher Dashboard')


@app.route('/team/<program>/hitters')
@admin_required
def team_hitters(program):
    rows = [r for r in hitting.list_hitters() if r['program'] == program]
    if not rows:
        abort(404)
    rows.sort(key=lambda r: r['name'].split()[-1].lower())
    return render_template('team_hitters.html', rows=rows, program=program, team_label=store.program_label(program))


@app.route('/team/<program>/dashboard')
@login_required
def team_dashboard(program):
    _team_ok(program)
    cfg = team.load(program)
    P = team.pitching_data(program)
    H = team.hitting_data(program, True) if is_admin() else None
    def half(side, D, ids):
        tiles = [D['tiles'][i] for i in ids if i in D['tiles']]
        return {'side': side, 'D': D, 'tiles': tiles, 'goals': team.goal_rows(program, side, D['tiles']),
                'picker': team.stat_picker(side, ids), 'metrics': team.goal_metric_options(side)}
    halves = [half('pitching', P, cfg['pitching_stats'])]
    if H is not None:
        halves.append(half('hitting', H, cfg['hitting_stats']))
    sessions = sorted(set(P['sessions']) | set(H['sessions'] if H else []))
    return render_template('team_dashboard.html', program=program, team_label=store.program_label(program), halves=halves,
                           last_session=sessions[-1] if sessions else None, is_coach=True, is_admin=is_admin(),
                           coach_key=session.get('coach') or '')


@app.route('/team/<program>/customize', methods=['POST'])
@login_required
def team_customize(program):
    _team_ok(program)
    side = 'hitting' if request.form.get('side') == 'hitting' else 'pitching'
    if side == 'hitting' and not is_admin():
        abort(403)
    team.set_stats(program, side, request.form.getlist('stat'))
    return redirect(url_for('team_dashboard', program=program) + f'#{side}')


@app.route('/team/<program>/goals', methods=['POST'])
@login_required
def team_goals(program):
    _team_ok(program)
    f = request.form
    side = 'hitting' if f.get('side') == 'hitting' else 'pitching'
    if side == 'hitting' and not is_admin():
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


@app.route('/player/<slug>')
def player_overview(slug):
    if not session.get('coach'):
        return redirect(url_for('login', next=request.path))
    bio = store.get_player(slug)
    if not bio or not can_view(slug):
        abort(404)
    b = overview.build(slug, bio)
    if not b:
        abort(404)
    if not store.is_demo(slug):
        _track('view', slug=slug)
    last, first = _split_name(bio['name'])
    has_photo = headshots.exists(slug)
    _b = pipeline.school_badge_file(bio.get('school'), bio.get('program'))
    badge = {'file': _b[0], 'bg': _b[1]} if _b else None
    css = re.sub(r'@font-face\s*\{[^}]*\}', '', pipeline.CSS)
    return render_template('player_overview.html', b=b, bio=bio, slug=slug, css=css, has_photo=has_photo, badge=badge,
                           photo_v=int(os.path.getmtime(headshots.path(slug))) if has_photo else 0,
                           initials=(first[:1] + last[:1]).upper(), pos=_player_pos(bio), is_coach=bool(session.get('coach')), can_edit=can_manage(slug), is_demo=store.is_demo(slug),
                           tour_next=(url_for('view_outing', slug=slug, date=b['log'][0]['id']) + '?tour=report') if b.get('log') else '')


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
@admin_required
def beta_hitter(key):
    h = hitting.hitter_profile(key)
    if not h:
        abort(404)
    css = re.sub(r'@font-face\s*\{[^}]*\}', '', pipeline.CSS)
    return render_template('beta_hitter.html', h=h, css=css)



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
def roster_page():
    prog = _roster_program()
    if not prog:
        abort(403)
    if not plans.allowed(prog, 'roster_upload'):
        return _upgrade('roster_upload')
    ctx = {'programs': store.list_programs() if is_admin() else None, 'prog': prog, 'prog_label': store.program_label(prog),
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
{% for u, c in coaches.items() %}<div class="card"><div><b>{{ c.display_name }}</b> <small>({{ u }})</small><br><small>{{ 'Admin -- full access' if c.get('role','admin') == 'admin' else (c.get('program_label') or c.get('program')) ~ ' coach -- only sees and edits their own program' }}</small></div>
{% if u != me %}<form method="post" action="{{ url_for('admin_coach_delete', username=u) }}" onsubmit="return confirm('Remove this login?');" style="margin:0;"><button class="del">Remove</button></form>{% endif %}</div>{% endfor %}
<h2 style="font-family:Oswald,Arial,sans-serif;margin-top:28px;">Add a login <small>(or reset a password: reuse the username)</small></h2>
<form method="post"><label>Username</label><input name="username" required autocomplete="off"><label>Display name</label><input name="display_name" required>
<label>Password</label><input name="password" type="text" required autocomplete="off" minlength="8">
<label>Access</label><select name="role"><option value="program">Program coach (sees only their own program)</option><option value="admin">Admin (everything)</option></select>
<label>Program / school <small>(program coaches only -- coaches with the same name share players)</small></label><input name="program_label" list="progs" placeholder="e.g. Long Beach State"><datalist id="progs">{% for s, l in programs %}<option value="{{ l }}">{% endfor %}</datalist>
<button type="submit">Save login</button></form></body></html>"""


STATUS_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Save Status</title>
<style>body{font-family:Barlow,Arial,sans-serif;background:#f7f6f2;color:#22303a;max-width:680px;margin:0 auto;padding:24px 16px 60px;} h1{font-family:Oswald,Arial,sans-serif;} .card{background:#fff;border-radius:12px;padding:14px 16px;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,.08);}
.ok{color:#2f7a4a;font-weight:700;} .bad{color:#b03a3a;font-weight:700;} small{color:#6b7680;} button{padding:10px 20px;border:none;border-radius:999px;background:#5c97a8;color:#fff;font-weight:600;cursor:pointer;} a{color:#5c97a8;font-size:13px;} code{background:#eef1f1;padding:1px 5px;border-radius:4px;}</style></head><body>
<a href="{{ url_for('dashboard') }}">&larr; Dashboard</a><h1>Save Status</h1>
<div class="card">Automatic GitHub saving: {% if on %}<span class="ok">ON</span> <small>repo <code>{{ repo }}</code>, branch <code>{{ branch }}</code></small>{% else %}<span class="bad">OFF</span><br><small>The Render environment variables <code>SHEPSAVANT_GITHUB_TOKEN</code> and <code>SHEPSAVANT_GITHUB_REPO</code> are missing, so edits only last until the next deploy.</small>{% endif %}</div>
<form method="post" action="{{ url_for('admin_status_test') }}"><button>Test save now</button></form>
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


@app.route('/admin/status')
@admin_required
def admin_status():
    import github_sync
    return render_template_string(STATUS_PAGE, on=github_sync.enabled(), repo=github_sync.GITHUB_REPO, branch=github_sync.GITHUB_BRANCH, log=github_sync.LOG)


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
        u = re.sub(r'[^A-Za-z0-9_.-]', '', f.get('username', '').strip())
        if not u or len(f.get('password', '')) < 8 or not f.get('display_name', '').strip():
            msg, err = 'Username, name and a password of at least 8 characters are required.', True
        else:
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
def delete_player_route(slug):
    if not can_manage(slug) or store.is_demo(slug):
        abort(403)
    if not store.delete_player(slug):
        abort(404)
    return redirect(url_for('dashboard'))


@app.route('/player/<slug>/rename', methods=['POST'])
@login_required
def rename_player_route(slug):
    if not can_manage(slug):
        abort(403)
    new_slug, err = store.rename_player(slug, request.form.get('name', ''))
    if err:
        return err, 400
    return redirect(url_for('dashboard'))


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
<p style="margin-top:10px;"><a href="{{ url_for('dashboard') }}">&larr; View the public dashboard</a></p>
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
<p style="margin-top:10px;"><a href="{{ url_for('dashboard') }}">&larr; View the public dashboard</a></p>
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
<title>Upload a .CSV</title>{% if welcome %}<div class="card" style="border-left:5px solid #5c97a8;"><h2 style="margin:0 0 6px;font-family:Oswald,Arial,sans-serif;">Welcome{% if welcome_name %}, {{ welcome_name }}{% endif %}!</h2>
<p style="margin:0 0 8px;">Let's start by adding your first Trackman session. It takes about a minute.</p>
<ol style="margin:0;padding-left:20px;line-height:1.6;"><li>Export a session from Trackman as a <b>CSV</b>.</li><li>Choose that file below and tap <b>Read file</b>.</li><li>On the next screen, confirm each pitcher and add class year, height and weight if you have them. Then tap <b>Generate all reports</b>.</li></ol>
<p style="margin:8px 0 0;color:#6b7680;font-size:14px;">Right after, we'll give you a quick tour of your player dashboard and outing reports.</p></div>{% endif %}<h1>Upload a .CSV</h1>
<p>Upload one Trackman CSV with any number of pitchers{% if prog_label %} for {{ prog_label }}{% endif %}. Everyone in the file is picked up automatically.</p>
{% if message %}<div class="card" style="color:#9c3a3a;">{{ message }}</div>{% endif %}
<form method="post" enctype="multipart/form-data">{% if programs %}<p><label style="font-weight:600;">Program: <select name="program">{% for s, l in programs %}<option value="{{ s }}" {{ 'selected' if s == prog }}>{{ l }}</option>{% endfor %}</select></label></p>{% endif %}<input type="file" name="trackman_file" accept=".csv" required><br><button type="submit">Read file</button></form>
<p><a href="{{ url_for('dashboard') }}">&larr; Dashboard</a></p>"""

BULK_REVIEW_PAGE = BULK_STYLE + """
<title>Review Pitchers</title><h1>Review pitchers</h1>
<p>{{ pitchers|length }} pitchers found. Fill in height/weight for the arm-angle badge (optional), uncheck anyone to skip, and review any flagged pitches.</p>
<form method="post" enctype="multipart/form-data" action="{{ url_for('intake_bulk_run') }}">
<input type="hidden" name="path" value="{{ path }}"><input type="hidden" name="program" value="{{ prog }}">
<label style="font-weight:600;"><input type="checkbox" name="live_ab" value="1"> Game / Live AB session (adds the Outing Summary; leave unchecked for bullpens)</label>
<div class="row" style="margin-top:10px;"><div><label>School</label><input type="text" name="school" value="{{ prog_label }}"></div></div>
{% for p in pitchers %}{% set i = loop.index0 %}
<div class="card">
  <label style="font-weight:700;font-size:16px;"><input type="checkbox" name="inc_{{ i }}" value="1" {{ '' if p.on_roster is sameas false else 'checked' }}> <input type="text" name="name_{{ i }}" value="{{ p.name }}" style="font-weight:600;"> {{ p.throws }}HP &middot; {{ p.n }} pitches{% if p.known %}<span class="tag">already on roster</span>{% endif %}{% if p.on_roster is sameas true %}<span class="tag" style="background:#e4f2ea;color:#2a7a4b;">on team roster</span>{% elif p.on_roster is sameas false %}<span class="tag" style="background:#fbf0d9;color:#8a6212;">not on team roster</span>{% endif %}</label>
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
<button type="submit">Generate all reports</button></form>"""


def _target_program():
    """A program coach always uploads to his own program; an admin picks one (default Long Beach State)."""
    if is_admin():
        return request.form.get('program') or 'long_beach_state'
    return my_program()


def _bulk_ctx(prog):
    return {'programs': store.list_programs() if is_admin() else None, 'prog': prog, 'prog_label': store.program_label(prog)}


def _first_upload_done(results, was_first):
    """True when this upload is a new program coach's first and it added at least one pitcher (starts the dashboard tour)."""
    return bool(was_first) and any(o for _, _, o in results)


def _after_upload(results, was_first):
    if _first_upload_done(results, was_first):
        store.set_coach_flag(session['coach'], 'uploaded_first', True)
        return redirect(url_for('dashboard') + '?tour=dash&first=1')
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


@app.route('/intake/bulk', methods=['GET', 'POST'])
@login_required
def intake_bulk():
    if request.method == 'GET':
        _wel = bool(request.args.get('welcome')) or store.needs_first_upload(session.get('coach'))
        return render_template_string(BULK_UPLOAD_PAGE, message=None, welcome=_wel, welcome_name=(current_coach() or {}).get('display_name', ''),
                                      **_bulk_ctx(my_program() or 'long_beach_state'))
    f = request.files.get('trackman_file')
    if not f or not f.filename:
        return render_template_string(BULK_UPLOAD_PAGE, message='Choose a Trackman CSV.', **_bulk_ctx(_target_program()))
    fname = 'bulk_' + os.path.basename(f.filename)
    path = os.path.join(UPLOAD_DIR, fname)
    f.save(path)
    try:
        prog = _target_program()
        pitchers = pipeline.pitchers_in_trackman(path, program=prog)
    except Exception as exc:
        return render_template_string(BULK_UPLOAD_PAGE, message=f"Couldn't read that file: {exc}", **_bulk_ctx(_target_program()))
    if not pitchers:
        return render_template_string(BULK_UPLOAD_PAGE, message='No pitchers found in that file.', **_bulk_ctx(_target_program()))
    return render_template_string(BULK_REVIEW_PAGE, pitchers=pitchers, path=fname, **_bulk_ctx(prog))


@app.route('/intake/bulk/run', methods=['GET', 'POST'])
@login_required
def intake_bulk_run():
    if request.method == 'GET':
        return redirect(url_for('intake_bulk'))
    f = request.form
    path = os.path.join(UPLOAD_DIR, os.path.basename(f.get('path', '')))
    if not os.path.exists(path):
        abort(400)
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
    results = pipeline.process_trackman_bulk(path, specs, live_ab=bool(f.get('live_ab')), reassign=reassign, program=prog)
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
    for name, slug, out in results:
        if out and name in photos:
            try:
                headshots.save(slug, photos[name])
            except Exception as exc:
                print(f'WARNING: headshot for {name} not saved: {exc}')
    if skipped and not _first_upload_done(results, _was_first):
        return (BULK_STYLE + '<h1>Done</h1><div class="card">Skipped (a player with that name already belongs to another program): <b>' + ', '.join(skipped).replace('<', '') +
                '</b>. Everyone else was added.</div><p><a href="' + url_for('dashboard') + '">Go to the dashboard</a></p>')
    return _after_upload(results, _was_first)


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
def intake_lbsu():
    return redirect(url_for('intake_bulk'))


def _intake_lbsu_legacy():
    message, ok = None, True
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        school = request.form.get('school', '').strip() or None
        grad_year = request.form.get('grad_year', '').strip()
        grad_year = int(grad_year) if grad_year.isdigit() else None
        position_pitch = request.form.get('position_pitch', '').strip() or None
        try:
            ft = float(request.form.get('height_ft', '') or 0)
            inch = float(request.form.get('height_in', '') or 0)
            height_in = ft * 12 + inch if ft else None
        except ValueError:
            height_in = None
        weight_lbs = _num_or_none(request.form.get('weight_lbs'))

        tm_f = request.files.get('trackman_file')
        if not name or not tm_f or not tm_f.filename:
            message, ok = 'Name and a Trackman CSV are required.', False
        else:
            trackman_path = os.path.join(UPLOAD_DIR, f'{store.slugify(name)}_trackman_{tm_f.filename}')
            tm_f.save(trackman_path)
            try:
                flagged = e_mod.detect_anomalies(e_mod.load_trackman_rows(trackman_path), name)
                if flagged:
                    return render_template_string(REVIEW_PAGE, flagged=flagged, name=name, school=school or '', grad_year=grad_year or '',
                                                  position_pitch=position_pitch or '', height_in=height_in or '', weight_lbs=weight_lbs or '',
                                                  path=os.path.basename(trackman_path), live_ab=request.form.get('live_ab', ''))
                slug, out = pipeline.process_trackman_only(trackman_path, name, school, grad_year, position_pitch, height_in, weight_lbs, live_ab=bool(request.form.get('live_ab')))
                if out:
                    message = f'Generated a Trackman report for {name}. View it on the dashboard below.'
                else:
                    message, ok = (f"{name} wasn't found in that Trackman file -- check the name matches "
                                    f"exactly (e.g. \"Last, First\" as it appears in the CSV's Pitcher column)."), False
            except Exception as exc:
                message, ok = f'Something went wrong processing that file: {exc}', False

    return render_template_string(LBSU_INTAKE_PAGE, message=message, ok=ok, coach=store.coach_display_name(session['coach']))


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


if __name__ == '__main__':
    # Local dev only -- on Render (or any real host) gunicorn imports `app`
    # directly per the Procfile below and this block never runs, so debug
    # mode here never reaches a public deployment.
    port = int(os.environ.get('PORT', 5050))
    app.run(host='0.0.0.0', port=port, debug=True)
