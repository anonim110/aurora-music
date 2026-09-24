// Offline interface regression checks. PLAYWRIGHT_MODULE may point to a bundled runtime.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
const { pathToFileURL } = require("node:url");
const path = require("node:path");
(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 1200, height: 800 },
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.addInitScript(() => {
      const tracks = [
        {
          id: "a",
          title: "Northern Lights",
          artist: "Kairo",
          duration: 240,
          kind: "audius",
          source: "Audius",
        },
        {
          id: "b",
          title: "A Quiet Morning",
          artist: "Sora",
          duration: 180,
          kind: "youtube",
          source: "YouTube",
        },
        {
          id: "c",
          title: "Between the Lines",
          artist: "Juno",
          duration: 210,
          kind: "audius",
          source: "Audius",
        },
        {
          id: "d",
          title: "Late Train",
          artist: "Monroe",
          duration: 195,
          kind: "audius",
          source: "Audius",
        },
        {
          id: "e",
          title: "Open Water",
          artist: "Hana",
          duration: 224,
          kind: "audius",
          source: "Audius",
        },
      ];
      const state = {
        track: null,
        state: "idle",
        volume: 0.37,
        liked: [],
        queue: [],
        history: [],
        shuffle: false,
        repeat: "off",
      };
      window.testCalls = [];
      const emit = (ev, d) => window.__emit(ev, d);
      window.pywebview = {
        api: {
          get_state: async () => state,
          page_home: async (genre) => {
            emit("tracks", { page: "home", genre, tracks });
            return "ok";
          },
          page_search: async (query) => {
            emit("loading", { page: "search", query });
            if (query === "offline")
              emit("page_error", {
                page: "search",
                query,
                msg: "Нет соединения",
              });
            else
              setTimeout(
                () =>
                  emit("tracks", {
                    page: "search",
                    query,
                    tracks: query === "empty" ? [] : tracks,
                  }),
                30,
              );
            return "ok";
          },
          page_favorites: async () => {
            emit("tracks", {
              page: "fav",
              tracks: tracks.filter((t) => state.liked.includes(t.id)),
            });
            return "ok";
          },
          page_library: async (page) => {
            emit("tracks", { page, tracks: state[page] });
            return "ok";
          },
          queue_add: async (id) => {
            state.queue.push(tracks.find((t) => t.id === id));
            emit("queue", { tracks: state.queue });
          },
          queue_remove: async (id) => {
            state.queue = state.queue.filter((t) => t.id !== id);
            emit("queue", { tracks: state.queue });
          },
          play: async (id, ids) => {
            window.testCalls.push(["play", id, ids]);
            state.track = tracks.find((t) => t.id === id);
            state.state = "playing";
            emit("status", { state: "playing", track: state.track });
          },
          toggle: async () => {
            state.state = state.state === "playing" ? "paused" : "playing";
            emit("status", { state: state.state, track: state.track });
          },
          like: async (id) => {
            state.liked = state.liked.includes(id)
              ? state.liked.filter((i) => i !== id)
              : [...state.liked, id];
            emit("liked", { liked: state.liked });
          },
          set_volume: async (v) => window.testCalls.push(["volume", v]),
          save_prefs: async () => {},
          seek: async (v) => {
            window.testCalls.push(["seek", v]);
            emit("position", { elapsed: v, duration: 240 });
          },
          shuffle_toggle: async () => {
            state.shuffle = !state.shuffle;
            emit("prefs", state);
          },
          repeat_cycle: async () => {
            state.repeat = { off: "all", all: "one", one: "off" }[state.repeat];
            emit("prefs", state);
          },
        },
      };
    });
    await page.goto(
      pathToFileURL(path.resolve(__dirname, "../ui/index.html")).href,
    );
    await page.locator(".card").first().waitFor();
    assert.equal(
      await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--bg").trim()),
      "#101010",
    );
    assert.equal(await page.locator(".card").count(), 5);
    await page.locator('[data-enqueue="a"]').click();
    await page.locator('[data-page="queue"]').click();
    assert.equal(await page.locator(".rowt").count(), 1);
    await page.locator('[data-remove="a"]').click();
    await page.getByText("Очередь пуста", { exact: true }).waitFor();
    await page.locator("#q").fill("offline");
    await page.locator("#q").press("Enter");
    await page.locator('[role="alert"]').waitFor();
    assert.equal(await page.locator(".state .spin").count(), 0);
    await page.locator("#q").fill("quiet");
    await page.locator("#q").press("Enter");
    await page.locator(".rowt").first().waitFor();
    assert.equal(await page.locator("#source").count(), 0);
    assert.equal(await page.getByText("Audius").count(), 0);
    assert.equal(await page.getByText("YouTube").count(), 0);
    assert.equal(await page.locator(".nav-btn svg").count(), 5);
    await page.locator("#sort").selectOption("title");
    assert.equal(
      await page.locator(".rowt .t").first().innerText(),
      "A Quiet Morning",
    );
    await page.locator("#filter").fill("juno");
    assert.equal(await page.locator(".rowt").count(), 1);
    await page.locator("#filter").fill("");
    await page.locator('[data-play="a"]').first().click();
    await page.locator("#btn-play").click();
    assert.equal(
      await page.locator("#btn-play").getAttribute("aria-label"),
      "Воспроизвести",
    );
    await page.locator("#vol-btn").click();
    await page.locator("#vol-btn").click();
    assert.equal(await page.locator("#vol").inputValue(), "0.37");
    await page.evaluate(() =>
      window.__emit("status", { state: "idle", track: null }),
    );
    assert.equal(
      await page.locator("#bar-title").innerText(),
      "Музыка начинается здесь",
    );
    await page.evaluate(() =>
      window.__emit("page_error", {
        page: "home",
        genre: "Rock",
        msg: "STALE ERROR",
      }),
    );
    assert.equal(
      await page.getByText("STALE ERROR", { exact: true }).count(),
      0,
    );
    await page.keyboard.press("Control+f");
    assert.equal(
      await page.locator("#q").evaluate((el) => document.activeElement === el),
      true,
    );
    await page.locator('[data-page="home"]').click();
    await page.screenshot({
      path: path.join(__dirname, "preview.png"),
      fullPage: true,
    });
    for (const width of [1000, 760, 600]) {
      await page.setViewportSize({ width, height: 740 });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        true,
        `Overflow at ${width}`,
      );
    }
    assert.deepEqual(errors, []);
    console.log(
      "PASS: queue, search errors, stale events, filtering, sorting, playback states, mute, keyboard, icons, responsive layout.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
