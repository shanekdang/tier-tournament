(function () {
  "use strict";

  /* ---------- tiny fetch helpers ---------- */
  function api(path, options) {
    return fetch(path, options).then(function (res) {
      if (!res.ok) return res.json().then(function (e) { throw new Error(e.error || res.statusText); });
      return res.json();
    });
  }
  function apiGet(path) { return api(path); }
  function apiPost(path, body) {
    return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  }
  function apiDelete(path) { return api(path, { method: "DELETE" }); }

  /* ---------- local draft (roster being built, before a tournament exists server-side) ---------- */
  var DRAFT_KEY = "tt.draft";
  function loadDraft() {
    try {
      var raw = localStorage.getItem(DRAFT_KEY);
      var parsed = raw ? JSON.parse(raw) : null;
      return Object.assign({ category: "", roster: [], mode: "full", topN: 3 }, parsed || {});
    } catch (e) { return { category: "", roster: [], mode: "full", topN: 3 }; }
  }
  function saveDraft() {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); } catch (e) { /* ignore */ }
  }

  var draft = loadDraft();
  var activeTournament = null; // last payload from /api/active or /api/tournaments
  var resultsSource = "live"; // "live" | "history"
  var historyCache = [];

  /* ---------- element refs ---------- */
  var el = {};
  ["view-setup", "view-tournament", "view-results", "view-history",
   "resume-banner", "resume-title", "resume-sub", "btn-resume", "btn-discard",
   "input-category", "input-candidate", "btn-add", "add-msg",
   "btn-toggle-bulk", "bulk-area", "input-bulk", "btn-add-bulk",
   "roster-list", "roster-empty", "btn-begin",
   "mode-toggle", "mode-desc", "topn-row", "topn-toggle",
   "bout-category", "bout-counter", "progress-fill",
   "card-a", "name-a", "card-b", "name-b", "btn-tie", "btn-abandon",
   "results-eyebrow", "results-category", "results-stat", "results-list", "btn-copy", "btn-pdf", "btn-new", "btn-back-history",
   "print-date",
   "fun-stats", "stat-tiles", "heaviest-list", "easiest-list",
   "history-list", "history-empty", "btn-back-setup", "btn-history"
  ].forEach(function (id) { el[id] = document.getElementById(id); });

  function showView(name) {
    ["view-setup", "view-tournament", "view-results", "view-history"].forEach(function (v) {
      document.getElementById(v).hidden = (v !== name);
    });
    el["btn-history"].hidden = (name === "view-history") || historyCache.length === 0;
  }

  /* ---------- setup view ---------- */
  function estimateComparisons(n) {
    if (n < 2) return 0;
    var queue = new Array(n).fill(1);
    var total = 0;
    while (queue.length > 1) {
      var left = queue.shift(), right = queue.shift();
      total += left + right - 1;
      queue.push(left + right);
    }
    return total;
  }

  function estimateQuickComparisons(n, topN) {
    if (n < 2) return 0;
    topN = Math.max(1, Math.min(topN, n));
    var total = n - 1;
    var remaining = n - 1;
    for (var k = 0; k < topN - 1; k++) {
      var poolGuess = Math.max(2, Math.ceil(Math.log2(Math.max(remaining, 2))) + 1);
      total += poolGuess - 1;
      remaining -= 1;
    }
    return total;
  }

  function renderRoster() {
    el["roster-list"].innerHTML = "";
    el["roster-empty"].hidden = draft.roster.length > 0;
    draft.roster.forEach(function (name, idx) {
      var li = document.createElement("li");
      li.className = "roster-row";
      var num = document.createElement("span");
      num.className = "roster-num mono";
      num.textContent = String(idx + 1).padStart(2, "0");
      var nameEl = document.createElement("span");
      nameEl.className = "roster-name";
      nameEl.textContent = name;
      var rm = document.createElement("button");
      rm.className = "roster-remove";
      rm.type = "button";
      rm.setAttribute("aria-label", "Remove " + name);
      rm.textContent = "✕";
      rm.addEventListener("click", function () {
        draft.roster.splice(idx, 1);
        saveDraft();
        renderRoster();
      });
      li.appendChild(num); li.appendChild(nameEl); li.appendChild(rm);
      el["roster-list"].appendChild(li);
    });
    renderModeControls();
  }

  function renderModeControls() {
    var n = draft.roster.length;
    Array.prototype.forEach.call(el["mode-toggle"].children, function (btn) {
      btn.classList.toggle("active", btn.dataset.mode === draft.mode);
    });
    Array.prototype.forEach.call(el["topn-toggle"].children, function (btn) {
      btn.classList.toggle("active", Number(btn.dataset.topn) === draft.topN);
    });
    el["topn-row"].hidden = draft.mode !== "quick";
    el["mode-desc"].textContent = draft.mode === "quick"
      ? "Finds just the top spot(s) without ranking everyone — much faster with a big list."
      : "Ranks every single candidate, 1st through last.";

    el["btn-begin"].disabled = n < 2;
    if (n < 2) { el["btn-begin"].textContent = "Begin Tournament"; return; }
    if (draft.mode === "quick") {
      var topN = Math.min(draft.topN, n);
      var est = estimateQuickComparisons(n, topN);
      el["btn-begin"].textContent = "Find Top " + topN + " (up to " + est + " matchups)";
    } else {
      el["btn-begin"].textContent = "Begin Tournament (up to " + estimateComparisons(n) + " matchups)";
    }
  }

  Array.prototype.forEach.call(el["mode-toggle"].children, function (btn) {
    btn.addEventListener("click", function () {
      draft.mode = btn.dataset.mode;
      saveDraft();
      renderModeControls();
    });
  });
  Array.prototype.forEach.call(el["topn-toggle"].children, function (btn) {
    btn.addEventListener("click", function () {
      draft.topN = Number(btn.dataset.topn);
      saveDraft();
      renderModeControls();
    });
  });

  function addCandidateName(name) {
    var trimmed = name.trim();
    if (!trimmed) return false;
    var dupe = draft.roster.some(function (n) { return n.toLowerCase() === trimmed.toLowerCase(); });
    if (dupe) { el["add-msg"].textContent = "“" + trimmed + "” is already on the roster."; return false; }
    draft.roster.push(trimmed);
    return true;
  }

  el["btn-add"].addEventListener("click", function () {
    el["add-msg"].textContent = "";
    if (addCandidateName(el["input-candidate"].value)) {
      el["input-candidate"].value = "";
      saveDraft();
      renderRoster();
    }
    el["input-candidate"].focus();
  });
  el["input-candidate"].addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); el["btn-add"].click(); }
  });
  el["input-candidate"].addEventListener("input", function () { el["add-msg"].textContent = ""; });

  el["input-category"].value = draft.category || "";
  el["input-category"].addEventListener("input", function () {
    draft.category = el["input-category"].value;
    saveDraft();
  });

  el["btn-toggle-bulk"].addEventListener("click", function () {
    el["bulk-area"].hidden = !el["bulk-area"].hidden;
    if (!el["bulk-area"].hidden) el["input-bulk"].focus();
  });
  el["btn-add-bulk"].addEventListener("click", function () {
    var lines = el["input-bulk"].value.split("\n");
    var added = 0, skipped = 0;
    lines.forEach(function (line) {
      if (!line.trim()) return;
      if (addCandidateName(line)) added++; else skipped++;
    });
    el["input-bulk"].value = "";
    saveDraft();
    renderRoster();
    el["add-msg"].textContent = added
      ? ("Added " + added + (skipped ? (", skipped " + skipped + " duplicate/empty") : "") + ".")
      : "Nothing new to add.";
  });

  el["btn-begin"].addEventListener("click", function () {
    if (draft.roster.length < 2) return;
    apiPost("/api/tournaments", {
      category: draft.category || "Untitled Tournament",
      candidates: draft.roster,
      mode: draft.mode,
      top_n: draft.topN
    })
      .then(function (payload) {
        draft.roster = [];
        draft.category = "";
        saveDraft();
        enterTournament(payload);
      })
      .catch(function (e) { el["add-msg"].textContent = e.message; });
  });

  function renderResumeBanner() {
    var has = activeTournament && !activeTournament.done;
    el["resume-banner"].hidden = !has;
    if (has) {
      var modeLabel = activeTournament.mode === "quick" ? "Quick · Top " + activeTournament.top_n : "Complete ranking";
      el["resume-title"].textContent = activeTournament.category || "Untitled Tournament";
      el["resume-sub"].textContent = modeLabel + " · Matchup " + (activeTournament.comparisons + 1) + " of up to " +
        activeTournament.total_estimate;
    }
  }
  el["btn-resume"].addEventListener("click", function () { enterTournament(activeTournament); });
  el["btn-discard"].addEventListener("click", function () {
    if (!confirm("Discard this unfinished tournament? This can’t be undone.")) return;
    apiPost("/api/tournaments/" + activeTournament.id + "/abandon", {}).then(function () {
      activeTournament = null;
      renderResumeBanner();
    });
  });

  el["btn-history"].addEventListener("click", function () { enterHistory(); });
  el["btn-back-setup"].addEventListener("click", function () { enterSetup(); });

  function enterSetup() {
    renderResumeBanner();
    renderRoster();
    showView("view-setup");
  }

  /* ---------- tournament view ---------- */
  var currentTid = null;
  var matchupShownAt = null; // timestamp a matchup became visible, for "heaviest debate" stats

  function enterTournament(payload) {
    currentTid = payload.id;
    showView("view-tournament");
    renderMatchup(payload);
  }

  function renderMatchup(payload) {
    if (payload.done) { finishTournament(payload); return; }
    var modeSuffix = payload.mode === "quick" ? " · TOP " + payload.top_n : "";
    el["bout-category"].textContent = (payload.category || "").toUpperCase() + modeSuffix;
    el["name-a"].textContent = payload.a.name;
    el["name-b"].textContent = payload.b.name;
    el["card-a"].dataset.id = payload.a.id;
    el["card-b"].dataset.id = payload.b.id;
    el["bout-counter"].textContent = "MATCHUP " + (payload.comparisons + 1) + " / up to " + payload.total_estimate;
    var pct = payload.total_estimate > 0 ? Math.min(payload.comparisons / payload.total_estimate, 1) : 1;
    el["progress-fill"].style.width = (pct * 100).toFixed(1) + "%";
    matchupShownAt = Date.now();
  }

  function castVote(choice) {
    var durationMs = matchupShownAt ? (Date.now() - matchupShownAt) : null;
    apiPost("/api/tournaments/" + currentTid + "/vote", { choice: choice, duration_ms: durationMs }).then(renderMatchup);
  }
  el["card-a"].addEventListener("click", function () { castVote("a"); });
  el["card-b"].addEventListener("click", function () { castVote("b"); });
  el["btn-tie"].addEventListener("click", function () { castVote("tie"); });

  el["btn-abandon"].addEventListener("click", function () {
    if (!confirm("Abandon this tournament and return to setup? Your progress will be discarded.")) return;
    apiPost("/api/tournaments/" + currentTid + "/abandon", {}).then(function () {
      activeTournament = null;
      enterSetup();
    });
  });

  function finishTournament(record) {
    activeTournament = null;
    resultsSource = "live";
    renderResults(record);
    refreshHistory().then(function () { showView("view-results"); });
  }

  /* ---------- results view ---------- */
  function renderResults(record) {
    var isQuick = record.mode === "quick";
    el["results-eyebrow"].textContent = isQuick ? "TOP " + record.top_n : "FINAL STANDINGS";
    el["results-category"].textContent = record.category;
    el["results-stat"].textContent = isQuick
      ? ("Top " + record.standings.length + " of " + record.total_candidates + " candidates · decided in " +
         record.comparisons + " matchups")
      : (record.standings.length + " contenders · decided in " + record.comparisons + " head-to-head matchups");
    el["results-list"].innerHTML = "";
    var seen = {};
    record.standings.forEach(function (s) { seen[s.rank] = (seen[s.rank] || 0) + 1; });
    record.standings.forEach(function (s) {
      var li = document.createElement("li");
      li.className = "standing-row" + (s.rank === 1 ? " rank-gold" : s.rank === 2 ? " rank-silver" : s.rank === 3 ? " rank-bronze" : "");
      var rank = document.createElement("span");
      rank.className = "standing-rank mono";
      rank.textContent = "#" + s.rank;
      var name = document.createElement("span");
      name.className = "standing-name";
      name.textContent = s.name;
      li.appendChild(rank); li.appendChild(name);
      if (seen[s.rank] > 1) {
        var tag = document.createElement("span");
        tag.className = "standing-tag";
        tag.textContent = "TIE";
        li.appendChild(tag);
      }
      el["results-list"].appendChild(li);
    });
    renderFunStats(record.fun_stats);
    el["btn-back-history"].hidden = resultsSource !== "history";
    el["btn-new"].hidden = resultsSource === "history";
    el["btn-copy"].dataset.category = record.category;
    el["print-date"].textContent = record.date ? new Date(record.date).toLocaleDateString() : new Date().toLocaleDateString();
  }

  function formatDuration(ms) {
    if (ms === null || ms === undefined) return "—";
    var totalSec = Math.round(ms / 1000);
    if (totalSec < 60) return totalSec + "s";
    var m = Math.floor(totalSec / 60), s = totalSec % 60;
    return m + "m " + String(s).padStart(2, "0") + "s";
  }

  function renderDebateList(container, title, items) {
    container.innerHTML = "";
    var h = document.createElement("div");
    h.className = "debate-list-title";
    h.textContent = title;
    container.appendChild(h);
    if (!items.length) {
      var empty = document.createElement("p");
      empty.className = "text-faint";
      empty.textContent = "Not enough timed matchups yet.";
      container.appendChild(empty);
      return;
    }
    var ol = document.createElement("ol");
    ol.className = "debate-list";
    items.forEach(function (m) {
      var li = document.createElement("li");
      var pair = document.createElement("span");
      pair.className = "debate-pair";
      pair.textContent = m.a + " vs " + m.b + (m.choice === "tie" ? " (tie)" : "");
      var dur = document.createElement("span");
      dur.className = "debate-duration mono";
      dur.textContent = formatDuration(m.duration_ms);
      li.appendChild(pair); li.appendChild(dur);
      ol.appendChild(li);
    });
    container.appendChild(ol);
  }

  function renderFunStats(stats) {
    if (!stats || stats.matchup_count === 0) { el["fun-stats"].hidden = true; return; }
    el["fun-stats"].hidden = false;

    var tiles = [{ label: "Total deliberation time", value: formatDuration(stats.total_duration_ms) }];
    if (stats.hot_streak) {
      tiles.push({
        label: "Hot streak",
        value: stats.hot_streak.names.join(" & ") + " — " + stats.hot_streak.streak + " wins in a row"
      });
    }
    if (stats.most_contested) {
      tiles.push({
        label: "Most contested",
        value: stats.most_contested.names.join(" & ") + " — " + stats.most_contested.matchups + " matchups"
      });
    }
    if (stats.tie_count > 0) {
      tiles.push({ label: "Too close to call", value: stats.tie_count + (stats.tie_count === 1 ? " tie" : " ties") });
    }

    el["stat-tiles"].innerHTML = "";
    tiles.forEach(function (t) {
      var tile = document.createElement("div");
      tile.className = "stat-tile";
      var label = document.createElement("div");
      label.className = "stat-tile-label";
      label.textContent = t.label.toUpperCase();
      var value = document.createElement("div");
      value.className = "stat-tile-value";
      value.textContent = t.value;
      tile.appendChild(label); tile.appendChild(value);
      el["stat-tiles"].appendChild(tile);
    });

    renderDebateList(el["heaviest-list"], "HEAVIEST DEBATES", stats.heaviest_debates);
    renderDebateList(el["easiest-list"], "EASIEST CALLS", stats.easiest_calls);
  }

  el["btn-new"].addEventListener("click", function () { enterSetup(); });
  el["btn-back-history"].addEventListener("click", function () { enterHistory(); });
  el["btn-copy"].addEventListener("click", function () {
    var cat = el["results-category"].textContent;
    var lines = ["TIER TOURNAMENT — " + cat, new Date().toLocaleDateString(), ""];
    Array.prototype.forEach.call(el["results-list"].children, function (li) {
      var rank = li.querySelector(".standing-rank").textContent.replace("#", "");
      var name = li.querySelector(".standing-name").textContent;
      lines.push(rank + ". " + name);
    });
    var text = lines.join("\n");
    var original = el["btn-copy"].textContent;
    function flash(msg) {
      el["btn-copy"].textContent = msg;
      setTimeout(function () { el["btn-copy"].textContent = original; }, 1500);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { flash("Copied ✓"); }).catch(function () { flash("Copy failed"); });
    } else {
      flash("Copy not supported");
    }
  });

  el["btn-pdf"].addEventListener("click", function () {
    var cat = el["results-category"].textContent || "Tier Tournament";
    var originalTitle = document.title;
    document.title = cat.replace(/[\\/:*?"<>|]/g, "").trim() || "Tier Tournament Results";
    window.print();
    document.title = originalTitle;
  });

  /* ---------- history view ---------- */
  function refreshHistory() {
    return apiGet("/api/history").then(function (rows) {
      historyCache = rows;
      el["btn-history"].hidden = historyCache.length === 0;
      return rows;
    });
  }

  function enterHistory() {
    el["history-list"].innerHTML = "";
    el["history-empty"].hidden = historyCache.length > 0;
    historyCache.forEach(function (record) {
      var li = document.createElement("li");
      li.className = "history-row";
      var btn = document.createElement("button");
      btn.className = "history-row-btn";
      btn.type = "button";
      var nameSpan = document.createElement("span");
      nameSpan.className = "history-name";
      nameSpan.textContent = record.category;
      var metaWrap = document.createElement("span");
      metaWrap.style.display = "flex";
      metaWrap.style.alignItems = "center";
      metaWrap.style.gap = "8px";
      var modeTag = document.createElement("span");
      modeTag.className = "mode-tag";
      modeTag.textContent = record.mode === "quick" ? "TOP " + record.top_n : "FULL";
      var metaSpan = document.createElement("span");
      metaSpan.className = "history-meta mono";
      metaSpan.textContent = record.standings.length + " · " + (record.date ? new Date(record.date).toLocaleDateString() : "");
      metaWrap.appendChild(modeTag); metaWrap.appendChild(metaSpan);
      btn.appendChild(nameSpan); btn.appendChild(metaWrap);
      btn.addEventListener("click", function () {
        resultsSource = "history";
        renderResults(record);
        showView("view-results");
      });
      var del = document.createElement("button");
      del.className = "history-del";
      del.type = "button";
      del.setAttribute("aria-label", "Delete " + record.category);
      del.textContent = "✕";
      del.addEventListener("click", function () {
        if (!confirm("Delete “" + record.category + "” from history?")) return;
        apiDelete("/api/tournaments/" + record.id).then(function () {
          refreshHistory().then(enterHistory);
        });
      });
      li.appendChild(btn); li.appendChild(del);
      el["history-list"].appendChild(li);
    });
    showView("view-history");
  }

  /* ---------- boot ---------- */
  Promise.all([
    apiGet("/api/active").catch(function () { return null; }),
    refreshHistory().catch(function () { return []; })
  ]).then(function (results) {
    activeTournament = results[0];
    renderResumeBanner();
    renderRoster();
    el["btn-history"].hidden = historyCache.length === 0;
    showView("view-setup");
  });
})();
