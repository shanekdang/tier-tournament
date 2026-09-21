"""Fun statistics derived from a tournament's vote log.

Kept separate from the ranking engines in tournament.py: these numbers are
purely descriptive -- they never influence the ranking itself, they just
tell the story of how the group got there (what took forever to decide,
who was on a streak, who came up constantly).

Each vote_log entry (appended by app.py after every vote) looks like:
    {
        "a_id": str, "a_name": str, "b_id": str, "b_name": str,
        "choice": "a" | "b" | "tie",
        "winner_id": str | None, "winner_name": str | None,
        "loser_id": str | None, "loser_name": str | None,
        "duration_ms": int | None,   # time from matchup shown -> voted, client-timed
    }
"""
from __future__ import annotations

from collections import defaultdict

EMPTY_STATS = {
    "matchup_count": 0,
    "tie_count": 0,
    "total_duration_ms": 0,
    "heaviest_debates": [],
    "easiest_calls": [],
    "hot_streak": None,
    "most_contested": None,
}


def _format_matchup(entry: dict) -> dict:
    return {
        "a": entry["a_name"],
        "b": entry["b_name"],
        "duration_ms": entry["duration_ms"],
        "choice": entry["choice"],
    }


def compute_fun_stats(items: dict[str, str], vote_log: list[dict]) -> dict:
    if not vote_log:
        return dict(EMPTY_STATS)

    timed = [e for e in vote_log if isinstance(e.get("duration_ms"), (int, float))]
    n_show = 5 if len(vote_log) >= 8 else 3

    heaviest = sorted(timed, key=lambda e: e["duration_ms"], reverse=True)[:n_show]
    heavy_ids = {id(e) for e in heaviest}
    # Only pull "easiest" from matchups not already shown as "heaviest" --
    # matters for small tournaments where the two lists would otherwise
    # just repeat the same handful of matchups in reverse order.
    easiest_pool = [e for e in timed if id(e) not in heavy_ids] or timed
    easiest = sorted(easiest_pool, key=lambda e: e["duration_ms"])[:n_show]

    contested: dict[str, int] = defaultdict(int)
    per_candidate_results: dict[str, list[str]] = defaultdict(list)
    tie_count = 0
    for e in vote_log:
        contested[e["a_id"]] += 1
        contested[e["b_id"]] += 1
        if e["choice"] == "tie":
            tie_count += 1
            continue
        per_candidate_results[e["winner_id"]].append("W")
        per_candidate_results[e["loser_id"]].append("L")

    best_streak = 0
    streak_holders: list[str] = []
    for cid, results in per_candidate_results.items():
        run = 0
        best = 0
        for r in results:
            if r == "W":
                run += 1
                best = max(best, run)
            else:
                run = 0
        if best > best_streak:
            best_streak = best
            streak_holders = [cid]
        elif best == best_streak and best > 0:
            streak_holders.append(cid)

    max_contested = max(contested.values()) if contested else 0
    most_contested_ids = [cid for cid, c in contested.items() if c == max_contested]

    return {
        "matchup_count": len(vote_log),
        "tie_count": tie_count,
        "total_duration_ms": sum(e["duration_ms"] for e in timed),
        "heaviest_debates": [_format_matchup(e) for e in heaviest],
        "easiest_calls": [_format_matchup(e) for e in easiest],
        "hot_streak": (
            {"names": [items[cid] for cid in streak_holders[:3]], "streak": best_streak}
            if best_streak >= 2
            else None
        ),
        "most_contested": (
            {"names": [items[cid] for cid in most_contested_ids[:3]], "matchups": max_contested}
            if max_contested >= 2
            else None
        ),
    }
