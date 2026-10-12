import functools
import os
import re
from flask import Flask, Response, render_template, request, session, redirect, url_for, render_template_string, send_file, jsonify, abort

import store
import pipeline
import extract as e_mod
import mlb_lookup
import headshots
import overview

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-me')
if app.secret_key == 'dev-only-change-me' and not app.debug:
    print('WARNING: SECRET_KEY env var is not set -- using the insecure default. '
          'Set a real SECRET_KEY in your host\'s environment variables before sharing this URL.')

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'uploads')
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
    if c and c.get('role', 'admin') != 'admin':          # a signed-in program coach sees only his own program
        return can_manage(slug)
    if p.get('program', 'shepherds') in store.PUBLIC_PROGRAMS:
        return True
    return can_manage(slug)


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
            return redirect(request.args.get('next') or url_for('dashboard'))
        error = 'Incorrect username or password.'
    return render_template_string(LOGIN_PAGE, error=error)


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


@app.route('/')
def dashboard():
    if not session.get('coach'):
        return redirect(url_for('login'))
    players = store.list_players()
    shep, priv = [], {}
    for slug, p in players.items():
        if not can_view(slug):
            continue
        p = dict(p)
        _b = pipeline.school_badge_file(p.get('school'), p.get('program'))
        p['badge'] = {'file': _b[0], 'bg': _b[1]} if _b else None
        p['can_edit'] = can_manage(slug)
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
    groups = [(store.program_label(k), sorted(v, key=key)) for k, v in sorted(priv.items(), key=lambda kv: store.program_label(kv[0]))]
    groups.append(('Shepherds', sorted(shep, key=key)))
    return render_template('dashboard.html', groups=groups, is_coach=bool(session.get('coach')), is_admin=is_admin(), coach_key=session.get('coach') or '')


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
    last, first = _split_name(bio['name'])
    has_photo = headshots.exists(slug)
    _b = pipeline.school_badge_file(bio.get('school'), bio.get('program'))
    badge = {'file': _b[0], 'bg': _b[1]} if _b else None
    css = re.sub(r'@font-face\s*\{[^}]*\}', '', pipeline.CSS)
    return render_template('player_overview.html', b=b, bio=bio, slug=slug, css=css, has_photo=has_photo, badge=badge,
                           photo_v=int(os.path.getmtime(headshots.path(slug))) if has_photo else 0,
                           initials=(first[:1] + last[:1]).upper(), pos=_player_pos(bio), is_coach=bool(session.get('coach')), can_edit=can_manage(slug))


@app.route('/report/<slug>/outing/<date>')
def view_outing(slug, date):
    if not session.get('coach'):
        return redirect(url_for('login', next=request.path))
    bio = store.get_player(slug)
    html = overview.outing_report_html(slug, date, bio) if bio and can_view(slug) else None
    if not html:
        abort(404)
    if request.args.get('download'):
        fname = re.sub(r'[^A-Za-z0-9]+', '_', bio['name']).strip('_') + f'_{date}_outing_report.html'
        return Response(html, mimetype='text/html', headers={'Content-Disposition': f'attachment; filename="{fname}"'})
    return html


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


@app.route('/player/<slug>/edit', methods=['GET', 'POST'])
@login_required
def edit_profile(slug):
    if not can_manage(slug):
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
    if not can_manage(slug):
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
<title>Upload a .CSV</title><h1>Upload a .CSV</h1>
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
  <label style="font-weight:700;font-size:16px;"><input type="checkbox" name="inc_{{ i }}" value="1" checked> <input type="text" name="name_{{ i }}" value="{{ p.name }}" style="font-weight:600;"> {{ p.throws }}HP &middot; {{ p.n }} pitches{% if p.known %}<span class="tag">already on roster</span>{% endif %}</label>
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


@app.route('/intake/bulk', methods=['GET', 'POST'])
@login_required
def intake_bulk():
    if request.method == 'GET':
        return render_template_string(BULK_UPLOAD_PAGE, message=None, **_bulk_ctx(my_program() or 'long_beach_state'))
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
        _ex = store.get_player(store.slugify(f.get(f'name_{i}', '').strip()))
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
    results = pipeline.process_trackman_bulk(path, specs, live_ab=bool(f.get('live_ab')), reassign=reassign, program=prog)
    for name, slug, out in results:
        if out and name in photos:
            try:
                headshots.save(slug, photos[name])
            except Exception as exc:
                print(f'WARNING: headshot for {name} not saved: {exc}')
    if skipped:
        return (BULK_STYLE + '<h1>Done</h1><div class="card">Skipped (a player with that name already belongs to another program): <b>' + ', '.join(skipped).replace('<', '') +
                '</b>. Everyone else was added.</div><p><a href="' + url_for('dashboard') + '">Go to the dashboard</a></p>')
    return redirect(url_for('dashboard'))


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
