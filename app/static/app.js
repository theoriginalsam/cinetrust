// CineTrust frontend: hash-routed single page app over /api/home and /api/movie/{id}.
"use strict";

const IMG = "https://image.tmdb.org/t/p/";
const SOURCE_LABELS = {
  imdb: "IMDb", rotten_tomatoes: "Rotten Tomatoes", metacritic: "Metacritic", tmdb: "TMDB votes",
  tmdb_reviews: "TMDB reviews", trakt_reviews: "Trakt reviews", youtube_reviews: "YouTube trailer comments",
};
const REVIEW_SOURCE = { tmdb: "TMDB", youtube: "YouTube", trakt: "Trakt" };
const REASONS = {
  near_duplicate_text: "Copy-paste text", account_burst: "Account mass-posting",
  coordinated_wave: "Part of a review wave", rating_text_mismatch: "Rating doesn't match text",
  statistical_outlier: "Unusual behaviour",
};
const SORTS = {
  positive: ["Most positive", (a, b) => (b.value ?? -1) - (a.value ?? -1)],
  negative: ["Most negative", (a, b) => (a.value ?? 101) - (b.value ?? 101)],
  newest: ["Newest", (a, b) => String(b.created_at).localeCompare(String(a.created_at))],
  trusted: ["Most trusted", (a, b) => (b.trust ?? 0) - (a.trust ?? 0)],
  liked: ["Most liked", (a, b) => (b.likes ?? 0) - (a.likes ?? 0)],
};
const PAGE = 25;
// Static mode (GitHub Pages): same UI, data from pre-exported JSON instead of the live API.
const STATIC = document.documentElement.dataset.static === "1";
const API = {
  home: () => (STATIC ? "data/home.json" : "api/home"),
  movie: (id) => (STATIC ? `data/movie/${encodeURIComponent(id)}.json` : `api/movie/${encodeURIComponent(id)}`),
};

const view = document.getElementById("view");
const search = document.getElementById("search");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const compact = (n) => Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n || 0);
const year = (d) => (d ? String(d).slice(0, 4) : "");
const tier = (s) => (s >= 75 ? "high" : s >= 60 ? "mid" : "low");
const fmtDate = (d, opts = { month: "short", day: "numeric", year: "numeric" }) =>
  d ? new Date(String(d).length <= 10 ? `${d}T00:00:00` : d).toLocaleDateString("en", opts) : "";
const runtime = (m) => (m ? `${Math.floor(m / 60)}h ${m % 60}m` : "");

let home = null;
let heroTimer = null;

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function ring(value, size = "md", kind = null, label = "") {
  const px = { lg: 104, md: 54, sm: 42 }[size];
  const stroke = { lg: 8, md: 5, sm: 4 }[size];
  const r = (px - stroke) / 2, c = 2 * Math.PI * r;
  const v = value == null ? 0 : Math.max(0, Math.min(100, value));
  const cls = kind || `tier-${tier(v)}`;
  return `<div class="ring ${size} ${cls}" role="img" aria-label="${label || "Score"} ${value == null ? "not available" : Math.round(v)}">
    <svg width="${px}" height="${px}"><circle class="track" cx="${px / 2}" cy="${px / 2}" r="${r}" stroke-width="${stroke}"/>
    <circle class="val" cx="${px / 2}" cy="${px / 2}" r="${r}" stroke-width="${stroke}" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - v / 100)}"/></svg>
    <div class="num">${value == null ? "–" : Math.round(v)}${size === "lg" && label ? `<small>${esc(label)}</small>` : ""}</div></div>`;
}

function poster(m, w = "w342") {
  return m.poster_path
    ? `<img src="${IMG}${w}${esc(m.poster_path)}" alt="${esc(m.title)} poster" loading="lazy">`
    : `<div class="noposter">${esc(m.title)}</div>`;
}

function setTab(tab) {
  document.querySelectorAll(".tabs a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
}

// ---------------------------------------------------------------- home
function heroHTML(list, upcoming) {
  const slides = list.filter((m) => m.backdrop_path).slice(0, 5);
  if (!slides.length) return "";
  return `<section class="hero" aria-label="Featured">
    ${slides.map((m, i) => `<div class="hero-slide ${i === 0 ? "on" : ""}">
      <img class="bg" src="${IMG}w1280${esc(m.backdrop_path)}" alt="" ${i ? 'loading="lazy"' : ""}>
      <div class="hero-content"><div class="wrap">
        <div class="hero-text">
          <div class="eyebrow">${upcoming ? `Coming ${fmtDate(m.release_date, { month: "long", day: "numeric" })}` : `#${i + 1} in theatres on CineTrust`}</div>
          <h1>${esc(m.title)}</h1>
          <div class="hero-meta">${[year(m.release_date), runtime(m.runtime), ...(m.genres || []).slice(0, 3)].filter(Boolean).map(esc).join(" · ")}
            ${m.farming_alert ? '<span class="tag alert">Farming alert</span>' : ""}</div>
          <p class="overview">${esc(m.overview)}</p>
          <div class="btn-row">
            <a class="btn btn-primary" href="#/movie/${esc(m.imdb_id)}">${upcoming ? "See the hype" : "Why this score"}</a>
            ${m.trailer_key ? `<a class="btn btn-ghost" href="#/movie/${esc(m.imdb_id)}?trailer=1">▶ Watch trailer</a>` : ""}
          </div>
        </div>
        ${upcoming ? ring(m.hype_score, "lg", "tier-hype", "hype") : ring(m.cinetrust_score, "lg", null, "score")}
      </div></div>
    </div>`).join("")}
    ${slides.length > 1 ? `<div class="dots">${slides.map((_, i) => `<button aria-label="Show slide ${i + 1}" class="${i === 0 ? "on" : ""}" data-i="${i}"></button>`).join("")}</div>` : ""}
  </section>`;
}

function startHero() {
  clearInterval(heroTimer);
  const slides = [...document.querySelectorAll(".hero-slide")];
  const dots = [...document.querySelectorAll(".dots button")];
  if (slides.length < 2) return;
  let i = 0;
  const show = (n) => {
    i = (n + slides.length) % slides.length;
    slides.forEach((s, k) => s.classList.toggle("on", k === i));
    dots.forEach((d, k) => d.classList.toggle("on", k === i));
  };
  dots.forEach((d) => d.addEventListener("click", () => { show(+d.dataset.i); startTimer(); }));
  const startTimer = () => { clearInterval(heroTimer); heroTimer = setInterval(() => show(i + 1), 7000); };
  startTimer();
}

function nowCard(m) {
  return `<a class="card" href="#/movie/${esc(m.imdb_id)}">
    <div class="poster-wrap">${poster(m)}
      ${m.farming_alert ? '<span class="tag alert flag">Farming alert</span>' : ""}
      ${ring(m.cinetrust_score, "md", null, "CineTrust score")}
    </div>
    <h3>${esc(m.title)}</h3>
    <div class="sub">${[(m.genres || [])[0], `${compact(m.n_reviews)} reviews`].filter(Boolean).map(esc).join(" · ")}</div>
  </a>`;
}

function soonCard(m) {
  const d = m.days_to_release;
  return `<a class="card" href="#/movie/${esc(m.imdb_id)}">
    <div class="poster-wrap">${poster(m)}
      <div class="date-badge"><small>${esc(fmtDate(m.release_date, { month: "short" }).toUpperCase())}</small>${esc(fmtDate(m.release_date, { day: "numeric" }))}</div>
      ${m.farming_alert ? '<span class="tag alert flag">Hype looks farmed</span>' : ""}
    </div>
    <h3>${esc(m.title)}</h3>
    <div class="sub">${d == null ? "" : d <= 0 ? "Out now" : d === 1 ? "Tomorrow" : `In ${d} days`}${m.genres?.[0] ? ` · ${esc(m.genres[0])}` : ""}</div>
    ${m.hype_score == null ? '<div class="sub">No buzz yet</div>' : `
      <div class="hype-bar" role="img" aria-label="Hype ${Math.round(m.hype_score)} of 100"><i style="width:${m.hype_score}%"></i></div>
      <div class="sub">Hype ${Math.round(m.hype_score)} · ${compact(Math.round(m.buzz_7d))} comments this week</div>`}
  </a>`;
}

const HOME_SORTS = {
  now: { score: ["Top rated", (a, b) => b.cinetrust_score - a.cinetrust_score],
    reviews: ["Most reviewed", (a, b) => b.n_reviews - a.n_reviews],
    confidence: ["Most certain", (a, b) => b.confidence - a.confidence],
    gap: ["Fixed the most", (a, b) => gap(b) - gap(a)] },
  upcoming: { buzz: ["Most buzz", (a, b) => b.buzz_7d - a.buzz_7d],
    hype: ["Highest hype", (a, b) => (b.hype_score ?? -1) - (a.hype_score ?? -1)],
    soon: ["Releasing soonest", (a, b) => (a.days_to_release ?? 999) - (b.days_to_release ?? 999)] },
};
const gap = (m) => (m.naive_review_average == null ? -1 : Math.abs(m.cinetrust_score - m.naive_review_average));
const homeState = { now: { sort: "score", alerts: false }, upcoming: { sort: "buzz", alerts: false } };

async function renderHome(tab) {
  setTab(tab);
  if (!home) {
    view.innerHTML = `<div class="skeleton" style="height:60vh"></div>`;
    home = await getJSON(API.home());
  }
  const upcoming = tab === "upcoming";
  const list = upcoming ? home.upcoming : home.now_playing;
  const s = home.stats;
  view.innerHTML = `${heroHTML(list, upcoming)}
    <div class="wrap">
      <div class="stats" style="${list.some((m) => m.backdrop_path) ? "" : "margin-top:24px"}">
        ${[[upcoming ? "Coming soon" : "Movies in theatres", upcoming ? s.upcoming : s.movies_in_theatres],
          ["Reviews checked", compact(s.reviews_checked)], ["Down-weighted as suspicious", compact(s.reviews_down_weighted)],
          ["Sources combined", s.sources]].map(([k, v]) => `<div class="stat"><span>${k}</span><b>${v}</b></div>`).join("")}
      </div>
      ${home.demo ? '<p class="note" style="background:var(--surface-2);color:var(--muted)">Demo mode: synthetic movies and reviews.</p>' : ""}
      <section class="section">
        <div class="section-head">
          <div><h2>${upcoming ? "Coming soon" : "In theatres now"}</h2>
            <p>${upcoming ? "Hype from trailer reactions, with bot and paid hype filtered out." : "One trustworthy score from many sources. Tap a movie to see every review."}</p></div>
          <div class="chips" id="home-controls">
            ${Object.entries(HOME_SORTS[tab]).map(([k, [label]]) => `<button class="chip ${homeState[tab].sort === k ? "on" : ""}" data-sort="${k}">${label}</button>`).join("")}
            <button class="chip ${homeState[tab].alerts ? "on" : ""}" data-alerts="1">⚠ Alerts only</button>
          </div>
        </div>
        <div class="grid" id="grid"></div>
      </section>
    </div>`;
  startHero();
  const draw = () => {
    const q = search.value.trim().toLowerCase();
    const st = homeState[tab];
    const items = list.filter((m) => (!q || m.title.toLowerCase().includes(q)) && (!st.alerts || m.farming_alert))
      .sort(HOME_SORTS[tab][st.sort][1]);
    document.getElementById("grid").innerHTML = items.length
      ? items.map(upcoming ? soonCard : nowCard).join("")
      : `<div class="empty">${list.length ? "No movies match." : "Nothing here yet. The daily job fills this in."}</div>`;
  };
  document.getElementById("home-controls").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.sort) homeState[tab].sort = b.dataset.sort;
    if (b.dataset.alerts) homeState[tab].alerts = !homeState[tab].alerts;
    document.querySelectorAll("#home-controls .chip").forEach((c) => c.classList.toggle("on",
      c.dataset.sort ? c.dataset.sort === homeState[tab].sort : homeState[tab].alerts));
    draw();
  });
  search.oninput = draw;
  draw();
}

// ---------------------------------------------------------------- movie page
function sourceBreakdown(m) {
  if (m.kind === "upcoming") return "";
  return `<div class="panel"><h3>How the score was built</h3>
    <p class="hint">Each source's score and how much it counts. No source can exceed 35% once there are three or more.</p>
    ${m.breakdown.map((b) => `<div class="src-row">
      <span class="name">${esc(SOURCE_LABELS[b.source] || b.source)}</span><span class="score">${Math.round(b.score)}</span>
      <div class="bar"><i style="width:${Math.round(b.share * 100)}%"></i></div>
      <span class="share">${Math.round(b.share * 100)}% of the final score</span></div>`).join("")}
  </div>`;
}

function opinionSplit(d) {
  const p = d.polarity, total = p.positive + p.mixed + p.negative;
  if (!total) return "";
  const pc = (n) => `${(100 * n / total).toFixed(1)}%`;
  return `<div class="panel" style="margin-top:16px"><h3>What people think</h3>
    <p class="hint">${total} of ${d.reviews.length} reviews state a clear opinion (star rating or readable sentiment).</p>
    <div class="sentiment-split"><i style="width:${pc(p.positive)};background:var(--good)"></i><i style="width:${pc(p.mixed)};background:var(--mid)"></i><i style="width:${pc(p.negative)};background:var(--bad)"></i></div>
    <div class="legend"><span style="--c:var(--good)">${p.positive} positive</span><span style="--c:var(--mid)">${p.mixed} mixed</span><span style="--c:var(--bad)">${p.negative} negative</span></div>
    ${d.down_weighted ? `<p class="hint" style="margin:12px 0 0">${d.down_weighted} reviews were down-weighted as suspicious. They're still listed, marked in red.</p>` : ""}
  </div>`;
}

function reviewCard(r) {
  const down = (r.trust ?? 1) < 0.5;
  const opinion = r.rating != null ? `★ ${Math.round(r.rating)}/10`
    : r.polarity ? r.polarity[0].toUpperCase() + r.polarity.slice(1) : "No clear opinion";
  const tcol = r.trust >= 0.8 ? "var(--good)" : r.trust >= 0.5 ? "var(--mid)" : "var(--bad)";
  const long = (r.text || "").length > 420;
  return `<article class="review ${down ? "down" : ""}">
    <div class="review-top">
      <span class="src ${REVIEW_SOURCE[r.source] ? esc(r.source) : "other"}">${esc(REVIEW_SOURCE[r.source] || r.source)}</span>
      ${r.author ? `<span class="author">${esc(r.author)}</span>` : ""}
      <span class="when">${esc(fmtDate(r.created_at))}</span>
      <span class="opinion ${r.polarity || "none"}">${esc(opinion)}</span>
    </div>
    <p class="review-text ${long ? "clamp" : ""}">${esc(r.text)}</p>
    ${long ? '<button class="more">Read more</button>' : ""}
    <div class="review-foot">
      ${r.trust != null ? `<span class="trust">Trust <span class="meter"><i style="width:${Math.round(r.trust * 100)}%;background:${tcol}"></i></span> ${Math.round(r.trust * 100)}%</span>` : ""}
      ${(r.reasons || []).map((x) => `<span class="tag alert">${esc(REASONS[x] || x)}</span>`).join("")}
      ${r.likes ? `<span>👍 ${compact(r.likes)}</span>` : ""}
      ${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">View original ↗</a>` : ""}
    </div>
  </article>`;
}

async function renderMovie(id, params) {
  clearInterval(heroTimer);
  setTab(null);
  view.innerHTML = `<div class="skeleton" style="height:520px"></div>`;
  let d;
  try {
    d = await getJSON(API.movie(id));
  } catch (e) {
    view.innerHTML = `<div class="error"><h2>Movie not found</h2><p>${esc(e.message)}</p><a class="btn btn-primary" href="#/">Back to movies</a></div>`;
    return;
  }
  const m = d.movie, upcoming = m.kind === "upcoming";
  const state = { source: "all", sort: "positive", filter: "all", shown: PAGE };
  const facts = upcoming
    ? [["Release", m.days_to_release > 0 ? `In ${m.days_to_release} days` : "Out now"], ["Comments", compact(m.n_reviews)], ["This week", compact(Math.round(m.buzz_7d))]]
    : [["Plain average", m.naive_review_average == null ? "–" : Math.round(m.naive_review_average)],
       ["Confidence", `${Math.round((m.confidence || 0) * 100)}%`], ["Sources", m.n_sources]];
  view.innerHTML = `
    <section class="mhero">
      ${m.backdrop_path ? `<img class="bg" src="${IMG}w1280${esc(m.backdrop_path)}" alt="">` : ""}
      <div class="wrap">
        <div class="poster-wrap">${poster(m, "w500")}</div>
        <div>
          <a class="back" href="${upcoming ? "#/upcoming" : "#/"}">← ${upcoming ? "Coming soon" : "In theatres"}</a>
          <div class="eyebrow">${upcoming ? `Releasing ${esc(fmtDate(m.release_date, { month: "long", day: "numeric", year: "numeric" }))}` : "In theatres now"}</div>
          <h1>${esc(m.title)}</h1>
          <div class="hero-meta">${[year(m.release_date), runtime(m.runtime)].filter(Boolean).map(esc).join(" · ")}
            ${(m.genres || []).map((g) => `<span class="tag">${esc(g)}</span>`).join("")}</div>
          <div class="score-row">
            ${upcoming ? ring(m.hype_score, "lg", "tier-hype", "hype") : ring(m.cinetrust_score, "lg", null, "CineTrust")}
            <div class="score-facts">${facts.map(([k, v]) => `<div><span>${k}</span><b>${esc(v)}</b></div>`).join("")}</div>
          </div>
          ${m.farming_alert ? `<div class="note">⚠ ${upcoming ? "Some of this hype looks farmed" : "Farming alert"}: ${m.n_suspicious_reviews} of ${m.n_reviews} ${upcoming ? "comments" : "reviews"} look coordinated and count much less.</div>` : ""}
          <p class="overview">${esc(m.overview)}</p>
          <div class="btn-row">${m.trailer_key ? '<button class="btn btn-primary" id="play">▶ Watch trailer</button>' : ""}
            <a class="btn btn-ghost" href="#reviews" id="jump">Read ${compact(d.reviews.length)} ${upcoming ? "reactions" : "reviews"}</a></div>
          <div id="trailer-slot"></div>
        </div>
      </div>
    </section>
    <div class="wrap section">
      <div class="two-col">
        <aside>${sourceBreakdown(m)}${opinionSplit(d)}</aside>
        <section id="reviews" aria-label="Reviews">
          <div class="reviews-head"><h2>${upcoming ? "Trailer reactions" : "Reviews"}</h2>
            <label><span class="sr-only">Sort reviews</span><select class="sort" id="sort">
              ${Object.entries(SORTS).map(([k, [label]]) => `<option value="${k}">${label}</option>`).join("")}</select></label></div>
          <div class="filter-row">
            <div class="chips" id="src-chips">
              <button class="chip on" data-src="all">All <span class="count">${d.reviews.length}</span></button>
              ${d.sources.map((s) => `<button class="chip" data-src="${esc(s.source)}">${esc(REVIEW_SOURCE[s.source] || s.source)} <span class="count">${s.count}</span></button>`).join("")}
            </div>
            <div class="chips" id="pol-chips">
              ${[["all", "Everything"], ["positive", "👍 Good"], ["mixed", "Mixed"], ["negative", "👎 Bad"], ["down", "⚠ Down-weighted"]]
                .map(([k, label]) => `<button class="chip ${k === "all" ? "on" : ""}" data-pol="${k}">${label}</button>`).join("")}
            </div>
          </div>
          <div id="review-list"></div>
        </section>
      </div>
    </div>`;

  const playTrailer = () => {
    document.getElementById("trailer-slot").innerHTML = `<div class="trailer"><iframe
      src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(m.trailer_key)}?autoplay=1&rel=0"
      title="${esc(m.title)} trailer" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div>`;
    document.getElementById("play")?.remove();
  };
  document.getElementById("play")?.addEventListener("click", playTrailer);
  if (params.get("trailer") && m.trailer_key) playTrailer();
  document.getElementById("jump").addEventListener("click", (e) => {
    e.preventDefault();
    document.getElementById("reviews").scrollIntoView({ behavior: "smooth" });
  });

  const list = document.getElementById("review-list");
  const draw = () => {
    const items = d.reviews
      .filter((r) => state.source === "all" || r.source === state.source)
      .filter((r) => state.filter === "all" || (state.filter === "down" ? (r.trust ?? 1) < 0.5 : r.polarity === state.filter))
      .sort(SORTS[state.sort][1]);
    list.innerHTML = items.length
      ? items.slice(0, state.shown).map(reviewCard).join("") +
        (items.length > state.shown ? `<button class="btn btn-ghost load-more" id="more">Show more (${items.length - state.shown} left)</button>` : "")
      : `<div class="empty">No reviews match these filters.</div>`;
  };
  const chipGroup = (id, key, attr) => document.getElementById(id).addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    state[key] = b.dataset[attr];
    state.shown = PAGE;
    document.querySelectorAll(`#${id} .chip`).forEach((c) => c.classList.toggle("on", c === b));
    draw();
  });
  chipGroup("src-chips", "source", "src");
  chipGroup("pol-chips", "filter", "pol");
  document.getElementById("sort").addEventListener("change", (e) => { state.sort = e.target.value; draw(); });
  list.addEventListener("click", (e) => {
    if (e.target.id === "more") { state.shown += PAGE; draw(); return; }
    if (e.target.classList.contains("more")) {
      const text = e.target.previousElementSibling;
      const open = text.classList.toggle("clamp");
      e.target.textContent = open ? "Read more" : "Show less";
    }
  });
  draw();
}

// ---------------------------------------------------------------- router
async function route() {
  const [path, query] = (location.hash.slice(1) || "/").split("?");
  const params = new URLSearchParams(query || "");
  const movie = path.match(/^\/movie\/([^/]+)$/);
  try {
    if (movie) await renderMovie(decodeURIComponent(movie[1]), params);
    else await renderHome(path === "/upcoming" ? "upcoming" : "now");
  } catch (e) {
    view.innerHTML = `<div class="error"><h2>Couldn't load CineTrust</h2><p>${esc(e.message)}</p>
      <button class="btn btn-primary" onclick="location.reload()">Try again</button></div>`;
  }
  window.scrollTo(0, 0);
}

search.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && location.hash.startsWith("#/movie/")) location.hash = "#/";
});
window.addEventListener("hashchange", route);
route();
