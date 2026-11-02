# shellcopy

Copy part of what's on your terminal without touching the mouse. Type `shcp`, narrow down to what you want with a few arrow presses, and press Enter twice to copy.

Website: https://chuwee.github.io/shellcopy/

## Install

**One line** (Linux and macOS, no sudo). It installs into `~/.local` and adds the shell hook, and running it again updates:

```sh
curl -fsSL https://chuwee.github.io/shellcopy/install.sh | sh
```

Add `sh -s -- --no-rc` in place of the final `sh` to leave your rc files alone.

**Homebrew** (macOS and Linux):

```sh
brew install chuwee/shellcopy/shellcopy
```

**apt** (Debian, Ubuntu): download the `.deb` from the [latest release](https://github.com/Chuwee/shellcopy/releases/latest), then:

```sh
sudo apt install ./shellcopy_*_all.deb
```

Packages don't touch your rc files. To let plain `shcp` pick from what the terminal shows, add the hook line for your shell. `shellcopy init --rc-line SHELL` prints it:

```sh
# ~/.bashrc (or ~/.zshrc, with zsh)
command -v shellcopy >/dev/null && eval "$(shellcopy init bash)" && shellcopy record
```

```fish
# ~/.config/fish/conf.d/shellcopy.fish
status is-interactive; and type -q shellcopy; and shellcopy init fish | source; and shellcopy record
```

**From a checkout:**

```sh
./install.sh            # creates .venv with pyte, links `shellcopy` and `shcp` into ~/.local/bin,
                        # and adds the hook line to ~/.bashrc, ~/.zshrc and fish's conf.d (for the ones installed)
./install.sh --no-rc    # same, without touching your rc files
```

Then open a new terminal, run something, and type `shcp`.

### Shells

`shcp` is a plain command, so it works from any shell: bash, zsh, fish, ksh, dash, nushell, xonsh, and others. The hook (`shellcopy init bash|zsh|fish|sh|ksh`) adds two things: it turns on recording, and it hands `shcp` your history so it can re-run your last command in a terminal that isn't recorded. For a shell without a hook, add the equivalent of this line to its startup file to turn on recording:

```sh
shellcopy record --check && exec shellcopy record
```

`shellcopy record [SHELL]` runs `SHELL` (by default `$SHELL`) with the terminal recorded, and `--check` tells you whether this terminal should be recorded at all. That way the line does nothing in tmux, in VS Code, or in a terminal that's already recorded.

## How it works

**1. Halve.** When `shcp` opens, every word on screen is in play. Each arrow keeps the half of the remaining words it points at, and the rest dims. Empty space never costs a key press, and a screen of 100 near-identical IPs takes only about 7 presses. When one word is left, a cursor lands on it.

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

- **`shcp`** picks from what this terminal shows, scrollback included. This needs the hook line in your rc file (see Install). It replaces your shell with one running inside util-linux `script`, which logs what the terminal prints (text only, no keystrokes) to a private file under `$XDG_RUNTIME_DIR`. That file is in memory, readable only by you, trimmed past 8 MB and deleted when the terminal closes. A small shellcopy process stays alive alongside it to do the trimming and cleanup. Remove the line, or set `SHELLCOPY_RECORD=0`, to turn it off. Recording is skipped inside tmux, where `shcp` reads the screen directly, and in VS Code's terminal.
- **`cmd | shcp`** picks from `cmd`'s output.
- In a terminal that isn't recorded, plain `shcp` offers to re-run your last command and capture its output. This needs the bash, zsh or fish hook, which passes your history. On macOS, where recording is unavailable (it needs util-linux `script`), this is what plain `shcp` does outside tmux. The command runs in a fresh copy of your shell, so aliases and functions defined in your rc files aren't available.
- **`shcp --print`** prints the selection instead of copying it, for `x=$(shcp --print)`.

It copies with `wl-copy`, `xclip`, `xsel` or `pbcopy`, whichever is installed, and otherwise asks the terminal to copy (OSC 52).

## Limits

- Resizing the window can make the rebuilt screen slightly off.
- Long lines that the terminal wrapped come back as separate lines.

## Releasing

1. Bump `__version__` in `shellcopy.py`, commit, then tag and push: `git tag v0.1.0 && git push origin v0.1.0`. The release workflow builds the `.deb` (`packaging/deb/build.sh`) and attaches it to a GitHub release.
2. Run `packaging/homebrew/update-formula.sh` to fill in the formula's url and sha256, then copy `packaging/homebrew/shellcopy.rb` to `Formula/shellcopy.rb` in the tap repo, [Chuwee/homebrew-shellcopy](https://github.com/Chuwee/homebrew-shellcopy).

## License

MIT, see [LICENSE](LICENSE).
