# Recipes

My recipe archive. Each recipe is a Markdown file, and the `recipe` script finds and shows them in the terminal.

## Setup

Add an alias to `~/.zshrc` so `recipe` works from any folder:

```sh
alias recipe=/path/to/recipes/recipe
```

For nicer formatting, install [glow](https://github.com/charmbracelet/glow). For a pick-from-a-list menu, install [fzf](https://github.com/junegunn/fzf). Both are optional:

```sh
brew install glow fzf
```

## Usage

```sh
recipe bread              # show a recipe (part of the name is enough)
recipe banana-bread.md    # file names work too
recipe                    # pick from a list, with a preview
recipe new Chicken Curry  # start a new recipe from a template
recipe edit curry         # open a recipe in your editor
recipe search garlic      # list recipes that mention a word
recipe list               # list all recipes
```

When the display uses glow, it switches between light and dark themes to match macOS.
