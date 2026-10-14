"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const GROUPS = ["Integration & EDI", "IT & Systems", "Cybersecurity"];
const S = {
  name: "there", jobs: [], search: null, mine: [], aiEnabled: false, settings: {},
  view: "jobs", group: "All", filters: new Set(), mineGroup: "All",
};

// ---------- helpers ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  let data = null;
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok) throw new Error((data && data.detail) || `Something went wrong (${res.status})`);
  return data;
}

function postedLabel(iso) {
  if (!iso) return "Date not listed";
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (d <= 0) return "Posted today";
  if (d === 1) return "Posted yesterday";
  return `Posted ${d} days ago`;
}
function agoLabel(iso) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${plural(hrs, "hour")} ago`;
  const d = Math.round(hrs / 24);
  return d === 1 ? "yesterday" : `${d} days ago`;
}
const niceDate = (iso) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
// "New" = first found in the last 24 hours, so searching twice in a row doesn't wipe the tags.
const NEW_WINDOW_MS = 24 * 60 * 60 * 1000;
const isNew = (j) => !!j.first_seen_at && Date.now() - new Date(j.first_seen_at).getTime() < NEW_WINDOW_MS;

const ICON = {
  pin: '<svg viewBox="0 0 24 24"><path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>',
  home: '<svg viewBox="0 0 24 24"><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/></svg>',
  cash: '<svg viewBox="0 0 24 24"><rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/></svg>',
  clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  ext: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  bookmark: '<svg viewBox="0 0 24 24"><path d="M6 3h12v18l-6-4-6 4z"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="M4 12.5l5 5L20 6.5"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  chev: '<svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>',
};

// ---------- job card ----------
function locationLabel(j) {
  const loc = (j.location || "").trim();
  if (!j.is_remote) return loc || "Location not listed";
  if (!loc) return "Remote";
  return /remote/i.test(loc) ? loc : `Remote · ${loc}`;
}
const badgeClass = (b) => (b === "Strong fit" ? "strong" : b === "In reach" ? "reach" : "stretch");
const applyLabel = (j) => (j.apply_site ? `Apply on ${j.apply_site}` : "Open job");
function siteIcon(j) {
  if (!j.apply_domain) return "";
  return `<img class="site-icon" alt="" loading="lazy" src="https://www.google.com/s2/favicons?domain=${encodeURIComponent(j.apply_domain)}&sz=32" onerror="this.remove()">`;
}
function trustBadge(j) {
  if (j.trust === "verified") return '<span class="trust trust-ok" title="Company career page or major job board, no warning signs">✓ Verified source</span>';
  if (j.trust === "caution") return `<span class="trust trust-warn" title="${esc((j.warnings || []).join(" "))}">⚠ Check carefully</span>`;
  return "";
}

function cardHTML(j, { mine = false } = {}) {
  const tags = [];
  if (!mine && isNew(j)) tags.push('<span class="tag tag-new">New</span>');
  if (j.entry_level) tags.push('<span class="tag tag-entry">Entry level</span>');
  if (j.status === "applied") tags.push('<span class="tag tag-applied">Applied</span>');
  else if (j.status === "saved") tags.push('<span class="tag tag-saved">Saved</span>');
  if (j.viewed_at) tags.push('<span class="tag tag-viewed">Viewed</span>');

  const meta = [
    `<span>${j.is_remote ? ICON.home : ICON.pin}${esc(locationLabel(j))}</span>`,
    j.salary ? `<span class="pay">${ICON.cash}${esc(j.salary)}</span>` : "",
    `<span>${ICON.clock}${postedLabel(j.posted_at)}</span>`,
    mine && j.applied_at ? `<span class="applied-date">Applied ${niceDate(j.applied_at)}</span>` : "",
    mine && !j.applied_at && j.status_at ? `<span>Saved ${niceDate(j.status_at)}</span>` : "",
  ].join("");

  const warnings = j.warnings || [];
  const trustRow = trustBadge(j) + (j.trust === "caution" && warnings.length
    ? `<span class="trust-reason">${esc(warnings[0])}${warnings.length > 1 ? ` (+${warnings.length - 1} more in Details)` : ""}</span>` : "");
  const skills = j.matched.length
    ? `<div class="card-skills">${j.matched.slice(0, 4).map((m) => `<span class="chip have">✓ ${esc(m)}</span>`).join("")}${j.matched.length > 4 ? `<span class="chip none">+${j.matched.length - 4} more</span>` : ""}</div>` : "";
  const matched = j.matched.length ? j.matched.map((s) => `<span class="chip have">✓ ${esc(s)}</span>`).join("") : '<span class="chip none">None of your listed skills were mentioned</span>';
  const missing = j.missing.length ? j.missing.map((s) => `<span class="chip miss">${esc(s)}</span>`).join("") : '<span class="chip none">Nothing major — nice</span>';

  return `
  <article class="card ${!mine && isNew(j) ? "is-new" : ""}" data-id="${j.id}">
    <div class="card-top" data-toggle>
      <div class="card-main">
        <h3 class="card-title">${esc(j.title)} ${tags.join("")}</h3>
        <div class="company">${esc(j.company)}</div>
        <div class="meta">${meta}</div>
        <div class="trust-row">${trustRow}</div>
        ${skills}
      </div>
      <div class="badge ${badgeClass(j.badge)}" title="Fit score out of 100">
        <span class="score">${j.score}</span><span class="label">${esc(j.badge)}</span>
      </div>
    </div>
    <div class="card-actions">
      <a class="btn-apply" href="${esc(j.url)}" target="_blank" rel="noopener" data-apply>${siteIcon(j)}<span>${esc(applyLabel(j))}</span>${ICON.ext}</a>
      <button class="act ${j.status === "saved" ? "on-saved" : ""}" data-status="saved">${ICON.bookmark}<span>${j.status === "saved" ? "Saved" : "Save"}</span></button>
      <button class="act ${j.status === "applied" ? "on-applied" : ""}" data-status="applied">${ICON.check}<span>${j.status === "applied" ? "Applied" : "Mark applied"}</span></button>
      ${mine ? "" : `<button class="act hide" data-status="hidden">${ICON.x}<span>Not interested</span></button>`}
      <button class="expand-toggle" data-toggle>Details ${ICON.chev}</button>
    </div>
    <div class="details"><div><div class="details-inner">
      ${j.trust === "caution" ? `<div class="skill-group"><h4>Why to check carefully</h4><ul class="warn-list">${warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
      ${j.summary ? `<div class="ai-summary"><b>Why this fits you</b>${esc(j.summary)}</div>` : ""}
      <div class="skill-group"><h4>Your skills that match</h4><div class="chips">${matched}</div></div>
      <div class="skill-group"><h4>Skills you'd be missing</h4><div class="chips">${missing}</div></div>
      ${j.snippet ? `<p class="snippet">${esc(j.snippet)}${j.snippet.length >= 700 ? "…" : ""}</p>` : ""}
      <div class="via">${j.apply_domain ? `Apply link goes to <b>${esc(j.apply_domain)}</b>. ` : ""}Also listed on: ${esc((j.sources || []).join(", "))}</div>
      <div class="problem-row">Problem with this job?
        <button class="problem-btn" data-broken>🔗 Link didn't work</button>
        <button class="problem-btn red" data-report>🚩 Report as sketchy</button>
      </div>
    </div></div></div>
  </article>`;
}

// ---------- jobs view ----------
function groupOf(j) { return GROUPS.includes(j.category) ? j.category : "IT & Systems"; }

function passesFilters(j) {
  for (const f of S.filters) {
    if (f === "new" && !isNew(j)) return false;
    if (f === "entry" && !j.entry_level) return false;
    if (f === "remote" && !j.is_remote) return false;
    if (f === "local" && j.is_remote) return false;
  }
  return true;
}
function visibleJobs() {
  return S.jobs.filter((j) => (S.group === "All" || groupOf(j) === S.group) && passesFilters(j));
}

function renderHero() {
  const h = new Date().getHours();
  const part = h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
  $("#greeting").innerHTML = `Good ${part}, <span class="accent">${esc(S.name)}</span> 👋`;
  $("#subline").textContent = S.search
    ? `Here's what I pulled up for you today: ${plural(S.jobs.length, "job")}`
    : "Click Search and I'll pull up fresh jobs for you.";
  $("#searchBtn span").textContent = S.search ? "Search again" : "Search";
  renderStatusLine();
}

function renderStatusLine() {
  const s = S.search, box = $("#statusLine");
  if (!s) { box.innerHTML = ""; return; }
  const st = S.settings || {};
  const lines = [];
  const js = (s.report || []).find((r) => r.source === "JSearch");
  const keyNewer = st.jsearch_saved && st.jsearch_saved_at && st.jsearch_saved_at > s.ran_at;
  if (!st.jsearch_saved) {
    lines.push(`<p>Want LinkedIn, Indeed and Glassdoor jobs too? <button class="link-btn strong" data-action="settings">Add your JSearch key</button></p>`);
  } else if (keyNewer) {
    lines.push(`<p class="ok">Your key is saved ✓ Click <b>Search</b> to pull in LinkedIn, Indeed and Glassdoor jobs.</p>`);
  } else if (js && js.status === "error") {
    lines.push(`<p class="warn">${esc(js.note)}</p><button class="link-btn strong" data-action="settings">Change key</button>`);
  }
  for (const r of s.report || []) {
    if (r.status === "error" && r.source !== "JSearch") lines.push(`<p>${esc(r.note)}</p>`);
  }
  const safety = s.safety || {};
  const bits = [`Checked ${agoLabel(s.ran_at)}`];
  if (safety.hidden_total) bits.push(`🛡 ${plural(safety.hidden_total, "unsafe or closed job")} hidden`);
  lines.push(`<p>${bits.join('<span class="dot">•</span>')}</p>`);
  box.innerHTML = lines.join("");
}

function renderToolbar() {
  const has = S.jobs.length > 0;
  $("#toolbar").hidden = !has;
  if (!has) return;
  const counts = { All: S.jobs.length };
  for (const g of GROUPS) counts[g] = S.jobs.filter((j) => groupOf(j) === g).length;
  $("#groups").innerHTML = ["All", ...GROUPS].map((g) =>
    `<button class="group ${S.group === g ? "active" : ""}" data-group="${esc(g)}" role="tab">${esc(g)}<span class="n">${counts[g]}</span></button>`).join("");
  $$("#filters .chip-toggle").forEach((b) => b.classList.toggle("on", S.filters.has(b.dataset.filter)));
}

function renderJobs() {
  renderHero();
  renderToolbar();
  $("#jobsCount").textContent = S.jobs.length || "";
  const list = visibleJobs();
  const sum = $("#resultsSummary");
  sum.hidden = !S.jobs.length;
  if (S.jobs.length) {
    const newCount = S.jobs.filter(isNew).length;
    const callout = newCount ? `${plural(newCount, "new job")} in the last day` : "";
    const filtered = S.group !== "All" || S.filters.size;
    sum.innerHTML = `Showing <b>${list.length}</b> of ${plural(S.jobs.length, "job")}`
      + (callout ? ` · <span class="new-callout">${callout}</span>` : "")
      + (filtered ? `<button class="clear" data-clear>Clear filters</button>` : "");
  }
  $("#results").innerHTML = list.map((j) => cardHTML(j)).join("");
  const empty = $("#empty");
  if (S.search && !list.length) {
    empty.hidden = false;
    empty.innerHTML = S.jobs.length
      ? 'No jobs match these filters. <button class="link-btn strong" data-clear>Clear filters</button>'
      : "No matching jobs this time. Try again later, or add more companies from the Menu.";
  } else empty.hidden = true;
}

// ---------- my jobs view ----------
function renderMine() {
  $("#mineCount").textContent = S.mine.length || "";
  const applied = S.mine.filter((j) => j.status === "applied").length;
  const saved = S.mine.filter((j) => j.status === "saved").length;
  $("#mineGroups").innerHTML = [["All", S.mine.length], ["Applied", applied], ["Saved", saved]].map(([g, n]) =>
    `<button class="group ${S.mineGroup === g ? "active" : ""}" data-mine-group="${g}">${g}<span class="n">${n}</span></button>`).join("");
  const list = S.mine.filter((j) => S.mineGroup === "All" || j.status === S.mineGroup.toLowerCase());
  $("#mineList").innerHTML = list.map((j) => cardHTML(j, { mine: true })).join("");
  $("#mineEmpty").hidden = list.length > 0;
}

function rerenderKeepingOpen() {
  const open = $$(".card.open").map((c) => c.dataset.id);
  renderJobs();
  renderMine();
  open.forEach((id) => $$(`.card[data-id="${id}"]`).forEach((c) => c.classList.add("open")));
}

function go(view) {
  S.view = view;
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.goto === view));
  $("#jobs").hidden = view !== "jobs";
  $("#mine").hidden = view !== "mine";
  if (view === "mine") refreshMine();
  window.scrollTo({ top: 0 });
}

// ---------- actions ----------
const LOADING_LINES = [
  "Checking LinkedIn, Indeed & more…",
  "Looking through company job boards…",
  "Dropping clearance, 7+ year & far-away jobs…",
  "Skipping pay-to-apply and sketchy sites…",
  "Scoring each job against your skills…",
  "Making sure every job is still open…",
];

async function runSearch() {
  const btn = $("#searchBtn");
  btn.disabled = true;
  btn.querySelector("span").textContent = "Searching…";
  $("#loading").hidden = false;
  $("#results").innerHTML = "";
  $("#toolbar").hidden = true;
  $("#resultsSummary").hidden = true;
  $("#empty").hidden = true;
  let i = 0;
  const lt = $("#loadingText");
  lt.textContent = LOADING_LINES[0];
  const timer = setInterval(() => {
    i = (i + 1) % LOADING_LINES.length;
    lt.style.opacity = 0;
    setTimeout(() => { lt.textContent = LOADING_LINES[i]; lt.style.opacity = 1; }, 250);
  }, 1800);
  try {
    const data = await api("/api/search", { method: "POST" });
    S.search = data.search;
    S.jobs = data.jobs;
    S.group = "All";          // a fresh search always shows everything
    S.filters.clear();
  } catch (e) {
    toast(e.message);
  } finally {
    clearInterval(timer);
    $("#loading").hidden = true;
    btn.disabled = false;
    renderJobs();
    loadSummaries();
  }
}

async function loadSummaries() {
  if (!S.aiEnabled || !S.jobs.length || S.jobs.slice(0, 20).every((j) => j.summary)) return;
  try {
    const data = await api("/api/summaries", { method: "POST" });
    if (data.error) { toast(data.error); return; }
    let changed = false;
    for (const j of S.jobs) if (data.summaries[j.id] && !j.summary) { j.summary = data.summaries[j.id]; changed = true; }
    if (changed) rerenderKeepingOpen();
  } catch (_) { /* summaries are a bonus */ }
}

function findJob(id) { return S.jobs.find((j) => j.id === id) || S.mine.find((j) => j.id === id); }
function removeCard(card, id) {
  card.classList.add("leaving");
  setTimeout(() => {
    S.jobs = S.jobs.filter((j) => j.id !== id);
    S.mine = S.mine.filter((j) => j.id !== id);
    rerenderKeepingOpen();
  }, 280);
}

async function setStatus(id, status, card) {
  const job = findJob(id);
  if (!job) return;
  const prev = job.status;
  const next = job.status === status && status !== "hidden" ? null : status;   // tap again to undo
  try {
    const updated = await api(`/api/jobs/${id}/status`, { method: "POST", body: JSON.stringify({ status: next }) });
    for (const list of [S.jobs, S.mine]) {
      const o = list.find((j) => j.id === id);
      if (o) Object.assign(o, { status: updated.status, status_at: updated.status_at, applied_at: updated.applied_at });
    }
  } catch (e) { toast(e.message); return; }

  if (next === "hidden") {
    removeCard(card, id);
    toast("Hidden for good.", "Undo", async () => {
      await api(`/api/jobs/${id}/status`, { method: "POST", body: JSON.stringify({ status: prev }) });
      job.status = prev;
      S.jobs.push(job);
      S.jobs.sort((a, b) => b.score - a.score);
      rerenderKeepingOpen();
    });
  } else {
    if (next === "applied") toast("Nice! Marked as applied.");
    else if (next === "saved") toast("Saved to My jobs.");
    await refreshMine();
    rerenderKeepingOpen();
  }
}

async function reportBroken(id, card, btn) {
  btn.disabled = true;
  btn.textContent = "Checking for another link…";
  try {
    const res = await api(`/api/jobs/${id}/broken`, { method: "POST" });
    if (res.outcome === "switched") {
      for (const list of [S.jobs, S.mine]) { const j = list.find((x) => x.id === id); if (j) Object.assign(j, res.job); }
      rerenderKeepingOpen();
    } else removeCard(card, id);
    toast(res.message);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "🔗 Link didn't work";
    toast(e.message);
  }
}

async function reportSketchy(id, card) {
  const job = findJob(id);
  const where = job && job.apply_kind === "board" ? `${job.company} (on ${job.apply_site})` : (job && (job.apply_domain || job.company)) || "this site";
  if (!confirm(`Hide this job and never show jobs from ${where} again?`)) return;
  try {
    const res = await api(`/api/jobs/${id}/report`, { method: "POST" });
    removeCard(card, id);
    toast(res.message);
  } catch (e) { toast(e.message); }
}

async function refreshMine() {
  try { S.mine = await api("/api/my-jobs"); } catch (_) { S.mine = []; }
  renderMine();
}

function markViewed(id) {
  for (const list of [S.jobs, S.mine]) {
    const j = list.find((x) => x.id === id);
    if (j && !j.viewed_at) j.viewed_at = new Date().toISOString();
  }
  const body = new Blob(["{}"], { type: "application/json" });
  if (!(navigator.sendBeacon && navigator.sendBeacon(`/api/jobs/${id}/viewed`, body))) {
    fetch(`/api/jobs/${id}/viewed`, { method: "POST", keepalive: true });
  }
  setTimeout(rerenderKeepingOpen, 300);
}

let toastTimer;
function toast(msg, actionLabel, action) {
  const t = $("#toast");
  t.innerHTML = `<span>${esc(msg)}</span>${actionLabel ? `<button>${esc(actionLabel)}</button>` : ""}`;
  t.hidden = false;
  if (actionLabel) t.querySelector("button").onclick = () => { t.hidden = true; action(); };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, actionLabel ? 6000 : 3000);
}

// ---------- menu + dialogs ----------
function toggleMenu(open) {
  const menu = $("#menu"), btn = $("#menuBtn");
  const show = open ?? menu.hidden;
  menu.hidden = !show;
  btn.setAttribute("aria-expanded", String(show));
}

async function menuAction(action) {
  toggleMenu(false);
  if (action === "settings") openSettings();
  else if (action === "companies") openCompanies();
  else if (action === "notes") openNotes();
  else if (action === "close") closeApp();
}

function renderSettings() {
  const st = S.settings || {};
  const saved = !!st.jsearch_saved;
  $("#keySaved").hidden = !saved;
  $("#keyForm").hidden = saved;
  $("#keyLast4").textContent = saved ? `(ends in ${st.jsearch_last4})` : "";
  $("#keyMsg").textContent = "";
  $("#keyMsg").className = "form-msg";
  $("#keyInput").value = "";
}
function openSettings() {
  renderSettings();
  const d = $("#settingsDialog");
  if (!d.open) d.showModal();
  if (!$("#keyForm").hidden) setTimeout(() => $("#keyInput").focus(), 50);
}

async function openCompanies() {
  await renderCompanies();
  $("#companyMsg").textContent = "";
  $("#companiesDialog").showModal();
}
async function renderCompanies() {
  const list = await api("/api/companies");
  $("#companyList").innerHTML = list.map((c) => `
    <li><span>${esc(c.name)}<span class="ats">${c.ats === "lever" ? "Lever" : "Greenhouse"}</span></span>
    <button data-ats="${esc(c.ats)}" data-slug="${esc(c.slug)}">Remove</button></li>`).join("");
}

async function openNotes() {
  let text = "";
  try { text = (await api("/api/review-notes")).text; } catch (_) { /* show empty state */ }
  const body = $("#notesBody");
  if (!text.trim()) {
    body.innerHTML = '<p class="subline">No notes yet. If a job link doesn\'t work, open its Details and click "🔗 Link didn\'t work". It\'ll be looked at that evening.</p>';
  } else {
    body.innerHTML = text.split(/^## /m).filter(Boolean).map((chunk) => {
      const [head, ...rest] = chunk.split("\n");
      return `<h4>${esc(head)}</h4><p>${esc(rest.join("\n").trim())}</p>`;
    }).join("");
  }
  $("#notesDialog").showModal();
}

async function closeApp() {
  if (!confirm("Close Job Finder? Your saved jobs will still be here next time.")) return;
  try { await api("/api/shutdown", { method: "POST" }); } catch (_) { /* already closed */ }
  $("#closedScreen").hidden = false;
}

// ---------- wiring ----------
function wire() {
  $("#searchBtn").addEventListener("click", runSearch);

  document.addEventListener("click", (e) => {
    const t = e.target;
    // navigation
    const goto = t.closest("[data-goto]");
    if (goto) { e.preventDefault(); go(goto.dataset.goto); return; }
    // menu
    if (t.closest("#menuBtn")) { toggleMenu(); return; }
    const act = t.closest("[data-action]");
    if (act) { menuAction(act.dataset.action); return; }
    if (!t.closest("#menu")) toggleMenu(false);
    // groups + filters
    const g = t.closest("[data-group]");
    if (g) { S.group = g.dataset.group; renderJobs(); return; }
    const f = t.closest("[data-filter]");
    if (f) { const k = f.dataset.filter; S.filters.has(k) ? S.filters.delete(k) : S.filters.add(k); renderJobs(); return; }
    if (t.closest("[data-clear]")) { S.group = "All"; S.filters.clear(); renderJobs(); return; }
    const mg = t.closest("[data-mine-group]");
    if (mg) { S.mineGroup = mg.dataset.mineGroup; renderMine(); return; }
    // dialogs: click outside to close
    if (t.tagName === "DIALOG") { t.close(); return; }
    // job cards
    const card = t.closest(".card");
    if (!card) return;
    const id = card.dataset.id;
    if (t.closest("[data-apply]")) { markViewed(id); return; }
    if (t.closest("[data-report]")) { reportSketchy(id, card); return; }
    const broken = t.closest("[data-broken]");
    if (broken) { reportBroken(id, card, broken); return; }
    const st = t.closest("[data-status]");
    if (st) { setStatus(id, st.dataset.status, card); return; }
    if (t.closest("[data-toggle]")) card.classList.toggle("open");
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") toggleMenu(false); });
  // Middle-click / ctrl-click on Apply also counts as viewed.
  document.addEventListener("auxclick", (e) => {
    const a = e.target.closest("[data-apply]");
    if (a) markViewed(a.closest(".card").dataset.id);
  });

  $("#changeKeyBtn").addEventListener("click", () => {
    $("#keySaved").hidden = true;
    $("#keyForm").hidden = false;
    $("#keyInput").focus();
  });
  $("#keyForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = $("#keyMsg"), btn = e.target.querySelector("button");
    btn.disabled = true;
    try {
      S.settings = await api("/api/settings", { method: "POST", body: JSON.stringify({ jsearch_key: $("#keyInput").value }) });
      renderSettings();
      renderStatusLine();
      toast("Key saved! Click Search to see LinkedIn, Indeed and Glassdoor jobs.");
      setTimeout(() => $("#settingsDialog").close(), 1400);
    } catch (err) {
      msg.className = "form-msg err"; msg.textContent = err.message;
    } finally { btn.disabled = false; }
  });

  $("#companyList").addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    await api(`/api/companies/${b.dataset.ats}/${b.dataset.slug}`, { method: "DELETE" });
    renderCompanies();
  });
  $("#addCompanyForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#companyInput"), msg = $("#companyMsg"), btn = e.target.querySelector("button");
    btn.disabled = true; msg.className = "form-msg"; msg.textContent = "Checking that job board…";
    try {
      const c = await api("/api/companies", { method: "POST", body: JSON.stringify({ text: input.value }) });
      msg.textContent = `Added ${c.name}. It'll be included in your next search.`;
      input.value = "";
      renderCompanies();
    } catch (err) {
      msg.className = "form-msg err"; msg.textContent = err.message;
    } finally { btn.disabled = false; }
  });
}

async function init() {
  wire();
  try {
    const st = await api("/api/state");
    S.name = st.name; S.search = st.search; S.jobs = st.jobs; S.aiEnabled = st.ai_enabled; S.settings = st.settings || {};
  } catch (e) { toast("Couldn't load your saved jobs."); }
  renderJobs();
  refreshMine();
  loadSummaries();
  // No key saved yet: show the key box once each time Job Finder is opened, until a key is saved.
  if (!S.settings.jsearch_saved) {
    let asked = false;
    try { asked = sessionStorage.getItem("askedForKey") === "1"; sessionStorage.setItem("askedForKey", "1"); } catch (_) { /* storage blocked */ }
    if (!asked) openSettings();
  }
}

init();
