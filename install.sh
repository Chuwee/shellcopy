#!/usr/bin/env bash
# Install shellcopy: a private virtualenv with pyte, `shellcopy` and `bcp` in ~/.local/bin, and the shell hook
# for each of bash, zsh and fish that's installed. Other shells get printed instructions.
# Usage: ./install.sh [--no-rc]
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo '› creating virtualenv'
if python3 -m venv "$here/.venv" 2>/dev/null; then
	"$here/.venv/bin/pip" install --quiet --upgrade pyte
else
	# No ensurepip (Debian/Ubuntu without python3-venv): make a pip-less venv and fill it with the system pip.
	rm -rf "$here/.venv"
	python3 -m venv --without-pip "$here/.venv"
	python3 -m pip --python "$here/.venv/bin/python" install --quiet --upgrade pyte
fi

bin="$HOME/.local/bin"
mkdir -p "$bin"
chmod +x "$here/bin/shellcopy"
# bashcopy is the old name of this tool
[ -L "$bin/bashcopy" ] && rm -f "$bin/bashcopy"
ln -sf "$here/bin/shellcopy" "$bin/shellcopy"
ln -sf "$here/bin/shellcopy" "$bin/bcp"
echo "› linked shellcopy and bcp into $bin"
case ":$PATH:" in *":$bin:"*) ;; *) echo "  (add $bin to your PATH to use them outside bash, zsh and fish)" ;; esac

if [ "${1:-}" != '--no-rc' ]; then
	add_posix() {  # $1 rc file, $2 shell name
		local rc="$1"
		# Replace earlier lines (an older install, or bashcopy, this tool's old name) rather than adding a second set.
		[ -f "$rc" ] && sed -i -E '/^# (shell|bash)copy$/d; /^export (SHELL|BASH)COPY_HOME=/d; /^source "\$(SHELL|BASH)COPY_HOME\/(shell|bash)copy\.sh"$/d; /^(shell|bash)copy record( |$)/d; /shellcopy init /d' "$rc"
		printf '\n# shellcopy\n%s  # copy terminal output with `bcp`; remove to uninstall\n' "$("$here/bin/shellcopy" init --rc-line "$2")" >>"$rc"
		echo "› added the shell hook to $rc"
	}
	command -v bash >/dev/null && add_posix "$HOME/.bashrc" bash
	command -v zsh >/dev/null && add_posix "${ZDOTDIR:-$HOME}/.zshrc" zsh
	if command -v fish >/dev/null; then
		conf="${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/shellcopy.fish"
		rm -f "$(dirname "$conf")/bashcopy.fish"  # the old name
		mkdir -p "$(dirname "$conf")"
		printf '# shellcopy: copy terminal output with `bcp`; delete this file to uninstall\n%s\n' "$("$here/bin/shellcopy" init --rc-line fish)" >"$conf"
		echo "› added the shell hook to $conf"
	fi
	case "$(basename "${SHELL:-bash}")" in
		bash | zsh | fish) ;;
		*)
			echo
			echo "› for $(basename "$SHELL"), bcp already works as a command. To record terminals so plain"
			echo '  `bcp` can pick from the screen, add the equivalent of this to its startup file:'
			echo '    shellcopy record --check && exec shellcopy record'
			echo '  (bash, zsh and fish get a fuller hook from `shellcopy init`)'
			;;
	esac
fi

echo
echo 'done. open a new terminal (or source your rc file), then run any command and:'
echo '  bcp                 # halve with the arrows, Enter to start selecting, Enter to copy'
echo '  ls -la | bcp        # or pick from a piped output'
