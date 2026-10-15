"""Content for the stats glossary page. Pitching definitions come straight from stats.py so the page can never drift
from what the dashboard actually computes; the rest is written here."""
import stats as stats_mod


def _group_pitching():
    out = []
    for g in stats_mod.GROUP_ORDER:
        items = [(lab, d) for sid, (lab, grp, d) in stats_mod.BASE.items() if grp == g]
        if items:
            out.append({'title': g, 'items': items})
    out.append({'title': 'Per pitch type', 'note': 'Each pitch type a pitcher throws gets its own set of these.',
                'items': [(lab, d) for _, lab, d in stats_mod.PT_STATS]})
    return out


CHARTS = [
    ('Pitch Movement Profile (PMP)', 'Where each pitch type ends up, horizontally and vertically, compared with a pitch thrown with no spin effect. '
     'Shown from the pitcher\'s point of view, so "1B" and "3B" mark which way a pitch moves toward the first-base or third-base side. '
     'Up means more rise (induced vertical break); a right-hander\'s fastball usually sits up and toward the first-base side, a slider down and toward third.'),
    ('Pitch location heat map', 'Where pitches crossed the plate, from the catcher\'s view (a right-handed batter stands on the left). Warmer color means more pitches there. '
     'Charts are split by batter side, and you can filter by pitch type.'),
    ('Percentile bars', 'A stat placed on a blue-to-red scale against college-level benchmarks. Blue is below average, the middle is average, red is better. '
     'The number in the circle is the percentile (50 = average).'),
    ('Velocity trend', 'Average fastball velocity for each of the last outings, oldest to newest. The note beside it compares the oldest and newest of those outings '
     '("Up 1.2 mph"); changes under 0.3 mph read as flat.'),
]

DATA_NOTES = [
    ('Where the numbers come from', 'Everything is calculated from the tracking-system file you upload (Trackman today; FullSwing, Yakkertech and Rapsodo are planned). '
     'Pitches are never double counted if the same file is uploaded twice.'),
    ('Operator tags', 'Pitch results use the tags your operator enters (PC_ for the call, HC_ for hit type, PR_ for the result) whenever they are present, '
     'because Trackman\'s automatic pitch call disagrees with the real call on roughly one pitch in four. Without tags, the automatic call is used. '
     'Consistent tagging makes every swing, whiff and chase number more accurate.'),
    ('The strike zone', 'The zone is a fixed box 1.66 ft wide (about 20 inches: the plate plus the width of a baseball) and 2.2 ft tall, from 1.4 ft to 3.6 ft off the ground, for every batter. '
     'It does not adjust to each batter\'s height, so pitches at the top and bottom edges can differ slightly from the umpire\'s zone.'),
    ('Estimates', 'Batters faced, innings pitched, walks and strikeouts are estimated from the count and tags, since a pitch file has no scorebook. '
     'Treat them as close, not official.'),
    ('Small samples', 'A single bullpen or scrimmage is a small sample. Percentages move a lot on a few pitches, so look for patterns across outings rather than one game.'),
]

HITTING = [
    {'title': 'Swing decisions', 'items': [
        ('Swing decision score', 'Of the pitches that clearly called for a swing or a take, the share where the hitter made the right choice, from 0 to 100. '
         'Swinging at a hittable pitch or taking one he can\'t drive is good. Taking a hittable pitch or swinging at a bad one is bad. Borderline pitches don\'t count either way.'),
        ('Grade', 'Elite 85+, Strong 75+, Solid 65+, Developing 55+, Needs work below that. These cutoffs are starting points and will be tuned as data builds. '
         'No grade is shown under 15 judged pitches.'),
        ('Heart', 'The middle of the zone: the inner two-thirds, about 1.1 ft wide and 1.4 ft tall. A hittable pitch. Taking one is a missed chance.'),
        ('Shadow', 'The edges of the zone plus a quarter foot (about 3 inches) just outside it. Hard to judge, so it counts as neither good nor bad.'),
        ('Chase zone / waste zone', 'Pitches more than a quarter foot outside the zone (chase), and farther still, about 9 inches or more off the zone (waste). Swinging at them is a bad decision.'),
        ('Chase rate', 'Swings at pitches in the chase and waste areas, divided by the number of pitches there. This is a stricter version of the pitching-side Chase %, which counts every pitch outside the zone.'),
        ('Swings at the heart', 'Share of heart pitches he swung at.'),
        ('Zone swing', 'Share of pitches in the strike zone (heart and shadow) he swung at.'),
        ('Zone contact', 'Of his swings at pitches in the zone, the share that made contact (foul or in play).'),
        ('Whiff rate', 'Swings and misses divided by all swings.'),
        ('Good decisions', 'Good decisions out of all judged pitches (not counting borderline pitches).'),
    ]},
    {'title': 'Batted-ball quality', 'items': [
        ('Avg / max exit velo', 'Average and hardest exit velocity on tracked balls in play, in mph.'),
        ('EV90', 'The exit velocity he reaches or beats on his hardest 10% of balls, a better read of his true power than the average. Needs at least 5 tracked balls.'),
        ('Hard-hit %', 'Balls in play hit 95 mph or harder.'),
        ('Avg launch angle', 'Average vertical angle off the bat, in degrees.'),
        ('Sweet spot %', 'Balls hit between 8 and 32 degrees, the range where most line drives and productive fly balls land.'),
        ('Ground ball / line drive / fly ball %', 'The hit type recorded by the tracking system for each ball in play (fly ball includes pop-ups).'),
        ('Pull / center / oppo', 'Where the ball went relative to the hitter: more than 15 degrees toward his pull side is pull, more than 15 degrees the other way is oppo, the rest is center. A switch hitter uses the side he batted from on each ball.'),
        ('xBA (expected batting average)', 'What his average would be from how hard and at what angle he hit the ball, ignoring defense, parks and luck. '
         'Each ball is given a chance of being a hit from its exit velocity and launch angle; the chances are added up and divided by at-bats (balls in play plus strikeouts, no walks or hit by pitches). '
         'The hit chances were fitted to about 25,000 MLB balls in play and will be refit with our own data. Sprint speed is not included. Swings a lot under about 20 at-bats.'),
    ]},
    {'title': 'Hitting charts', 'items': [
        ('Decision map', 'Every pitch he saw, from the catcher\'s view. Filled dots are swings and rings are takes. Green is a good decision, red is bad, grey is borderline.'),
        ('Spray chart', 'Every tracked ball in play on a field diagram, colored by exit velocity. Tap a dot to see exit velocity, distance, launch angle and expected batting average on that ball.'),
        ('Exit velo heat map', 'The strike zone split into a 3 by 3 grid, each square split again into four, colored by the average exit velocity of balls in play that crossed the plate there. '
         'Blue is soft, red is hard. Filter by pitch type. Balls hit off pitches outside the zone are not shown.'),
    ]},
]


def sections(is_admin=False):
    s = [
        {'id': 'pitching', 'title': 'Pitching stats', 'groups': _group_pitching()},
        {'id': 'charts', 'title': 'Charts and visuals', 'groups': [{'title': '', 'items': CHARTS}]},
    ]
    if is_admin:
        s.append({'id': 'hitting', 'title': 'Hitting (beta, admin only)', 'groups': HITTING})
    s.append({'id': 'data', 'title': 'About the data', 'groups': [{'title': '', 'items': DATA_NOTES}]})
    return s
