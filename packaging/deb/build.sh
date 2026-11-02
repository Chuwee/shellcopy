#!/usr/bin/env bash
# Build dist/shellcopy_<version>_all.deb. Needs only dpkg-deb. Install it with: sudo apt install ./dist/shellcopy_*.deb
# Python and pyte come from Debian/Ubuntu (python3-pyte), so the package itself is architecture-independent.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
version="$(sed -n "s/^__version__ = '\(.*\)'$/\1/p" "$root/shellcopy.py")"
maintainer="${DEBFULLNAME:-$(git -C "$root" config user.name)} <${DEBEMAIL:-$(git -C "$root" config user.email)}>"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

install -Dm644 "$root/shellcopy.py" "$stage/usr/share/shellcopy/shellcopy.py"
install -Dm755 "$root/bin/shellcopy" "$stage/usr/share/shellcopy/bin/shellcopy"
mkdir -p "$stage/usr/bin"
ln -s ../share/shellcopy/bin/shellcopy "$stage/usr/bin/shellcopy"
ln -s ../share/shellcopy/bin/shellcopy "$stage/usr/bin/cy"
install -Dm644 "$root/README.md" "$stage/usr/share/doc/shellcopy/README.md"
install -Dm644 "$root/LICENSE" "$stage/usr/share/doc/shellcopy/copyright"

mkdir -p "$stage/DEBIAN"
chmod -R u=rwX,go=rX "$stage"
cat >"$stage/DEBIAN/control" <<CONTROL
Package: shellcopy
Version: $version
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.8), python3-pyte, util-linux
Recommends: wl-clipboard | xclip | xsel
Maintainer: $maintainer
Homepage: https://github.com/Chuwee/shellcopy
Description: copy part of your terminal's output with the keyboard
 Type cy, narrow down to what you want with a few arrow presses, and press
 Enter twice to copy it. Works from any shell. Run "shellcopy setup" once to
 add the shell hook, which lets plain cy pick from what the terminal shows.
CONTROL

mkdir -p "$root/dist"
out="$root/dist/shellcopy_${version}_all.deb"
dpkg-deb --root-owner-group --build "$stage" "$out" >/dev/null
echo "$out"
