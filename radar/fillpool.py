"""Run ingest, sieve, enrich in a loop until the enriched pool reaches the
target (companies_per_issue), or until a full round adds no new enriched
company, meaning the live sources are exhausted for the current lookback
window.

It never relaxes the four gates and never pads. If the real London
sources yield fewer than the target in the window, it stops and says so:
feature the real ones, and widen discovery (more sources, the accelerator
watchlist) over time rather than stretching the gates to hit a number.

  python -m radar.fillpool [--target N] [--max-rounds N] [--fixtures]

This writes to the working database (it advances the pipeline); it never
publishes, posts, or sends anything.
"""

import argparse
import sys

from radar import config, db, domains, enrich, ingest, sieve, stats, util


def _enriched_count(db_path):
    conn = db.connect(db_path)
    db.init_db(conn)
    n = stats.pipeline_counts(conn).get("enriched", 0)
    conn.close()
    return n


def _run_pipeline_round(db_path, fixtures):
    """One ingest, domains, sieve, enrich pass. Returns (ok, reason). Stops
    the round at the first stage that fails so the caller can report it.

    domains runs between ingest and sieve so a discovered company without a
    website gets a verified one before the reality gate, instead of dropping
    for want of a link nobody added to website_overrides."""
    base = ["--db", db_path] if db_path else []
    extra = ["--fixtures"] if fixtures else []
    for module, name in ((ingest, "ingest"), (domains, "domains"),
                         (sieve, "sieve"), (enrich, "enrich")):
        rc = module.main(base + extra)
        if rc not in (0, None):
            return False, "%s failed (rc=%s)" % (name, rc)
    return True, ""


def fill_pool(db_path=None, target=None, max_rounds=8, fixtures=False,
              _round=None, _count=None):
    """Loop ingest, sieve, enrich until enriched >= target or a round adds
    nothing. _round and _count are injection points for tests."""
    if target is None:
        target = config.companies_per_issue()
    do_round = _round or (lambda: _run_pipeline_round(db_path, fixtures))
    count = _count or (lambda: _enriched_count(db_path))

    start = count()
    prev = start
    rounds = []
    reason = "stopped"

    for i in range(max_rounds):
        if prev >= target:
            break
        ok, err = do_round()
        if not ok:
            reason = err
            break
        now = count()
        rounds.append({"round": i + 1, "enriched": now, "added": now - prev})
        if now <= prev:
            reason = "no new companies; live sources exhausted for this window"
            prev = now
            break
        prev = now

    if prev >= target:
        reason = "target reached"
    elif reason == "stopped":
        reason = "hit the max-rounds cap (%d)" % max_rounds

    return {"start": start, "end": prev, "target": target,
            "reached": prev >= target, "rounds": rounds, "reason": reason}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.fillpool", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    util.add_common_args(parser, as_of=False)
    parser.add_argument("--target", type=int, default=None,
                        help="enriched companies to aim for "
                             "(default: companies_per_issue)")
    parser.add_argument("--max-rounds", type=int, default=8,
                        help="safety cap on ingest/sieve/enrich rounds "
                             "(default 8)")
    args = parser.parse_args(argv)

    target = args.target or config.companies_per_issue()
    print("fillpool: aiming for %d enriched companies; it stops early if a "
          "round adds nothing new, and never relaxes the gates." % target)
    print()
    result = fill_pool(args.db, target=target, max_rounds=args.max_rounds,
                       fixtures=args.fixtures)
    print()
    for r in result["rounds"]:
        print("  round %d: %d enriched (+%d)"
              % (r["round"], r["enriched"], r["added"]))
    print()
    print("fillpool: %d -> %d enriched of %d target. %s"
          % (result["start"], result["end"], result["target"], result["reason"]))
    if not result["reached"]:
        print("  Honest stop: no gate was relaxed and nothing was padded. "
              "Feature the real ones and widen discovery over time.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
