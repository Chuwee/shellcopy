# bashcopy

Copy part of what's on your terminal without touching the mouse. Type `bcp`, narrow down to what you want with a few arrow presses, and press Enter twice to copy.

## Install

```sh
./install.sh            # creates .venv with pyte and adds the hook (and `bashcopy record`) to ~/.bashrc or ~/.zshrc
./install.sh --no-rc    # same, without touching your rc file
```

Then open a new terminal, run something, and type `bcp`.

## How it works

**1. Halve.** When `bcp` opens, every word on screen is in play. Each arrow keeps the half of the remaining words it points at, and the rest dims. Empty space never costs a key press, and a screen of 100 near-identical IPs takes only about 7 presses. When one word is left, a cursor lands on it.

**2. Point.** The arrows now move the cursor one character at a time. Press Enter to start selecting, move, and press Enter again to copy.

| Key | While halving | With the cursor |
|---|---|---|
| ← → ↑ ↓ | keep that half of the words | move one character or line |
| Enter | put the cursor on the first word left | first time: start selecting; second time: copy |
| Tab | show ids on the words left; type one to jump there | show ids on every word on screen |
| Shift + id | copy that word right away | (same) |
| Shift + ← → | | jump a whole word (while selecting forward, to the word's end so it's included) |
| Shift + ↑ ↓ | | jump 5 lines; PgUp/PgDn a page; Home/End line start and end |
| Space | | select whole lines |
| z | | halve again from the whole screen (keeps your selection) |
| Backspace | undo the last halving; at the start, quit | clear the selection; with nothing selected, back to halving |
| Esc | quit | quit |

Ids are inserted in front of their words, pushing the line right while they're shown, so they never cover text.

## Where the text comes from

- **`bcp`** picks from what this terminal shows, scrollback included. This needs `bashcopy record` in your rc file, which `install.sh` adds. It runs your shell inside util-linux `script`, which logs what the terminal prints (text only, no keystrokes) to a private file under `$XDG_RUNTIME_DIR`. That file is in memory, readable only by you, trimmed past 8 MB and deleted when the terminal closes. Remove the line, or set `BASHCOPY_RECORD=0`, to turn it off. Recording is skipped inside tmux, where `bcp` reads the screen directly, and in VS Code's terminal.
- **`cmd | bcp`** picks from `cmd`'s output.
- In a terminal that isn't recorded, plain `bcp` offers to re-run your last command and capture its output.
- **`bcp --print`** prints the selection instead of copying it, for `x=$(bcp --print)`.

It copies with `wl-copy`, `xclip`, `xsel` or `pbcopy`, whichever is installed, and otherwise asks the terminal to copy (OSC 52).

## Limits

- Resizing the window can make the rebuilt screen slightly off.
- Long lines that the terminal wrapped come back as separate lines.
