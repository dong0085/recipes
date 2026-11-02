#!/usr/bin/env python3
"""Make a photo for each recipe with the OpenAI image API.

    python3 site/thumbnails.py              # only recipes that have no photo yet
    python3 site/thumbnails.py chili        # make (or remake) photos for these recipes
    python3 site/thumbnails.py --all        # remake every photo

Photos are saved as images/<recipe>.jpg. The API key comes from the
OPENAI_API_KEY variable, or from the macOS keychain entry "openai-api-key".
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "images"
MODEL = "gpt-image-2"
DOCS = {"README.md", "AGENTS.md", "CLAUDE.md"}  # Markdown files that are docs, not recipes

# One art direction for every photo, so the archive looks like a set.
STYLE = (
    "Overhead still-life photograph of a single home-cooked dish, seen from directly above. "
    "It sits in one handmade matte stoneware bowl or plate, centered, on a pale warm linen "
    "tablecloth with lots of empty space around it. Soft, diffuse daylight from a window on "
    "the left, gentle natural shadows. Muted, earthy colours; calm and quiet; real, slightly "
    "imperfect home cooking, not styled for an advert. Shot on medium-format film with fine "
    "grain. No text, no labels, no hands, no people, no cutlery clutter, no extra props."
)


def api_key():
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    try:
        return subprocess.run(
            ["security", "find-generic-password", "-a", os.environ.get("USER", ""),
             "-s", "openai-api-key", "-w"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit("No OpenAI key found. Set OPENAI_API_KEY or add the 'openai-api-key' keychain entry.")


def recipes():
    return sorted(p for p in ROOT.glob("*.md") if p.name not in DOCS)


def prompt_for(path):
    text = path.read_text(encoding="utf-8").strip()
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), path.stem)
    return (
        f"{STYLE}\n\nThe dish is: {title}. Show it finished and ready to eat, the way this "
        f"recipe would turn out. The recipe, for reference:\n\n{text}"
    )


def generate(path, key):
    body = json.dumps({
        "model": MODEL,
        "prompt": prompt_for(path),
        "size": "1536x1024",
        "quality": "medium",
        "n": 1,
    }).encode()
    request = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode(errors="replace")) from None

    image = base64.b64decode(data["data"][0]["b64_json"])
    out = IMAGES / f"{path.stem}.jpg"
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        tmp.write(image)
        tmp.flush()
        # Shrink to 1200 px wide and save as JPEG so pages load fast on a phone.
        subprocess.run(
            ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "82",
             "--resampleWidth", "1200", tmp.name, "--out", str(out)],
            capture_output=True, check=True,
        )
    return out


def main():
    parser = argparse.ArgumentParser(description="Make recipe photos with the OpenAI image API.")
    parser.add_argument("names", nargs="*", help="recipes to (re)make, by part of the name")
    parser.add_argument("--all", action="store_true", help="remake every photo")
    args = parser.parse_args()

    all_recipes = recipes()
    if args.names:
        todo = [p for p in all_recipes if any(n.lower() in p.stem.lower() for n in args.names)]
    elif args.all:
        todo = all_recipes
    else:
        todo = [p for p in all_recipes if not (IMAGES / f"{p.stem}.jpg").exists()]

    if not todo:
        print("Every recipe already has a photo.")
        return

    IMAGES.mkdir(exist_ok=True)
    key = api_key()
    print(f"Making {len(todo)} photo(s) with {MODEL}…")

    def run(path):
        try:
            out = generate(path, key)
            print(f"  ✓ {path.stem} → {out.relative_to(ROOT)}")
            return True
        except Exception as error:  # report and carry on with the others
            print(f"  ✗ {path.stem}: {error}")
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        ok = sum(pool.map(run, todo))
    if ok < len(todo):
        sys.exit(1)


if __name__ == "__main__":
    main()
