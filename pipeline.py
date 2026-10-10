"""
The actual report-generation pipeline, adapted from the original build/render.py
used in the chat-based workflow. Same extraction/template logic; the two
differences are (1) it takes an uploaded workbook path instead of a fixed
file, and (2) comps come from comps_engine + store (auto-generated, locked
slots preserved) instead of a hand-maintained config file.
"""
import os
import jinja2
import extract as e
import savant_components as sc
import brand_assets
import comps_engine as ce
import arsenal_comps as ac
import mlb_lookup
import store
import fonts_embed

APP_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(APP_DIR, 'data', 'reports')
os.makedirs(REPORTS_DIR, exist_ok=True)

# Fonts are embedded once at process start (not per-render -- they never
# change) so each report keeps the real brand typefaces instead of silently
# falling back to the Google-Fonts stand-ins baked into report.css.
CSS = open(os.path.join(APP_DIR, 'report.css')).read().replace(
    '{{ FONT_FACE_CSS }}', fonts_embed.build_font_face_css()
)
# Looks in templates/ first, then the app root -- GitHub's web uploader makes it
# easy to drop a template into the wrong folder, and a missing template used to
# crash the whole app at startup.
env = jinja2.Environment(loader=jinja2.FileSystemLoader([os.path.join(APP_DIR, 'templates'), APP_DIR]))
tpl = env.get_template('report_template.html')
tm_mini_tpl = env.get_template('trackman_report_template.html')
BRAND = brand_assets.build_brand_uris()


def safe_round(v, n):
    return round(v, n) if isinstance(v, (int, float)) else '—'


# School logos for the badge at the top of a report: (match keywords, logo file in assets/schools/,
# circle background colour). Add a line + drop the PNG in assets/schools/ to support another school.
SCHOOL_BADGES = [
    (('long beach state', 'lbsu', 'csulb'), 'long_beach_state.png', '#FFB81C'),
]


def school_badge(school, program=None):
    """-> {'logo': data-uri, 'bg': colour} or None. Long Beach State players
    (program 'long_beach_state') get the LB badge even if the school box was left blank."""
    import base64
    s = (school or '').lower()
    for keys, fname, bg in SCHOOL_BADGES:
        if any(k in s for k in keys) or (program == 'long_beach_state' and fname == 'long_beach_state.png'):
            path = os.path.join(APP_DIR, 'assets', 'schools', fname)
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    return {'logo': 'data:image/png;base64,' + base64.b64encode(f.read()).decode('ascii'), 'bg': bg}
    return None


def _school_display(school, grad_year):
    if school and grad_year:
        return f'{school} · Class of {grad_year}'
    if grad_year:
        return f'Class of {grad_year}'
    return None


def _resolve_comps(comps_list):
    """Turns [{'name','position','source','blurb'?}] into the full dicts the
    template needs (photo/url/blurb), via the cache-first MLB lookup."""
    out = []
    for c in comps_list:
        if not c.get('name'):
            out.append({'name': None, 'pos': None, 'photo': None, 'url': None, 'blurb': None})
            continue
        info = mlb_lookup.resolve(c['name'])
        blurb = c.get('blurb')
        if not blurb:
            # a coach's manual override has no engine-computed rationale
            blurb = f"Added by a coach as a comp worth studying for this player."
        out.append({
            'name': c['name'],
            'pos': info.get('position') or c.get('position'),
            'photo': info.get('photo'),
            'url': info.get('url'),
            'blurb': blurb,
        })
    return out


def render_pitcher(name, totals_row, master_rows, bio, trackman_rows=None):
    slug = store.slugify(name)
    velo_ev = e.pitcher_velo_ev_metrics(master_rows, name)
    overall, tracking = e.pitcher_master_stats(master_rows, name)
    pctl_rows = e.build_pitcher_percentiles_master(overall, velo_ev)
    for t in tracking:
        t['color'] = e.PITCH_COLORS.get(t['type'], '#555')
    tracking.sort(key=lambda t: t['pct'], reverse=True)

    pctl_html = sc.percentile_bars_html([
        {'label': r['label'], 'pctl': r['pctl'], 'value_display': f"{r['value']:.1f}{r['unit']}"}
        for r in pctl_rows if r['pctl'] is not None
    ])

    # Trackman (optional): real break/spin numbers per pitch type, keyed off
    # the same labels Full Swing's own `tracking` rows use. Falls back to the
    # old sample/placeholder values for any pitch type it has no data for
    # (or when no Trackman file was ever attached for this pitcher).
    tm_movement = e.pitcher_trackman_movement(trackman_rows, name) if trackman_rows else {}

    sample_shape = {'Fastball': (7, 14), 'Slider': (-6, -4), 'Changeup': (10, 4), 'Curveball': (-8, -12), 'Other': (6, -2)}
    movement_pitches = []
    movement_is_sample = False
    for t in tracking:
        tm = tm_movement.get(t['type'])
        pts = []
        if tm and tm.get('hb') is not None and tm.get('ivb') is not None:
            hb, vb = tm['hb'], tm['ivb']
            pts = tm.get('points') or []
        else:
            hb, vb = sample_shape.get(t['type'], (0, 0))
            movement_is_sample = True
        movement_pitches.append({'type': t['type'], 'color': t['color'], 'hb': hb, 'vb': vb, 'points': pts})
    if movement_pitches:
        movement_html = (
            sc.movement_plot_caption_html()
            + sc.movement_plot_svg(movement_pitches, width=270, height=282, max_range=20, all_pitches=True)
            + sc.pitch_usage_legend_html(tracking)
        )
    else:
        movement_html = '<div style="color:#999;font-size:11px;">No pitch data</div>'

    spin_pitches = []
    spin_is_sample = False
    sample_clocks = {'Fastball': ('1:00', '12:45', 15), 'Slider': ('8:45', '8:15', 30),
                      'Changeup': ('1:45', '2:45', -60), 'Curveball': ('7:15', '7:15', 0), 'Other': ('2:00', '1:30', 15)}
    for t in tracking:
        tm = tm_movement.get(t['type'])
        if tm and tm.get('spin_based_clock'):
            sb = tm['spin_based_clock']
            ob = tm.get('observed_clock') or sb
            dv = tm.get('spin_deviation') or 0
        else:
            sb, ob, dv = sample_clocks.get(t['type'], ('12:00', '12:00', 0))
            spin_is_sample = True
        spin_pitches.append({'type': t['type'], 'spin_based': sb, 'observed': ob, 'deviation': dv, 'color': t['color']})
    spin_html = sc.spin_clock_row_svg(spin_pitches) if spin_pitches else '<div style="color:#999;font-size:11px;">No pitch data</div>'
    # Only show the Spin Direction panel at all once there's real Trackman
    # spin data for at least one pitch type -- otherwise it's pure fiction
    # and the old build correctly just hid it (show_spin_direction=False).
    show_spin_direction = any(tm.get('spin_based_clock') for tm in tm_movement.values())

    bf, so, bb = overall.get('bf'), overall.get('k'), overall.get('bb')

    # Comps: auto-generate, merge with any locked slots, resolve for display.
    auto = ce.find_comps(pctl_rows, 'pitcher', our_name=name,
                          position=bio['roles'].get('pitch', {}).get('position'), n=3)
    comps_list = store.set_auto_comps(slug, 'pitch', auto, n_slots=3)
    comps_display = _resolve_comps(comps_list)

    p = {
        'name': name, 'family': 'pitcher',
        'position': bio['roles'].get('pitch', {}).get('position'),
        'school': _school_display(bio.get('school'), bio.get('grad_year')),
        'bats_throws': None, 'height': None, 'weight_lbs': None, 'age': None, 'year': '2026',
        'g': totals_row.get('G'), 'ip': safe_round(totals_row.get('IP'), 1),
        'bf': bf, 'h': totals_row.get('H'), 'so': so,
        'bb': bb, 'whip': safe_round(totals_row.get('WHIP'), 2),
        'tracking': tracking, 'comps': comps_display,
        'movement_is_sample': movement_is_sample, 'spin_is_sample': spin_is_sample,
        'show_spin_direction': show_spin_direction,
        'action_photo': None, 'headshot': None, 'coach_notes': None,
    }
    html = tpl.render(p=p, css=CSS, pctl_html=pctl_html, movement_html=movement_html, spin_html=spin_html, brand=BRAND)
    out_path = os.path.join(REPORTS_DIR, f'{slug}_pitching.html')
    open(out_path, 'w').write(html)
    return out_path


_RESULT_LABELS = {'strikecalled': 'Called Strike', 'ballcalled': 'Ball', 'inplay': 'In Play',
                  'strikeswinging': 'Swinging Strike', 'foulball': 'Foul', 'foulballnotfieldable': 'Foul',
                  'foulballfieldable': 'Foul', 'hitbypitch': 'Hit By Pitch', 'ballintheDirt'.lower(): 'Ball',
                  'intentionalball': 'Intentional Ball'}


def _short_date(d):
    mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    try:
        y, m, dd = str(d).split('-')
        return f'{mo[int(m) - 1]} {int(dd)}'
    except (ValueError, IndexError):
        return str(d or '')


def _pitch_log_rows(log):
    """Pitch-by-pitch rows for the Pitch Log table: adds the pitch-type colour
    and a readable result label to what extract.pitcher_trackman_summary collected."""
    rows = []
    prev_date, pno = None, 0
    multi = len({r.get('date') for r in log if r.get('date')}) > 1
    for r in log:
        r = dict(r)
        if r.get('date') != prev_date:
            pno = 0
            r['new_day'] = _short_date(r.get('date')) if multi else None
            prev_date = r.get('date')
        pno += 1
        r['pno'] = pno if multi else r['n']
        r['color'] = e.MINI_PITCH_COLORS.get(r['type'], '#555')
        r['result'] = _RESULT_LABELS.get((r.get('call') or '').replace('_', '').lower(), '\u2014')
        # A ball thrown with 3 balls already in the count is ball four: a walk.
        if r['result'] == 'Ball' and r.get('balls') is not None and r['balls'] >= 3:
            r['result'] = 'BB'
        rows.append(r)
    return rows


def render_trackman_mini(name, trackman_rows, bio=None, summary_rows=None):
    """A scoped report for a pitcher who has a Trackman session but no Full
    Swing workbook yet: real pitch movement, spin direction and velocity
    straight from the CSV, with none of the season-stat/percentile/comps
    sections that need a Full Swing export. Swap this for the full
    render_pitcher() output once a Full Swing workbook exists for them."""
    slug = store.slugify(name)
    meta, tm_pitches = e.pitcher_trackman_summary(trackman_rows, name)
    for t in tm_pitches:
        t['color'] = e.MINI_PITCH_COLORS.get(t['type'], '#555')

    slot = e.arm_slot_stats(meta.get('release'), (bio or {}).get('height_in'))
    arm_badge = {'angle': slot['angle'], 'throws': meta.get('throws') or 'R'} if slot else None

    movement_pitches = [
        {'type': t['type'], 'color': t['color'], 'hb': t['hb'], 'vb': t['ivb'],
         'points': [(h, v, ve) for h, v, ve in t['points']]}
        for t in tm_pitches if t['points']
    ]
    movement_html = (
        sc.movement_plot_caption_html()
        + sc.movement_plot_svg(movement_pitches, width=680, height=680, all_pitches=True,
                             r24_frac=0.80, font_scale=1.3, pt_r=9, arm_badge=arm_badge)
        + sc.pitch_usage_legend_html(tm_pitches)
    ) if movement_pitches else '<div style="color:#999;font-size:11px;">No movement data</div>'

    location_html = sc.location_heatmap_html(tm_pitches, width=340, uid='loc')

    spin_pitches = [
        {'type': t['type'], 'spin_based': t['spin_based_clock'], 'observed': t['observed_clock'],
         'deviation': t['spin_deviation'] or 0, 'color': t['color']}
        for t in tm_pitches if t['spin_based_clock']
    ]
    spin_html = sc.spin_clock_row_svg(spin_pitches) if spin_pitches else ''

    arm_html = ''   # superseded by the arm-angle badge drawn inside the Pitch Movement Profile

    ars = [{'type': t['type'], 'pct': t['pct'], 'velo': t['velo'], 'spin': t['spin_avg'], 'hb': t['hb'], 'ivb': t['ivb']}
           for t in tm_pitches if t.get('hb') is not None and t.get('ivb') is not None]
    ang = slot['angle'] if slot else None
    cols = {t['type']: t['color'] for t in tm_pitches}
    mlb_comps = ac.find_arsenal_comps(ars, meta.get('throws') or 'R', ang, n=3) if ars else []
    comps_html = sc.arsenal_comps_html(mlb_comps, ars, meta.get('throws') or 'R', cols)
    ideas_html = sc.arsenal_ideas_html(ac.suggest_pitches(ars, meta.get('throws') or 'R', ang, n=3), {**e.MINI_PITCH_COLORS, **cols}, throws=meta.get('throws') or 'R') if ars else ''

    p = {
        'name': name,
        'position': bio['roles'].get('pitch', {}).get('position') if bio else None,
        'school': _school_display(bio.get('school'), bio.get('grad_year')) if bio else None,
        'school_badge': school_badge((bio or {}).get('school'), (bio or {}).get('program')),
        'throws': meta.get('throws'), 'team': meta.get('team'), 'date': meta.get('date'),
        'dates': [_short_date(d) for d in (meta.get('dates') or [])],
        'n_pitches': sum(t['n'] for t in tm_pitches), 'tracking': tm_pitches,
        'log': _pitch_log_rows(meta.get('log') or []),
        'show_spin_direction': bool(spin_pitches), 'year': '2026',
        'outing': e.outing_summary([r for r in summary_rows if e._pitcher_match(r, name)]) if summary_rows else None,
    }
    html = tm_mini_tpl.render(p=p, css=CSS, movement_html=movement_html, location_html=location_html, arm_html=arm_html, comps_html=comps_html, ideas_html=ideas_html, spin_html=spin_html, brand=BRAND)
    out_path = os.path.join(REPORTS_DIR, f'{slug}_trackman_mini.html')
    open(out_path, 'w').write(html)
    return out_path


def process_trackman_only(trackman_path, name, school, grad_year, position_pitch, height_in=None, weight_lbs=None, exclude_uids=(), live_ab=False):
    """Entry point for the Long Beach State side of the roster: a pitcher
    who has a Trackman session but no Full Swing export. Mirrors
    process_upload()'s shape (bio upsert -> store the source file -> render
    -> sync) but tags the player 'long_beach_state' instead of 'shepherds'
    and renders the scoped Trackman-only report instead of the full one.
    Returns (slug, out_path) -- out_path is None if this name doesn't
    actually appear in the CSV (e.g. a typo, or wrong file attached)."""
    slug = store.upsert_player_bio(name, school, grad_year, position_pitch=position_pitch, height_in=height_in, weight_lbs=weight_lbs)
    store.set_program(slug, 'long_beach_state')
    store.set_last_trackman(slug, trackman_path)
    bio = store.get_player(slug)

    trackman_rows = e.load_trackman_rows(trackman_path)
    if exclude_uids:
        ex = set(exclude_uids)
        trackman_rows = [r for r in trackman_rows if (r.get('PitchUID') or r.get('PitchNo')) not in ex]
    _, pitches = e.pitcher_trackman_summary(trackman_rows, name)
    if not pitches:
        store.sync_to_github()
        return slug, None

    out = render_trackman_mini(name, trackman_rows, bio, summary_rows=trackman_rows if live_ab else None)
    store.sync_to_github()
    return slug, out


def render_hitter(name, totals_row, master_rows, bio):
    slug = store.slugify(name)
    derived = e.hitter_derived_metrics(master_rows, name)
    pctl_rows = e.build_hitter_percentiles(totals_row, derived)
    pctl_html = sc.percentile_bars_html([
        {'label': r['label'], 'pctl': r['pctl'], 'value_display': f"{r['value']:.1f}{r['unit']}"}
        for r in pctl_rows if r['pctl'] is not None
    ])
    points = e.hitter_spray_points(master_rows, name)
    spray_html = sc.spray_chart_interactive_html(points, width=260, height=232) + sc.spray_chart_legend_html() if points else '<div style="color:#999;font-size:11px;">No batted-ball data</div>'

    running_rows = e.build_running_metrics(bio.get('sixty_yd_time'))
    if running_rows:
        running_html = sc.percentile_bars_html([
            {'label': r['label'], 'pctl': r['pctl'], 'value_display': f"{r['value']}{r['unit']}"}
            for r in running_rows
        ])
    else:
        running_html = sc.percentile_bars_html([]) + '<div class="warn-note">⚠ 60 Yard Dash / Sprint Speed require a 60 time -- add it on the intake or edit page.</div>'

    auto = ce.find_comps(pctl_rows, 'hitter', our_name=name,
                          position=bio['roles'].get('hit', {}).get('position'), n=5)
    comps_list = store.set_auto_comps(slug, 'hit', auto, n_slots=5)
    comps_display = _resolve_comps(comps_list)

    p = {
        'name': name, 'family': 'hitter',
        'position': bio['roles'].get('hit', {}).get('position'),
        'school': _school_display(bio.get('school'), bio.get('grad_year')),
        'bats_throws': None, 'height': None, 'weight_lbs': None, 'age': None, 'year': '2026',
        'comps': comps_display,
        'action_photo': None, 'headshot': None, 'coach_notes': None,
    }
    html = tpl.render(p=p, css=CSS, pctl_html=pctl_html, spray_html=spray_html, running_html=running_html, brand=BRAND)
    out_path = os.path.join(REPORTS_DIR, f'{slug}_hitting.html')
    open(out_path, 'w').write(html)
    return out_path


def process_upload(xlsx_path, name, school, grad_year, position_pitch, position_hit, roles_needed, sixty_yd_time=None, trackman_path=None):
    """roles_needed: set/list containing 'pitch' and/or 'hit'. Returns list of
    (role, out_path) for whichever reports were generated."""
    slug = store.upsert_player_bio(name, school, grad_year, position_pitch, position_hit)
    store.set_program(slug, 'shepherds')
    store.set_last_xlsx(slug, xlsx_path)
    if sixty_yd_time is not None:
        store.set_sixty_yd_time(slug, sixty_yd_time)
    if trackman_path is not None:
        store.set_last_trackman(slug, trackman_path)
    bio = store.get_player(slug)

    pitching, hitting = e.load_totals(xlsx_path)
    master = e.load_master_rows(xlsx_path)
    trackman_rows = e.load_trackman_rows(bio.get('last_trackman_path'))

    results = []
    if 'pitch' in roles_needed:
        row = next((r for r in pitching if r['Name'] == name), None)
        if row:
            out = render_pitcher(name, row, master, bio, trackman_rows)
            results.append(('pitch', out))
    if 'hit' in roles_needed:
        row = next((r for r in hitting if r['Name'] == name), None)
        if row:
            out = render_hitter(name, row, master, bio)
            results.append(('hit', out))
    store.sync_to_github()
    return slug, results


def regenerate_role(slug, role):
    """Re-renders a single role's report from the player's last-uploaded
    workbook, without needing a fresh upload -- used right after a coach
    overrides/unlocks a comp slot, so the published report reflects the
    change immediately instead of waiting for the next data refresh."""
    bio = store.get_player(slug)
    if not bio or not bio.get('last_xlsx_path') or not os.path.exists(bio['last_xlsx_path']):
        return None
    name = bio['name']
    pitching, hitting = e.load_totals(bio['last_xlsx_path'])
    master = e.load_master_rows(bio['last_xlsx_path'])
    if role == 'pitch':
        trackman_rows = e.load_trackman_rows(bio.get('last_trackman_path'))
        row = next((r for r in pitching if r['Name'] == name), None)
        out = render_pitcher(name, row, master, bio, trackman_rows) if row else None
    else:
        row = next((r for r in hitting if r['Name'] == name), None)
        out = render_hitter(name, row, master, bio) if row else None
    store.sync_to_github()
    return out
