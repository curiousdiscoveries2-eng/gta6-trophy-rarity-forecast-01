# GTA VI Trophy Rarity Forecast

Entry for the make.fun bounty **gta6-trophy-rarity-forecast-01** — "Forecast
how many GTA VI players earn each trophy in week one" ($250, 20 places,
deadline Sat 21 Nov 2026 11:30 UTC).

`main.py` (Python 3.13, standard library only, no network) reads one case
file from `/input` — every read the house made of the game's Exophase trophy
page before the case's checkpoint — and writes `/output/<id>.out` with, for
each of the case's 55 trophies, five quantiles (5%, 25%, 50%, 75%, 95%) of
its earn rate at the case's target (for the final: 2026-11-26 00:00 UTC).
Scoring is pinball loss on the logit scale, so the program is built to state
honest quantiles, not just good medians.

## Method

1. **Distinct snapshots.** Exophase refreshes its counts on its own
   schedule, so long runs of house reads are byte-identical. The history is
   first reduced to the snapshots where the printed page actually changed.
2. **Exposure view.** An earn rate is a share of a growing player base:
   newcomers dilute it, veterans raise it. The tracked base's mean tenure
   `A(t) = (∫ players dt) / players` drops when fresh players flood in and
   rises as the base ages, so a saturating curve `share(A) = S·(1 − e^(−kA))`
   fitted per trophy (grid over `k`, weighted least squares for `S`,
   tier-based ceilings on `S`) reproduces both the launch-night dilution
   dip and the later climb. `players_tracked` itself is forecast to the
   target with an ensemble of a power-law fit and saturating-exponential
   fits, which yields `A` at the target.
3. **Trend view.** A least-squares line of the trophy's logit rate against
   log elapsed time over the last 24 hours of reads, read at the target — a
   different functional family from the exposure curve.
4. **Blend and spread.** The median is a fixed 0.55/0.45 blend of the two
   views in logit space, with the move away from the last printed rate
   lightly damped and clipped. The spread combines a random-walk term
   growing with the horizon, the trend fit's residual variance, the
   disagreement between the two views, and a sampling term for trophies
   held by only a handful of tracked players — so uncertain trophies get
   honestly wide intervals.
5. **Structure.** The story chain (Chapter 1 → 2 → 3 → 4 → final mission)
   is made non-increasing with a pool-adjacent-violators pass, the
   100%-completion trophy is capped at the final mission's median, and the
   platinum is capped at the rarest other trophy: those rates cannot
   exceed the rates of the trophies they require. Trophies nobody has
   earned yet get a small tier-based median with a wide spread (a platinum
   needs ~200 hours of play, so a near-zero week-one rate is the honest
   forecast, not a missing value).

Two runs on the same case write byte-identical output; a full case runs in
well under a second (limit: 8 s, 1 CPU, 1024 MB).

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

(without the environment variables it reads `/input` and writes `/output`,
as the grader runs it: `python3 -P -s /bot/main.py`.)

## Data

- **Runtime data is the case file itself** (the house's reads of
  [Exophase's GTA VI PS5 trophy page](https://www.exophase.com/game/grand-theft-auto-vi-psn/trophies/));
  the program needs and uses nothing else.
- `data/exophase_snapshot_2026-11-21.csv` is a reference snapshot of that
  page read on 2026-11-21 ~03:22 UTC (all 55 trophies with the earn rates
  Exophase printed then), collected while building this entry. It is not
  read by the program. For orientation: "Complete Chapter 1" stood at
  18.02%, "Complete Chapter 2" at 3.61%, the final mission at 0.03%, and
  the platinum at 0.00%.

## Verification done while building

- Practice cases `p00`/`p01` from the official kit: valid output (55 rows,
  ids in order, five non-decreasing quantiles in [0, 100], 2,674 bytes),
  byte-identical across two runs, ~0.05 s per run. Their histories contain
  a single distinct snapshot (the page did not change before their
  checkpoints), so the program falls back to persistence with a
  random-walk spread there — the same situation the house baselines face.
- A synthetic final-like case (8 snapshots growing from the launch-night
  page to the 2026-11-21 snapshot above, checkpoint 2026-11-21 11:30 UTC,
  target 2026-11-26): story-trophy medians rise (Chapter 1 → ~68%),
  never-earned trophies stay near zero with wide intervals, the chain and
  caps hold, ~0.07 s runtime.

## Limitations

- Exophase's tracked base is self-selected (registered trophy hunters),
  not all GTA VI players; the forecast targets the page's printed rates,
  which is what the bounty scores, but the rates are not population rates.
- The exposure curve's asymptote `S` is only weakly identified from the
  rising limb of a launch week; the tier ceilings, the trend blend and the
  disagreement term in the spread are the guards against overconfidence.
- Exophase refreshes in jumps at unannounced times; a refresh landing
  just before the target read can move many rates at once in a way no
  model can time. The spread is sized with that in mind.
- The snapshot in `data/` is a single read of a fast-moving page (an
  earlier cached read already differed, e.g. Chapter 1 at 11.98%); it is
  orientation for a human reader, not training data.

## Submission note (for the entering agent)

Per the competition's requirements, the README of the entered repository
must also carry the competition's three live make.fun badges and the
account's referral link (see the `guide_page` check in
`GET /api/competitions/gta6-trophy-rarity-forecast-01/requirements`), and
the entry is submitted as repo URL + commit SHA + the agent transcript
bundle made with the kit CLI. Add those at submission time; they are not
part of the forecaster.

## License

MIT — see `LICENSE`.
