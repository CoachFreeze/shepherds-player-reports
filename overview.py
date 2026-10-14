"""Player overview page: aggregate of a pitcher's most recent outings (see outings.py)."""
import re
from html import escape

import extract as e
import stats as stats_mod
import savant_components as sc
import outings as outings_mod
import pipeline


def _colored(tm):
    for t in tm:
        t['color'] = e.MINI_PITCH_COLORS.get(t['type'], '#555')
    return tm


def _date_label(d):
    try:
        y, m, dd = d.split('-')
        return f'{int(m)}/{int(dd)}'
    except Exception:
        return d


def _long_date(d):
    import datetime
    try:
        return datetime.date.fromisoformat(d).strftime('%a, %b %-d, %Y')
    except Exception:
        return d


def trend_svg(series, dates, width=680, height=300):
    """series: {type: {'color':hex, 'vals':[avg velo or None per outing, oldest first]}}"""
    vals = [v for s in series.values() for v in s['vals'] if v is not None]
    if not vals:
        return ''
    lo, hi = min(vals), max(vals)
    step = 2 if hi - lo > 6 else 1
    ymin = (int(lo) // step) * step - step
    ymax = (int(hi) // step + 1) * step + step
    L, R, T, B = 46, 18, 16, 38
    pw, ph = width - L - R, height - T - B
    n = len(dates)
    X = lambda i: L + (pw / 2 if n == 1 else pw * i / (n - 1))
    Y = lambda v: T + ph * (1 - (v - ymin) / (ymax - ymin))
    o = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;">']
    y = ymin
    while y <= ymax:
        o.append(f'<line x1="{L}" x2="{width-R}" y1="{Y(y):.1f}" y2="{Y(y):.1f}" stroke="#e3e8ea"/>'
                 f'<text x="{L-8}" y="{Y(y)+4:.1f}" text-anchor="end" font-size="12" fill="#6b7680">{y}</text>')
        y += step
    for i, d in enumerate(dates):
        o.append(f'<text x="{X(i):.1f}" y="{height-14}" text-anchor="middle" font-size="12" fill="#6b7680">{_date_label(d)}</text>')
    o.append(f'<text x="12" y="{T+ph/2}" transform="rotate(-90 12 {T+ph/2})" text-anchor="middle" font-size="12" fill="#6b7680">Avg velocity (mph)</text>')
    for ty, s in series.items():
        pts = [(X(i), Y(v), v, dates[i]) for i, v in enumerate(s['vals']) if v is not None]
        if len(pts) > 1:
            o.append(f'<polyline fill="none" stroke="{s["color"]}" stroke-width="3" stroke-linejoin="round" points="' +
                     ' '.join(f'{x:.1f},{yy:.1f}' for x, yy, _, _ in pts) + '"/>')
        for x, yy, v, d in pts:
            o.append(f'<circle class="mv-pt" cx="{x:.1f}" cy="{yy:.1f}" r="5.5" fill="{s["color"]}" stroke="#fff" stroke-width="1.5" '
                     f'data-tip="{escape(ty)} · {v:.1f} mph · {_date_label(d)}"/>')
    o.append('</svg>')
    return ''.join(o)


def _stamp(outs, name):
    # each outings file belongs to one pitcher; stamp the current spelling so renames never break matching
    for o in outs:
        for r in o['rows']:
            r['Pitcher'] = name
    return outs


def build(slug, bio):
    name = bio['name']
    recent = _stamp(outings_mod.recent(slug), name)
    if not recent:
        return None
    rows = [r for o in recent for r in o['rows']]
    meta, tm = e.pitcher_trackman_summary(rows, name)
    _colored(tm)
    slot = e.arm_slot_stats(meta.get('release'), bio.get('height_in'))
    arm_badge = {'angle': slot['angle'], 'throws': meta.get('throws') or 'R'} if slot else None

    mv = [{'type': t['type'], 'color': t['color'], 'hb': t['hb'], 'vb': t['ivb'], 'points': [(h, v, ve) for h, v, ve in t['points']]}
          for t in tm if t['points']]
    movement_html = (sc.movement_plot_caption_html() + sc.movement_plot_svg(
        mv, width=680, height=680, all_pitches=True, r24_frac=0.80, font_scale=1.3, pt_r=9, arm_badge=arm_badge)
        + sc.pitch_usage_legend_html(tm)) if mv else ''
    location_html = sc.location_heatmap_html(tm, width=340, uid='loc')

    summ = e.outing_summary(rows) or {}
    stat_vals = stats_mod.compute(rows)
    stat_tiles = stats_mod.tiles(stat_vals, bio.get('stat_ids'))
    stat_catalog = stats_mod.catalog(stat_vals)

    # velocity trend, oldest -> newest
    chron = list(reversed(recent))
    dates = [o['date'] for o in chron]
    series = {}
    for i, o in enumerate(chron):
        _, ptm = e.pitcher_trackman_summary(o['rows'], name)
        for t in ptm:
            if t.get('velo') is None:
                continue
            s = series.setdefault(t['type'], {'color': e.MINI_PITCH_COLORS.get(t['type'], '#555'), 'vals': [None] * len(chron), 'n': 0})
            s['vals'][i] = t['velo']
            s['n'] += t['n']
    order = [t['type'] for t in tm]
    series = {k: series[k] for k in order if k in series}
    trend_html = trend_svg(series, dates)
    legend = [{'type': k, 'color': v['color']} for k, v in series.items()]

    log = []
    for o in recent:
        _, otm = e.pitcher_trackman_summary(o['rows'], name)
        top = max((t['top_velo'] for t in otm if t.get('top_velo')), default=None)
        os_ = e.outing_summary(o['rows']) or {}
        log.append({'id': o['id'], 'label': _long_date(o['date']), 'live_ab': o.get('live_ab'), 'n': len(o['rows']),
                    'top': top, 'strike': os_.get('strike_pct'), 'whiff': os_.get('whiff_pct'),
                    'ip': os_.get('ip') if o.get('live_ab') else None,
                    'types': ', '.join(t['type'] for t in otm)})
    return {'name': name, 'meta': meta, 'summary': summ, 'stat_tiles': stat_tiles, 'stat_catalog': stat_catalog, 'movement_html': movement_html, 'location_html': location_html,
            'trend_html': trend_html, 'legend': legend, 'log': log, 'n_outings': len(recent), 'n_pitches': len(rows),
            'range': (_long_date(recent[-1]['date']) + ' – ' + _long_date(recent[0]['date'])) if len(recent) > 1 else _long_date(recent[0]['date'])}


def outing_report_html(slug, date, bio):
    for o in _stamp(outings_mod.outings(slug), bio['name']):
        if o['id'] == date:
            return pipeline.render_trackman_mini(bio['name'], o['rows'], bio, summary_rows=o['rows'] if o.get('live_ab') else None, write=False)
    return None
