"use strict";
const $ = (s) => document.querySelector(s),
  $$ = (s) => [...document.querySelectorAll(s)];
const S = {
  cur: null,
  status: "idle",
  elapsed: 0,
  duration: 0,
  vol: 0.8,
  lastVol: 0.8,
  shuffle: false,
  repeat: "off",
  liked: new Set(),
  page: "home",
  genre: "Все",
  query: "",
  home: {},
  search: null,
  fav: [],
  queue: [],
  history: [],
  pending: new Set(),
  errors: new Map(),
  sort: "default",
  filter: "",
  pct: null,
};
const esc = (x) =>
  String(x ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const fmt = (n) => {
  n = Math.max(0, Math.floor(n || 0));
  return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;
};
const key = (page = S.page, d = S) =>
  `${page}:${page === "home" ? d.genre : page === "search" ? d.query : ""}`;
const fill = (el) =>
  el.style.setProperty(
    "--p",
    `${(100 * (el.value - el.min)) / Math.max(el.max - el.min, 1)}%`,
  );
const art = (t) =>
  /^https?:\/\//i.test(t?.art_small || t?.art_big || "")
    ? t.art_small || t.art_big
    : "";
async function call(method, ...args) {
  try {
    if (!window.pywebview?.api)
      throw new Error("Откройте Aurora через run.bat");
    return await window.pywebview.api[method](...args);
  } catch (e) {
    toast(e.message || "Не удалось выполнить действие");
    return null;
  }
}
function toast(text) {
  $("#toast").textContent = text;
  $("#toast").classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $("#toast").classList.remove("show"), 3600);
}
window.__emit = (event, d = {}) => {
  if (event === "tracks") {
    S.pending.delete(key(d.page, d));
    S.errors.delete(key(d.page, d));
    if (d.page === "home") S.home[d.genre] = d.tracks;
    else if (d.page === "search" && d.query === S.query) S.search = d.tracks;
    else if (["fav", "queue", "history"].includes(d.page)) S[d.page] = d.tracks;
    if (key(d.page, d) === key()) render();
  } else if (event === "loading") {
    S.pending.add(key(d.page, d));
    S.errors.delete(key(d.page, d));
    if (key(d.page, d) === key()) render();
  } else if (event === "page_error") {
    S.pending.delete(key(d.page, d));
    S.errors.set(key(d.page, d), d.msg);
    if (key(d.page, d) === key()) render();
  } else if (event === "status") {
    if (
      S.cur?.id !== d.track?.id ||
      (d.state === "loading" && S.status !== "loading")
    )
      S.elapsed = 0;
    if (Object.hasOwn(d, "track")) {
      S.cur = d.track;
      S.duration = d.track?.duration || 0;
    }
    S.status = d.state;
    S.pct = d.pct ?? null;
    updateBar();
    highlight();
  } else if (event === "position") {
    S.elapsed = d.elapsed || 0;
    S.duration = d.duration || 0;
    updateSeek();
  } else if (event === "liked") {
    S.liked = new Set(d.liked);
    hearts();
  } else if (event === "prefs") {
    S.shuffle = d.shuffle;
    S.repeat = d.repeat;
    toggles();
  } else if (event === "queue" || event === "history") {
    S[event] = d.tracks;
    $("#queue-count").textContent = S.queue.length;
    if (S.page === event) render();
  } else if (event === "toast") toast(d.text);
};
async function go(page, opts = {}) {
  if (S.page !== page) {
    S.filter = "";
    S.sort = "default";
  }
  S.page = page;
  S.genre = opts.genre || S.genre;
  if (opts.query !== undefined) {
    if (opts.query !== S.query) S.search = null;
    S.query = opts.query;
    $("#q").value = S.query;
  }
  $$(".nav-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.page === page);
    b.setAttribute("aria-current", b.dataset.page === page ? "page" : "false");
  });
  const requestKey = key();
  S.errors.delete(requestKey);
  if (page !== "search" || S.query) S.pending.add(requestKey);
  render();
  let result;
  if (page === "home")
    result = await call("page_home", S.genre, opts.force ? 1 : 0);
  else if (page === "search" && S.query)
    result = await call("page_search", S.query);
  else if (page === "fav") result = await call("page_favorites");
  else if (["queue", "history"].includes(page))
    result = await call("page_library", page);
  if (result === null) {
    S.pending.delete(requestKey);
    S.errors.set(
      requestKey,
      "Нет соединения с плеером. Запустите приложение через run.bat.",
    );
    if (key() === requestKey) render();
  }
  if (page === "search" && !S.query) $("#q").focus();
}
const allTracks = () =>
  S.page === "home" ? S.home[S.genre] || [] : S[S.page] || [];
function visibleList() {
  let tracks = allTracks().filter((t) =>
    `${t.title} ${t.artist}`
      .toLocaleLowerCase()
      .includes(S.filter.toLocaleLowerCase()),
  );
  if (S.page !== "queue" && S.sort !== "default")
    tracks = [...tracks].sort((a, b) =>
      S.sort === "duration"
        ? a.duration - b.duration
        : a[S.sort].localeCompare(b[S.sort], "ru"),
    );
  return tracks;
}
function trackHtml(t, index) {
  const card = S.page === "home",
    liked = S.liked.has(t.id),
    url = art(t);
  return `<article class="${card ? "card" : "rowt"}" data-track="${esc(t.id)}">
    ${card ? "" : `<span class="track-index">${String(index + 1).padStart(2, "0")}</span>`}
    <div class="art-wrap">${url ? `<img src="${esc(url)}" alt="" loading="lazy">` : `<span class="art-ph">${I.music}</span>`}</div>
    <button class="track-info" data-play="${esc(t.id)}" title="Слушать: ${esc(t.title)}"><span class="t">${esc(t.title)}</span><span class="a">${esc(t.artist)}</span></button>
    <span class="dur">${t.duration ? fmt(t.duration) : "—"}</span>
    <div class="track-actions"><button class="ghost-btn small ${liked ? "liked" : ""}" data-like="${esc(t.id)}" aria-label="Избранное: ${esc(t.title)}" aria-pressed="${liked}">${liked ? I.heartF : I.heartO}</button>
    <button class="ghost-btn small queue-action" data-${S.page === "queue" ? "remove" : "enqueue"}="${esc(t.id)}" title="${S.page === "queue" ? "Убрать из очереди" : "Добавить в очередь"}" aria-label="${S.page === "queue" ? "Убрать из очереди" : "Добавить в очередь"}: ${esc(t.title)}">${S.page === "queue" ? I.remove : I.add}</button>
    <button class="play-mini" data-play="${esc(t.id)}" aria-label="Слушать: ${esc(t.title)}">${I.play}</button></div></article>`;
}
function toolbar() {
  return `<div class="library-tools"><button class="primary-btn" data-play-all ${visibleList().length ? "" : "disabled"}>${I.play} Слушать всё</button>
    ${S.page !== "queue" ? '<label class="filter-field"><span>Порядок</span><select id="sort"><option value="default">Исходный</option><option value="title">По названию</option><option value="artist">По исполнителю</option><option value="duration">По длительности</option></select></label>' : ""}
    <input id="filter" type="search" aria-label="Фильтр списка" placeholder="Фильтр списка" value="${esc(S.filter)}"></div>`;
}
function render() {
  const names = {
    home: "Популярное",
    search: "Поиск",
    fav: "Избранное",
    queue: "Очередь",
    history: "Недавно слушали",
  };
  const subs = {
    home: "Подборка на эту неделю.",
    search: S.query
      ? `Результаты для «${S.query}»`
      : "Любимые исполнители и новые имена — в одном поиске.",
    fav: "Треки, к которым хочется возвращаться.",
    queue:
      "Ваш порядок воспроизведения. Добавляйте треки кнопкой «Добавить в очередь».",
    history: "Последние 100 треков, которые вы слушали.",
  };
  $("#crumbs").textContent =
    S.page === "home" ? "Обзор / Музыка" : `Моя музыка / ${names[S.page]}`;
  const tracks = visibleList(),
    loading = S.pending.has(key()),
    error = S.errors.get(key());
  let html = `<header class="page-head"><div class="eyebrow">${S.page === "home" ? "ВАШ ЕЖЕДНЕВНЫЙ ПЛЕЙЛИСТ" : "БИБЛИОТЕКА AURORA"}</div><h1>${names[S.page]}</h1><p>${esc(subs[S.page])}</p></header>`;
  if (S.page === "home")
    html += `<div class="chips">${["Все", "Electronic", "Hip-Hop/Rap", "House", "Pop", "Techno", "Lo-Fi", "Rock"].map((g) => `<button class="chip ${S.genre === g ? "active" : ""}" data-genre="${esc(g)}" aria-pressed="${S.genre === g}">${esc(g)}</button>`).join("")}</div>`;
  if (allTracks().length) html += toolbar();
  if (error)
    html += `<div class="error-state" role="alert">${esc(error)} <button class="retry" data-retry>Повторить</button></div>`;
  if (loading && !allTracks().length)
    html +=
      '<div class="state" role="status"><span class="spin">◠</span><h2>Загружаем музыку</h2><p>Получаем треки из каталога…</p></div>';
  else if (tracks.length)
    html += `<div class="list-caption"><span>${S.page === "home" ? "ПОПУЛЯРНЫЕ ТРЕКИ" : "ТРЕКИ"} <b>${tracks.length}</b></span><span>${loading ? "Обновляем…" : fmt(tracks.reduce((sum, t) => sum + t.duration, 0)) + " суммарно"}</span></div><div class="${S.page === "home" ? "cards" : "list"}">${tracks.map(trackHtml).join("")}</div>`;
  else if (!error) {
    const messages = {
      home: ["Пока нет треков", "Выберите другой жанр или обновите каталог."],
      search: [
        S.query ? "Ничего не найдено" : "Что послушаем?",
        S.query
          ? "Попробуйте другое название или имя исполнителя."
          : "Введите название трека или исполнителя в строке сверху.",
      ],
      fav: [
        "Сохраните любимое",
        "Нажмите на сердце рядом с треком — он появится здесь.",
      ],
      queue: [
        "Очередь пуста",
        "Добавьте треки кнопкой + или начните слушать подборку.",
      ],
      history: [
        "Здесь будет ваша история",
        "Включите первый трек — мы сохраним его здесь.",
      ],
    };
    const [title, description] = allTracks().length
      ? ["Нет совпадений", "Измените текст фильтра."]
      : messages[S.page];
    html += `<div class="state"><span class="empty-mark">${I.music}</span><h2>${title}</h2><p>${description}</p>${["fav", "queue", "history"].includes(S.page) ? '<button class="primary-btn" data-browse>Открыть музыку</button>' : ""}</div>`;
  }
  const c = $("#content"),
    scroll = c.scrollTop;
  c.innerHTML = html;
  c.scrollTop = scroll;
  if ($("#sort")) $("#sort").value = S.sort;
  $("#queue-count").textContent = S.queue.length;
  highlight();
}
function highlight() {
  $$("[data-track]").forEach((el) => {
    const current = el.dataset.track === S.cur?.id;
    el.classList.toggle("current", current);
    el.querySelector(".play-mini").innerHTML =
      current && S.status === "playing" ? I.pause : I.play;
  });
}
function hearts() {
  $$("[data-like]").forEach((b) => {
    const liked = S.liked.has(b.dataset.like);
    b.innerHTML = liked ? I.heartF : I.heartO;
    b.classList.toggle("liked", liked);
    b.setAttribute("aria-pressed", String(liked));
  });
  const liked = S.liked.has(S.cur?.id);
  $("#bar-like").innerHTML = liked ? I.heartF : I.heartO;
  $("#bar-like").classList.toggle("liked", liked);
  $("#bar-like").setAttribute("aria-pressed", String(liked));
}
let seeking = false;
function updateSeek() {
  const seek = $("#seek");
  seek.max = Math.max(S.duration, 1);
  seek.disabled =
    !S.cur || !S.duration || !["playing", "paused"].includes(S.status);
  if (!seeking) {
    seek.value = S.elapsed;
    $("#t-cur").textContent = fmt(S.elapsed);
    fill(seek);
  }
  $("#t-dur").textContent = fmt(S.duration);
}
function updateBar() {
  $("#bar-title").textContent = S.cur?.title || "Музыка начинается здесь";
  $("#bar-artist").textContent =
    S.status === "loading"
      ? `Загрузка${S.pct === null ? "…" : ` · ${S.pct}%`}`
      : S.cur?.artist || "Выберите трек и нажмите «Слушать»";
  const url = art(S.cur);
  if (url) $("#bar-art").src = url;
  else $("#bar-art").removeAttribute("src");
  $("#bar-art").style.visibility = url ? "visible" : "hidden";
  $("#btn-play").innerHTML =
    S.status === "loading"
      ? '<span class="spin">◠</span>'
      : S.status === "playing"
        ? I.pause
        : I.play;
  $("#btn-play").disabled = S.status === "loading";
  $("#btn-play").setAttribute(
    "aria-label",
    S.status === "playing" ? "Пауза" : "Воспроизвести",
  );
  $("#bar-like").disabled = !S.cur;
  hearts();
  updateSeek();
}
function toggles() {
  $("#btn-shuffle").classList.toggle("on", S.shuffle);
  $("#btn-shuffle").setAttribute("aria-pressed", String(S.shuffle));
  $("#btn-repeat").classList.toggle("on", S.repeat !== "off");
  $("#btn-repeat").setAttribute("aria-pressed", String(S.repeat !== "off"));
  $("#btn-repeat").title =
    `Повтор: ${{ off: "выключен", all: "всей очереди", one: "одного трека" }[S.repeat]}`;
  $("#repeat-one").classList.toggle("hidden", S.repeat !== "one");
}
function volume(value) {
  S.vol = value;
  if (value > 0) S.lastVol = value;
  $("#vol").value = value;
  fill($("#vol"));
  $("#vol-btn").innerHTML = value ? I.volume : I.volMute;
}
function playTrack(id) {
  call("play", id, S.page === "queue" ? null : visibleList().map((t) => t.id));
}
function bind() {
  $$("button[title]").forEach((b) => b.setAttribute("aria-label", b.title));
  $$(".nav-btn").forEach((b) =>
    b.addEventListener("click", () => go(b.dataset.page)),
  );
  $("#content").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.hasAttribute("data-like")) call("like", b.dataset.like);
    else if (b.hasAttribute("data-enqueue"))
      call("queue_add", b.dataset.enqueue);
    else if (b.hasAttribute("data-remove"))
      call("queue_remove", b.dataset.remove);
    else if (b.hasAttribute("data-play")) playTrack(b.dataset.play);
    else if (b.hasAttribute("data-play-all")) {
      const first = visibleList()[0];
      if (first) playTrack(first.id);
    } else if (b.hasAttribute("data-genre"))
      go("home", { genre: b.dataset.genre });
    else if (b.hasAttribute("data-retry")) go(S.page, { force: true });
    else if (b.hasAttribute("data-browse")) go("home");
  });
  $("#content").addEventListener("change", (e) => {
    if (e.target.id === "sort") {
      S[e.target.id] = e.target.value;
      render();
    }
  });
  $("#content").addEventListener("input", (e) => {
    if (e.target.id === "filter") {
      const start = e.target.selectionStart,
        end = e.target.selectionEnd;
      S.filter = e.target.value;
      render();
      const input = $("#filter");
      if (input) {
        input.focus({ preventScroll: true });
        input.setSelectionRange(start, end);
      }
    }
  });
  $("#content").addEventListener(
    "error",
    (e) => {
      if (e.target.tagName === "IMG") {
        e.target.hidden = true;
        e.target.parentElement.classList.add("art-failed");
      }
    },
    true,
  );
  const search = () => go("search", { query: $("#q").value.trim() });
  $("#q").addEventListener("keydown", (e) => {
    if (e.key === "Enter") search();
  });
  $("#btn-search-go").addEventListener("click", search);
  $("#btn-refresh").addEventListener("click", () =>
    go(S.page, { force: true }),
  );
  const actions = {
    "btn-play": "toggle",
    "btn-next": "next_track",
    "btn-prev": "prev_track",
    "btn-shuffle": "shuffle_toggle",
    "btn-repeat": "repeat_cycle",
    "btn-quit": "quit_app",
  };
  for (const [id, method] of Object.entries(actions))
    $(`#${id}`).addEventListener("click", () => call(method));
  $("#bar-like").addEventListener("click", () => {
    if (S.cur) call("like", S.cur.id);
  });
  $("#seek").addEventListener("input", (e) => {
    seeking = true;
    fill(e.target);
    $("#t-cur").textContent = fmt(+e.target.value);
  });
  $("#seek").addEventListener("change", (e) => {
    S.elapsed = +e.target.value;
    seeking = false;
    call("seek", S.elapsed);
    updateSeek();
  });
  $("#seek").addEventListener("blur", () => {
    seeking = false;
    updateSeek();
  });
  $("#vol").addEventListener("input", (e) => {
    volume(+e.target.value);
    call("set_volume", S.vol);
  });
  $("#vol").addEventListener("change", () => call("save_prefs"));
  $("#vol-btn").addEventListener("click", async () => {
    volume(S.vol ? 0 : S.lastVol);
    await call("set_volume", S.vol);
    call("save_prefs");
  });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
      e.preventDefault();
      $("#q").focus();
      $("#q").select();
      return;
    }
    if (e.target.closest("input,select,textarea,button,[contenteditable]"))
      return;
    if (e.code === "Space") {
      e.preventDefault();
      call("toggle");
    }
    if (e.altKey && e.key === "ArrowRight") {
      e.preventDefault();
      call("next_track");
    }
    if (e.altKey && e.key === "ArrowLeft") {
      e.preventDefault();
      call("prev_track");
    }
  });
}
let initialized = false;
async function init() {
  if (initialized) return;
  initialized = true;
  const st = await call("get_state");
  if (!st) {
    initialized = false;
    return;
  }
  S.cur = st.track;
  S.status = st.state;
  S.elapsed = st.elapsed || 0;
  S.duration = st.duration || 0;
  S.shuffle = !!st.shuffle;
  S.repeat = st.repeat || "off";
  S.liked = new Set(st.liked || []);
  S.queue = st.queue || [];
  S.history = st.history || [];
  volume(st.volume ?? 0.8);
  toggles();
  updateBar();
  const ui = st.ui || {};
  S.query = ui.query || "";
  $("#q").value = S.query;
  go(
    ["home", "search", "fav", "queue", "history"].includes(ui.page)
      ? ui.page
      : "home",
    { genre: ui.genre || "Все" },
  );
}
mountIcons();
bind();
volume(0.8);
updateBar();
render();
window.addEventListener("pywebviewready", init);
if (window.pywebview?.api) init();
window.addEventListener("focus", async () => {
  if (!initialized) return;
  const st = await call("get_state");
  if (!st) return;
  S.cur = st.track;
  S.status = st.state;
  S.elapsed = st.elapsed || 0;
  S.duration = st.duration || 0;
  S.shuffle = !!st.shuffle;
  S.repeat = st.repeat || "off";
  S.liked = new Set(st.liked || []);
  S.queue = st.queue || [];
  S.history = st.history || [];
  volume(st.volume ?? S.vol);
  toggles();
  updateBar();
  render();
});
