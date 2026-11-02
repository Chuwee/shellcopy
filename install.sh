#!/usr/bin/env bash
# Install shellcopy: a private virtualenv with pyte, `shellcopy` and `cy` in ~/.local/bin, and the shell hook
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
ln -sf "$here/bin/shellcopy" "$bin/cy"
# bcp and shcp were earlier short names
for old in bcp shcp; do
	[ "$(readlink "$bin/$old" 2>/dev/null)" = "$here/bin/shellcopy" ] && rm -f "$bin/$old"
done
echo "› linked shellcopy and cy into $bin"
case ":$PATH:" in *":$bin:"*) ;; *) echo "  (add $bin to your PATH to use them outside bash, zsh and fish)" ;; esac

if [ "${1:-}" != '--no-rc' ]; then
	"$here/bin/shellcopy" setup
else
	echo
	echo 'skipped the shell hook; run `shellcopy setup` to add it later.'
fi

echo
echo 'done. then run any command and:'
echo '  cy                 # halve with the arrows, Enter to start selecting, Enter to copy'
echo '  ls -la | cy        # or pick from a piped output'
