#!/usr/bin/env bash
# Point the formula at a release: fills in its url and sha256 from the GitHub tag's source tarball.
# Usage: packaging/homebrew/update-formula.sh [VERSION]   (default: the version in shellcopy.py; the tag vVERSION must be pushed)
# Then copy packaging/homebrew/shellcopy.rb to Formula/shellcopy.rb in the tap repo (Chuwee/homebrew-shellcopy).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
version="${1:-$(sed -n "s/^__version__ = '\(.*\)'$/\1/p" "$root/shellcopy.py")}"
url="https://github.com/Chuwee/shellcopy/archive/refs/tags/v$version.tar.gz"
sha="$(curl -fsSL "$url" | sha256sum | cut -d' ' -f1)"
formula="$root/packaging/homebrew/shellcopy.rb"
sed -i -E "s|^  url \"https://github.com/Chuwee/shellcopy/archive/refs/tags/v[^\"]*\"|  url \"$url\"|; 0,/^  sha256 /s|^  sha256 \"[^\"]*\"|  sha256 \"$sha\"|" "$formula"
echo "$formula -> v$version ($sha)"
