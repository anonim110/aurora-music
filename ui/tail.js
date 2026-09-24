"use strict";

const $ = (selector) => document.querySelector(selector);
const api = () => window.pywebview?.api;
const fmt = (value) => {
  const seconds = Math.max(0, Math.floor(value || 0));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
};
let current = null;
let state = "idle";
let elapsed = 0;
let duration = 0;
let needsReveal = true;

function reveal() {
  if (!needsReveal) return;
  needsReveal = false;
  const widget = $(".widget");
  widget.classList.remove("entering");
  void widget.offsetWidth;
  widget.classList.add("entering");
}

function render() {
  const cover = current?.art_small || current?.art_big || "";
  const artwork = /^https?:\/\//i.test(cover) ? cover : "";
  const image = $("#art");
  if (artwork) image.src = artwork;
  else image.removeAttribute("src");
  image.hidden = !artwork;
  $("#t").textContent = current?.title || "Выберите трек";
  $("#a").textContent = current?.artist || "Музыка рядом";
  $("#pp").innerHTML = state === "playing" ? I.pause : I.play;
  $("#pp").disabled = state === "loading";
  $("#pp").setAttribute(
    "aria-label",
    state === "playing" ? "Пауза" : "Воспроизвести",
  );
  $("#stop").disabled = state === "idle";
  $(".widget").classList.toggle("is-idle", !current);
  updatePosition();
}

function updatePosition() {
  $("#pr").style.width = duration
    ? `${Math.min(100, Math.max(0, (elapsed / duration) * 100))}%`
    : "0%";
  $("#elapsed").textContent = fmt(elapsed);
  $("#duration").textContent = fmt(duration);
}

window.__emit = (event, data = {}) => {
  if (event === "show") {
    needsReveal = true;
    reveal();
  } else if (event === "status") {
    if (Object.hasOwn(data, "track")) {
      if (current?.id !== data.track?.id) elapsed = 0;
      current = data.track;
      duration = current?.duration || 0;
    }
    state = data.state;
    render();
  } else if (event === "position") {
    elapsed = data.elapsed || 0;
    duration = data.duration || 0;
    updatePosition();
  }
};

mountIcons();
$("#art").addEventListener("error", () => {
  $("#art").hidden = true;
});
for (const [selector, method] of Object.entries({
  "#restore": "restore",
  "#quit": "quit_app",
  "#prev": "prev_track",
  "#pp": "toggle",
  "#next": "next_track",
  "#stop": "stop_playback",
})) {
  $(selector).addEventListener("click", () => api()?.[method]());
}

render();
async function refreshState() {
  if (!api()) return;
  try {
    const snapshot = await api().get_state();
    current = snapshot.track;
    state = snapshot.state;
    elapsed = snapshot.elapsed || 0;
    duration = snapshot.duration || 0;
    render();
  } catch (error) {
    console.error(error);
  }
}
window.addEventListener("pywebviewready", refreshState);
window.addEventListener("focus", () => {
  reveal();
  refreshState();
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) needsReveal = true;
  else {
    reveal();
    refreshState();
  }
});
