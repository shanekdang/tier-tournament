# Tier Tournament

Build a roster of anything (fruits, movies, restaurants...), then rank the
whole list by voting on head-to-head matchups. Instead of a single-elimination
bracket (which only crowns one winner) or a full round-robin (which needs
n*(n-1)/2 comparisons), this uses a merge-sort-based comparison order that
produces a complete ranking of every candidate in roughly n*log2(n) matchups.

Runs entirely on your own machine — no account, no hosting, nothing leaves
your computer. Data is stored locally in `data/tournaments.db` (SQLite).

## Setup

```
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

## How it works

1. **Setup** — name a category and add contenders (one at a time, or paste a
   whole list).
2. **Tournament** — vote on each matchup: red corner, blue corner, or "too
   close to call." Progress is saved after every vote, so closing the tab
   mid-tournament is safe — reopen the page and you'll be offered a **Resume**.
3. **Results** — a numbered ranking of everyone, medal-marked top 3, ties
   called out. Past tournaments are kept under **History**.

## Project layout

```
app.py            Flask routes / JSON API
tournament.py      Core ranking engine (no framework dependency — plain
                    data + advance()/vote(), easy to unit test on its own)
storage.py          SQLite persistence
templates/index.html  Page shell
static/style.css      Styling
static/app.js         Frontend logic (talks to the API via fetch)
data/                 SQLite database lives here (gitignored)
```

## Extending it later

Some natural next steps, since this is meant to grow:
- Swap the "one shared device" flow for remote voting (each friend opens the
  page on their own phone and the group's votes get combined).
- Export standings as an image instead of just text.
- Group results into S/A/B/C tiers instead of a strict numbered list.
- Add authentication if this ever needs to run somewhere other than your
  own machine.
