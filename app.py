"""Tier Tournament -- local web app.

Run with:   python app.py
Then open:  http://127.0.0.1:5000

Everything runs on your own machine: Flask serves the page, votes are sent
to a small JSON API, and results are stored in data/tournaments.db
(SQLite, created automatically). No account, no hosting, nothing leaves
your computer.

Two modes share the same API shape (advance -> comparison -> vote -> repeat
-> standings), just backed by different engines:
  "full"  -- Tournament: ranks every candidate (tournament.py)
  "quick" -- QuickTournament: finds just the top N, far fewer comparisons

Every vote is also appended to a vote log (timestamped client-side, from
when the matchup appeared to when it was decided) so results can show fun
stats -- heaviest debates, easiest calls, streaks -- via stats.py.
"""
from __future__ import annotations

import json

from flask import Flask, jsonify, render_template, request

import storage
from stats import compute_fun_stats
from tournament import QuickTournament, Tournament

app = Flask(__name__)
storage.init_db()


def _load_engine(row: dict):
    """Reconstruct the right engine class for a stored row."""
    data = json.loads(row["engine_json"])
    if row["mode"] == "quick":
        return QuickTournament.from_dict(data)
    return Tournament.from_dict(data)


def _result_order(t) -> list[str]:
    """The engine-specific list of candidate ids in final order."""
    return t.placed if isinstance(t, QuickTournament) else t.final_order


def _matchup_payload(t, tid: str, category: str, mode: str, top_n, vote_log: list) -> dict:
    """Shape the engine's current state into what the frontend needs next:
    either the next matchup to show, or the final standings + fun stats."""
    pair = t.advance()
    if pair is None:
        order = _result_order(t)
        ranks = t.ranks()
        standings = [{"name": t.items[cid], "rank": r} for cid, r in zip(order, ranks)]
        return {
            "done": True,
            "id": tid,
            "category": category,
            "mode": mode,
            "top_n": top_n,
            "total_candidates": len(t.items),
            "comparisons": t.comparisons_count,
            "standings": standings,
            "fun_stats": compute_fun_stats(t.items, vote_log),
        }
    a, b = pair
    return {
        "done": False,
        "id": tid,
        "category": category,
        "mode": mode,
        "top_n": top_n,
        "comparisons": t.comparisons_count,
        "total_estimate": t.total_estimate,
        "a": {"id": a, "name": t.items[a]},
        "b": {"id": b, "name": t.items[b]},
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/active")
def api_active():
    """The most recent unfinished tournament, so the page can offer to resume it."""
    row = storage.get_active()
    if not row:
        return jsonify(None)
    t = _load_engine(row)
    vote_log = json.loads(row["vote_log_json"])
    return jsonify(_matchup_payload(t, row["id"], row["category"], row["mode"], row["top_n"], vote_log))


@app.route("/api/tournaments", methods=["POST"])
def api_create():
    body = request.get_json(force=True) or {}
    category = (body.get("category") or "Untitled Tournament").strip()
    names = [n.strip() for n in body.get("candidates", []) if n.strip()]
    mode = body.get("mode") or "full"
    if mode not in ("full", "quick"):
        return jsonify({"error": "Invalid mode."}), 400
    if len(names) < 2:
        return jsonify({"error": "Need at least two candidates."}), 400

    items = {str(i): name for i, name in enumerate(names)}
    top_n = None
    if mode == "quick":
        try:
            top_n = int(body.get("top_n") or 3)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid top_n."}), 400
        if top_n < 1:
            return jsonify({"error": "top_n must be at least 1."}), 400
        top_n = min(top_n, len(names))
        t = QuickTournament(items, top_n)
    else:
        t = Tournament(items)

    tid = storage.create(category, t.to_dict(), mode=mode, top_n=top_n)
    # advance() populates the first pending comparison; that mutation must
    # be persisted, or the next vote will find nothing pending.
    payload = _matchup_payload(t, tid, category, mode, top_n, vote_log=[])
    storage.update(tid, t.to_dict(), done=payload["done"], vote_log=[])
    return jsonify(payload)


@app.route("/api/tournaments/<tid>/vote", methods=["POST"])
def api_vote(tid):
    row = storage.get(tid)
    if not row or row["done"]:
        return jsonify({"error": "Tournament not found or already finished."}), 404
    body = request.get_json(force=True) or {}
    choice = body.get("choice")
    if choice not in ("a", "b", "tie"):
        return jsonify({"error": "Invalid choice."}), 400
    duration_ms = body.get("duration_ms")
    if not isinstance(duration_ms, (int, float)) or duration_ms < 0:
        duration_ms = None

    t = _load_engine(row)
    # advance() is a no-op if a comparison is already pending (the normal
    # case) -- it's here so a state saved before that happened can still
    # be voted on, rather than raising.
    pair = t.advance()
    a_id, b_id = pair
    a_name, b_name = t.items[a_id], t.items[b_id]

    t.vote(choice)

    if choice == "tie":
        winner_id = winner_name = loser_id = loser_name = None
    else:
        winner_id, loser_id = (a_id, b_id) if choice == "a" else (b_id, a_id)
        winner_name, loser_name = (a_name, b_name) if choice == "a" else (b_name, a_name)

    vote_log = json.loads(row["vote_log_json"])
    vote_log.append(
        {
            "a_id": a_id, "a_name": a_name,
            "b_id": b_id, "b_name": b_name,
            "choice": choice,
            "winner_id": winner_id, "winner_name": winner_name,
            "loser_id": loser_id, "loser_name": loser_name,
            "duration_ms": duration_ms,
        }
    )

    payload = _matchup_payload(t, tid, row["category"], row["mode"], row["top_n"], vote_log)
    storage.update(tid, t.to_dict(), done=payload["done"], vote_log=vote_log)
    return jsonify(payload)


@app.route("/api/tournaments/<tid>/abandon", methods=["POST"])
def api_abandon(tid):
    storage.delete(tid)
    return jsonify({"ok": True})


@app.route("/api/tournaments/<tid>", methods=["DELETE"])
def api_delete(tid):
    storage.delete(tid)
    return jsonify({"ok": True})


@app.route("/api/history")
def api_history():
    out = []
    for row in storage.list_history():
        t = _load_engine(row)
        order = _result_order(t)
        ranks = t.ranks()
        standings = [{"name": t.items[cid], "rank": r} for cid, r in zip(order, ranks)]
        vote_log = json.loads(row["vote_log_json"])
        out.append(
            {
                "id": row["id"],
                "category": row["category"],
                "mode": row["mode"],
                "top_n": row["top_n"],
                "total_candidates": len(t.items),
                "date": row["finished_at"],
                "comparisons": t.comparisons_count,
                "standings": standings,
                "fun_stats": compute_fun_stats(t.items, vote_log),
            }
        )
    return jsonify(out)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
