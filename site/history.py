#!/usr/bin/env python3
"""Each recipe's changelog, read from git history.

Nobody writes the changelog by hand. Every commit that touches a recipe is one
entry, and the entry shows exactly which lines changed and in which part of the
recipe. serve.py and build.py use this for the History section on recipe pages
and for the /changes page.

    python3 site/history.py save [name ...]      # commit each changed recipe on its own
    python3 site/history.py save -m "message"     # commit them together with your message
    python3 site/history.py save --push           # commit, then push (publishes the site)
    python3 site/history.py save --dry-run        # show what would be committed
    python3 site/history.py log                   # recent changes across the archive
    python3 site/history.py log lentil-soup       # one recipe's changelog

`save` writes the commit message for you from the change itself, such as
"Add Gazpacho" or "Update Shakshuka: time, ingredients, and notes".
Uses only the Python standard library.
"""

import argparse
import difflib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Recipe files and their photos. Doc files also match the first; callers leave them out.
PATHSPECS = [":(top,glob)*.md", ":(top,glob)images/*.jpg"]

META = re.compile(r"^(tags|serves|time|source):", re.I)
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
TOKEN = re.compile(r"\w+|\s+|[^\w\s]")
MAX_LINES = 40  # diff lines shown per change on a page


def git(*args):
    """Run git in the archive and return its output, or "" if git or the repo is missing."""
    try:
        return subprocess.run(
            ["git", "-c", "core.quotepath=false", "-C", str(ROOT), *args],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


# ------------------------------------------------------------------ reading diffs

@dataclass
class Block:
    """A run of changed lines in one part of the recipe."""
    part: str
    rows: list = field(default_factory=list)  # ("del" | "add", text) or ("mod", [(op, text), ...])


@dataclass
class Change:
    """One entry in a recipe's changelog."""
    sha: str
    day: date
    author: str
    subject: str
    kind: str = "changed"   # added, changed, renamed, removed, photo, unsaved
    parts: list = field(default_factory=list)  # "title", "tags", "Ingredients", "photo", …
    blocks: list = field(default_factory=list)
    plus: int = 0
    minus: int = 0
    renamed_from: str = ""


def part_of(text, section):
    """Which part of the recipe a Markdown line belongs to."""
    if text.startswith("# "):
        return "title"
    meta = META.match(text)
    if meta:
        return meta.group(1).lower()
    heading = HEADING.match(text)
    if heading:
        return heading.group(2).strip()
    if section:
        return section
    # Older recipes have no ## sections: name the line by its shape.
    if re.match(r"\s*\d+[.)]\s", text):
        return "Steps"
    if re.match(r"\s*[-*+]\s", text):
        return "Ingredients"
    return "Intro"


def word_diff(old, new):
    """[(op, text)] where op is "same", "del", or "add", word by word."""
    a, b = TOKEN.findall(old), TOKEN.findall(new)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(("same", "".join(a[i1:i2])))
            continue
        if i2 > i1:
            out.append(("del", "".join(a[i1:i2])))
        if j2 > j1:
            out.append(("add", "".join(b[j1:j2])))
    return out


def pair_rows(dels, adds):
    """Show an edited line as one row with the words that changed, when the lines are alike."""
    rows = []
    for i in range(max(len(dels), len(adds))):
        old = dels[i] if i < len(dels) else None
        new = adds[i] if i < len(adds) else None
        if old is not None and new is not None and \
                difflib.SequenceMatcher(None, old, new, autojunk=False).ratio() >= 0.5:
            rows.append(("mod", word_diff(old, new)))
            continue
        if old is not None:
            rows.append(("del", old))
        if new is not None:
            rows.append(("add", new))
    return rows


def parse_patch(patch, change):
    """Fill in a Change from a one-file patch made with plenty of context (-U1000)."""
    section = ""
    in_hunk = False
    block, dels, adds = None, [], []

    def flush():
        nonlocal block, dels, adds
        if block is not None:
            block.rows += pair_rows(dels, adds)
            change.blocks.append(block)
        block, dels, adds = None, [], []

    for line in patch.splitlines():
        if not in_hunk:
            if line.startswith("new file mode"):
                change.kind = "added"
            elif line.startswith("deleted file mode"):
                change.kind = "removed"
            elif line.startswith("rename from "):
                change.kind = "renamed"
                change.renamed_from = Path(line[len("rename from "):]).stem
            elif line.startswith("@@"):
                in_hunk = True
            continue
        if line.startswith(("@@", "\\")):
            continue
        sign, text = line[:1], line[1:]
        if sign not in " +-":
            continue
        heading = HEADING.match(text)
        if heading and len(heading.group(1)) > 1 and sign != "-":
            section = heading.group(2).strip()
        if sign == " " or not text.strip():
            if sign == " ":
                flush()
            continue

        part = part_of(text, section)
        if part not in change.parts:
            change.parts.append(part)
        if block is None or block.part != part:
            flush()
            block = Block(part)
        if sign == "-":
            if adds:  # git lists removals before additions; a new removal starts a new pair
                block.rows += pair_rows(dels, adds)
                dels, adds = [], []
            dels.append(text)
            change.minus += 1
        else:
            adds.append(text)
            change.plus += 1
    flush()
    return change


# ------------------------------------------------------------------ history

def _commits(output, fields=4):
    """Split `git log --format=%x00%H%x1f%ct%x1f%as%x1f%an%x1f%s` output into (head, rest)."""
    for chunk in output.split("\x00")[1:]:
        head, _, rest = chunk.partition("\n")
        sha, stamp, day, author, subject = head.split("\x1f", 4)
        yield (sha, int(stamp), date.fromisoformat(day), author, subject), rest


LOG_FORMAT = "--format=%x00%H%x1f%ct%x1f%as%x1f%an%x1f%s"


def recipe_history(slug):
    """Every change to one recipe, newest first, including its photo and unsaved edits."""
    entries = []
    log = git("log", "--follow", "-p", "-U1000", "--no-color", "--no-ext-diff", LOG_FORMAT,
              "--", f"{slug}.md")
    for (sha, stamp, day, author, subject), patch in _commits(log):
        entries.append((stamp, parse_patch(patch, Change(sha, day, author, subject))))

    by_sha = {c.sha: c for _, c in entries}
    for (sha, stamp, day, author, subject), _ in _commits(git("log", LOG_FORMAT, "--", f"images/{slug}.jpg")):
        if sha in by_sha:
            if by_sha[sha].kind != "added":
                by_sha[sha].parts.append("photo")
        else:
            entries.append((stamp, Change(sha, day, author, subject, kind="photo", parts=["photo"])))

    entries.sort(key=lambda e: -e[0])
    changes = [c for _, c in entries]
    pending = unsaved(slug)
    return ([pending] if pending else []) + changes


def unsaved(slug):
    """Edits to a recipe that are not committed yet, as a Change, or None."""
    name = f"{slug}.md"
    if not (ROOT / name).exists() or not git("rev-parse", "--git-dir"):
        return None
    change = Change("", date.today(), "", "", kind="unsaved")
    if not git("ls-files", "--", name):
        change.parts = ["new recipe"]
        return change
    patch = git("diff", "HEAD", "-U1000", "--no-color", "--no-ext-diff", "--", name)
    if not patch.strip():
        return None
    return parse_patch(patch, change)


@dataclass
class Commit:
    sha: str
    day: date
    author: str
    subject: str
    recipes: dict = field(default_factory=dict)  # slug -> list of verbs, such as ["changed", "new photo"]
    renamed: dict = field(default_factory=dict)  # new slug -> old slug


def archive_log(docs, limit=60):
    """Recent commits that touched recipes or photos, newest first."""
    log = git("log", "-M", "--name-status", "--no-color", f"-{limit}", LOG_FORMAT, "--", *PATHSPECS)
    commits = []
    verbs = {"A": "added", "M": "changed", "D": "removed"}
    for (sha, _, day, author, subject), rest in _commits(log):
        commit = Commit(sha, day, author, subject)
        for line in rest.splitlines():
            status, *paths = line.split("\t")
            if not paths:
                continue
            path = Path(paths[-1])
            if path.parent.name == "images":
                verb = "photo removed" if status == "D" else "new photo"
            elif path.name in docs:
                continue
            elif status.startswith("R"):
                verb = "renamed"
                commit.renamed[path.stem] = Path(paths[0]).stem
            else:
                verb = verbs.get(status[:1], "changed")
            said = commit.recipes.setdefault(path.stem, [])
            if verb not in said:
                said.append(verb)
        for said in commit.recipes.values():
            if "added" in said and "new photo" in said:
                said.remove("new photo")  # a new recipe comes with its photo
        if commit.recipes:
            commits.append(commit)
    return commits


# ------------------------------------------------------------------ saving

def title_of(text, slug):
    first = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), "")
    return first or slug.replace("-", " ").title()


def and_list(words):
    words = list(dict.fromkeys(words))
    if len(words) <= 2:
        return " and ".join(words)
    return ", ".join(words[:-1]) + ", and " + words[-1]


def pending_files(docs):
    """Changed recipe files and photos: path -> git status letter ("A" new, "M", "D")."""
    out = git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *PATHSPECS)
    files = {}
    items = out.split("\0")
    i = 0
    while i < len(items):
        item = items[i]
        i += 1
        if len(item) < 4:
            continue
        status, path = item[:2], item[3:]
        if Path(path).name in docs:
            continue
        if "R" in status or "C" in status:
            # A staged rename: the old path follows. Treat it as delete + add; plan_commits
            # pairs them up again.
            old = items[i]
            i += 1
            files[path] = "A"
            if "R" in status:
                files[old] = "D"
            continue
        if "D" in status:
            files[path] = "D"
        elif status == "??" or "A" in status:
            files[path] = "A"
        else:
            files[path] = "M"
    return files


def head_text(path):
    return git("show", f"HEAD:{path}")


def plan_commits(docs, only=()):
    """Group pending files into one commit per recipe, each with a message."""
    files = pending_files(docs)
    recipes = {}  # slug -> {"md": status, "photo": status}
    for path, status in files.items():
        p = Path(path)
        key = "photo" if p.parent.name == "images" else "md"
        recipes.setdefault(p.stem, {})[key] = status

    # A deleted recipe and a new one that reads almost the same are a rename. Commit them
    # together so `git log --follow` keeps the history.
    removed = [s for s, f in recipes.items() if f.get("md") == "D"]
    added = [s for s, f in recipes.items() if f.get("md") == "A"]
    renames = {}
    for old in removed:
        old_text = head_text(f"{old}.md")
        best, score = None, 0.0
        for new in added:
            if new in renames:
                continue
            ratio = difflib.SequenceMatcher(None, old_text, (ROOT / f"{new}.md").read_text(encoding="utf-8")).ratio()
            if ratio > score:
                best, score = new, ratio
        if best and score >= 0.6:
            renames[best] = old

    plans = []
    for slug in sorted(recipes):
        if slug in renames.values():
            continue  # committed together with its new name
        parts = recipes[slug]
        paths = [f"{slug}.md"] if "md" in parts else []
        if "photo" in parts:
            paths.append(f"images/{slug}.jpg")
        md = parts.get("md")
        if md == "D":
            title = title_of(head_text(f"{slug}.md"), slug)
            message = f"Remove {title}"
        else:
            title = title_of((ROOT / f"{slug}.md").read_text(encoding="utf-8"), slug) \
                if (ROOT / f"{slug}.md").exists() else slug.replace("-", " ").title()
            if slug in renames:
                old = renames[slug]
                paths.append(f"{old}.md")
                if recipes[old].get("photo"):
                    paths.append(f"images/{old}.jpg")
                message = f"Rename {title_of(head_text(f'{old}.md'), old)} to {title}"
            elif md == "A":
                message = f"Add {title}"
            elif md == "M":
                change = parse_patch(git("diff", "HEAD", "-U1000", "--no-color", "--no-ext-diff",
                                         "--", f"{slug}.md"), Change("", date.today(), "", ""))
                words = [p if p in ("title", "tags", "serves", "time", "source") else p.lower()
                         for p in change.parts]
                if "photo" in parts:
                    words.append("photo")
                message = f"Update {title}: {and_list(words)}" if words else f"Update {title}"
            else:
                message = f"New photo for {title}"
        names = {slug, renames.get(slug, slug)}
        plans.append({"slugs": names, "paths": paths, "message": message, "title": title,
                      "photo": (ROOT / "images" / f"{slug}.jpg").exists()})

    if only:
        wanted = [re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-") for q in only]
        picked = [p for p in plans if any(w and any(w in s for s in p["slugs"]) for w in wanted)]
        missing = [q for q, w in zip(only, wanted) if not any(any(w in s for s in p["slugs"]) for p in plans)]
        if missing:
            sys.exit(f"No unsaved changes to a recipe matching: {', '.join(missing)}. "
                     "Run 'recipe save --dry-run' to see what has changed.")
        plans = picked
    return plans


def run(*args):
    result = subprocess.run(["git", "-C", str(ROOT), *args], text=True, capture_output=True)
    if result.returncode:
        sys.exit(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout


def save(names, message, push, dry_run, docs):
    plans = plan_commits(docs, names)
    if message and plans:
        plans = [{"slugs": set().union(*(p["slugs"] for p in plans)),
                  "paths": [path for p in plans for path in p["paths"]],
                  "message": message, "title": "", "photo": True}]

    if not plans:
        print("Nothing to save: every recipe matches its last saved version.")
    for plan in plans:
        if dry_run:
            print(f"  would commit  {plan['message']}")
            for path in plan["paths"]:
                print(f"                {path}")
            continue
        for path in plan["paths"]:
            if (ROOT / path).exists():
                run("add", "--", path)
            elif git("ls-files", "--", path):
                run("rm", "-q", "--cached", "--", path)
            # else: the deletion is already staged (for example after `git mv`)
        run("commit", "-q", "-m", plan["message"], "--", *plan["paths"])
        print(f"  ✓ {plan['message']}")
        if not plan["photo"] and plan["title"] and not plan["message"].startswith("Remove"):
            print(f"    No photo yet. Run 'recipe photos' to make one, then 'recipe save' again.")

    if dry_run:
        return
    if push:
        if not git("rev-parse", "--abbrev-ref", "@{upstream}").strip():
            sys.exit("This branch has no upstream to push to. Push it once with 'git push -u origin <branch>'.")
        result = subprocess.run(["git", "-C", str(ROOT), "push", "-q"], text=True)
        if result.returncode:
            sys.exit(result.returncode)
        print("Pushed. The website updates in a minute or two.")
    elif plans:
        print("Saved. Run 'recipe save --push' (or 'git push') to publish.")


def print_recipe_log(slug):
    """One line per change: date, the parts it touched, and the commit message."""
    for change in recipe_history(slug):
        when = "not saved " if change.kind == "unsaved" else str(change.day)
        if change.kind == "renamed":
            what = f"renamed from {change.renamed_from}"
        elif change.kind in ("added", "photo"):
            what = change.kind
        else:
            what = ", ".join(p.lower() for p in change.parts)
        stat = f"+{change.plus} -{change.minus}" if change.kind in ("changed", "unsaved", "renamed") and change.blocks else ""
        print(f"{when}  {what:<28} {stat:>8}  {change.subject}".rstrip())


def print_log(docs, limit):
    for commit in archive_log(docs, limit):
        print(f"{commit.day}  {commit.subject}")
        for slug, verbs in commit.recipes.items():
            if slug in commit.renamed:
                verbs = [f"renamed from {commit.renamed[slug]}" if v == "renamed" else v for v in verbs]
            print(f"            {slug}: {', '.join(verbs)}")


def main():
    import serve  # for DOCS; imported here because serve imports this module

    parser = argparse.ArgumentParser(description="Save and read the recipe changelog (git history).")
    sub = parser.add_subparsers(dest="command", required=True)
    p_save = sub.add_parser("save", help="commit changed recipes, one commit each")
    p_save.add_argument("names", nargs="*", help="only these recipes (part of the name is enough)")
    p_save.add_argument("-m", "--message", help="commit everything together with this message")
    p_save.add_argument("--push", action="store_true", help="push after committing")
    p_save.add_argument("-n", "--dry-run", action="store_true", help="show what would be committed")
    p_log = sub.add_parser("log", help="one recipe's changelog, or recent changes across the archive")
    p_log.add_argument("slug", nargs="?", help="a recipe's file name without .md")
    p_log.add_argument("-n", "--limit", type=int, default=30)
    args = parser.parse_args()

    if not git("rev-parse", "--git-dir"):
        sys.exit("This folder is not a git repository, so there is no history. Run 'git init' to start one.")
    if args.command == "save":
        save(args.names, args.message, args.push, args.dry_run, serve.DOCS)
    elif args.slug:
        print_recipe_log(args.slug)
    else:
        print_log(serve.DOCS, args.limit)


if __name__ == "__main__":
    main()
