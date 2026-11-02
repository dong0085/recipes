#!/usr/bin/env python3
"""Serve the recipe archive as a small website you can open on your phone.

    python3 site/serve.py              # http://<this computer>:8000
    python3 site/serve.py --port 9000

Pages are built from the Markdown files each time they load, so edits show
up on refresh. Uses only the Python standard library.
"""

import argparse
import html
import mimetypes
import re
import socket
import subprocess
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

SITE = Path(__file__).resolve().parent
ROOT = SITE.parent
IMAGES = ROOT / "images"
STATIC = SITE / "static"
DOCS = {"README.md", "AGENTS.md", "CLAUDE.md"}  # Markdown files that are docs, not recipes


# ------------------------------------------------------------------ recipes

class Recipe:
    def __init__(self, path, added, revised):
        self.path = path
        self.slug = path.stem
        self.text = path.read_text(encoding="utf-8")
        self.title = next(
            (l[2:].strip() for l in self.text.splitlines() if l.startswith("# ")),
            self.slug.replace("-", " ").title(),
        )
        self.added = added
        self.revised = revised
        self.number = 0
        self.steps = len(re.findall(r"^\d+[.)]\s", self.text, re.M))
        image = IMAGES / f"{self.slug}.jpg"
        self.image = (
            f"/images/{quote(image.name)}?v={int(image.stat().st_mtime)}" if image.exists() else None
        )

    @property
    def url(self):
        return f"/r/{quote(self.slug)}"

    @property
    def body(self):
        """The Markdown without its title line, which the page shows on its own."""
        return re.sub(r"\A\s*# .*\n?", "", self.text, count=1)


def git_dates():
    """Map file name -> (first commit date, last commit date) from git history."""
    try:
        log = subprocess.run(
            ["git", "-C", str(ROOT), "log", "--format=%x00%as", "--name-only", "--", "*.md"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    dates = {}
    for chunk in log.split("\x00")[1:]:
        lines = chunk.strip().splitlines()
        day = date.fromisoformat(lines[0])
        for name in lines[1:]:
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
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
    return text


LIST_ITEM = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$|^(\s*)[-*+]\s+(.*)$")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def markdown(text):
    """Enough Markdown for recipes: headings, paragraphs, and nested lists."""
    out, para, stack = [], [], []  # stack holds (tag, indent) for each open list

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
                out.append(f"<{tag}>")
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
    return f"/static/{name}?v={int(path.stat().st_mtime)}"


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
<link rel="manifest" href="/static/manifest.webmanifest">
<link rel="stylesheet" href="{asset('style.css')}">
<title>{esc(title)}</title>
<script>try{{var s=localStorage.getItem("text-size");if(s)document.documentElement.dataset.size=s}}catch(e){{}}</script>
</head>
<body>
{body}
<script src="{asset('app.js')}" defer></script>
</body>
</html>"""


def thumb(recipe, cls):
    if recipe.image:
        return f'<img class="{cls}" src="{esc(recipe.image)}" alt="" loading="lazy" decoding="async">'
    return f'<div class="{cls} {cls}--blank" aria-hidden="true"><span>{esc(recipe.title[:1])}</span></div>'


def index_page(all_recipes):
    cards = []
    for r in all_recipes:
        search = esc(f"{r.title} {r.text}".lower())
        cards.append(f"""<li class="card" data-text="{search}" data-number="{r.number}">
  <a href="{r.url}">
    {thumb(r, "card__img")}
    <span class="card__no">No. {r.number:02d}</span>
    <span class="card__title">{esc(r.title)}</span>
  </a>
</li>""")

    since = min((r.added for r in all_recipes), default=date.today())
    count = len(all_recipes)
    body = f"""<div class="wrap">
<header class="masthead">
  <p class="eyebrow">A personal archive</p>
  <h1 class="masthead__title">Recipes</h1>
  <p class="masthead__meta">{count} recipe{'s' if count != 1 else ''} · kept since {since:%B %Y}</p>
</header>

<div class="toolbar">
  <label class="search">
    <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5"/><path d="M13 13l4 4"/></svg>
    <input type="search" name="q" placeholder="Search" autocomplete="off"
           autocorrect="off" autocapitalize="off" spellcheck="false" aria-label="Search recipes">
  </label>
  <div class="sort" role="group" aria-label="Sort">
    <button type="button" data-sort="az" aria-pressed="true">A–Z</button>
    <button type="button" data-sort="new" aria-pressed="false">Newest</button>
  </div>
</div>

<ul class="grid">
{''.join(cards)}
</ul>
<p class="empty" hidden>Nothing in the archive matches that.</p>

<footer class="colophon">Kept in plain text. Served from the kitchen.</footer>
</div>"""
    return page("Recipes", body, "index")


def recipe_page(recipe, all_recipes):
    i = all_recipes.index(recipe)
    prev_r = all_recipes[i - 1] if i > 0 else None
    next_r = all_recipes[i + 1] if i + 1 < len(all_recipes) else None

    dates = f"Added {day(recipe.added)}"
    if recipe.revised != recipe.added:
        dates += f" · Revised {day(recipe.revised)}"
    steps = f" · {recipe.steps} steps" if recipe.steps else ""

    hero = (
        f'<figure class="hero"><img src="{esc(recipe.image)}" alt="{esc(recipe.title)}" '
        f'decoding="async"></figure>'
        if recipe.image else ""
    )

    def pager(r, label, cls):
        if not r:
            return '<span class="pager__spacer"></span>'
        return (f'<a class="pager__link {cls}" href="{r.url}"><span class="eyebrow">{label}</span>'
                f'<span class="pager__title">{esc(r.title)}</span></a>')

    body = f"""<nav class="topbar">
  <a class="topbar__back" href="/">
    <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M12.5 4.5L7 10l5.5 5.5"/></svg>Archive
  </a>
  <button class="topbar__size" type="button" aria-label="Change text size">
    <span class="a-small">A</span><span class="a-large">A</span>
  </button>
</nav>

<main class="read">
{hero}
<header class="recipe-head">
  <p class="eyebrow">No. {recipe.number:02d}</p>
  <h1 class="recipe-head__title">{esc(recipe.title)}</h1>
  <p class="recipe-head__meta">{dates}{steps}</p>
</header>

<article class="recipe" data-key="{esc(recipe.slug)}">
{markdown(recipe.body)}
</article>

<div class="progress">
  <p>Tap an ingredient or step to cross it off.</p>
  <button class="progress__clear" type="button" hidden>Clear</button>
</div>

<nav class="pager">
  {pager(prev_r, "Previous", "pager__link--prev")}
  {pager(next_r, "Next", "pager__link--next")}
</nav>
</main>"""
    return page(recipe.title, body, "recipe")


def not_found_page():
    body = """<div class="wrap"><header class="masthead">
  <p class="eyebrow">Not in the archive</p>
  <h1 class="masthead__title">Recipe not found</h1>
  <p class="masthead__meta"><a href="/">Back to all recipes</a></p>
</header></div>"""
    return page("Not found", body, "index")


# ------------------------------------------------------------------ server

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = unquote(urlparse(self.path).path)

        if url == "/":
            return self.send_html(200, index_page(load_recipes()))

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
