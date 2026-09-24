"use strict";

// One 24px outline family for every surface, including the desktop player.
const outline = (paths) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;

const I = {
  logo: outline('<path d="M3 14V10m4 8V6m4 14V4m4 14V6m4 8v-4"/>'),
  home: outline(
    '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V10Z"/><path d="M9 21v-7h6v7"/>',
  ),
  search: outline(
    '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  ),
  heartO: outline(
    '<path d="M20.3 5.7a5.3 5.3 0 0 0-7.5 0L12 6.5l-.8-.8a5.3 5.3 0 0 0-7.5 7.5L12 21l8.3-7.8a5.3 5.3 0 0 0 0-7.5Z"/>',
  ),
  heartF:
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M20.3 5.7a5.3 5.3 0 0 0-7.5 0L12 6.5l-.8-.8a5.3 5.3 0 0 0-7.5 7.5L12 21l8.3-7.8a5.3 5.3 0 0 0 0-7.5Z"/></svg>',
  queue: outline(
    '<path d="M3 6h13M3 12h13M3 18h8"/><path d="m17 15 4 3-4 3v-6Z"/>',
  ),
  history: outline(
    '<path d="M3.5 11a8.5 8.5 0 1 1 .8 5.2"/><path d="M3 4v6h6m3-3v5l3 2"/>',
  ),
  refresh: outline(
    '<path d="M20 8a8 8 0 0 0-14-2L4 8m0-5v5h5M4 16a8 8 0 0 0 14 2l2-2m0 5v-5h-5"/>',
  ),
  play: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4.8a1 1 0 0 1 1.5-.86l11.2 7.2a1 1 0 0 1 0 1.72l-11.2 7.2A1 1 0 0 1 7 19.2V4.8Z"/></svg>',
  pause:
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="4.5" width="4" height="15" rx="1"/><rect x="14" y="4.5" width="4" height="15" rx="1"/></svg>',
  previous:
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="4" y="5" width="2.5" height="14" rx="1"/><path d="M19 5.8a1 1 0 0 0-1.5-.8L8 11.2a1 1 0 0 0 0 1.6l9.5 6.2a1 1 0 0 0 1.5-.8V5.8Z"/></svg>',
  next: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="17.5" y="5" width="2.5" height="14" rx="1"/><path d="M5 5.8a1 1 0 0 1 1.5-.8l9.5 6.2a1 1 0 0 1 0 1.6L6.5 19A1 1 0 0 1 5 18.2V5.8Z"/></svg>',
  shuffle: outline(
    '<path d="M3 6h3c5 0 7 12 12 12h3m-4-4 4 4-4 4M3 18h3c2.4 0 4-2.6 5.5-5M15 8c1-1.2 2-2 3-2h3m-4-4 4 4-4 4"/>',
  ),
  repeat: outline(
    '<path d="M17 3 21 7l-4 4M3 11V9a2 2 0 0 1 2-2h16M7 21l-4-4 4-4m14 0v2a2 2 0 0 1-2 2H3"/>',
  ),
  volume: outline(
    '<path d="M4 9v6h4l5 4V5L8 9H4Zm12-.5a5 5 0 0 1 0 7m2.5-9.5a9 9 0 0 1 0 12"/>',
  ),
  volMute: outline('<path d="M4 9v6h4l5 4V5L8 9H4Zm12 1 5 5m0-5-5 5"/>'),
  add: outline('<path d="M12 5v14M5 12h14"/>'),
  remove: outline('<path d="M5 12h14"/>'),
  stop: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>',
  open: outline(
    '<path d="M14 4h6v6m0-6-9 9"/><path d="M20 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h6"/>',
  ),
  close: outline('<path d="M5 5 19 19M19 5 5 19"/>'),
  music: outline(
    '<path d="M9 18V6l11-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
  ),
};

function mountIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((node) => {
    node.innerHTML = I[node.dataset.icon] || "";
  });
}
