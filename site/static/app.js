// Recipe archive — small enhancements. Every page works without this file.

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
  },
};

// ------------------------------------------------------------ index page

function setUpIndex() {
  const grid = document.querySelector(".grid");
  const cards = [...grid.querySelectorAll(".card")];
  const input = document.querySelector(".search input");
  const empty = document.querySelector(".empty");
  const sortButtons = [...document.querySelectorAll(".sort button")];
  const alphabetical = cards.slice();

  function filter() {
    const words = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const card of cards) {
      const hit = words.every((w) => card.dataset.text.includes(w));
      card.hidden = !hit;
      if (hit) shown++;
    }
    empty.hidden = shown > 0;
  }

  function sort(mode) {
    const order = mode === "new"
      ? cards.slice().sort((a, b) => b.dataset.number - a.dataset.number)
      : alphabetical;
    grid.append(...order);
    for (const b of sortButtons) b.setAttribute("aria-pressed", String(b.dataset.sort === mode));
    store.set("sort", mode);
  }

  input.addEventListener("input", filter);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const first = cards.find((c) => !c.hidden);
      if (first) first.querySelector("a").click();
    }
  });
  for (const b of sortButtons) b.addEventListener("click", () => sort(b.dataset.sort));

  sort(store.get("sort", "az"));
  filter(); // the browser may restore typed text on back
}

// ------------------------------------------------------------ recipe page

function setUpRecipe() {
  const recipe = document.querySelector(".recipe");
  const items = [...recipe.querySelectorAll("li")];
  const clear = document.querySelector(".progress__clear");
  const key = "done:" + recipe.dataset.key;
  const done = new Set(store.get(key, []));

  function render() {
    items.forEach((li, i) => li.classList.toggle("done", done.has(i)));
    clear.hidden = done.size === 0;
  }

  items.forEach((li, i) => {
    li.addEventListener("click", (e) => {
      if (e.target.closest("a") || window.getSelection().toString()) return;
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

  // Text size: normal → large → extra large → normal.
  const sizes = ["normal", "large", "xlarge"];
  document.querySelector(".topbar__size").addEventListener("click", () => {
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

if (document.documentElement.dataset.page === "index") setUpIndex();
if (document.documentElement.dataset.page === "recipe") setUpRecipe();
