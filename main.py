"""Forecast GTA VI PS5 trophy earn rates on Exophase at a case's target.

Entry for make.fun bounty "gta6-trophy-rarity-forecast-01". Python 3.13,
standard library only, no network, deterministic: the same case always
produces the same forecast file.

How it works
------------
The case file carries every read the house made of the game's Exophase
trophy page before the checkpoint: each read prints the players tracked
and every trophy's earn rate (percent of tracked players holding it).
Exophase only refreshes those numbers on its own schedule, so consecutive
identical reads are one observation, not many; the program first reduces
the history to its distinct snapshots.

Two views of each trophy are then combined:

1. Exposure view. A trophy's earn rate is a share of a growing player
   base. New players dilute the share, veterans push it up. The mean
   tenure of the tracked base, A(t) = (integral of players dt) / players,
   falls when fresh players flood in and rises as the base ages, so a
   saturating curve share(A) = S * (1 - exp(-k * A)) fitted per trophy
   reproduces both the early dilution dip and the later climb. The
   players-tracked count itself is forecast to the target with an
   ensemble of a power-law fit and saturating-exponential fits, which
   gives A at the target.

2. Trend view. A least-squares line of the trophy's logit rate against
   log elapsed time over the recent reads, read at the target. This is a
   different functional family from the exposure curve, so where the two
   agree the forecast is trusted more, and where they disagree the
   spread widens.

The median is a fixed blend of the two views in logit space. The spread
combines a random-walk term growing with the horizon, the trend fit's
residual variance, the disagreement between the views, and a sampling
term for trophies held by only a handful of tracked players. Trophies
nobody has earned yet get a small tier-based median with a wide spread.
Finally the story chain (Chapter 1 .. 4, then the final mission) is made
non-increasing with a pool-adjacent-violators pass, the 100%-completion
trophy is capped at the final mission's median, and the platinum is
capped at the rarest other trophy, because those rates cannot exceed
the rates of the trophies they require.

Run by the grader as `python3 -P -s /bot/main.py` with the case in
/input and forecasts written to /output; MAKEFUN_INPUT_DIR and
MAKEFUN_OUTPUT_DIR override the two directories for local runs.
"""

import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

RATE_LO = 0.01
RATE_HI = 99.99

# Eventual-share ceilings by tier for the exposure fit: a platinum is
# ultimately held by a small minority of a tracked base, a bronze by most.
TIER_SHARE_CAP = {"platinum": 0.30, "gold": 0.65, "silver": 0.85, "bronze": 0.98}

# Medians for trophies with no earner in any read, by tier (percent).
ZERO_MEDIAN = {"platinum": 0.01, "gold": 0.015, "silver": 0.03, "bronze": 0.03}


def clamp_rate(x):
    return min(RATE_HI, max(RATE_LO, x))


def logit(pct):
    p = clamp_rate(pct) / 100.0
    return math.log(p / (1.0 - p))


def logistic(lg):
    return 100.0 / (1.0 + math.exp(-lg))


def round4(x):
    """Round to 4 decimals, half up; whole numbers stay whole in JSON."""
    scaled = x * 10000.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000.0
    return int(value) if float(value).is_integer() else value


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def linfit(xs, ys, ws=None):
    """Weighted least squares y ~ a + b*x. Returns (a, b, residual_var)."""
    n = len(xs)
    if ws is None:
        ws = [1.0] * n
    sw = sum(ws)
    if sw <= 0:
        return 0.0, 0.0, 0.0
    mx = sum(w * x for x, w in zip(xs, ws)) / sw
    my = sum(w * y for y, w in zip(ys, ws)) / sw
    sxx = sum(w * (x - mx) ** 2 for x, w in zip(xs, ws))
    if sxx <= 1e-12:
        return my, 0.0, 0.0
    sxy = sum(w * (x - mx) * (y - my) for x, y, w in zip(xs, ys, ws))
    b = sxy / sxx
    a = my - b * mx
    if n > 2:
        resid = sum(w * (y - (a + b * x)) ** 2 for x, y, w in zip(xs, ys, ws)) / sw
    else:
        resid = 0.0
    return a, b, resid


def distinct_snapshots(history):
    """Collapse consecutive reads with identical players and rates."""
    snaps = []
    for read in history:
        key = (read["players_tracked"], tuple(read["rates"]))
        if snaps and snaps[-1][0] == key:
            continue
        snaps.append((key, read))
    return [read for _, read in snaps]


def forecast_players(snaps, t_days, target_day):
    """Forecast players_tracked at target_day; also return A(target).

    t_days are the snapshot times in days since the first snapshot.
    A(t) is the tracked base's mean tenure under the printed step series.
    """
    times = t_days
    counts = [float(s["players_tracked"]) for s in snaps]
    last_n = counts[-1]
    horizon = target_day - times[-1]

    # Step integral of the printed counts, and mean tenure at each snap.
    integral = [0.0]
    for j in range(1, len(snaps)):
        integral.append(integral[-1] + counts[j - 1] * (times[j] - times[j - 1]))
    tenure = [integral[j] / counts[j] if counts[j] > 0 else 0.0 for j in range(len(snaps))]

    forecasts = []
    distinct_counts = sorted(set(counts))
    if len(distinct_counts) >= 2 and times[-1] > times[0]:
        # Power law: ln N against ln(1 + hours since first snapshot).
        xs = [math.log1p((t - times[0]) * 24.0) for t in times]
        ys = [math.log(max(n, 1.0)) for n in counts]
        a, b, _ = linfit(xs, ys)
        xt = math.log1p((target_day - times[0]) * 24.0)
        forecasts.append(math.exp(a + b * xt))
        # Saturating exponentials: ln(N_inf - N) linear in t.
        for mult in (1.5, 2.0, 3.0, 5.0, 8.0):
            n_inf = last_n * mult
            if all(n_inf - n > 0 for n in counts):
                ys2 = [math.log(n_inf - n) for n in counts]
                a2, b2, _ = linfit(times, ys2)
                if b2 < 0:
                    forecasts.append(n_inf - math.exp(a2 + b2 * target_day))
    if forecasts:
        logs = [math.log(min(max(f, last_n), last_n * 40.0)) for f in forecasts if f > 0]
        n_target = math.exp(sum(logs) / len(logs)) if logs else last_n
    else:
        n_target = last_n
    n_target = min(max(n_target, last_n), last_n * 40.0)

    # Mean tenure at the target: extend the integral with a trapezoid of
    # the count path from the last snapshot to the target.
    area = integral[-1] + 0.5 * (last_n + n_target) * max(horizon, 0.0)
    a_target = area / n_target if n_target > 0 else tenure[-1]
    return n_target, tenure, a_target


def exposure_forecast(points, tier, a_target):
    """Fit share(A) = S*(1-exp(-k*A)) on (A, share, weight) points.

    Returns the forecast share (a fraction) at a_target, or None when the
    trophy has points but the fit is unusable.
    """
    pts = [(a, s, w) for a, s, w in points if s > 0.0]
    if not pts:
        return None
    s_last = points[-1][1]
    cap = TIER_SHARE_CAP.get(tier, 0.98)
    best = None
    # Fixed grid of rates k (per day of mean tenure), deterministic.
    grid = [0.02 * (1.13 ** i) for i in range(48)]
    for k in grid:
        num = 0.0
        den = 0.0
        for a, s, w in pts:
            d = 1.0 - math.exp(-k * a)
            num += w * s * d
            den += w * d * d
        if den <= 1e-15:
            continue
        s_hat = min(max(num / den, s_last), cap)
        sse = 0.0
        for a, s, w in pts:
            d = 1.0 - math.exp(-k * a)
            sse += w * (s - s_hat * d) ** 2
        if best is None or sse < best[0]:
            best = (sse, s_hat, k)
    if best is None:
        return None
    _, s_hat, k = best
    return s_hat * (1.0 - math.exp(-k * a_target))


def trend_forecast(points_t_logit, target_x):
    """Least-squares logit rate against log-hours; returns (rate, resid_var)."""
    if len(points_t_logit) < 3:
        return None, 0.0
    xs = [p[0] for p in points_t_logit]
    ys = [p[1] for p in points_t_logit]
    if max(xs) - min(xs) < 1e-9:
        return None, 0.0
    a, b, resid = linfit(xs, ys)
    return logistic(a + b * target_x), resid


CHAPTER_RE = re.compile(r"Complete Chapter (\d+)\.")


def story_chain_order(trophies):
    """Indices of the story chain in required order, plus special trophies."""
    chain = []
    for idx, t in enumerate(trophies):
        m = CHAPTER_RE.search(t["description"])
        if m:
            chain.append((int(m.group(1)), idx))
        elif t["description"] == "Complete the final mission.":
            chain.append((99, idx))
    chain.sort()
    return [idx for _, idx in chain]


def pava_nonincreasing(values):
    """Pool adjacent violators: the greatest non-increasing fit (L2)."""
    blocks = [[v, 1] for v in values]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] < blocks[i + 1][0] - 1e-15:
            total = blocks[i][0] * blocks[i][1] + blocks[i + 1][0] * blocks[i + 1][1]
            count = blocks[i][1] + blocks[i + 1][1]
            blocks[i] = [total / count, count]
            del blocks[i + 1]
            if i > 0:
                i -= 1
        else:
            i += 1
    out = []
    for v, c in blocks:
        out.extend([v] * c)
    return out


def forecast_case(case):
    if case["levels"] != LEVELS:
        raise ValueError("unexpected levels")
    trophies = case["trophies"]
    history = case["history"]
    if not history:
        raise ValueError("empty history")

    t0 = parse_time(history[0]["at"])
    target_dt = parse_time(case["target"])
    target_day = (target_dt - t0).total_seconds() / 86400.0
    horizon_days = case["horizon_minutes"] / 1440.0

    snaps = distinct_snapshots(history)
    snap_days = [(parse_time(s["at"]) - t0).total_seconds() / 86400.0 for s in snaps]
    n_target, tenure, a_target = forecast_players(snaps, snap_days, target_day)
    n_last = float(snaps[-1]["players_tracked"])

    medians = []   # logit of the median rate, per trophy
    spreads = []   # sigma on the logit scale, per trophy
    for i, trophy in enumerate(trophies):
        pts_share = []   # (tenure, share fraction, weight=players)
        pts_trend = []   # (snap day, log-hours since first snap, logit rate)
        last_rate = None
        for j, snap in enumerate(snaps):
            rate = snap["rates"][i]
            if rate is None:
                continue
            last_rate = rate
            pts_share.append((tenure[j], rate / 100.0, float(snap["players_tracked"])))
            hours = snap_days[j] * 24.0
            pts_trend.append((snap_days[j], math.log1p(hours), logit(rate)))
        if last_rate is None:
            last_rate = 0.0
        earners_last = last_rate / 100.0 * n_last

        # Recent-window trend (last 24 h of reads); fall back to all points.
        cutoff = snap_days[-1] - 1.0
        recent = [(x, y) for d, x, y in pts_trend if d >= cutoff]
        all_pts = [(x, y) for _, x, y in pts_trend]
        trend_pts = recent if len(recent) >= 3 else all_pts
        target_x = math.log1p(target_day * 24.0)
        trend_rate, trend_resid = trend_forecast(trend_pts, target_x)

        exp_share = exposure_forecast(pts_share, trophy["tier"], a_target)
        exp_rate = None if exp_share is None else clamp_rate(exp_share * 100.0)

        if last_rate <= 0.0 and exp_rate is None:
            med = logit(ZERO_MEDIAN.get(trophy["tier"], 0.03))
            sigma = 1.15
        else:
            views = []
            if exp_rate is not None:
                views.append((0.55, logit(exp_rate)))
            if trend_rate is not None:
                views.append((0.45, logit(trend_rate)))
            if views:
                wsum = sum(w for w, _ in views)
                med = sum(w * v for w, v in views) / wsum
            else:
                med = logit(last_rate)
            # Damp the move away from the last printed rate a little (both
            # views extrapolate, and extrapolation overshoots), and keep the
            # blend within a sane move of that rate.
            base = logit(last_rate if last_rate > 0 else RATE_LO)
            move = med - base
            if abs(move) > 0.3:
                med = base + math.copysign(0.3 + 0.9 * (abs(move) - 0.3), move)
            med = min(max(med, base - 1.6), base + 5.0)
            disagree = 0.0
            if exp_rate is not None and trend_rate is not None:
                disagree = abs(logit(exp_rate) - logit(trend_rate))
            var = 0.20 * horizon_days            # random-walk part (0.45^2 ~ 0.20)
            var += min(trend_resid, 1.5)         # trend fit's own noise
            var += 0.25 * disagree * disagree    # model disagreement
            var += 0.5 / max(earners_last, 1.0)  # few-earner sampling noise
            sigma = min(max(math.sqrt(var), 0.30), 2.40)
        medians.append(med)
        spreads.append(sigma)

    # Structural caps, applied as logit shifts of the whole row.
    shifts = [0.0] * len(trophies)
    chain = story_chain_order(trophies)
    if len(chain) >= 2:
        fitted = pava_nonincreasing([medians[i] for i in chain])
        for pos, idx in enumerate(chain):
            shifts[idx] += fitted[pos] - medians[idx]
    by_desc = {t["description"]: i for i, t in enumerate(trophies)}
    if "Complete the final mission." in by_desc and "Attain 100% Completion." in by_desc:
        fi = by_desc["Complete the final mission."]
        ci = by_desc["Attain 100% Completion."]
        cap = medians[fi] + shifts[fi]
        if medians[ci] + shifts[ci] > cap:
            shifts[ci] += cap - (medians[ci] + shifts[ci])
    if trophies and trophies[0]["tier"] == "platinum":
        others = [medians[i] + shifts[i] for i in range(1, len(trophies))]
        if others:
            cap = min(others)
            if medians[0] + shifts[0] > cap:
                shifts[0] += cap - (medians[0] + shifts[0])

    rows = []
    for i, trophy in enumerate(trophies):
        med = medians[i] + shifts[i]
        qs = []
        for z in Z:
            q = logistic(med + z * spreads[i])
            qs.append(round4(clamp_rate(q)))
        for j in range(1, len(qs)):
            if qs[j] < qs[j - 1]:
                qs[j] = qs[j - 1]
        rows.append({"id": trophy["id"], "q": qs})
    return {"trophies": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        result = forecast_case(case)
        text = json.dumps(result, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / (path.stem + ".out")).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
