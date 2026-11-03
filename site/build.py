#!/usr/bin/env python3
"""Build the recipe archive as plain files for GitHub Pages.

    python3 site/build.py                  # writes _site/ for <user>.github.io/recipes/
    python3 site/build.py --base ""        # for a site at the root of a domain
    python3 site/build.py --out /tmp/site  # somewhere else

Uses the same page templates as serve.py. Each page becomes an .html file, and
GitHub Pages serves /r/lentil-soup from r/lentil-soup.html. Uses only the
Python standard library.
"""

import argparse
import shutil
import sys
from pathlib import Path

import serve


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def page_file(out, url):
    """"/" -> index.html, "/salads" -> salads.html, "/r/x" -> r/x.html"""
    return out / ("index.html" if url == "/" else url.strip("/") + ".html")


def build(out, base):
    serve.BASE = base.rstrip("/")
    recipes = serve.load_recipes()

    # Start from an empty folder, but never remove the archive itself.
    root = serve.ROOT.resolve()
    if out.resolve() in (root, *root.parents) or (out / ".git").exists():
        sys.exit(f"Refusing to empty {out}: choose a separate output folder.")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for slug, (url, _, _) in serve.TABS.items():
        write(page_file(out, url), serve.index_page(recipes, slug))
    write(page_file(out, "/list"), serve.list_page())
    write(out / "404.html", serve.not_found_page())
    for recipe in recipes:
        write(page_file(out, f"/r/{recipe.slug}"), serve.recipe_page(recipe, recipes))

    for folder in (serve.IMAGES, serve.STATIC):
        dest = out / folder.name
        dest.mkdir()
        for path in folder.iterdir():
            if path.is_file() and not path.name.startswith("."):
                shutil.copy2(path, dest / path.name)

    return len(recipes)


def main():
    parser = argparse.ArgumentParser(description="Build the recipe archive as static files.")
    parser.add_argument("--out", type=Path, default=serve.ROOT / "_site")
    parser.add_argument("--base", default="/recipes",
                        help='path the site lives under (default "/recipes"; "" for a domain root)')
    args = parser.parse_args()
    count = build(args.out, args.base)
    print(f"Built {count} recipes into {args.out} (links start with {args.base or '/'}).")


if __name__ == "__main__":
    main()
