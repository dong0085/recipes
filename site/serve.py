#!/usr/bin/env python3
"""Serve the recipe archive as a small website you can open on your phone.

    python3 site/serve.py              # http://<this computer>:8000
    python3 site/serve.py --port 9000

Pages are built from the Markdown files each time they load, so edits show
up on refresh. Uses only the Python standard library.
"""

import argparse
import functools
import hashlib
import html
import mimetypes
import re
import socket
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import history

SITE = Path(__file__).resolve().parent
ROOT = SITE.parent
IMAGES = ROOT / "images"
STATIC = SITE / "static"
DOCS = {"README.md", "AGENTS.md", "CLAUDE.md"}  # Markdown files that are docs, not recipes

# Prefix for every link the pages write. Empty when serving here; build.py sets it to
# "/recipes" for GitHub Pages, where the site lives at <user>.github.io/recipes/.
BASE = ""


def link(path):
    """A site path such as "/r/lentil-soup", with BASE in front."""
    return BASE + path


def version(path):
    """A short hash of a file's contents, for ?v= in its URL."""
    stat = path.stat()
    return _version(path, stat.st_mtime_ns, stat.st_size)


@functools.lru_cache(maxsize=None)
def _version(path, mtime, size):
    return hashlib.md5(path.read_bytes()).hexdigest()[:8]

# The tabs on the home page: slug -> (URL, title, sections). Each section is
# (tag, heading, blurb). A recipe belongs to the first tab with a section matching
# one of its tags; the Recipes tab holds everything else as one grid.
TABS = {
    "recipes": ("/", "Recipes", ()),
    "salads": ("/salads", "Salads", (
        ("salad", "Salads", "Bowls to build a meal around."),
        ("dressing", "Dressings", "Shake in a jar. Each one dresses a salad for four."),
    )),
}


# ------------------------------------------------------------------ recipes

# Lines under the title such as "Tags: indian, main", "Serves: 4", "Time: 45 min".
META_LINE = re.compile(r"^(tags|serves|time|source):[ \t]*(.*)\n?", re.M | re.I)


class Recipe:
    def __init__(self, path, added, revised):
        self.path = path
        self.slug = path.stem
        self.text = path.read_text(encoding="utf-8")
        self.title = next(
            (l[2:].strip() for l in self.text.splitlines() if l.startswith("# ")),
            self.slug.replace("-", " ").title(),
        )
        meta = {}
        for key, value in META_LINE.findall(self.text):
            meta.setdefault(key.lower(), value.strip())
        self.tags = [t.strip().lower() for t in meta.get("tags", "").split(",") if t.strip()]
        self.serves = meta.get("serves", "")
        number = re.match(r"\d+", self.serves)
        self.serves_n = int(number.group()) if number else 0
        self.time = meta.get("time", "")
        self.source = meta.get("source", "")
        self.added = added
        self.revised = revised
        self.number = 0
        self.tab = "recipes"
        self.steps = len(re.findall(r"^\d+[.)]\s", self.text, re.M))
        image = IMAGES / f"{self.slug}.jpg"
        self.image = (
            link(f"/images/{quote(image.name)}?v={version(image)}") if image.exists() else None
        )

    @property
    def url(self):
        return link(f"/r/{quote(self.slug)}")

    @property
    def body(self):
        """The Markdown without its title and meta lines, which the page shows on their own."""
        text = re.sub(r"\A\s*# .*\n?", "", self.text, count=1)
        return META_LINE.sub("", text)

    @property
    def facts(self):
        """Short facts for a card: "45 min · Serves 4"."""
        parts = [self.time] if self.time else []
        if self.serves:
            parts.append(f"Serves {self.serves}")
        return " · ".join(parts)


def tab_of(recipe):
    for slug, (_, _, sections) in TABS.items():
        if any(tag in recipe.tags for tag, _, _ in sections):
            return slug
    return "recipes"


def tag_url(tag, tab="recipes"):
    return link(f"{TABS[tab][0]}?tag={quote(tag)}")


def git_dates():
    """Map file name -> (first commit date, last commit date) from git history.

    A renamed recipe keeps the dates of its old name, so it keeps its number too.
    """
    log = history.git("log", "--reverse", "-M", "--format=%x00%as", "--name-status", "--", "*.md")
    dates = {}
    for chunk in log.split("\x00")[1:]:
        lines = chunk.strip().splitlines()
        day = date.fromisoformat(lines[0])
        for line in lines[1:]:
            status, *paths = line.split("\t")
            if not paths:
                continue
            name = paths[-1]
            if status.startswith("R") and paths[0] in dates:
                dates[name] = dates.pop(paths[0])
            first, last = dates.get(name, (day, day))
            dates[name] = (min(first, day), max(last, day))
    return dates


def load_recipes():
    """Every recipe, numbered in the order it joined the archive, sorted A–Z."""
    history = git_dates()
    found = []
    for path in ROOT.glob("*.md"):
        if path.name in DOCS:
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime).date()
        first, last = history.get(path.name, (modified, modified))
        found.append(Recipe(path, first, last))
    for number, recipe in enumerate(sorted(found, key=lambda r: (r.added, r.slug)), start=1):
        recipe.number = number
        recipe.tab = tab_of(recipe)
    return sorted(found, key=lambda r: r.title.lower())


# ------------------------------------------------------------------ markdown

FRACTIONS = {"1/2": "½", "1/3": "⅓", "2/3": "⅔", "1/4": "¼", "3/4": "¾", "1/8": "⅛"}


def fractions(text):
    """1 1/2 cups -> 1½ cups"""
    for plain, glyph in FRACTIONS.items():
        text = re.sub(rf"(?<![\d/]){plain}(?![\d/])", glyph, text)
    return re.sub(r"(\d) ([½⅓⅔¼¾⅛])", r"\1\2", text)


def inline(text):
    text = fractions(html.escape(text, quote=False))
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)\*(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{site_link(m[2])}">{m[1]}</a>', text)
    return text


def site_link(href):
    """Links such as /r/apple-cider-vinaigrette point into the site, so they get BASE."""
    return link(href) if href.startswith("/") and not href.startswith("//") else href


LIST_ITEM = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$|^(\s*)[-*+]\s+(.*)$")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
# Bullet lists are ingredients, except under headings like these.
NOT_INGREDIENTS = re.compile(r"note|tip|serv|storage|variation", re.I)


def markdown(text):
    """Enough Markdown for recipes: headings, paragraphs, and nested lists.

    Bullet lists get class="ingredients" (for the scaler and the shopping list)
    unless they sit under a heading such as "Notes".
    """
    out, para, stack = [], [], []  # stack holds (tag, indent) for each open list
    heading = ""

    def flush_para():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    def close_lists(to_indent=-1):
        while stack and stack[-1][1] > to_indent:
            out.append(f"</li></{stack.pop()[0]}>")

    for line in text.splitlines():
        m = LIST_ITEM.match(line)
        if m:
            flush_para()
            if m.group(2) is not None:
                indent, tag, number, body = len(m.group(1)), "ol", m.group(2), m.group(3)
            else:
                indent, tag, number, body = len(m.group(4)), "ul", None, m.group(5)
            close_lists(indent)
            if stack and stack[-1][1] == indent and stack[-1][0] != tag:
                out.append(f"</li></{stack.pop()[0]}>")
            if stack and stack[-1][1] == indent:
                out.append("</li>")
            else:
                cls = ' class="ingredients"' if tag == "ul" and not NOT_INGREDIENTS.search(heading) else ""
                out.append(f"<{tag}{cls}>")
                stack.append((tag, indent))
            data = f' data-n="{number}"' if number else ""
            out.append(f"<li{data}>{inline(body)}")
            continue

        if not line.strip():
            flush_para()
            close_lists()
            continue

        if stack and line.startswith(" "):  # a list item that wraps onto the next line
            out.append(" " + inline(line.strip()))
            continue

        close_lists()
        h = HEADING.match(line)
        if h:
            flush_para()
            heading = h.group(2)
            level = min(len(h.group(1)) + 1, 6)  # the page title is the only <h1>
            out.append(f"<h{level}>{inline(h.group(2))}</h{level}>")
        else:
            para.append(line.strip())

    flush_para()
    close_lists()
    return "\n".join(out)


# ------------------------------------------------------------------ pages

def esc(text):
    return html.escape(str(text), quote=True)


def day(d):
    return f"{d.day} {d:%b %Y}"


def asset(name):
    path = STATIC / name
    return link(f"/static/{name}?v={version(path)}")


# Small line icons, drawn on a 20×20 grid with the current text colour.
ICONS = {
    "back": '<path d="M12.5 4.5L7 10l5.5 5.5"/>',
    "search": '<circle cx="8.5" cy="8.5" r="5.5"/><path d="M13 13l4 4"/>',
    "list": '<path d="M7 5.5h10M7 10h10M7 14.5h10"/><circle cx="3.5" cy="5.5" r=".6"/>'
            '<circle cx="3.5" cy="10" r=".6"/><circle cx="3.5" cy="14.5" r=".6"/>',
    "heart": '<path d="M10 16.5s-6.5-3.9-6.5-8.4A3.6 3.6 0 0 1 10 6a3.6 3.6 0 0 1 6.5 2.1c0 4.5-6.5 8.4-6.5 8.4z"/>',
    "print": '<path d="M5.5 8V3.5h9V8M5.5 14h-2V8.5h13V14h-2"/><path d="M5.5 11.5h9v5h-9z"/>',
    "clock": '<circle cx="10" cy="10" r="7"/><path d="M10 6v4l2.5 2"/>',
    "plus": '<path d="M10 4.5v11M4.5 10h11"/>',
    "minus": '<path d="M4.5 10h11"/>',
    "close": '<path d="M5.5 5.5l9 9M14.5 5.5l-9 9"/>',
}


def icon(name):
    return f'<svg class="icon" viewBox="0 0 20 20" aria-hidden="true">{ICONS[name]}</svg>'


def page(title, body, kind):
    return f"""<!doctype html>
<html lang="en" data-page="{kind}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f4efe6" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#161411" media="(prefers-color-scheme: dark)">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="Recipes">
<link rel="icon" href="{asset('icon.svg')}" type="image/svg+xml">
<link rel="apple-touch-icon" href="{asset('icon-180.png')}">
<link rel="manifest" href="{asset('manifest.webmanifest')}">
<link rel="stylesheet" href="{asset('style.css')}">
<title>{esc(title)}</title>
<script>try{{var s=localStorage.getItem("text-size");if(s)document.documentElement.dataset.size=s}}catch(e){{}}</script>
</head>
<body>
{body}
<aside class="dock" aria-label="Timers" aria-live="polite" hidden></aside>
<script src="{asset('app.js')}" defer></script>
</body>
</html>"""


def thumb(recipe, cls):
    if recipe.image:
        return f'<img class="{cls}" src="{esc(recipe.image)}" alt="" loading="lazy" decoding="async">'
    return f'<div class="{cls} {cls}--blank" aria-hidden="true"><span>{esc(recipe.title[:1])}</span></div>'


def list_link(cls):
    """The shopping list link; app.js fills in the count."""
    return (f'<a class="{cls}" href="{link("/list")}">{icon("list")}<span>Shopping list</span>'
            f'<span class="count" data-list-count hidden></span></a>')


def card(r, tag):
    search = esc(f"{r.title} {r.text}".lower())
    hidden = " hidden" if tag and tag not in r.tags else ""
    facts = f'<span class="card__facts">{icon("clock")}{esc(r.facts)}</span>' if r.facts else ""
    return f"""<li class="card" data-slug="{esc(r.slug)}" data-text="{search}" data-tags="{esc(' '.join(r.tags))}" data-number="{r.number}"{hidden}>
  <a href="{r.url}">
    <span class="card__frame">{thumb(r, "card__img")}<span class="card__saved" aria-label="Saved" hidden>{icon("heart")}</span></span>
    <span class="card__no">No. {r.number:02d}</span>
    <span class="card__title">{esc(r.title)}</span>
    {facts}
  </a>
</li>"""


def index_page(all_recipes, tab="recipes", tag=""):
    url, tab_title, sections = TABS[tab]
    members = [r for r in all_recipes if r.tab == tab]
    section_tags = {t for t, _, _ in sections}

    # One shelf per section; the Recipes tab is a single shelf with no heading.
    shelves = []
    for sec_tag, heading, blurb in sections or ((None, "", ""),):
        items = [r for r in members if sec_tag is None or sec_tag in r.tags]
        if not items:
            continue
        shown = sum(1 for r in items if not tag or tag in r.tags)
        head = ""
        if heading:
            head = f"""<header class="shelf__head">
    <h2 class="shelf__title">{esc(heading)}</h2>
    <span class="shelf__count">{len(items)}</span>
    <p class="shelf__blurb">{esc(blurb)}</p>
  </header>"""
        shelves.append(f"""<section class="shelf"{"" if shown else " hidden"}>
  {head}
  <ul class="grid">
{''.join(card(r, tag) for r in items)}
  </ul>
</section>""")

    # Tag links, most used first. They work without JavaScript; app.js filters in place.
    counts = {}
    for r in members:
        for t in r.tags:
            if t not in section_tags:
                counts[t] = counts.get(t, 0) + 1

    def chip(href, label, t):
        current = ' aria-current="true"' if t == tag else ""
        return f'<a class="chip" href="{esc(href)}" data-tag="{esc(t)}"{current}>{esc(label)}</a>'

    chips = [chip(link(url), "All", "")]
    chips.append(f'<button class="chip chip--saved" type="button" data-tag="saved" hidden>'
                 f'{icon("heart")}Saved</button>')
    chips += [chip(tag_url(t, tab), t, t) for t in sorted(counts, key=lambda t: (-counts[t], t))]
    tag_bar = f'<nav class="tagbar" aria-label="Tags" data-base="{esc(link(url))}">{"".join(chips)}</nav>'

    shown = sum(1 for r in members if not tag or tag in r.tags)
    empty_hidden = "" if not shown else " hidden"

    tabs = []
    for slug, (t_url, t_title, _) in TABS.items():
        n = sum(1 for r in all_recipes if r.tab == slug)
        current = ' aria-current="page"' if slug == tab else ""
        tabs.append(f'<a href="{link(t_url)}"{current}>{esc(t_title)}<span class="tabs__count">{n}</span></a>')

    since = min((r.added for r in all_recipes), default=date.today())
    count = len(all_recipes)
    body = f"""<div class="wrap">
<header class="masthead">
  <div class="masthead__top">
    <p class="eyebrow">A personal archive</p>
    {list_link("masthead__list")}
  </div>
  <h1 class="masthead__title">Recipes</h1>
  <p class="masthead__meta">{count} recipe{'s' if count != 1 else ''} · kept since {since:%B %Y}</p>
</header>

<nav class="tabs" aria-label="Sections">{''.join(tabs)}</nav>

<div class="toolbar">
  <label class="search">
    {icon("search")}
    <input type="search" name="q" placeholder="Search {esc(tab_title.lower())}" autocomplete="off"
           autocorrect="off" autocapitalize="off" spellcheck="false" aria-label="Search {esc(tab_title.lower())}">
  </label>
  <div class="sort" role="group" aria-label="Sort">
    <button type="button" data-sort="az" aria-pressed="true">A–Z</button>
    <button type="button" data-sort="new" aria-pressed="false">Newest</button>
  </div>
</div>
{tag_bar}

{''.join(shelves)}
<p class="empty"{empty_hidden}>Nothing here matches that.</p>

<footer class="colophon">Kept in plain text. Served from the kitchen. <a href="{link("/changes")}">Every change, from the start</a></footer>
</div>"""
    title = "Recipes" if tab == "recipes" else f"{tab_title} · Recipes"
    return page(title, body, "index")


def topbar(back_url, back_label):
    return f"""<nav class="topbar">
  <a class="topbar__back" href="{esc(back_url)}">{icon("back")}{esc(back_label)}</a>
  <div class="topbar__tools">
    {list_link("topbar__list")}
    <button class="topbar__size" type="button" aria-label="Change text size" hidden>
      <span class="a-small">A</span><span class="a-large">A</span>
    </button>
  </div>
</nav>"""


def recipe_page(recipe, all_recipes):
    siblings = [r for r in all_recipes if r.tab == recipe.tab]
    i = siblings.index(recipe)
    prev_r = siblings[i - 1] if i > 0 else None
    next_r = siblings[i + 1] if i + 1 < len(siblings) else None
    tab_url, tab_title, _ = TABS[recipe.tab]

    changes = history.recipe_history(recipe.slug)
    dates = f"Added {day(recipe.added)}"
    if recipe.revised != recipe.added:
        dates += f" · Revised {day(recipe.revised)}"
    if len(changes) > 1:
        dates += f' · <a href="#history">{len(changes) - 1} change{"s" if len(changes) > 2 else ""}</a>'
    history_html = history_section(changes)
    tags = "".join(f'<a class="chip" href="{esc(tag_url(t, recipe.tab))}">{esc(t)}</a>' for t in recipe.tags)
    tags = f'<p class="recipe-head__tags">{tags}</p>' if tags else ""

    hero = (
        f'<figure class="hero"><img src="{esc(recipe.image)}" alt="{esc(recipe.title)}" '
        f'decoding="async"></figure>'
        if recipe.image else ""
    )

    # Facts: servings (with a scaler when it starts with a number), time, steps, source.
    facts = []
    if recipe.serves:
        stepper = ""
        if recipe.serves_n:
            stepper = (f'<button class="stepper" type="button" data-step="-1" aria-label="Fewer servings" hidden>{icon("minus")}</button>'
                       f'<output class="serves" data-base="{recipe.serves_n}">{esc(recipe.serves)}</output>'
                       f'<button class="stepper" type="button" data-step="1" aria-label="More servings" hidden>{icon("plus")}</button>')
        else:
            stepper = f"<span>{esc(recipe.serves)}</span>"
        facts.append(f'<div class="fact"><span class="fact__label">Serves</span><span class="fact__value">{stepper}</span></div>')
    if recipe.time:
        facts.append(f'<div class="fact"><span class="fact__label">Time</span><span class="fact__value">{esc(recipe.time)}</span></div>')
    if recipe.steps:
        facts.append(f'<div class="fact"><span class="fact__label">Steps</span><span class="fact__value">{recipe.steps}</span></div>')
    facts_html = f'<section class="facts" aria-label="At a glance">{"".join(facts)}</section>' if facts else ""
    scaled_note = '<p class="facts__note" hidden>Amounts in the lists are scaled. Amounts written in the steps are for the original recipe.</p>'

    source = ""
    if recipe.source:
        if re.match(r"https?://", recipe.source):
            source = f'<p class="recipe-head__source">Source: <a href="{esc(recipe.source)}">{esc(urlparse(recipe.source).netloc)}</a></p>'
        else:
            source = f'<p class="recipe-head__source">Source: {esc(recipe.source)}</p>'

    # "Used in": other recipes that link here, such as a salad that uses this dressing.
    target = f"/r/{recipe.slug})"
    used_in = [r for r in all_recipes if r is not recipe and target in r.text]
    used_html = ""
    if used_in:
        links = "".join(f'<li><a href="{r.url}">{thumb(r, "mini__img")}<span>{esc(r.title)}</span></a></li>' for r in used_in)
        used_html = f'<section class="related"><h2 class="eyebrow">Used in</h2><ul class="mini">{links}</ul></section>'

    def pager(r, label, cls):
        if not r:
            return '<span class="pager__spacer"></span>'
        return (f'<a class="pager__link {cls}" href="{r.url}"><span class="eyebrow">{label}</span>'
                f'<span class="pager__title">{esc(r.title)}</span></a>')

    back_label = "Archive" if recipe.tab == "recipes" else tab_title
    section = "" if recipe.tab == "recipes" else f" · {esc(tab_title)}"
    body = f"""{topbar(link(tab_url), back_label)}

<main class="read">
{hero}
<header class="recipe-head">
  <p class="eyebrow">No. {recipe.number:02d}{section}</p>
  <h1 class="recipe-head__title">{esc(recipe.title)}</h1>
  <p class="recipe-head__meta">{dates}</p>
  {source}
  {tags}
</header>

{facts_html}
{scaled_note}

<div class="actions" hidden>
  <button class="action action--list" type="button">{icon("list")}<span>Add to shopping list</span></button>
  <button class="action action--save" type="button" aria-pressed="false">{icon("heart")}<span>Save</span></button>
  <button class="action action--print" type="button">{icon("print")}<span>Print</span></button>
</div>

<article class="recipe" data-key="{esc(recipe.slug)}" data-title="{esc(recipe.title)}">
{markdown(recipe.body)}
</article>

<div class="progress">
  <p>Tap an ingredient or step to cross it off. Tap a time to start a timer.</p>
  <button class="progress__clear" type="button" hidden>Clear</button>
</div>

{used_html}

{history_html}

<nav class="pager">
  {pager(prev_r, "Previous", "pager__link--prev")}
  {pager(next_r, "Next", "pager__link--next")}
</nav>
</main>"""
    return page(recipe.title, body, "recipe")


def list_page():
    body = f"""{topbar(link("/"), "Archive")}

<main class="read">
<header class="recipe-head">
  <p class="eyebrow">Shopping list</p>
  <h1 class="recipe-head__title">To buy</h1>
  <p class="recipe-head__meta" data-list-summary>Nothing on the list yet.</p>
</header>

<div class="actions" hidden>
  <button class="action action--share" type="button">{icon("list")}<span>Copy list</span></button>
  <button class="action action--clear-done" type="button">{icon("close")}<span>Remove crossed off</span></button>
  <button class="action action--clear-all" type="button">{icon("close")}<span>Clear all</span></button>
</div>

<div class="shop"></div>
<p class="empty shop__empty">Open a recipe and tap <strong>Add to shopping list</strong>. Its ingredients collect here, grouped by recipe.</p>
<noscript><p class="empty">The shopping list lives on this device and needs JavaScript.</p></noscript>
</main>"""
    return page("Shopping list · Recipes", body, "list")


# ------------------------------------------------------------------ history

PART_NAMES = {"title": "Title", "tags": "Tags", "serves": "Serves", "time": "Time",
              "source": "Source", "photo": "Photo", "new recipe": "New recipe"}


def part_names(parts):
    return ", ".join(PART_NAMES.get(p, p) for p in parts)


def diff_rows(change):
    """The changed lines of one change, grouped by the part of the recipe they are in."""
    out, shown = [], 0
    total = sum(len(b.rows) for b in change.blocks)
    last_part = None
    for block in change.blocks:
        if shown >= history.MAX_LINES:
            break
        if block.part != last_part:
            out.append(f'<p class="diff__part">{esc(PART_NAMES.get(block.part, block.part))}</p>')
            last_part = block.part
        for kind, content in block.rows:
            if shown >= history.MAX_LINES:
                break
            shown += 1
            if kind == "mod":
                tags = {"del": "del", "add": "ins"}
                words = "".join(
                    f"<{tags[op]}>{esc(text)}</{tags[op]}>" if op in tags else esc(text)
                    for op, text in content)
                out.append(f'<p class="diff__line diff__line--mod">{words}</p>')
            else:
                tag = "del" if kind == "del" else "ins"
                out.append(f'<p class="diff__line diff__line--{kind}"><{tag}>{esc(content)}</{tag}></p>')
    if total > shown:
        more = total - shown
        out.append(f'<p class="diff__more">and {more} more line{"s" if more != 1 else ""}</p>')
    return "".join(out)


def change_item(change, show_author):
    if change.kind == "unsaved":
        when = '<span class="change__date change__date--unsaved">Not saved yet</span>'
    else:
        when = f'<time class="change__date" datetime="{change.day.isoformat()}">{day(change.day)}</time>'

    if change.kind == "added":
        what = "Added"
    elif change.kind == "renamed":
        what = f"Renamed from {change.renamed_from}" + (f" · {part_names(change.parts)}" if change.parts else "")
    else:
        what = part_names(change.parts) or "No visible change"

    if change.kind == "unsaved":
        message = "Edited on this computer. Run <code>recipe save</code> to add it to the history."
    else:
        message = esc(change.subject)
        if show_author and change.author:
            message += f' <span class="change__author">{esc(change.author)}</span>'

    diff = ""
    if change.blocks and change.kind != "added":
        stat = f'<span class="change__stat"><ins>+{change.plus}</ins> <del>−{change.minus}</del></span>'
        diff = (f'<details class="change__diff"><summary>What changed {stat}</summary>'
                f'<div class="diff">{diff_rows(change)}</div></details>')

    return f"""<li class="change">
  <p class="change__head">{when}<span class="change__what">{esc(what)}</span></p>
  <p class="change__msg">{message}</p>
  {diff}
</li>"""


def history_section(changes):
    """The recipe's changelog. Hidden when the only entry is the day it was added."""
    if len(changes) < 2:
        return ""
    show_author = len({c.author for c in changes if c.author}) > 1
    items = "".join(change_item(c, show_author) for c in changes)
    return f"""<section class="history" id="history">
  <h2 class="eyebrow">History</h2>
  <ol class="history__list">{items}</ol>
  <p class="history__all"><a href="{link("/changes")}">Every change in the archive</a></p>
</section>"""


def changes_page(all_recipes):
    by_slug = {r.slug: r for r in all_recipes}
    commits = history.archive_log(DOCS)
    show_author = len({c.author for c in commits}) > 1

    def name(slug):
        r = by_slug.get(slug)
        if r:
            return f'<a href="{r.url}#history">{esc(r.title)}</a>'
        return f'<span class="gone">{esc(slug.replace("-", " ").title())}</span>'

    items = []
    for c in commits:
        rows = []
        for slug, verbs in c.recipes.items():
            words = [f"renamed from {c.renamed[slug]}" if v == "renamed" else v for v in verbs]
            rows.append(f'<li>{name(slug)} <span class="change__verb">{esc(", ".join(words))}</span></li>')
        author = f' <span class="change__author">{esc(c.author)}</span>' if show_author else ""
        items.append(f"""<li class="change">
  <p class="change__head"><time class="change__date" datetime="{c.day.isoformat()}">{day(c.day)}</time></p>
  <p class="change__msg">{esc(c.subject)}{author}</p>
  <ul class="change__recipes">{"".join(rows)}</ul>
</li>""")

    if items:
        listing = f'<ol class="history__list">{"".join(items)}</ol>'
    else:
        listing = '<p class="empty">No history yet. Run <code>recipe save</code> after you change a recipe.</p>'
    body = f"""{topbar(link("/"), "Archive")}

<main class="read">
<header class="recipe-head">
  <p class="eyebrow">Changelog</p>
  <h1 class="recipe-head__title">Every change</h1>
  <p class="recipe-head__meta">Newest first, straight from the archive's git history.</p>
</header>

<section class="history history--archive">{listing}</section>
</main>"""
    return page("Changes · Recipes", body, "changes")


def not_found_page():
    body = f"""<div class="wrap"><header class="masthead">
  <p class="eyebrow">Not in the archive</p>
  <h1 class="masthead__title">Recipe not found</h1>
  <p class="masthead__meta"><a href="{link("/")}">Back to all recipes</a></p>
</header></div>"""
    return page("Not found", body, "missing")


# ------------------------------------------------------------------ server

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        url = unquote(parsed.path)
        if len(url) > 1:
            url = url.rstrip("/")

        for slug, (tab_url, _, _) in TABS.items():
            if url == tab_url:
                tag = parse_qs(parsed.query).get("tag", [""])[0].strip().lower()
                return self.send_html(200, index_page(load_recipes(), slug, tag))

        if url == "/list":
            return self.send_html(200, list_page())

        if url == "/changes":
            return self.send_html(200, changes_page(load_recipes()))

        if url.startswith("/r/"):
            all_recipes = load_recipes()
            match = next((r for r in all_recipes if r.slug == url[3:]), None)
            if match:
                return self.send_html(200, recipe_page(match, all_recipes))

        for prefix, folder in (("/images/", IMAGES), ("/static/", STATIC)):
            if url.startswith(prefix):
                name = url[len(prefix):]
                # Only serve files that are directly inside the folder.
                if folder.is_dir() and name in {p.name for p in folder.iterdir() if p.is_file()}:
                    return self.send_file(folder / name)

        self.send_html(404, not_found_page())

    def send_html(self, status, text):
        self.send_bytes(status, text.encode("utf-8"), "text/html; charset=utf-8", "no-store")

    def send_file(self, path):
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".webmanifest":
            kind = "application/manifest+json"
        if kind.startswith("text/") or kind.endswith(("javascript", "json")):
            kind += "; charset=utf-8"
        # URLs carry a ?v= version, so files can be cached until they change.
        self.send_bytes(200, path.read_bytes(), kind, "public, max-age=31536000, immutable")

    def send_bytes(self, status, data, kind, cache):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet


def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # picks the network card; sends nothing
            return s.getsockname()[0]
    except OSError:
        return None


def main():
    parser = argparse.ArgumentParser(description="Serve the recipe archive as a website.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    host = socket.gethostname()
    if not host.endswith(".local"):
        host += ".local"
    ip = local_ip()

    print("Recipe archive is running. On your phone (same Wi-Fi), open:")
    if ip:
        print(f"  http://{ip}:{args.port}")
    print(f"  http://{host}:{args.port}")
    print(f"On this computer: http://localhost:{args.port}")
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
