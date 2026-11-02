#!/usr/bin/env bash
# Install shellcopy: pyte in a vendor/ folder, `shellcopy` and `cy` in ~/.local/bin, and the shell hook
# for each of bash, zsh and fish that's installed. Other shells get printed instructions.
# Usage: ./install.sh [--no-rc]
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo '› fetching pyte'
# pyte and wcwidth are pure Python, so they go in a vendor/ folder next to shellcopy.py: no venv, pip or sudo needed.
python3 -I "$here/packaging/vendor-deps.py" "$here/vendor"
rm -rf "$here/.venv"  # older versions installed pyte into a virtualenv

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
