"""Core tournament ranking engine.

Ranks every candidate by running it through a queue-based bottom-up merge
sort, where each comparison is supplied by a person instead of a comparator
function. This produces a full ranking of every candidate in roughly
n*log2(n) head-to-head matchups, instead of a full round-robin (n*(n-1)/2)
or a single-elimination bracket (which only ever crowns one winner).

The engine holds no I/O or web concerns -- it is plain data plus two
methods (`advance` and `vote`) so it is easy to serialize to/from JSON for
storage, and easy to test on its own.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Optional


def estimate_comparisons(n: int) -> int:
    """Worst-case number of matchups needed to fully rank n candidates.

    Mirrors the exact merge order the engine below uses, so this is an
    upper bound the live comparison count will reach only in the worst
    case (progress bars should treat it as "up to", not exact).
    """
    if n < 2:
        return 0
    queue = [1] * n
    total = 0
    while len(queue) > 1:
        left, right = queue.pop(0), queue.pop(0)
        total += left + right - 1
        queue.append(left + right)
    return total


@dataclass
class MergeState:
    left: list
    right: list
    i: int = 0
    j: int = 0
    result: list = field(default_factory=list)


class Tournament:
    """A single tournament's ranking engine."""

    def __init__(self, items: dict[str, str]):
        # items: candidate id -> candidate name
        self.items = items
        self.queue: list[list[str]] = [[cid] for cid in items]
        self.current: Optional[MergeState] = None
        self.ties: list[tuple[str, str]] = []
        self.comparisons_count = 0
        self.total_estimate = estimate_comparisons(len(items))
        self.done = False
        self.final_order: Optional[list[str]] = None

    def advance(self):
        """Advance until a comparison is needed or the sort is complete.

        Returns (a_id, b_id) if a decision is needed, or None once the
        full ranking is settled (self.final_order is populated then).
        """
        while True:
            if self.current:
                cur = self.current
                if cur.i < len(cur.left) and cur.j < len(cur.right):
                    return cur.left[cur.i], cur.right[cur.j]
                merged = cur.result + cur.left[cur.i:] + cur.right[cur.j:]
                self.queue.append(merged)
                self.current = None
                continue
            if len(self.queue) <= 1:
                self.done = True
                self.final_order = self.queue[0] if self.queue else []
                return None
            left = self.queue.pop(0)
            right = self.queue.pop(0)
            self.current = MergeState(left=left, right=right)

    def vote(self, choice: str) -> None:
        """Record the decision for the currently pending comparison.

        choice: 'a' (left wins), 'b' (right wins), or 'tie'.
        """
        if choice not in ("a", "b", "tie"):
            raise ValueError(f"invalid choice: {choice!r}")
        cur = self.current
        if cur is None:
            raise RuntimeError("vote() called with no pending comparison -- call advance() first")
        self.comparisons_count += 1
        if choice == "tie":
            self.ties.append((cur.left[cur.i], cur.right[cur.j]))
            cur.result.append(cur.left[cur.i])
            cur.result.append(cur.right[cur.j])
            cur.i += 1
            cur.j += 1
        elif choice == "a":
            cur.result.append(cur.left[cur.i])
            cur.i += 1
        else:
            cur.result.append(cur.right[cur.j])
            cur.j += 1

    def ranks(self) -> list[int]:
        """Standard competition ranking (1,2,2,4,...) over self.final_order,
        using recorded ties to let adjacent tied candidates share a rank."""
        if self.final_order is None:
            raise RuntimeError("ranks() called before the tournament finished")
        tie_set = {tuple(sorted(p)) for p in self.ties}
        result = []
        for k, cid in enumerate(self.final_order):
            if k == 0:
                result.append(1)
                continue
            key = tuple(sorted((self.final_order[k - 1], cid)))
            result.append(result[k - 1] if key in tie_set else k + 1)
        return result

    def to_dict(self) -> dict:
        return {
            "items": self.items,
            "queue": self.queue,
            "current": None if self.current is None else asdict(self.current),
            "ties": [list(p) for p in self.ties],
            "comparisons_count": self.comparisons_count,
            "total_estimate": self.total_estimate,
            "done": self.done,
            "final_order": self.final_order,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Tournament":
        obj = cls.__new__(cls)
        obj.items = data["items"]
        obj.queue = data["queue"]
        obj.current = MergeState(**data["current"]) if data["current"] else None
        obj.ties = [tuple(p) for p in data["ties"]]
        obj.comparisons_count = data["comparisons_count"]
        obj.total_estimate = data["total_estimate"]
        obj.done = data["done"]
        obj.final_order = data["final_order"]
        return obj


def estimate_quick_comparisons(n: int, top_n: int) -> int:
    """Rough upper-bound comparison count for QuickTournament: n-1 for the
    knockout that finds 1st place (this part is exact -- a knockout of n
    always takes exactly n-1 matches), plus one small playoff per further
    place, each roughly log2(n) matches at worst."""
    if n < 2:
        return 0
    top_n = max(1, min(top_n, n))
    total = n - 1
    remaining = n - 1
    for _ in range(top_n - 1):
        pool_guess = max(2, math.ceil(math.log2(max(remaining, 2))) + 1)
        total += pool_guess - 1
        remaining -= 1
    return total


class QuickTournament:
    """Finds just the top `top_n` candidates, in order, without ranking
    everyone else.

    Phase 1 is a single-elimination knockout over every candidate: each
    match eliminates its loser, so crowning 1st place always takes exactly
    n-1 matches, regardless of outcomes -- far fewer than a full ranking.

    Phase 2+: to find the next place, only the candidates who lost
    *directly* to someone already placed are still in contention -- anyone
    else lost to a non-placed candidate, so (assuming consistent
    preferences) they can't outrank the placed candidates either. That
    small pool plays its own mini-knockout to settle the next place.
    """

    def __init__(self, items: dict[str, str], top_n: int):
        self.items = items
        self.top_n = max(1, min(top_n, len(items)))
        self.beaten: dict[str, list[str]] = {cid: [] for cid in items}
        self.ties: list[tuple[str, str]] = []
        self.comparisons_count = 0
        self.total_estimate = estimate_quick_comparisons(len(items), self.top_n)
        self.done = False
        self.placed: list[str] = []
        self._active: set[str] = set(items.keys())
        self._queue: list[str] = list(items.keys())
        self._pending_pair: Optional[tuple[str, str]] = None

    def advance(self):
        """Advance until a comparison is needed or the top-N is settled.

        Returns (a_id, b_id) if a decision is needed, or None once
        self.placed holds (up to) top_n candidates in order.
        """
        while True:
            if self._pending_pair:
                return self._pending_pair
            if len(self._queue) > 1:
                a = self._queue.pop(0)
                b = self._queue.pop(0)
                self._pending_pair = (a, b)
                return self._pending_pair
            if len(self._queue) == 1:
                winner = self._queue.pop()
                self.placed.append(winner)
                self._active.discard(winner)
                if len(self.placed) >= self.top_n or not self._active:
                    self.done = True
                    return None
                pool = set()
                for p in self.placed:
                    pool.update(self.beaten[p])
                pool &= self._active
                if not pool:
                    self.done = True
                    return None
                self._queue = list(pool)
                continue
            # queue exhausted with nothing pending and nothing to place --
            # only reachable if items was empty.
            self.done = True
            return None

    def vote(self, choice: str) -> None:
        """choice: 'a' (left wins), 'b' (right wins), or 'tie'."""
        if choice not in ("a", "b", "tie"):
            raise ValueError(f"invalid choice: {choice!r}")
        if not self._pending_pair:
            raise RuntimeError("vote() called with no pending comparison -- call advance() first")
        a, b = self._pending_pair
        self.comparisons_count += 1
        if choice == "tie":
            self.ties.append((a, b))
        winner, loser = (b, a) if choice == "b" else (a, b)
        self.beaten[winner].append(loser)
        self._queue.append(winner)
        self._pending_pair = None

    def ranks(self) -> list[int]:
        """Standard competition ranking over self.placed, same convention
        as Tournament.ranks()."""
        tie_set = {tuple(sorted(p)) for p in self.ties}
        result = []
        for k, cid in enumerate(self.placed):
            if k == 0:
                result.append(1)
                continue
            key = tuple(sorted((self.placed[k - 1], cid)))
            result.append(result[k - 1] if key in tie_set else k + 1)
        return result

    def to_dict(self) -> dict:
        return {
            "items": self.items,
            "top_n": self.top_n,
            "beaten": self.beaten,
            "ties": [list(p) for p in self.ties],
            "comparisons_count": self.comparisons_count,
            "total_estimate": self.total_estimate,
            "done": self.done,
            "placed": self.placed,
            "active": list(self._active),
            "queue": self._queue,
            "pending_pair": list(self._pending_pair) if self._pending_pair else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QuickTournament":
        obj = cls.__new__(cls)
        obj.items = data["items"]
        obj.top_n = data["top_n"]
        obj.beaten = {k: list(v) for k, v in data["beaten"].items()}
        obj.ties = [tuple(p) for p in data["ties"]]
        obj.comparisons_count = data["comparisons_count"]
        obj.total_estimate = data["total_estimate"]
        obj.done = data["done"]
        obj.placed = data["placed"]
        obj._active = set(data["active"])
        obj._queue = data["queue"]
        obj._pending_pair = tuple(data["pending_pair"]) if data["pending_pair"] else None
        return obj
