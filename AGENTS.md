# Recipe archive

A personal recipe archive. Each recipe is one Markdown file in this folder. Two tools read them:

- `recipe`, a Bash script for the terminal
- `site/`, a small website for reading recipes on a phone in the kitchen, also published to GitHub Pages at https://dong0085.github.io/recipes/

The owner types `recipes` (plural), which is a shell function in `~/.zshrc`. On its own, `recipes` moves into this folder. With arguments, it runs `./recipe` with those arguments. The README shows the function.

## Layout

```
*.md                   one file per recipe; README.md, AGENTS.md, CLAUDE.md are docs
recipe                 terminal tool: show, search, list, tags, new, edit, serve, build, photos, save, log, diff
images/<slug>.jpg      one photo per recipe, 1200×800 JPEG
site/serve.py          web server and page templates (Python standard library)
site/build.py          writes the same pages as static files to _site/ for GitHub Pages
site/history.py        each recipe's changelog from git history, and `recipe save`
.github/workflows/     pages.yml builds and deploys the site on every push to main
site/thumbnails.py     makes recipe photos with the OpenAI image API
site/static/           style.css, app.js, icons, manifest
docs/screenshots/      phone screenshots shown in the README
```

The slug is the file name without `.md`. It links a recipe to its photo and its page URL (`/r/<slug>`).

## Recipes

- The first line is the title: `# Avocado Hummus`.
- Below the title, after a blank line, comes a tags line: `Tags: middle-eastern, dip, vegetarian, quick, no-cook`. The site shows tags under the title and filters by them on the home page; `./recipe list --tag` and `./recipe tags` read them in the terminal. Tags are lowercase English, separated by commas, with hyphens inside a tag. Take them from these groups, in this order, and ask the owner before adding a new tag:
  - Cuisine: `chinese`, `indian`, `japanese`, `korean`, `italian`, `american`, `middle-eastern` (leave out when none fits)
  - Type: `main`, `side`, `soup`, `dip`, `baking`, `salad`, `dressing` (`salad` and `dressing` put a recipe on the Salads tab)
  - Diet: `vegetarian`, `meat`
  - Practical: `quick` (30 min or less), `one-pot`, `make-ahead`, `no-cook`, `cold`
- Optional lines can follow the tags line: `Serves: 4`, `Time: 45 min`, and `Source: <url or name>`. The site shows them as facts at the top of the page and on the card. A `Serves` value that starts with a number turns on the serving scaler.
- To point a salad at its dressing, link to it in the ingredient list: `- 1 batch [Apple Cider Vinaigrette](/r/apple-cider-vinaigrette)`. The dressing's page then lists the salad under "Used in".
- The body uses a small set of Markdown: `##` section headings, paragraphs, numbered steps, `-` lists, and lists nested under a step with three spaces of indent. `site/serve.py` has its own small Markdown converter for exactly this set, so keep recipes within it or extend the converter.
- Write amounts in the recipe, with metric and US units where useful (for example, "1 can chickpeas, 400 g / 15 oz").
- File names are lowercase words joined by hyphens, such as `lentil-soup.md`.
- Some older recipes include Chinese dish names in parentheses. The avocado hummus recipe is English only, at the owner's request. Ask before changing the other recipes.

After adding a recipe, run `./recipe photos` to make its photo.

## History

Each recipe's changelog is its git history; there is no changelog file to keep up. `site/history.py` reads it:

- `./recipe save` commits each changed recipe (and its photo) on its own, with a message it writes from the diff: "Add <Title>", "Update <Title>: time and ingredients", "New photo for <Title>", "Rename <Old> to <New>", "Remove <Title>". `-m` puts everything in one commit with your message; `--push` pushes afterwards, which publishes the site; `-n` shows the plan. It only touches top-level recipe files and `images/*.jpg`, and leaves other staged work alone. Use it to commit recipe changes, so each recipe's history stays one commit per change.
- A deleted recipe and a new one with nearly the same text are committed together as a rename, so `git log --follow` and the site keep the history. When renaming by hand, use `git mv` or commit both paths in one commit.
- `./recipe log [name] [-p]` and `./recipe diff [name]` read the history in the terminal.
- The recipe page's History section (shown once a recipe has changed since it was added) reads `git log --follow -p -U1000` for the file, plus the log of its photo. Each entry names the parts that changed (title, tags, serves, time, source, a `##` section, photo) and shows the changed lines, pairing an edited line with its old version word by word. Uncommitted edits show first as "Not saved yet". `/changes` lists recent commits across the archive.
- Git is run with `core.quotepath=false`, so recipe file names with Chinese characters match their history. Without git or without history, the pages simply leave the History section out.

## Website

Start it with `./recipe serve` (port 8000). It prints a LAN address for the phone.

- Pages are built from the Markdown on every request, so recipe edits show up on refresh. Edits to `serve.py` need a server restart.
- Static files and photos load with a `?v=<content hash>` version and long caching, so CSS and JS changes show up on refresh too.
- The server only serves files directly inside `images/` and `site/static/`.
- Every URL a page writes goes through `link()` in `serve.py`, which puts `BASE` in front. `BASE` is empty for `./recipe serve`; `site/build.py` sets it to `/recipes` because GitHub Pages serves the site under that path. Never write a bare `"/..."` URL into a page. `manifest.webmanifest` uses relative paths for the same reason.
- `./recipe build` writes each page as an `.html` file (`r/<slug>.html`, `salads.html`, `list.html`, `changes.html`, `404.html`); GitHub Pages serves `/r/<slug>` from `r/<slug>.html`. The Pages copy has no server, so `?tag=` filtering there is done by `app.js`.
- Recipe numbers ("No. 07") and "Added" dates come from git history: the first commit that added the file, following renames. Uncommitted recipes use the file's modified date. The Pages workflow checks out the full history (`fetch-depth: 0`) for this.
- The code uses only the Python standard library and plain CSS and JavaScript, and runs straight from the source files. Keep it that way so it runs anywhere with `python3`.
- The list of doc files (`DOCS` in `serve.py` and `thumbnails.py`, and the `find`/`grep` lines and `RECIPE_FILES` in `recipe`; `history.py` reads `serve.DOCS`) keeps them out of the recipe list. Add any new top-level doc file to all three.
- The home page has tabs, set by `TABS` in `serve.py`: Recipes at `/`, and Salads at `/salads` with a Salads section (tag `salad`) and a Dressings section (tag `dressing`). Each recipe belongs to one tab. Recipe pages link back to their tab, and Previous/Next stay within it.
- Tag filtering works without JavaScript: `/?tag=vegetarian` and `/salads?tag=quick` are filtered on the server. `app.js` then filters in place when a tag is tapped.
- The Markdown converter marks bullet lists as `class="ingredients"`; lists under headings such as Notes or Tips stay plain. The serving scaler and the shopping list read the ingredient lists.
- `app.js` adds search, sorting, tag filtering, saved recipes, the serving scaler, step timers, the shopping list at `/list`, printing, crossing off items, the text-size button, and a screen wake lock. It keeps its data in `localStorage` under `saved`, `list`, `timers`, `sort`, `text-size`, and `done:<slug>`. Every page still reads well with JavaScript turned off.

### Design system

All styling lives in `site/static/style.css`, with tokens at the top. Build new things from those tokens.

- Colors: warm paper background (`--paper`), ink text, one terracotta accent (`--accent`). Dark mode redefines the same tokens under `prefers-color-scheme: dark` and dims photos slightly.
- Type: `--serif` (system serif, New York on Apple devices) for titles and recipe text; `--sans` for small uppercase labels and buttons. Both come with the device, so pages load with zero font downloads.
- Space: a 4px grid (`--s1` to `--s8`). Hairline rules (`--rule`) separate items; a solid ink rule sits under each page header.
- Tone: minimal and quiet, like a printed archive. Small corner radius, generous white space, italic serif for meta text.
- Phone first: test at 390px wide. Body text is large for reading at a distance, and inputs use 16px text so iOS keeps the zoom level steady.

## Photos

`./recipe photos` makes photos for recipes that have none. `./recipe photos <name>` remakes one, and `--all` remakes every photo.

- Model: `gpt-image-2`, 1536×1024, medium quality, about $0.05 per photo. The script shrinks each one to 1200px wide with `sips`.
- Every photo uses the same art direction (the `STYLE` text in `thumbnails.py`): seen from directly above, one stoneware bowl or plate, pale linen, soft window light, muted colors. Keep this style so the archive looks like one set.
- The API key comes from `OPENAI_API_KEY`, or from the macOS keychain entry `openai-api-key`.
- Making photos sends the recipe text to OpenAI and costs money, so check with the owner before remaking many photos.

## Checking changes

- Quick check: start the server and `curl` the pages (`/`, `/salads`, `/list`, `/changes`, `/r/<slug>`, a missing slug, a static file).
- History check: try `./recipe save -n` and real saves in a throwaway clone (`git clone . <scratch>/clone`), not in the archive itself.
- Pages check: run `./recipe build` and make sure every `href` and `src` in `_site/` starts with `/recipes/` and points at a file that exists.
- Visual check: look at the home page and a recipe page at 390×844 in light and dark mode. Ask the owner before opening a real browser.
- Keep the README in step with any change to commands or features. Retake the screenshots in `docs/screenshots/` when the design changes.
