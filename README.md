# Recipes

My recipe archive. Each recipe is a Markdown file, and the `recipe` script finds and shows them in the terminal. `recipes serve` also shows them as a website for reading on a phone in the kitchen. Git keeps each recipe's history, so you can always see what changed in a recipe and when.

<table>
  <tr>
    <td><img src="docs/screenshots/home.jpeg" width="200" alt="Home page: a grid of recipe photos with search and sort"></td>
    <td><img src="docs/screenshots/recipe.jpeg" width="200" alt="Lentil soup recipe with the first step and garlic crossed off"></td>
    <td><img src="docs/screenshots/search-dark.jpeg" width="200" alt="Searching for chickpeas in dark mode shows three recipes"></td>
    <td><img src="docs/screenshots/recipe-dark.jpeg" width="200" alt="Avocado hummus recipe in dark mode with an ingredient crossed off"></td>
  </tr>
  <tr>
    <td align="center">Browse</td>
    <td align="center">Cook and cross off</td>
    <td align="center">Search by ingredient</td>
    <td align="center">Dark mode</td>
  </tr>
</table>

## Setup

Add a `recipes` function to `~/.zshrc` so it works from any folder. On its own, `recipes` takes you to this folder. With anything after it, it runs the script:

```sh
recipes() {
  if [[ $# -eq 0 ]]; then
    cd /path/to/recipes
  else
    /path/to/recipes/recipe "$@"
  fi
}
```

For nicer formatting, install [glow](https://github.com/charmbracelet/glow). When several recipes match a name, [fzf](https://github.com/junegunn/fzf) lets you pick one from a list. Both are optional:

```sh
brew install glow fzf
```

## Usage

```sh
recipes                    # go to the recipes folder
recipes bread              # show a recipe (part of the name is enough)
recipes banana-bread.md    # file names work too
recipes new Chicken Curry  # start a new recipe from a template
recipes edit curry         # open a recipe in your editor
recipes search garlic      # list recipes that mention a word
recipes list               # list all recipes
recipes list --tag vegetarian   # list recipes with a tag
recipes tags               # list every tag and how many recipes use it
```

Each recipe has a tags line under its title, such as `Tags: indian, main, vegetarian, one-pot`. Tags cover cuisine, type of dish (main, side, soup, salad, dressing), diet (vegetarian, meat), and practical notes (quick, one-pot, make-ahead). Optional `Serves: 4` and `Time: 45 min` lines can follow the tags line; the website shows them and uses the serving count to scale amounts.

Inside the recipes folder, `./recipe` with nothing after it opens a pick-from-a-list menu with a preview.

Adding or changing a recipe, from start to finish:

```sh
recipes new Chicken Curry  # write it (or: recipes edit curry)
recipes photos             # make a photo for any recipe that has none
recipes save --push        # add it to the history and publish the website
```

## History

Every recipe keeps a changelog, and nobody has to write it. The archive is a git repository: each saved change is a commit, and the history of a recipe is the list of commits that touched it. After you change recipes, one command saves them:

```sh
recipes save               # commit each changed recipe on its own, with a message written for you
recipes save --push        # the same, then push so the website updates
recipes save -n            # show what would be saved, without saving
recipes save chili -m "Less cumin, more smoked paprika"   # one recipe, your own message
```

`save` names the recipe and the parts that changed, such as "Add Gazpacho", "Update Shakshuka: time, ingredients, and notes", or "New photo for Chili". It only commits recipe files and their photos, so other work in the folder stays as it is. After `recipes edit` or `recipes new`, the script reminds you to save.

A renamed recipe keeps its history, its number, and its "Added" date. `save` spots a rename when a deleted recipe and a new one have nearly the same text. If you rename by hand, use `git mv`.

To read the history:

```sh
recipes diff               # what has changed since the last save
recipes log                # recent changes across the archive
recipes log chana          # one recipe: date, the parts that changed, and the message
recipes log chana -p       # the same, with every edit word by word
```

On the website, each recipe that has changed since it was added has a **History** section at the bottom. Each entry gives the date and the parts that changed, such as Time or Ingredients. Tap **What changed** to see the edited lines, with the changed words marked. Edits on your computer that are not saved yet show at the top. `/changes` lists every change in the archive, newest first.

Plain `git commit` works too: the history comes from the commits themselves, so the site shows what changed even when a commit message is short or covers several recipes. Without git (for example, a copy of the folder), everything else still works and the History sections are left out.

## Website

`recipes serve` shows the archive as a website, so you can read recipes on your phone in the kitchen. It prints an address like `http://10.0.0.160:8000`. Open it on a phone on the same Wi-Fi. In Safari, tap Share → Add to Home Screen to get an app icon.

On the site you can:

- switch between the **Recipes** and **Salads** tabs. Salads has two sections, Salads and Dressings.
- search by dish or ingredient, and sort A–Z or newest first
- tap a tag, such as vegetarian or quick, to show only those recipes (tags also appear under each recipe's title, and tapping one there opens the filtered list)
- tap **Save** on a recipe, then tap **Saved** on the home page to see only your saved recipes
- change the servings with **−** and **+** to scale the ingredient amounts
- tap a time in a step, such as "12–15 minutes", to start a timer. Timers keep running while you move between pages, and beep and vibrate when they finish.
- tap **Add to shopping list** to collect ingredients from several recipes at `/list`, cross them off in the shop, and share or copy the list
- tap an ingredient or step to cross it off (each recipe remembers this until you tap Clear)
- tap **Print** for a clean printed page, or the **A A** button to make the text bigger
- see "Used in" on a dressing, which lists the salads that link to it
- read a recipe's **History** to see what changed and when, or open `/changes` for the whole archive

Saved recipes, the shopping list, and timers are stored in the browser on each device.

Pages are built from the Markdown files each time they load, so edits show up on refresh. The site uses only Python, with nothing to install. Its code is in `site/`.

### Published copy

The site is also published at <https://dong0085.github.io/recipes/>. Every push to `main` rebuilds it with GitHub Actions (`.github/workflows/pages.yml`), so a new recipe goes live about a minute after you push it (`recipes save --push` does both). The workflow fetches the full git history, so the published pages show each recipe's History too. Saved recipes, lists, and timers there are separate from the ones on the home Wi-Fi copy.

To build the same files yourself:

```sh
recipes build              # writes plain HTML to _site/ (links start with /recipes)
recipes build --base ""    # for a site at the root of a domain
```

## Photos

Each recipe has a photo in `images/<recipe>.jpg`, made with the OpenAI image API (`gpt-image-2`). Every photo uses the same art direction, so they look like a set.

```sh
recipes photos           # make photos for recipes that have none yet
recipes photos chili     # remake one recipe's photo
recipes photos --all     # remake every photo
```

The API key comes from `OPENAI_API_KEY`, or from the macOS keychain entry `openai-api-key`. You can also drop in your own photo as `images/<recipe>.jpg`.

When the display uses glow, it switches between light and dark themes to match macOS.
