import functools
import os
from flask import Flask, request, session, redirect, url_for, render_template_string, send_file, jsonify, abort

import store
import pipeline
import mlb_lookup

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
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


LOGIN_PAGE = """
<!doctype html><title>Coach Login</title>
<style>
  body{font-family:Barlow,Arial,sans-serif;background:#f3ebdd;color:#6f4f2f;display:flex;
       align-items:center;justify-content:center;height:100vh;margin:0;}
  form{background:#fff;border:1px solid #e1d6c2;border-radius:12px;padding:28px 26px;width:280px;}
  h1{font-size:18px;margin:0 0 16px;}
  input{width:100%;padding:9px 10px;margin-bottom:10px;border:1px solid #e1d6c2;border-radius:7px;box-sizing:border-box;}
  button{width:100%;padding:10px;border:none;border-radius:999px;background:#5c84a6;color:#fff;font-weight:600;cursor:pointer;}
  .error{color:#b33;font-size:13px;margin-bottom:10px;}
</style>
<form method="post">
  <h1>Shepherds Player Reports &mdash; Coach Login</h1>
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
            return redirect(request.args.get('next') or url_for('intake'))
        error = 'Incorrect username or password.'
    return render_template_string(LOGIN_PAGE, error=error)


@app.route('/logout')
def logout():
    session.pop('coach', None)
    return redirect(url_for('login'))


# --- dashboard (public -- players view this, no login needed) -----------

DASHBOARD_PAGE = """
<!doctype html><title>Player Reports</title>
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=Barlow:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{ --cream:#f3ebdd; --tan:#aa8b68; --brown:#6f4f2f; --blue-strong:#5c84a6; --border:#e1d6c2; --muted:#8a7557; }
  *{box-sizing:border-box;}
  body{background:var(--cream);color:var(--brown);font-family:'Barlow',sans-serif;margin:0;padding-bottom:40px;}
  .hero{background:var(--tan);padding:30px 16px 26px;}
  .hero-wrap,.wrap{max-width:720px;margin:0 auto;}
  .eyebrow{font-family:'Oswald',sans-serif;font-weight:600;font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--cream);opacity:.85;margin:0 0 6px;}
  h1{font-family:'Oswald',sans-serif;font-weight:700;font-size:32px;margin:0 0 8px;color:var(--cream);}
  .sub{color:var(--cream);opacity:.9;font-size:14.5px;margin:0;}
  .wrap{padding:24px 16px 0;}
  .roster{display:flex;flex-direction:column;gap:10px;}
  .card{background:#fff;border:1px solid var(--border);border-radius:10px;padding:14px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;}
  .name{font-family:'Oswald',sans-serif;font-weight:600;font-size:17px;}
  .meta{font-size:12.5px;color:var(--muted);margin-top:2px;}
  .links a{font-family:'Barlow',sans-serif;font-weight:600;font-size:13.5px;text-decoration:none;color:#fff;background:var(--blue-strong);border-radius:999px;padding:7px 14px;margin-left:6px;}
  .coachlink{display:block;text-align:right;margin:14px 16px 0;font-size:12.5px;}
  .coachlink a{color:var(--muted);}
</style>
<div class="coachlink"><a href="{{ url_for('intake') }}">Coach login &rarr;</a></div>
<div class="hero"><div class="hero-wrap">
  <p class="eyebrow">Shepherds Baseball &middot; Training Program</p>
  <h1>Player Reports</h1>
  <p class="sub">Full Swing data turned into a Baseball Savant&ndash;style report card. Tap a report to open it.</p>
</div></div>
<div class="wrap">
  <div class="roster">
  {% for slug, p in players.items() %}
    <div class="card">
      <div>
        <div class="name">{{ p.name }}</div>
        <div class="meta">{% if p.school %}{{ p.school }}{% endif %}{% if p.grad_year %} &middot; Class of {{ p.grad_year }}{% endif %}</div>
      </div>
      <div class="links">
        {% if p.roles.pitch %}<a href="{{ url_for('view_report', slug=slug, role='pitching') }}">Pitching Report</a>{% endif %}
        {% if p.roles.hit %}<a href="{{ url_for('view_report', slug=slug, role='hitting') }}">Hitting Report</a>{% endif %}
        {% if is_coach %}<a href="{{ url_for('edit_comps', slug=slug) }}" style="background:#aa8b68;">Edit Comps</a>{% endif %}
      </div>
    </div>
  {% endfor %}
  </div>
</div>
"""


@app.route('/')
def dashboard():
    players = store.list_players()
    players = dict(sorted(players.items(), key=lambda kv: kv[1]['name']))
    return render_template_string(DASHBOARD_PAGE, players=players, is_coach=bool(session.get('coach')))


@app.route('/report/<slug>/<role>')
def view_report(slug, role):
    if role not in ('pitching', 'hitting'):
        abort(404)
    path = os.path.join(pipeline.REPORTS_DIR, f'{slug}_{role}.html')
    if not os.path.exists(path):
        abort(404)
    return send_file(path)


# --- intake form (coach-only) --------------------------------------------

INTAKE_PAGE = """
<!doctype html><title>New Player Intake</title>
<style>
  body{font-family:Barlow,Arial,sans-serif;background:#f3ebdd;color:#6f4f2f;max-width:560px;margin:0 auto;padding:28px 16px 60px;}
  h1{font-family:Oswald,Arial,sans-serif;}
  label{display:block;font-weight:600;font-size:13px;margin:14px 0 4px;}
  input[type=text],input[type=number]{width:100%;padding:9px 10px;border:1px solid #e1d6c2;border-radius:7px;box-sizing:border-box;}
  .row{display:flex;gap:10px;} .row > div{flex:1;}
  button{margin-top:20px;padding:11px 22px;border:none;border-radius:999px;background:#5c84a6;color:#fff;font-weight:600;cursor:pointer;}
  .msg{padding:10px 14px;border-radius:8px;margin-bottom:14px;}
  .msg.ok{background:#e3ecdf;color:#3f6b42;} .msg.err{background:#f6dede;color:#9c3a3a;}
  .top{display:flex;justify-content:space-between;align-items:center;}
  .top a{color:#8a7557;font-size:13px;}
  fieldset{border:1px solid #e1d6c2;border-radius:10px;margin-top:16px;}
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
  <fieldset style="padding:12px 14px;">
    <label style="margin-top:0;">Full Swing export (.xlsx)</label>
    <input type="file" name="xlsx_file" accept=".xlsx" required>
    <p style="font-size:12.5px;color:#8a7557;">The workbook must include this player's rows on the Master and Totals tabs.</p>
  </fieldset>
  <button type="submit">Generate report(s)</button>
</form>
<p style="margin-top:28px;"><a href="{{ url_for('dashboard') }}">&larr; View the public dashboard</a></p>
"""


@app.route('/intake', methods=['GET', 'POST'])
@login_required
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

        f = request.files.get('xlsx_file')
        if not name or not f or not f.filename:
            message, ok = 'Name and a Full Swing export file are required.', False
        else:
            xlsx_path = os.path.join(UPLOAD_DIR, f'{store.slugify(name)}_{f.filename}')
            f.save(xlsx_path)
            try:
                slug, results = pipeline.process_upload(
                    xlsx_path, name, school, grad_year, position_pitch, position_hit, roles_needed,
                )
                if results:
                    links = ', '.join(f"{role}" for role, _ in results)
                    message = f'Generated: {links} for {name}. View on the dashboard below.'
                else:
                    message, ok = f"{name} wasn't found on the Totals tab for the role(s) requested — check the name matches exactly.", False
            except Exception as exc:
                message, ok = f'Something went wrong processing that file: {exc}', False

    return render_template_string(INTAKE_PAGE, message=message, ok=ok, coach=store.coach_display_name(session['coach']))


# --- comps override API (coach-only) -------------------------------------

@app.route('/api/comps/search')
@login_required
def api_comps_search():
    q = request.args.get('q', '')
    if len(q) < 2:
        return jsonify([])
    return jsonify(mlb_lookup.search(q))


@app.route('/api/comps/<slug>/<role>/<int:index>', methods=['POST'])
@login_required
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
@login_required
def api_comps_unlock(slug, role, index):
    store.unlock_comp(slug, role, index)
    pipeline.regenerate_role(slug, role)
    return jsonify({'ok': True})


# --- comps edit page (coach-only, simple form -- the published report card
#     itself stays untouched/pixel-perfect; this is a separate admin view) --

EDIT_COMPS_PAGE = """
<!doctype html><title>Edit Comps &mdash; {{ player.name }}</title>
<style>
  body{font-family:Barlow,Arial,sans-serif;background:#f3ebdd;color:#6f4f2f;max-width:560px;margin:0 auto;padding:28px 16px 60px;}
  h1{font-family:Oswald,Arial,sans-serif;font-size:22px;}
  h2{font-family:Oswald,Arial,sans-serif;font-size:15px;color:#8a7557;text-transform:uppercase;letter-spacing:.06em;margin-top:28px;}
  .slot{display:flex;align-items:center;gap:8px;background:#fff;border:1px solid #e1d6c2;border-radius:8px;padding:10px 12px;margin-bottom:8px;}
  .slot .info{flex:1;}
  .slot .nm{font-weight:600;}
  .slot .tag{font-size:11px;padding:2px 7px;border-radius:999px;margin-left:6px;}
  .tag.auto{background:#e6dac5;color:#6f4f2f;}
  .tag.locked{background:#dce8f0;color:#355;}
  form.inline{display:flex;gap:6px;}
  input[type=text]{padding:6px 8px;border:1px solid #e1d6c2;border-radius:6px;width:150px;}
  button{padding:6px 12px;border:none;border-radius:999px;background:#5c84a6;color:#fff;font-weight:600;cursor:pointer;font-size:12.5px;}
  button.unlock{background:#aa8b68;}
  .top a{color:#8a7557;font-size:13px;}
</style>
<p class="top"><a href="{{ url_for('intake') }}">&larr; Back to intake</a></p>
<h1>{{ player.name }} &mdash; Players to Watch</h1>
{% for role, label in [('pitch','Pitching'), ('hit','Hitting')] %}
  {% if player.roles.get(role) %}
  <h2>{{ label }}</h2>
  {% for c in player.comps.get(role, []) %}
    <div class="slot">
      <div class="info">
        <span class="nm">{{ c.name or '(empty)' }}</span>
        <span class="tag {{ c.source }}">{{ c.source }}</span>
        {% if c.position %}<div style="font-size:12px;color:#8a7557;">{{ c.position }}</div>{% endif %}
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
@login_required
def edit_comps(slug):
    player = store.get_player(slug)
    if not player:
        abort(404)
    return render_template_string(EDIT_COMPS_PAGE, player=player, slug=slug)


@app.route('/edit/<slug>/<role>/<int:index>/override', methods=['POST'])
@login_required
def edit_comps_override(slug, role, index):
    name = request.form.get('name', '').strip()
    if name:
        store.override_comp(slug, role, index, name)
        pipeline.regenerate_role(slug, role)
    return redirect(url_for('edit_comps', slug=slug))


@app.route('/edit/<slug>/<role>/<int:index>/unlock', methods=['POST'])
@login_required
def edit_comps_unlock(slug, role, index):
    store.unlock_comp(slug, role, index)
    pipeline.regenerate_role(slug, role)
    return redirect(url_for('edit_comps', slug=slug))


if __name__ == '__main__':
    # Local dev only -- on Render (or any real host) gunicorn imports `app`
    # directly per the Procfile below and this block never runs, so debug
    # mode here never reaches a public deployment.
    port = int(os.environ.get('PORT', 5050))
    app.run(host='0.0.0.0', port=port, debug=True)
