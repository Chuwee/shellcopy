#!/usr/bin/env bash
# Install bashcopy: a private virtualenv with pyte, plus the shell hook in your rc file.
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

if [ "${1:-}" != '--no-rc' ]; then
	case "$(basename "${SHELL:-bash}")" in
		zsh) rc="$HOME/.zshrc" ;;
		*) rc="$HOME/.bashrc" ;;
	esac
	if ! grep -q 'bashcopy.sh' "$rc" 2>/dev/null; then
		printf '\n# bashcopy\nexport BASHCOPY_HOME=%q\nsource "$BASHCOPY_HOME/bashcopy.sh"\nbashcopy record  # log terminal output so plain `bcp` can copy from it; remove to turn off\n' "$here" >>"$rc"
		echo "› added the shell hook to $rc"
	fi
fi

echo
echo 'done. open a new terminal (or source your rc file), then run any command and:'
echo '  bcp                 # halve with the arrows, Enter to start selecting, Enter to copy'
echo '  ls -la | bcp        # or pick from a piped output'
