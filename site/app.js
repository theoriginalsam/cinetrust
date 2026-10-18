// CineTrust public site: renders leaderboard.json (exported by jobs/export_site.py).
// Falls back to leaderboard.sample.json (synthetic demo data) so the page works offline.

const POSTER = "https://image.tmdb.org/t/p/w342";
const SOURCE_LABELS = {
  imdb: "IMDb", rotten_tomatoes: "Rotten Tomatoes", metacritic: "Metacritic",
  tmdb: "TMDB votes", tmdb_reviews: "TMDB reviews", trakt_reviews: "Trakt reviews", youtube_reviews: "YouTube trailer comments",
};
const REASON_LABELS = {
  near_duplicate_text: "Copy-paste text",
  account_burst: "Account mass-posting",
  coordinated_wave: "Part of a review wave",
  rating_text_mismatch: "Rating doesn't match text",
  statistical_outlier: "Unusual behaviour",
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (v, d = 0) => (v == null ? "—" : Number(v).toFixed(d));
const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const tier = (s) => (s >= 75 ? "high" : s >= 60 ? "mid" : "low");

let movies = [];

async function load() {
  for (const file of ["leaderboard.json", "leaderboard.sample.json"]) {
    try {
      const res = await fetch(file, { cache: "no-cache" });
      if (res.ok) return { doc: await res.json(), file };
    } catch { /* try the next file */ }
  }
  throw new Error("Couldn't load leaderboard.json");
}

function poster(m) {
  return m.poster_path
    ? `<img class="poster" src="${POSTER}${esc(m.poster_path)}" alt="${esc(m.title)} poster" loading="lazy">`
    : `<div class="noposter">${esc(m.title)}</div>`;
}

function renderKpis() {
  const sources = new Set(movies.flatMap((m) => Object.keys(m.breakdown || {})));
  const sum = (k) => movies.reduce((a, m) => a + (m[k] || 0), 0);
  $("kpis").innerHTML = [
    ["Movies in theatres", movies.length],
    ["Reviews checked", sum("n_reviews")],
    ["Reviews down-weighted", sum("n_suspicious_reviews")],
    ["Sources combined", sources.size],
  ].map(([label, value]) => `<div class="kpi"><span>${label}</span><b>${value}</b></div>`).join("");
}

function renderGrid() {
  const q = $("q").value.trim().toLowerCase();
  const key = $("sort").value;
  const val = (m) => (key === "gap"
    ? (m.naive_review_average == null ? null : Math.abs(m.cinetrust_score - m.naive_review_average))
    : m[key]);
  const view = movies
    .filter((m) => !q || m.title.toLowerCase().includes(q))
    .filter((m) => !$("alerts").checked || m.farming_alert)
    .sort((a, b) => (val(b) ?? -Infinity) - (val(a) ?? -Infinity));

  $("empty").hidden = view.length > 0;
  $("grid").innerHTML = view.map((m) => {
    const meta = (m.naive_review_average != null
      ? `plain avg ${num(m.naive_review_average)}<br>` : "no written reviews<br>")
      + `${m.n_reviews} reviews · ${pct(m.confidence)} sure`;
    return `<button class="card" data-id="${esc(m.imdb_id)}" aria-label="${esc(m.title)}: why this score?">
      ${poster(m)}
      <div class="body">
        <div class="title">${esc(m.title)}</div>
        <div class="row"><span class="score ${tier(m.cinetrust_score)}">${num(m.cinetrust_score)}</span>
          <span class="meta">${meta}</span></div>
        ${m.farming_alert ? '<span class="alert">🚨 Farming alert</span>' : ""}
        <span class="why">Why this score? →</span>
      </div>
    </button>`;
  }).join("");
}

function openDetails(m) {
  const naive = m.naive_review_average;
  const delta = naive == null ? "" : `<small>${m.cinetrust_score - naive >= 0 ? "+" : ""}${num(m.cinetrust_score - naive)} vs plain average</small>`;
  const parts = Object.entries(m.breakdown || {});
  const rows = parts.map(([src, p]) => `<tr>
      <td>${esc(SOURCE_LABELS[src] || src)}</td>
      <td>${num(p.score)}</td>
      <td><div class="bar"><div class="track"><i style="width:${Math.round(p.share * 100)}%"></i></div>${pct(p.share)}</div></td>
    </tr>`).join("");
  const reviews = (m.flagged_reviews || []).map((r) => `<article class="review">
      <div class="head">
        <b>${esc(String(r.source || "").toUpperCase())}</b>
        <span>${r.rating == null ? "no rating" : `${num(r.rating)} / 10`}</span>
        <span>trust ${pct(r.trust)}</span>
        ${r.created_at ? `<span>${esc(r.created_at.slice(0, 10))}</span>` : ""}
      </div>
      ${(r.reasons || []).map((x) => `<span class="chip">${esc(REASON_LABELS[x] || x)}</span>`).join("")}
      <p>${esc(r.text)}</p>
    </article>`).join("");

  $("d-body").innerHTML = `
    <div class="d-top">
      <div>${poster(m)}</div>
      <div>
        <h2 id="d-title">${esc(m.title)}</h2>
        ${m.release_date ? `<div class="muted">Released ${esc(m.release_date)}</div>` : ""}
        <div class="metrics">
          <div class="metric"><span>CineTrust score</span><b>${num(m.cinetrust_score)}</b>${delta}</div>
          <div class="metric"><span>Confidence</span><b>${pct(m.confidence)}</b></div>
          <div class="metric"><span>Source disagreement</span><b>${num(m.controversy)} pts</b></div>
        </div>
        ${m.farming_alert ? `<div class="farm">🚨 Farming alert: ${m.n_suspicious_reviews} of ${m.n_reviews} reviews look coordinated and were down-weighted.</div>` : ""}
      </div>
    </div>
    <h3>How each source counted</h3>
    <table><thead><tr><th>Source</th><th>Score (0–100)</th><th>Weight in final score</th></tr></thead>
      <tbody>${rows}</tbody></table>
    ${parts.length < 3 ? `<p class="muted">Only one or two sources so far, so the 35% per-source cap isn't active yet.</p>` : ""}
    <h3>Down-weighted reviews (${m.flagged_reviews.length})</h3>
    ${reviews ? `<div class="reviews">${reviews}</div>`
      : `<p class="muted">${m.n_reviews ? `None of the ${m.n_reviews} written reviews look farmed.` : "No written reviews yet; this score comes from aggregate ratings only."}</p>`}`;
  const dlg = $("details");
  dlg.showModal();
  dlg.scrollTop = 0;
}

async function main() {
  try {
    const { doc, file } = await load();
    movies = doc.movies || [];
    const when = doc.generated_at ? new Date(doc.generated_at) : null;
    $("updated").textContent = when ? `Scores updated ${when.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}.` : "";
    if (doc.demo || file.includes("sample")) {
      $("banner").textContent = "Demo mode: synthetic movies and reviews, including two simulated review farms.";
      $("banner").hidden = false;
    }
  } catch (err) {
    $("banner").textContent = `Couldn't load ratings: ${err.message}`;
    $("banner").classList.add("error");
    $("banner").hidden = false;
    return;
  }
  renderKpis();
  renderGrid();
  for (const id of ["q", "sort", "alerts"]) $(id).addEventListener("input", renderGrid);
  $("grid").addEventListener("click", (e) => {
    const card = e.target.closest(".card");
    if (card) openDetails(movies.find((m) => m.imdb_id === card.dataset.id));
  });
  $("details").addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
}

main();
