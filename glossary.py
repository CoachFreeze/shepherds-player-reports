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
        ('Swing decision score', 'One 0 to 100 number blending three sub-scores: Chase discipline (35%), Hittable pitches (35%) and Damage (30%). '
         'A sub-score that doesn\'t have enough pitches yet (5 pitches, or 3 balls in play for Damage) is left out and the rest are re-weighted.'),
        ('Chase discipline', 'On pitches well off the zone (chase and waste areas), the weighted share where he laid off. Chasing is a little worse in a hitter\'s count, forgiven by half on a close pitch with two strikes, and laying off with two strikes counts extra.'),
        ('Hittable pitches', 'On pitches in the heart, the weighted share where he swung. Taking a fastball in the heart in a hitter\'s count (more balls than strikes) counts double, and taking any hittable pitch with two strikes counts 1.5 times. '
         'Taking a breaking ball or off-speed pitch in the heart early in the count is not held against him: on 0-0 it doesn\'t count at all, and in other early counts it counts half.'),
        ('Damage', 'The expected batting average (xBA) of the balls he put in play off pitches in the zone, turned into a 0 to 100 scale where about .330 is 50, and .530 is 100. It rewards squaring up pitches he can hit, not just swinging.'),
        ('Hitter\'s count, pitcher\'s count', 'A hitter\'s count has more balls than strikes (1-0, 2-0, 2-1, 3-0, 3-1). A pitcher\'s count has more strikes than balls, or two strikes. Even counts are the rest.'),
        ('Fastballs vs breaking balls / off-speed', 'Fastballs include four-seamers, sinkers and cutters. Everything else (sliders, curveballs, changeups, splitters) is breaking or off-speed. Both groups are shown as separate decision scores once there are at least 8 pitches in each.'),
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
        ('Good decisions', 'Number of good decisions out of all the pitches that counted (borderline pitches and excused takes aren\'t included).'),
    ]},
    {'title': 'Batted-ball quality', 'items': [
        ('Avg / max exit velo', 'Average and hardest exit velocity on tracked balls in play, in mph.'),
        ('EV90', 'The exit velocity he reaches or beats on his hardest 10% of balls, a better read of his true power than the average. Needs at least 5 tracked balls.'),
        ('Hard-hit %', 'Balls in play hit 95 mph or harder.'),
        ('Avg launch angle', 'Average vertical angle off the bat, in degrees.'),
        ('Sweet spot %', 'Balls hit between 8 and 32 degrees, the range where most line drives and productive fly balls land.'),
        ('Bat speed', 'How fast the barrel of the bat was moving at contact, in mph. Only comes from a bat-tracking system (Full Swing today). It is logged on every swing, including misses, so the average covers all tracked swings.'),
        ('Squared-up %', 'How well the swing used its speed on a ball in play: the exit velocity you got divided by the exit velocity that swing could have produced with perfect contact. 100% would be a perfectly squared ball. Averaged across balls in play.'),
        ('Smash factor', 'Exit velocity divided by bat speed on a ball in play. Higher means more of the swing went into the ball; the best contact is usually around 1.2 or a bit above against pitched balls.'),
        ('EV left on the table', 'Average gap between the exit velocity a swing could have produced with perfect contact and the exit velocity of the ball. Smaller is better.'),
        ('Barrel %', 'Share of balls in play that were barrels: the exit velocity and launch angle combos that have produced at least a .500 average and 1.500 slugging in the majors. A ball needs 98+ mph; at 98 mph the launch angle window is 26 to 30 degrees, it widens as the ball is hit harder, and at 116 mph anything from 8 to 50 degrees counts. Calculated per ball in play (not per plate appearance). Bunts are left out. The cutoffs come from MLB data, so college hitters are being measured against a major-league yardstick, and the edge of the zone is approximated between the speeds MLB publishes.'),
        ('Ground ball / line drive / fly ball / pop-up %', 'Each ball in play is typed by launch angle alone, the same way Statcast does it: ground ball under 10 degrees, line drive 10 to 25, fly ball 25 to 50, pop-up over 50. Exit velocity does not matter. Bunts are left out.'),
        ('Pull / center / oppo', 'Where the ball went relative to the hitter: more than 15 degrees toward his pull side is pull, more than 15 degrees the other way is oppo, the rest is center. A switch hitter uses the side he batted from on each ball.'),
        ('xBA (expected batting average)', 'What his average would be from how hard and at what angle he hit the ball, ignoring defense, parks and luck. '
         'Each ball is given a chance of being a hit from its exit velocity and launch angle; the chances are added up and divided by at-bats (balls in play plus strikeouts, no walks or hit by pitches). '
         'The hit chances were fitted to about 25,000 MLB balls in play and will be refit with our own data. Sprint speed is not included. Swings a lot under about 20 at-bats.'),
        ('xBAA (expected batting average against)', 'The pitcher-side version of xBA: what opposing hitters would hit against him, from how hard and at what angle they hit the balls he allowed, ignoring defense, parks and luck. Same method as xBA, so it also swings a lot on small samples.'),
    ]},
    {'title': 'Hitting charts', 'items': [
        ('Decision map', 'Every pitch he saw, from the catcher\'s view. Filled dots are swings and rings are takes. Green is a good decision, red is bad, grey is borderline.'),
        ('Spray chart', 'Every tracked ball in play on a field diagram, colored by exit velocity. Tap a dot to see exit velocity, distance, launch angle and expected batting average on that ball.'),
        ('Exit velo heat map', 'The strike zone split into a 3 by 3 grid, each square split again into four, colored by the average exit velocity of balls in play that crossed the plate there. '
         'Blue is soft, red is hard. Filter by pitch type. Balls hit off pitches outside the zone are not shown.'),
    ]},
]


SCOREBOOK = [
    ('Where it comes from', 'The scorebook is built from the pitch-by-pitch file, not from an official scorer. Results, hit types, hit direction and distance come from the data and the operator\'s tags, so treat it as a close guide, not an official box score.'),
    ('Result shorthand', 'K strikeout, BB walk, HBP hit by pitch, 1B single, 2B double, 3B triple, HR home run, BIP ball in play when the result could not be told, SH sacrifice bunt, SF sacrifice fly, FC fielder\'s choice, E error.'),
    ('Outs on balls in play', 'The first letter is how it was hit: G ground ball, L line drive, F fly ball, P pop-up. The number is the fielder it went to. A ground out is written as the fielder who fielded it, then 3 for the throw to first (6-3 is shortstop to first). 3U is unassisted at first. The fielder is worked out from the direction and distance of the ball.'),
    ('Position numbers', 'The standard scorebook numbers: 1 pitcher, 2 catcher, 3 first base, 4 second base, 5 third base, 6 shortstop, 7 left field, 8 center field, 9 right field.'),
    ('Runners and runs', 'The diamond in each box shows how far that batter got. A filled diamond means he scored. Where runners ended up is inferred from the results of the plate appearances behind them, since the pitch data has no baserunning, so steals and some advances on throws or errors can be missed.'),
    ('Pitching changes and pinch hitters', 'A hard line on the left of a box marks a pinch hitter entering. When a new pitcher comes in, his last name is written above the first batter he faces.'),
    ('Balls, strikes and pitch counts', 'The pitch count in each box counts every pitch thrown to that batter. A ball in play counts as a strike in the strike totals, and a foul with two strikes does not add a strike to the count.'),
]

DEFENSE = [
    ('What it is', 'A suggested fielding alignment for each hitter, built from where his tracked balls in play went. Starters with the most at-bats come first. A hitter with few tracked balls stays close to a standard alignment.'),
    ('Shade', 'A small adjustment: 1 to 2 steps in the intended direction.'),
    ('Shift', 'A major adjustment: 3 to 5 steps in the intended direction.'),
    ('Reading a call', 'Calls name the group, the call and the direction, such as "Infield Pull Shade" or "Outfield Oppo Shade". Pull and oppo are relative to the hitter, so the same call moves the other way for a lefty.'),
]


def sections(is_admin=False):
    s = [
        {'id': 'pitching', 'title': 'Pitching stats', 'groups': _group_pitching()},
        {'id': 'charts', 'title': 'Charts and visuals', 'groups': [{'title': '', 'items': CHARTS}]},
    ]
    s.append({'id': 'hitting', 'title': 'Hitting', 'groups': HITTING})
    s.append({'id': 'games', 'title': 'Game reports (scorebook)', 'groups': [{'title': '', 'items': SCOREBOOK}]})
    if is_admin:
        s.append({'id': 'defense', 'title': 'Defensive positioning (beta, admin only)', 'groups': [{'title': '', 'items': DEFENSE}]})
    s.append({'id': 'data', 'title': 'About the data', 'groups': [{'title': '', 'items': DATA_NOTES}]})
    return s
