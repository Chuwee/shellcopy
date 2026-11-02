#!/bin/sh
# shellcopy installer: https://github.com/Chuwee/shellcopy
#
#   curl -fsSL https://chuwee.github.io/shellcopy/install.sh | sh
#   curl -fsSL https://chuwee.github.io/shellcopy/install.sh | sh -s -- --no-rc     # don't touch rc files
#
# Downloads the latest release into ~/.local/share/shellcopy (or $SHELLCOPY_DIR) and runs its install.sh, which
# fetches pyte into it (only python3 is needed: no venv, pip or sudo), links `shellcopy` and `cy` into ~/.local/bin, and adds the shell hook
# to ~/.bashrc, ~/.zshrc and fish's conf.d. No sudo. Run it again to update.
#
# Everything is inside main(), so a partly downloaded script does nothing.

main() {
	set -eu
	repo=Chuwee/shellcopy
	dir="${SHELLCOPY_DIR:-$HOME/.local/share/shellcopy}"

	say() { printf '› %s\n' "$*"; }
	die() { printf 'shellcopy install: %s\n' "$*" >&2; exit 1; }

	command -v curl >/dev/null || die 'needs curl'
	command -v tar >/dev/null || die 'needs tar'
	command -v bash >/dev/null || die 'needs bash (only to run the installer; shellcopy itself works from any shell)'
	command -v python3 >/dev/null || die 'needs python3'

	# The latest release's tag, from where /releases/latest redirects (no API call, so no rate limit).
	latest="$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/$repo/releases/latest")"
	tag="${latest##*/}"
	case "$tag" in v[0-9]*) ;; *) die "could not find the latest release (got: $latest)" ;; esac

	say "downloading shellcopy $tag"
	tmp="$(mktemp -d)"
	trap 'rm -rf "$tmp"' EXIT
	curl -fsSL "https://github.com/$repo/archive/refs/tags/$tag.tar.gz" | tar -xz -C "$tmp"
	src="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
	[ -f "$src/install.sh" ] || die 'the download does not look like shellcopy'

	# Replace the code, keeping nothing from an older version (the installer fetches pyte again).
	case "$dir" in "" | / | "$HOME") die "refusing to install into '$dir'" ;; esac
	rm -rf "$dir"
	mkdir -p "$(dirname "$dir")"
	mv "$src" "$dir"
	say "installed into $dir"

	bash "$dir/install.sh" "$@"
}

main "$@"
