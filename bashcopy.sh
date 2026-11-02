# bashcopy shell integration for bash and zsh. Source it from ~/.bashrc or ~/.zshrc (install.sh does this for you):
#   export BASHCOPY_HOME=/path/to/bashcopy
#   source "$BASHCOPY_HOME/bashcopy.sh"
#   bashcopy record
#   bcp                pick from what this terminal shows (needs `bashcopy record`, or tmux)
#   cmd | bcp          pick from cmd's output
#   bashcopy record    log this terminal's output so plain `bcp` can use it (install.sh adds this to your rc)

if [ -z "$BASHCOPY_HOME" ] && [ -n "$BASH_VERSION" ]; then
	BASHCOPY_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

_bashcopy_py() {
	local py="$BASHCOPY_HOME/.venv/bin/python"
	[ -x "$py" ] || py=python3
	"$py" "$BASHCOPY_HOME/bashcopy.py" "$@"
}

# A recording only belongs to the terminal that made it. A new terminal opened from a recorded shell
# inherits the variables, so check the tty too.
_bashcopy_recording() {
	[ -n "$BASHCOPY_LOG" ] && [ -f "$BASHCOPY_LOG" ] && [ "$BASHCOPY_TTY" = "$(tty 2>/dev/null)" ]
}

# Run this terminal's shell inside util-linux `script`, which logs what the terminal prints to a
# private file in memory (XDG_RUNTIME_DIR). The log is trimmed as it grows and deleted on exit.
_bashcopy_record() {
	case $- in *i*) ;; *) return 0 ;; esac
	[ -t 0 ] && [ -t 1 ] || return 0
	if [ -n "$BASHCOPY_LOG" ]; then
		# Inside the recorder: claim this tty on the first prompt, or ignore a recording inherited from elsewhere.
		if [ -z "$BASHCOPY_TTY" ]; then
			export BASHCOPY_TTY="$(tty)"
			return 0
		fi
		_bashcopy_recording && return 0
		unset BASHCOPY_LOG BASHCOPY_TTY
	fi
	[ -z "$TMUX" ] && [ "$BASHCOPY_RECORD" != 0 ] && [ "$TERM_PROGRAM" != vscode ] || return 0
	script --version 2>/dev/null | grep -q util-linux || return 0

	local dir="${XDG_RUNTIME_DIR:-/tmp}/bashcopy-$(id -u)" f shell started rc
	mkdir -p "$dir" && chmod 700 "$dir" || return 0
	for f in "$dir"/*.log; do
		[ -e "$f" ] && ! kill -0 "$(basename "$f" .log)" 2>/dev/null && rm -f "$f"
	done
	shell="${BASH:-$(command -v zsh)}"
	export BASHCOPY_LOG="$dir/$$.log"
	(umask 077 && : >"$BASHCOPY_LOG")
	started=$SECONDS
	script -q -f -a -c "$shell" "$BASHCOPY_LOG"
	rc=$?
	rm -f "$BASHCOPY_LOG"
	if [ $rc -ne 0 ] && [ $((SECONDS - started)) -lt 2 ]; then
		# The recorder failed to start: stay in this shell rather than closing the terminal.
		echo 'bashcopy: could not start recording this terminal; plain `bcp` will re-run commands instead' >&2
		unset BASHCOPY_LOG
		return 0
	fi
	exit $rc
}

# Keep the log small: when it passes 8 MB, keep the last 2 MB (the recorder appends, so this is safe).
_bashcopy_trim() {
	_bashcopy_recording || return 0
	local size
	size=$(stat -c %s "$BASHCOPY_LOG" 2>/dev/null) || return 0
	if [ "$size" -gt 8000000 ]; then
		local keep
		keep="$(tail -c 2000000 "$BASHCOPY_LOG")"
		printf '%s' "$keep" >"$BASHCOPY_LOG"
	fi
}
if [ -n "$ZSH_VERSION" ]; then
	precmd_functions+=(_bashcopy_trim)
else
	case ";$PROMPT_COMMAND;" in *';_bashcopy_trim;'*) ;; *) PROMPT_COMMAND="_bashcopy_trim${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;; esac
fi

# The most recent history entry that isn't a bashcopy call itself.
_bashcopy_last_command() {
	local line
	fc -ln -10 -1 2>/dev/null | sed 's/^[[:space:]]*//' | tac | while IFS= read -r line; do
		case "$line" in
			'' | *bashcopy* | *bcp*) ;;
			*) printf '%s\n' "$line"; break ;;
		esac
	done
}

bashcopy() {
	if [ "$1" = record ]; then
		_bashcopy_record
		return
	fi
	if [ ! -t 0 ]; then
		_bashcopy_py "$@"
	elif _bashcopy_recording; then
		_bashcopy_py --log "$BASHCOPY_LOG" "$@"
	elif [ -n "$TMUX" ]; then
		_bashcopy_py "$@"
	else
		# No recording of this terminal: the only way to get output back is to run the command again.
		local last answer
		last="$(_bashcopy_last_command)"
		if [ -z "$last" ]; then
			echo 'bashcopy: no previous command found; try: cmd | bashcopy' >&2
			return 1
		fi
		printf 'bashcopy: this terminal is not recorded (see `bashcopy record`).\nRe-run \033[1m%s\033[0m to grab its output? [Enter/n] ' "$last" >&2
		read -r answer
		case "$answer" in n* | N*) return 1 ;; esac
		eval "$last" 2>&1 | _bashcopy_py "$@"
	fi
}

alias bcp=bashcopy
