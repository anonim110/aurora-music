const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
const { pathToFileURL } = require("node:url");
const path = require("node:path");

(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 378, height: 180 },
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => {
      window.testCalls = [];
      const song = {
        id: "local",
        title: "Тихий вечер",
        artist: "Лев Берг",
        duration: 210,
      };
      window.pywebview = {
        api: {
          get_state: async () => ({
            track: song,
            state: "playing",
            elapsed: 73,
            duration: 210,
          }),
          restore: async () => window.testCalls.push("restore"),
          quit_app: async () => window.testCalls.push("quit_app"),
          prev_track: async () => window.testCalls.push("prev_track"),
          toggle: async () => {
            window.testCalls.push("toggle");
            window.__emit("status", { track: song, state: "paused" });
          },
          next_track: async () => window.testCalls.push("next_track"),
          stop_playback: async () => {
            window.testCalls.push("stop_playback");
            window.__emit("status", { track: null, state: "idle" });
          },
        },
      };
    });
    await page.goto(
      pathToFileURL(path.resolve(__dirname, "../ui/tail.html")).href,
    );
    await page.evaluate(() =>
      window.dispatchEvent(new Event("pywebviewready")),
    );
    await page.getByText("Тихий вечер").waitFor();
    assert.equal(
      await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--surface").trim()),
      "#141414",
    );
    assert.equal(await page.locator("#elapsed").innerText(), "1:13");
    assert.equal(await page.locator("#duration").innerText(), "3:30");
    assert.equal(await page.locator(".widget-controls svg").count(), 4);
    assert.equal(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <= innerWidth &&
          document.documentElement.scrollHeight <= innerHeight,
      ),
      true,
    );
    const layout = await page.evaluate(() => {
      const box = (selector) => document.querySelector(selector).getBoundingClientRect();
      return {
        art: box(".artwork").toJSON(),
        timeline: box(".timeline").toJSON(),
        controls: box(".widget-controls").toJSON(),
        title: box("#t").toJSON(),
      };
    });
    assert.ok(layout.art.bottom < layout.timeline.top);
    assert.ok(layout.timeline.bottom <= layout.controls.top);
    assert.ok(layout.title.right <= 378);
    await page.evaluate(() => window.__emit("show"));
    assert.equal(await page.locator(".widget").evaluate((el) => el.classList.contains("entering")), true);
    assert.equal(await page.locator(".widget").evaluate((el) => getComputedStyle(el).animationName), "widget-enter");
    await page.emulateMedia({ reducedMotion: "reduce" });
    assert.ok(await page.locator(".widget").evaluate((el) => parseFloat(getComputedStyle(el).animationDuration) < .001));
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.screenshot({ path: path.join(__dirname, "widget-preview.png") });
    for (const id of ["prev", "pp", "next", "restore", "stop"])
      await page.locator(`#${id}`).click();
    assert.equal(await page.locator("#t").innerText(), "Выберите трек");
    await page.locator("#quit").click();
    assert.deepEqual(await page.evaluate(() => window.testCalls), [
      "prev_track",
      "toggle",
      "next_track",
      "restore",
      "stop_playback",
      "quit_app",
    ]);
    assert.deepEqual(errors, []);
    console.log(
      "PASS: widget metadata, progress, controls, stop, restore, no overflow.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
