// Recipe archive — enhancements. Every page reads well without this file.
// Saved recipes, the shopping list, and timers live in localStorage on this device.

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
  },
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// ------------------------------------------------------------ shared: saved, list count

const saved = new Set(store.get("saved", []));
function saveSaved() { store.set("saved", [...saved]); }

function shoppingList() { return store.get("list", []); }

function updateListCount() {
  const n = shoppingList().reduce((sum, r) => sum + r.items.filter((i) => !i.done).length, 0);
  for (const el of $$("[data-list-count]")) {
    el.textContent = n;
    el.hidden = n === 0;
  }
}

// ------------------------------------------------------------ amounts: read, scale, write

const GLYPHS = { "½": 1 / 2, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 1 / 4, "¾": 3 / 4, "⅛": 1 / 8 };
const NUM = "(?:\\d+(?:\\.\\d+)?(?:\\s?[½⅓⅔¼¾⅛])?|[½⅓⅔¼¾⅛])";
// A quantity or a range ("3–4"). Sizes such as "2.5 cm", "220 °C", or "70%" stay as they are.
const QUANTITY = new RegExp(
  `(?<![\\d.½⅓⅔¼¾⅛])(${NUM})(?:(\\s*[–-]\\s*)(${NUM}))?(?![\\d.½⅓⅔¼¾⅛])(?!\\s?(?:°|cm\\b|mm\\b|in\\b|inch|%))`,
  "g",
);

function parseAmount(text) {
  const m = text.match(/^(\d+(?:\.\d+)?)?\s?([½⅓⅔¼¾⅛])?$/);
  if (!m) return NaN;
  return (m[1] ? parseFloat(m[1]) : 0) + (m[2] ? GLYPHS[m[2]] : 0);
}

function formatAmount(v) {
  if (v >= 10) return String(Math.round(v));
  const whole = Math.floor(v);
  const options = [[0, ""], [1 / 8, "⅛"], [1 / 4, "¼"], [1 / 3, "⅓"], [1 / 2, "½"], [2 / 3, "⅔"], [3 / 4, "¾"], [1, ""]];
  const [frac, glyph] = options.reduce((best, o) => (Math.abs(o[0] - (v - whole)) < Math.abs(best[0] - (v - whole)) ? o : best));
  const w = whole + (frac === 1 ? 1 : 0);
  if (!w && !glyph) return "⅛";
  return (w ? String(w) : "") + glyph;
}

function scaleText(text, factor) {
  if (factor === 1) return text;
  // A part such as "400 g / 15 oz each" describes a can's size, so it keeps its numbers.
  return text.split(/(,)/).map((part) => (/\beach\b/i.test(part) ? part : part.replace(QUANTITY, (all, a, dash, b) => {
    const x = parseAmount(a);
    if (Number.isNaN(x)) return all;
    let out = formatAmount(x * factor);
    if (b !== undefined) {
      const y = parseAmount(b);
      out += dash + (Number.isNaN(y) ? b : formatAmount(y * factor));
    }
    return out;
  }))).join("");
}

// Text nodes that belong to this list item, not to a list nested inside it.
function ownTextNodes(li) {
  const walker = document.createTreeWalker(li, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement.closest("li") === li ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  return nodes;
}

function itemText(li) {
  return ownTextNodes(li).map((n) => n.textContent).join("").replace(/\s+/g, " ").trim();
}

// ------------------------------------------------------------ timers (every page)

const timers = {
  list: store.get("timers", []),
  audio: null,
  tick: null,

  save() { store.set("timers", this.list); },

  start(label, seconds, url) {
    this.unlockSound();
    this.list.push({ id: Date.now() + Math.random(), label, url, end: Date.now() + seconds * 1000, seconds, rang: false });
    this.save();
    this.render();
  },

  remove(id) {
    this.list = this.list.filter((t) => t.id !== id);
    this.save();
    this.render();
  },

  unlockSound() {
    try {
      this.audio ||= new (window.AudioContext || window.webkitAudioContext)();
      if (this.audio.state === "suspended") this.audio.resume();
    } catch {}
  },

  ring() {
    try { navigator.vibrate?.([300, 150, 300, 150, 300]); } catch {}
    if (!this.audio) return;
    const now = this.audio.currentTime;
    for (let i = 0; i < 3; i++) {
      const osc = this.audio.createOscillator();
      const gain = this.audio.createGain();
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.0001, now + i * 0.45);
      gain.gain.exponentialRampToValueAtTime(0.3, now + i * 0.45 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.45 + 0.35);
      osc.connect(gain).connect(this.audio.destination);
      osc.start(now + i * 0.45);
      osc.stop(now + i * 0.45 + 0.4);
    }
  },

  // Build one row per timer; update() then changes only the times, so taps are never lost.
  render() {
    const dock = $(".dock");
    if (!dock) return;
    dock.hidden = this.list.length === 0;
    dock.replaceChildren(...this.list.map((t) => {
      const row = document.createElement("div");
      row.className = "timer";
      row.dataset.id = t.id;
      row.innerHTML = `<a class="timer__label"></a><span class="timer__time"></span>`
        + `<button class="timer__more" type="button" aria-label="Add a minute">+1</button>`
        + `<button class="timer__close" type="button" aria-label="Cancel timer">×</button>`;
      const label = $(".timer__label", row);
      label.textContent = t.label;
      label.href = t.url;
      $(".timer__more", row).addEventListener("click", () => {
        t.end = Math.max(t.end, Date.now()) + 60000;
        t.rang = false;
        this.save();
        this.render();
      });
      $(".timer__close", row).addEventListener("click", () => this.remove(t.id));
      return row;
    }));
    if (this.list.length && !this.tick) this.tick = setInterval(() => this.update(), 1000);
    if (!this.list.length && this.tick) { clearInterval(this.tick); this.tick = null; }
    this.update();
  },

  update() {
    let changed = false;
    for (const t of this.list) {
      if (!t.rang && Date.now() >= t.end) { t.rang = true; changed = true; this.ring(); }
      const row = $(`.timer[data-id="${t.id}"]`);
      if (!row) continue;
      const left = Math.max(0, Math.ceil((t.end - Date.now()) / 1000));
      $(".timer__time", row).textContent = left === 0
        ? "Done" : `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
      row.classList.toggle("timer--done", left === 0);
      $(".timer__close", row).setAttribute("aria-label", left === 0 ? "Dismiss timer" : "Cancel timer");
    }
    if (changed) this.save();
    const ringing = this.list.some((t) => t.rang);
    const plain = document.title.replace(/^⏰ /, "");
    document.title = ringing ? `⏰ ${plain}` : plain;
  },
};

// Another tab or page may change the timers or the list.
window.addEventListener("storage", (e) => {
  if (e.key === "timers") { timers.list = store.get("timers", []); timers.render(); }
  if (e.key === "list") updateListCount();
});

// "12–15 minutes" -> 12 minutes; the shorter time is the first check.
const DURATION = /(\d+(?:\.\d+)?)(?:\s*[–-]\s*\d+(?:\.\d+)?)?\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b/gi;

function secondsOf(amount, unit) {
  const u = unit.toLowerCase();
  const n = parseFloat(amount);
  if (u.startsWith("s")) return n;
  if (u.startsWith("h")) return n * 3600;
  return n * 60;
}

// ------------------------------------------------------------ index page

function setUpIndex() {
  const shelves = $$(".shelf");
  const grids = $$(".grid").map((grid) => ({ grid, az: [...grid.children] }));
  const cards = $$(".card");
  const input = $(".search input");
  const empty = $(".empty");
  const sortButtons = $$(".sort button");
  const bar = $(".tagbar");
  const chips = $$(".chip", bar);
  const savedChip = $(".chip--saved", bar);
  const base = bar.dataset.base;
  let tag = new URLSearchParams(location.search).get("tag")?.trim().toLowerCase() || "";

  for (const c of cards) $(".card__saved", c).hidden = !saved.has(c.dataset.slug);
  savedChip.hidden = saved.size === 0 && tag !== "saved";

  function filter() {
    const words = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const card of cards) {
      const hasTag = !tag || (tag === "saved" ? saved.has(card.dataset.slug) : card.dataset.tags.split(" ").includes(tag));
      const hit = hasTag && words.every((w) => card.dataset.text.includes(w));
      card.hidden = !hit;
      if (hit) shown++;
    }
    for (const shelf of shelves) shelf.hidden = !$$(".card", shelf).some((c) => !c.hidden);
    empty.hidden = shown > 0;
    for (const c of chips) {
      if (c.dataset.tag === tag) c.setAttribute("aria-current", "true");
      else c.removeAttribute("aria-current");
    }
  }

  function sort(mode) {
    for (const { grid, az } of grids) {
      const order = mode === "new" ? az.slice().sort((a, b) => b.dataset.number - a.dataset.number) : az;
      grid.append(...order);
    }
    for (const b of sortButtons) b.setAttribute("aria-pressed", String(b.dataset.sort === mode));
    store.set("sort", mode);
  }

  input.addEventListener("input", filter);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") $(".card:not([hidden]) a")?.click();
  });
  for (const b of sortButtons) b.addEventListener("click", () => sort(b.dataset.sort));

  // Tags: one at a time. Tapping the current tag again shows everything.
  for (const chip of chips) {
    chip.addEventListener("click", (e) => {
      e.preventDefault();
      tag = chip.dataset.tag === tag ? "" : chip.dataset.tag;
      history.replaceState(null, "", tag ? `${base}?tag=${encodeURIComponent(tag)}` : base);
      filter();
    });
  }

  sort(store.get("sort", "az"));
  filter(); // the browser may restore typed text on back
}

// ------------------------------------------------------------ recipe page

function setUpRecipe() {
  const recipe = $(".recipe");
  const slug = recipe.dataset.key;
  const title = recipe.dataset.title;
  const items = $$("li", recipe);
  const ingredients = $$("ul.ingredients > li", recipe); // includes lists nested under a step
  const clear = $(".progress__clear");
  const key = "done:" + slug;
  const done = new Set(store.get(key, []));

  // Cross off ingredients and steps.
  function render() {
    items.forEach((li, i) => li.classList.toggle("done", done.has(i)));
    clear.hidden = done.size === 0;
  }
  items.forEach((li, i) => {
    li.addEventListener("click", (e) => {
      if (e.target.closest("a, button") || window.getSelection().toString()) return;
      e.stopPropagation(); // a spice inside a step only crosses off the spice
      done.has(i) ? done.delete(i) : done.add(i);
      store.set(key, [...done]);
      render();
    });
  });
  clear.addEventListener("click", () => {
    done.clear();
    store.set(key, []);
    render();
  });
  render();

  // Servings: scale the amounts in the ingredient lists.
  const serves = $(".serves");
  let factor = 1;
  if (serves) {
    const baseServes = Number(serves.dataset.base);
    const originalLabel = serves.textContent;
    const originals = new Map();
    // Every ingredient list, including one nested under a step (such as the spices).
    for (const li of ingredients) for (const n of ownTextNodes(li)) originals.set(n, n.textContent);
    let count = baseServes;
    const note = $(".facts__note");
    const hasSteps = $$("ol > li", recipe).length > 0;

    const apply = () => {
      factor = count / baseServes;
      serves.textContent = factor === 1 ? originalLabel : String(count);
      serves.classList.toggle("serves--scaled", factor !== 1);
      for (const [node, text] of originals) node.textContent = scaleText(text, factor);
      if (note) note.hidden = factor === 1 || !hasSteps;
    };
    for (const b of $$(".stepper")) {
      b.hidden = false;
      b.addEventListener("click", () => {
        count = Math.max(1, Math.min(baseServes * 8, count + Number(b.dataset.step)));
        apply();
      });
    }
  }

  // Timers: tap a time in a step to start one.
  for (const li of $$("ol > li", recipe)) {
    for (const node of ownTextNodes(li)) {
      const text = node.textContent;
      DURATION.lastIndex = 0;
      if (!DURATION.test(text)) continue;
      DURATION.lastIndex = 0;
      const frag = document.createDocumentFragment();
      let last = 0;
      for (const m of text.matchAll(DURATION)) {
        frag.append(text.slice(last, m.index));
        const b = document.createElement("button");
        b.type = "button";
        b.className = "timer-link";
        b.textContent = m[0];
        const seconds = secondsOf(m[1], m[2]);
        const label = `${title} · step ${li.dataset.n}`;
        b.setAttribute("aria-label", `Start a ${m[0]} timer`);
        b.addEventListener("click", () => timers.start(label, seconds, location.pathname));
        frag.append(b);
        last = m.index + m[0].length;
      }
      frag.append(text.slice(last));
      node.replaceWith(frag);
    }
  }

  if (!$(".timer-link", recipe)) $(".progress p").textContent = "Tap an ingredient or step to cross it off.";

  // Actions: shopping list, save, print.
  const actions = $(".actions");
  actions.hidden = false;
  const listButton = $(".action--list", actions);
  const listLabel = $("span", listButton);
  const allIngredients = ingredients;
  const refreshListButton = () => {
    const there = shoppingList().some((r) => r.slug === slug);
    listLabel.textContent = there ? "Update shopping list" : "Add to shopping list";
  };
  if (allIngredients.length === 0) listButton.hidden = true;
  refreshListButton();
  listButton.addEventListener("click", () => {
    const list = shoppingList().filter((r) => r.slug !== slug);
    const label = factor === 1 ? title : `${title} (serves ${$(".serves").textContent})`;
    list.push({ slug, title: label, url: location.pathname, items: allIngredients.map((li) => ({ text: itemText(li), done: false })) });
    store.set("list", list);
    updateListCount();
    listLabel.textContent = "Added ✓";
    setTimeout(refreshListButton, 1600);
  });

  const saveButton = $(".action--save", actions);
  const renderSave = () => {
    const on = saved.has(slug);
    saveButton.setAttribute("aria-pressed", String(on));
    $("span", saveButton).textContent = on ? "Saved" : "Save";
  };
  saveButton.addEventListener("click", () => {
    saved.has(slug) ? saved.delete(slug) : saved.add(slug);
    saveSaved();
    renderSave();
  });
  renderSave();

  $(".action--print", actions).addEventListener("click", () => window.print());

  // Text size: normal → large → extra large → normal.
  const sizes = ["normal", "large", "xlarge"];
  const sizeButton = $(".topbar__size");
  sizeButton.hidden = false;
  sizeButton.addEventListener("click", () => {
    const now = document.documentElement.dataset.size || "normal";
    const next = sizes[(sizes.indexOf(now) + 1) % sizes.length];
    if (next === "normal") delete document.documentElement.dataset.size;
    else document.documentElement.dataset.size = next;
    try { localStorage.setItem("text-size", next === "normal" ? "" : next); } catch {}
  });

  // Keep the screen on while cooking, where the browser allows it.
  async function stayAwake() {
    try { if ("wakeLock" in navigator) await navigator.wakeLock.request("screen"); } catch {}
  }
  stayAwake();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") stayAwake();
  });
}

// ------------------------------------------------------------ shopping list page

function setUpList() {
  const shop = $(".shop");
  const empty = $(".shop__empty");
  const summary = $("[data-list-summary]");
  const actions = $(".actions");
  $(".topbar__list").hidden = true;

  function render() {
    const list = shoppingList();
    const left = list.reduce((n, r) => n + r.items.filter((i) => !i.done).length, 0);
    empty.hidden = list.length > 0;
    actions.hidden = list.length === 0;
    summary.textContent = list.length
      ? `${left} item${left === 1 ? "" : "s"} left from ${list.length} recipe${list.length === 1 ? "" : "s"}`
      : "Nothing on the list yet.";

    shop.replaceChildren(...list.map((r, ri) => {
      const group = document.createElement("section");
      group.className = "shop__group";
      group.innerHTML = `<header class="shop__head"><a class="shop__title"></a>`
        + `<button class="shop__remove" type="button">Remove</button></header><ul class="shop__items"></ul>`;
      const link = $(".shop__title", group);
      link.textContent = r.title;
      link.href = r.url;
      $(".shop__remove", group).addEventListener("click", () => {
        store.set("list", shoppingList().filter((_, i) => i !== ri));
        render();
      });
      const ul = $(".shop__items", group);
      r.items.forEach((item, ii) => {
        const li = document.createElement("li");
        li.textContent = item.text;
        li.classList.toggle("done", item.done);
        li.addEventListener("click", () => {
          const now = shoppingList();
          now[ri].items[ii].done = !now[ri].items[ii].done;
          store.set("list", now);
          render();
        });
        ul.append(li);
      });
      return group;
    }));
    updateListCount();
  }

  $(".action--clear-done").addEventListener("click", () => {
    const list = shoppingList()
      .map((r) => ({ ...r, items: r.items.filter((i) => !i.done) }))
      .filter((r) => r.items.length);
    store.set("list", list);
    render();
  });
  $(".action--clear-all").addEventListener("click", () => {
    if (confirm("Clear the whole shopping list?")) { store.set("list", []); render(); }
  });

  // Copy (or share, on a phone) the items still to buy as plain text.
  const share = $(".action--share");
  if (navigator.share) $("span", share).textContent = "Share list";
  share.addEventListener("click", async () => {
    const text = shoppingList()
      .map((r) => [r.title, ...r.items.filter((i) => !i.done).map((i) => `- ${i.text}`)].join("\n"))
      .join("\n\n");
    try {
      if (navigator.share) await navigator.share({ title: "Shopping list", text });
      else { await navigator.clipboard.writeText(text); $("span", share).textContent = "Copied ✓"; }
    } catch {}
  });

  window.addEventListener("storage", (e) => { if (e.key === "list") render(); });
  render();
}

// ------------------------------------------------------------ start

const kind = document.documentElement.dataset.page;
if (kind === "index") setUpIndex();
if (kind === "recipe") setUpRecipe();
if (kind === "list") setUpList();
updateListCount();
timers.render();
