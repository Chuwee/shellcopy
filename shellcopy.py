#!/usr/bin/env python3
"""shellcopy: pick part of a command's output with the keyboard and copy it to the clipboard."""

import argparse
import base64
import curses
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time

__version__ = '0.1.5'

# Packages (Homebrew) put the Python dependencies next to this file instead of in a virtualenv.
_VENDOR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'vendor')
if os.path.isdir(_VENDOR):
	sys.path.insert(0, _VENDOR)
# The launcher's path, so `init` can point the shell hook at it (popped so the recorded shell doesn't inherit it).
_EXE = os.environ.pop('SHELLCOPY_EXE', None)

ANSI = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]')
TOKEN = re.compile(r'\S+')
LEADING = '([{<"\'`'
TRAILING = ')]}>"\'`,;:.!?'
ALPHABET = 'asdfjklghqwertyuiopzxcvbnm'
LOG_TAIL = 4_000_000
ALT_SCREEN = re.compile(rb'\x1b\[\?(1049|1047|47)h.*?(?:\x1b\[\?\1l|$)', re.DOTALL)


class ShellcopyError(Exception):
	pass


class Cancelled(Exception):
	pass


def clean(text):
	"""Strip colors and control sequences, keep the final state of redrawn lines, drop trailing blank lines."""
	lines = []
	for raw in ANSI.sub('', text).replace('\r\n', '\n').split('\n'):
		lines.append(raw.split('\r')[-1].expandtabs(8))
	while lines and not lines[-1].strip():
		lines.pop()
	return lines


def tokenize(lines):
	"""Split lines into whitespace-separated words, trimming quotes, brackets and trailing punctuation."""
	tokens = []
	for row, line in enumerate(lines):
		for match in TOKEN.finditer(line):
			start, end = match.span()
			while end - start > 1 and line[start] in LEADING:
				start += 1
			while end - start > 1 and line[end - 1] in TRAILING:
				end -= 1
			tokens.append((row, start, end))
	return tokens


def make_labels(count):
	if count <= len(ALPHABET):
		return list(ALPHABET[:count])
	return [a + b for a in ALPHABET for b in ALPHABET][:count]


class Picker:
	"""Two steps: halve the words on screen with the arrows until you're close, then a cursor takes over.

	Enter drops the start of a selection and Enter again copies it. Tab shows ids on the words still in play.
	Backspace always goes one step back.
	"""

	def __init__(self, lines, tokens, view_height, ids_mode=False):
		self.lines = lines
		self.tokens = tokens
		self.view = max(1, view_height - 1)
		self.top = max(0, len(lines) - self.view)  # show the newest output
		self.left = 0
		self.mode = 'zoom'
		self.region = self.visible_tokens()  # words still in play while halving
		self.history = []                    # earlier regions, for Backspace
		self.zoom_from_cursor = False        # Backspace with no history goes back to the cursor instead of quitting
		self.show_ids = ids_mode            # ids mode: pick the start and end of the selection by typing ids
		self.ids_start = None                # the word the first id picked, while waiting for the second
		self.ids = {}
		self.typed = ''
		self.row = len(lines) - 1
		self.col = len(lines[-1]) - len(lines[-1].lstrip())
		self.want_col = self.col
		self.anchor = None
		self.line_mode = False

	# ------------------------------------------------------------ halving

	def visible_tokens(self):
		return [i for i, (r, _, _) in enumerate(self.tokens) if self.top <= r < self.top + self.view]

	def middle(self, axis):
		"""Where the words still in play split in two: the first row (axis 0) or column (axis 1) of the second
		half, or None when they're all on one row or column."""
		values = sorted({self.tokens[i][axis] for i in self.region})
		return values[len(values) // 2] if len(values) > 1 else None

	def halve(self, key):
		"""Keep the half of the remaining words that the arrow points at; land the cursor once one word is left."""
		axis = 0 if key in (curses.KEY_UP, curses.KEY_DOWN) else 1
		middle = self.middle(axis)
		if middle is None:
			return
		position = lambda i: self.tokens[i][axis]
		first_half = key in (curses.KEY_UP, curses.KEY_LEFT)
		self.history.append(self.region)
		self.region = [i for i in self.region if (position(i) < middle) == first_half]
		if len(self.region) == 1:
			self.enter_cursor(self.region[0])

	def enter_cursor(self, index):
		self.mode = 'cursor'
		self.show_ids = False
		self.typed = ''
		self.jump_to_token(index)

	def start_zoom(self, show_ids=False):
		"""Halve again from everything on screen, keeping any selection in progress."""
		self.mode = 'zoom'
		self.region = self.visible_tokens()
		self.history = []
		self.zoom_from_cursor = True
		self.show_ids = show_ids
		self.ids_start = None
		self.typed = ''

	# ------------------------------------------------------------ cursor movement

	def line_end(self, row):
		return max(0, len(self.lines[row]) - 1)

	def move_to(self, row, col, keep_column=False):
		self.row = max(0, min(row, len(self.lines) - 1))
		self.col = max(0, min(col, self.line_end(self.row)))
		if not keep_column:
			self.want_col = self.col

	def vertical(self, delta):
		self.move_to(self.row + delta, self.want_col, keep_column=True)

	def step(self, delta):
		"""Move one character. Outside a selection, wrap to the neighbouring line at either end. While selecting,
		stop at the line's end: one press too many shouldn't pull in a newline and the next line's first
		character (↑↓ and Space are there for multi-line selections)."""
		if delta < 0:
			if self.col > 0:
				self.move_to(self.row, self.col - 1)
			elif self.row > 0 and self.anchor is None:
				self.move_to(self.row - 1, len(self.lines[self.row - 1]))
		elif self.col < self.line_end(self.row):
			self.move_to(self.row, self.col + 1)
		elif self.row < len(self.lines) - 1 and self.anchor is None:
			self.move_to(self.row + 1, 0)

	def word_jump(self, direction):
		"""Jump a whole word. While selecting forward, land on the word's last character so it's included."""
		here = (self.row, self.col)
		if direction > 0:
			if self.anchor is not None and self.anchor <= here:
				targets = [(r, e - 1) for r, _, e in self.tokens if (r, e - 1) > here]
			else:
				targets = [(r, s) for r, s, _ in self.tokens if (r, s) > here]
			if targets:
				self.move_to(*min(targets))
		else:
			targets = [(r, s) for r, s, _ in self.tokens if (r, s) < here]
			if targets:
				self.move_to(*max(targets))

	def jump_to_token(self, index):
		"""Put the cursor on a word: its start, or its end when that grows a selection forward."""
		row, start, end = self.tokens[index]
		if self.anchor is not None and (row, start) >= self.anchor:
			self.move_to(row, end - 1)
		else:
			self.move_to(row, start)

	# ------------------------------------------------------------ selection

	def bounds(self):
		"""Selected range as inclusive (row, col) pairs."""
		here = (self.row, self.col)
		start, end = sorted((self.anchor, here)) if self.anchor is not None else (here, here)
		if self.line_mode:
			return (start[0], 0), (end[0], self.line_end(end[0]))
		return start, end

	def selection(self):
		(start_row, start_col), (end_row, end_col) = self.bounds()
		if self.line_mode:
			return '\n'.join(self.lines[start_row:end_row + 1])
		if start_row == end_row:
			return self.lines[start_row][start_col:end_col + 1]
		return '\n'.join([self.lines[start_row][start_col:]] + self.lines[start_row + 1:end_row] + [self.lines[end_row][:end_col + 1]])

	# ------------------------------------------------------------ drawing

	def draw(self, screen):
		screen.erase()
		height, width = screen.getmaxyx()
		self.view, width = max(1, height - 1), max(1, width - 1)
		if self.mode == 'cursor':
			if self.row < self.top:
				self.top = self.row
			elif self.row >= self.top + self.view:
				self.top = self.row - self.view + 1
			if self.col < self.left:
				self.left = self.col
			elif self.col >= self.left + width:
				self.left = self.col - width + 1
		else:
			self.left = 0

		# Ids: shortest labels go to the words nearest the bottom, where the newest output is.
		self.ids = {}
		if self.show_ids:
			ordered = sorted(self.region, key=lambda i: (-self.tokens[i][0], -self.tokens[i][1]))
			self.ids = dict(zip(make_labels(len(ordered)), ordered))
		badge_at = {(self.tokens[i][0], self.tokens[i][1]): label for label, i in self.ids.items() if label.startswith(self.typed)}
		in_region = {(self.tokens[i][0], self.tokens[i][1]): self.tokens[i][2] for i in self.region} if self.mode == 'zoom' else {}

		(start_row, start_col), (end_row, end_col) = self.bounds()
		for y, row in enumerate(range(self.top, min(len(self.lines), self.top + self.view))):
			line = self.lines[row]
			x = 0
			region_end = -1
			for col in range(self.left, len(line)):
				if x >= width:
					break
				if (row, col) in badge_at:
					# Ids are inserted before their word, pushing the line right, so they never cover text.
					label = badge_at[(row, col)]
					done = len(self.typed)
					for k, ch in enumerate(label):
						if x < width:
							screen.addstr(y, x, ch, curses.color_pair(1) | (curses.A_DIM if k < done else curses.A_BOLD))
							x += 1
				if (row, col) in in_region:
					region_end = in_region[(row, col)]
				attr = curses.A_NORMAL
				if self.mode == 'zoom':
					attr = curses.A_BOLD if col < region_end else curses.A_DIM
				if self.anchor is not None and (start_row, start_col if not self.line_mode else 0) <= (row, col) <= (end_row, end_col if not self.line_mode else len(line)):
					attr |= curses.A_REVERSE
				screen.addstr(y, x, line[col], attr)
				x += 1

		if self.mode == 'zoom' and not self.show_ids:
			self.draw_splits(screen, width)

		if self.mode == 'cursor':
			line = self.lines[self.row]
			screen.addstr(self.row - self.top, self.col - self.left, line[self.col] if self.col < len(line) else ' ', curses.color_pair(3) | curses.A_BOLD)

		if self.mode == 'zoom' and self.show_ids and self.anchor is None:
			status = ' IDS · type an id to start there · Shift+id copies that word · Tab halve instead · Esc quit'
		elif self.mode == 'zoom' and self.show_ids:
			status = ' IDS · type an id to end there · Enter copy · Shift+id copy up to there · arrows adjust · Backspace undo · Tab halve'
		elif self.mode == 'zoom':
			status = f' {len(self.region)} words · ↑↓ keep the half above/below the line · ←→ left/right of │ · Enter put the cursor here · Tab ids · Backspace undo · Esc quit'
		elif self.anchor is not None:
			status = ' SELECTING · move to grow · Enter copy · z halve again · Tab ids · Backspace clear selection · Esc quit'
		else:
			status = ' arrows move · Shift+←→ word · Shift+↑↓ 5 lines · Enter start selecting · Space lines · z halve again · Tab ids · Backspace back'
		screen.addstr(height - 1, 0, status[:width].ljust(width), curses.color_pair(2))
		screen.refresh()

	def draw_splits(self, screen, width):
		"""Show where the arrows would cut: a line under the last row ↑ keeps, and a bar just before the
		column → keeps from, across the words still in play. Text stays where it is."""
		rows = [self.tokens[i][0] for i in self.region]
		top, bottom = max(min(rows), self.top), min(max(rows), self.top + self.view - 1)
		left = min(self.tokens[i][1] for i in self.region)
		right = min(max(self.tokens[i][2] for i in self.region), width)
		accent = curses.color_pair(4) | curses.A_BOLD

		def cell(row, col):
			line = self.lines[row]
			return line[col] if col < len(line) else ' '

		row_middle = self.middle(0)
		if row_middle is not None:
			above = max(r for r in rows if r < row_middle)  # the last row ↑ keeps
			if self.top <= above < self.top + self.view:
				y = above - self.top
				# Keep each word's look (bold while in play, dim otherwise); only the gaps take the line's colour.
				in_play = {c for i in self.region if self.tokens[i][0] == above for c in range(self.tokens[i][1], self.tokens[i][2])}
				for x in range(left, right):
					ch = cell(above, x)
					attr = curses.color_pair(4) if ch == ' ' else (curses.A_BOLD if x in in_play else curses.A_DIM)
					screen.addstr(y, x, ch, attr | curses.A_UNDERLINE)
				if width < screen.getmaxyx()[1]:
					screen.addstr(y, width, '↑', accent)
					if y + 1 < self.view:
						screen.addstr(y + 1, width, '↓', accent)
		col_middle = self.middle(1)
		if col_middle is not None and 0 < col_middle <= width:
			x = col_middle - 1
			for row in range(top, bottom + 1):
				if cell(row, x) == ' ':  # only in the gaps, so it never recolours part of a word
					screen.addstr(row - self.top, x, '│', accent | (curses.A_UNDERLINE if row_middle is not None and row == above else 0))

	# ------------------------------------------------------------ input

	def pick_id(self, key):
		"""Type an id. The first one starts the selection at that word (covering it), the second ends it at that
		word, after which Enter copies or the arrows adjust. Shift+id copies right away. Returns the selection
		when it's time to copy."""
		instant = key.isupper()
		self.typed += key.lower()
		if self.typed not in self.ids:
			if not any(label.startswith(self.typed) for label in self.ids):
				self.typed = ''
			return None
		index = self.ids[self.typed]
		self.typed = ''
		row, start, end = self.tokens[index]
		if self.anchor is None:
			self.anchor = (row, start)
			self.move_to(row, end - 1)
			if instant:
				return self.selection()
			self.ids_start = index
			self.region, self.history = self.visible_tokens(), []  # the end can be anywhere on screen
			return None
		if self.ids_start is not None:
			# Whichever of the two words comes first is the start; the selection runs to the other's end.
			first, last = sorted((self.ids_start, index), key=lambda i: self.tokens[i][:2])
			self.anchor = tuple(self.tokens[first][:2])
			self.move_to(self.tokens[last][0], self.tokens[last][2] - 1)
			self.ids_start = None
			self.mode, self.show_ids = 'cursor', False
		else:
			self.enter_cursor(index)  # a selection started some other way: just move its end here
		return self.selection() if instant else None

	def run(self, screen):
		curses.curs_set(0)
		curses.use_default_colors()
		curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_YELLOW)
		curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
		curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_GREEN)
		curses.init_pair(4, curses.COLOR_MAGENTA, -1)  # where the arrows would split
		arrows = (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT)
		moves = {
			curses.KEY_LEFT: lambda: self.step(-1),
			curses.KEY_RIGHT: lambda: self.step(1),
			curses.KEY_UP: lambda: self.vertical(-1),
			curses.KEY_DOWN: lambda: self.vertical(1),
			curses.KEY_SLEFT: lambda: self.word_jump(-1),
			curses.KEY_SRIGHT: lambda: self.word_jump(1),
			curses.KEY_SR: lambda: self.vertical(-5),
			curses.KEY_SF: lambda: self.vertical(5),
			curses.KEY_HOME: lambda: self.move_to(self.row, 0),
			curses.KEY_END: lambda: self.move_to(self.row, self.line_end(self.row)),
			curses.KEY_PPAGE: lambda: self.vertical(-self.view),
			curses.KEY_NPAGE: lambda: self.vertical(self.view),
		}
		while True:
			self.draw(screen)
			key = screen.get_wch()
			if key in ('\x1b', '\x03', '\x04'):
				return None
			backspace = key in (curses.KEY_BACKSPACE, '\x7f', '\b')

			if self.mode == 'zoom':
				if backspace:
					if self.typed:
						self.typed = self.typed[:-1]
					elif self.ids_start is not None:  # undo the start picked by id
						self.anchor = self.ids_start = None
					elif self.show_ids:
						self.show_ids = False
						if self.zoom_from_cursor and not self.history:
							self.mode = 'cursor'
					elif self.history:
						self.region = self.history.pop()
					elif self.zoom_from_cursor:
						self.mode = 'cursor'
					else:
						return None
				elif key == '\t':  # switch between halving and ids
					self.show_ids, self.typed = not self.show_ids, ''
					self.ids_start = None
				elif self.show_ids:
					if isinstance(key, str) and key.isalpha() and key.isascii():
						copied = self.pick_id(key)
						if copied is not None:
							return copied
					elif key in ('\n', '\r', curses.KEY_ENTER) and self.anchor is not None:
						return self.selection()
					elif key in arrows or key in moves:
						if self.anchor is not None:  # fine-tune the selection by hand
							self.ids_start = None
							self.mode, self.show_ids = 'cursor', False
							moves[key]()
						elif key in arrows:  # nothing picked yet: halve instead
							self.show_ids = False
							self.halve(key)
				elif key in arrows:
					self.halve(key)
				elif key in ('\n', '\r', curses.KEY_ENTER):
					self.enter_cursor(min(self.region, key=lambda i: self.tokens[i][:2]))
				elif key in (curses.KEY_PPAGE, curses.KEY_NPAGE):
					step = -self.view if key == curses.KEY_PPAGE else self.view
					self.top = max(0, min(self.top + step, max(0, len(self.lines) - self.view)))
					self.region, self.history = self.visible_tokens() or self.region, []
				continue

			if key in moves:
				moves[key]()
			elif key in ('\n', '\r', curses.KEY_ENTER):
				if self.anchor is None:
					self.anchor = (self.row, self.col)
				else:
					return self.selection()
			elif backspace:
				if self.anchor is not None:
					self.anchor = None
					self.line_mode = False
				else:
					self.mode = 'zoom'  # back to halving, where we left off
			elif key == ' ':
				self.line_mode = not self.line_mode
				if self.anchor is None:
					self.anchor = (self.row, self.col)
			elif key == 'z':
				self.start_zoom()
			elif key == '\t':
				self.start_zoom(show_ids=True)


# ---------------------------------------------------------------- clipboard

def copy(text):
	"""Copy to the system clipboard; returns the name of the tool used."""
	candidates = []
	if os.environ.get('WAYLAND_DISPLAY'):
		candidates.append(['wl-copy'])
	if os.environ.get('DISPLAY'):
		candidates += [['xclip', '-selection', 'clipboard'], ['xsel', '--clipboard', '--input']]
	candidates += [['pbcopy'], ['clip.exe']]
	for command in candidates:
		if shutil.which(command[0]):
			subprocess.run(command, input=text, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
			return command[0]
	# No clipboard tool: ask the terminal itself (OSC 52), which many terminals and SSH sessions support.
	with open('/dev/tty', 'w') as tty:
		tty.write(f'\x1b]52;c;{base64.b64encode(text.encode()).decode()}\x07')
	return 'the terminal (OSC 52)'


# ---------------------------------------------------------------- main

def read_log(path):
	"""Rebuild what the terminal shows, scrollback included, from the tail of a `script` recording."""
	try:
		import pyte
	except ImportError:
		raise ShellcopyError('the pyte package is missing; run ./install.sh')
	try:
		size = os.path.getsize(path)
		with open(path, 'rb') as f:
			f.seek(max(0, size - LOG_TAIL))
			data = f.read()
	except OSError as e:
		raise ShellcopyError(f'could not read the terminal recording: {e}')
	# Full-screen programs (less, vim, shellcopy itself) draw on the alternate screen, which the terminal
	# throws away when they exit; drop them too.
	data = ALT_SCREEN.sub(b'', data.replace(b'\x00', b''))
	if data.startswith(b'Script started on'):
		data = data.split(b'\n', 1)[-1]  # the recorder's own header line
	columns, rows = shutil.get_terminal_size()
	screen = pyte.HistoryScreen(columns, rows, history=5000)
	pyte.ByteStream(screen).feed(data)
	history = [''.join(line[x].data for x in range(columns)) for line in screen.history.top]
	lines = [line.rstrip() for line in history + screen.display]
	while lines and not lines[-1].strip():
		lines.pop()
	return lines[:-1]  # drop the line where shellcopy itself was typed


def parent_shell():
	"""The shell that ran us, to re-run a command in; falls back to $SHELL."""
	try:
		name = subprocess.run(['ps', '-o', 'comm=', '-p', str(os.getppid())], capture_output=True, text=True).stdout.strip()
	except OSError:
		name = ''
	path = shutil.which(os.path.basename(name.lstrip('-'))) if name else None
	return path or os.environ.get('SHELL') or '/bin/sh'


def last_command():
	"""The newest history entry that isn't a shellcopy call, from SHELLCOPY_HISTORY (newest first), which the
	shell integrations fill in. Shells without an integration don't pass their history."""
	for line in os.environ.get('SHELLCOPY_HISTORY', '').splitlines():
		line = line.strip()
		# Whole words only: `cy` is a substring of plenty of other commands (fancy, cycle, ...).
		if line and not {'shellcopy', 'cy', 'shcp', 'bcp'} & set(re.split(r'[\s|;&()]+', line)):
			return line
	return None


def rerun():
	"""No recording of this terminal: the only way to get output back is to run the last command again."""
	command = last_command()
	if not command:
		raise ShellcopyError('this terminal is not recorded; run `shellcopy setup` once so plain `cy` works, or pipe output in: cmd | cy')
	shell = parent_shell()
	sys.stderr.write(f'shellcopy: this terminal is not recorded (see `shellcopy record`).\n'
	                 f'Re-run \x1b[1m{command}\x1b[0m to grab its output? [Enter/n] ')
	sys.stderr.flush()
	if sys.stdin.readline().strip().lower().startswith('n'):
		raise Cancelled
	result = subprocess.run([shell, '-c', command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
	return clean(result.stdout.decode(errors='replace'))


def read_input(log):
	"""Get the lines to pick from, and make sure the terminal is on stdin for the picker."""
	if not sys.stdin.isatty():
		text = sys.stdin.buffer.read().decode(errors='replace')
		os.dup2(os.open('/dev/tty', os.O_RDWR), 0)
		return clean(text)
	log = log or current_recording()
	if log:
		return read_log(log)
	if os.environ.get('TMUX'):
		result = subprocess.run(['tmux', 'capture-pane', '-p', '-J', '-S', '-500'], capture_output=True, text=True)
		return clean(result.stdout)[:-1]  # drop the line where shellcopy itself was typed
	return rerun()


# ---------------------------------------------------------------- recording

RECORD_MAX = 8_000_000   # trim the log when it passes this size...
RECORD_KEEP = 2_000_000  # ...down to its last this-many bytes
# `script` runs sh with this, which notes the recording's tty (so a recording only counts in the terminal
# that made it), restores $SHELL and starts the real shell.
RECORD_INNER = ('SHELLCOPY_TTY=$(tty); export SHELLCOPY_TTY; SHELL=$_SHELLCOPY_SHELL; s=$_SHELLCOPY_EXEC; '
                'unset _SHELLCOPY_SHELL _SHELLCOPY_EXEC; [ -n "$SHELL" ] || unset SHELL; exec "$s"')


def current_recording():
	"""This terminal's recording, if it has one. A new terminal opened from a recorded shell inherits the
	variables, so check the tty too."""
	log = os.environ.get('SHELLCOPY_LOG')
	try:
		tty = os.ttyname(0)
	except OSError:
		return None
	if log and os.path.isfile(log) and os.environ.get('SHELLCOPY_TTY') == tty:
		return log
	return None


def why_not_record():
	"""None if this terminal should be recorded, otherwise the reason it shouldn't."""
	if not (sys.stdin.isatty() and sys.stdout.isatty()):
		return 'not a terminal'
	if current_recording():
		return 'already recorded'
	if os.environ.get('SHELLCOPY_RECORD') == '0':
		return 'SHELLCOPY_RECORD=0'
	if os.environ.get('TMUX'):
		return 'inside tmux, where cy reads the screen directly'
	if os.environ.get('TERM_PROGRAM') == 'vscode':
		return "VS Code's terminal"
	if script_variant() is None:
		return 'needs `script` (on Linux, the util-linux one)'
	return None


def script_variant():
	"""'util-linux' (Linux), 'bsd' (macOS, FreeBSD, ...) or None, by which `script` this system has."""
	if not shutil.which('script'):
		return None
	if sys.platform == 'darwin' or 'bsd' in sys.platform:
		return 'bsd'  # (don't probe with --version: some BSD versions would take it as a file name and start recording)
	try:
		result = subprocess.run(['script', '--version'], capture_output=True, text=True, timeout=5)
	except (OSError, subprocess.TimeoutExpired):
		return None
	return 'util-linux' if 'util-linux' in result.stdout + result.stderr else None


def recording_dir():
	"""Private per-user folder for recordings: in memory on Linux (XDG_RUNTIME_DIR), the per-user temp folder on macOS."""
	base = os.environ.get('XDG_RUNTIME_DIR') or (os.environ.get('TMPDIR') if sys.platform == 'darwin' else None) or '/tmp'
	return os.path.join(base, f'shellcopy-{os.getuid()}')


def trim(log):
	"""Keep the log small. The recorder appends, so rewriting the file under it is safe."""
	try:
		if os.path.getsize(log) > RECORD_MAX:
			with open(log, 'rb') as f:
				f.seek(-RECORD_KEEP, os.SEEK_END)
				keep = f.read()
			with open(log, 'wb') as f:
				f.write(keep)
	except OSError:
		pass


def record(shell):
	"""Run `shell` inside `script`, which logs what the terminal prints (text only, no keystrokes) to a private
	file (see recording_dir). The log is trimmed as it grows and deleted on exit.
	Meant to be exec'd from the shell's rc file, so this process stands in for the shell."""
	reason = why_not_record()
	if reason:
		if reason.startswith('needs'):  # the other reasons are expected skips; stay quiet in rc files
			sys.stderr.write(f'shellcopy: not recording: {reason}\n')
		return 1
	shell = shutil.which(shell or os.environ.get('SHELL') or 'sh') or '/bin/sh'

	directory = recording_dir()
	os.makedirs(directory, mode=0o700, exist_ok=True)
	os.chmod(directory, 0o700)
	for name in os.listdir(directory):  # logs of terminals that are gone
		pid = name[:-4]
		if name.endswith('.log') and pid.isdigit():
			try:
				os.kill(int(pid), 0)
			except ProcessLookupError:
				os.remove(os.path.join(directory, name))
			except PermissionError:
				pass
	log = os.path.join(directory, f'{os.getpid()}.log')
	os.close(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))

	env = dict(os.environ, SHELLCOPY_LOG=log, SHELL='/bin/sh', _SHELLCOPY_SHELL=os.environ.get('SHELL', ''), _SHELLCOPY_EXEC=shell)
	env.pop('SHELLCOPY_TTY', None)

	def stop(signum, frame):
		raise SystemExit(128 + signum)
	signal.signal(signal.SIGHUP, stop)   # the terminal closed: clean up
	signal.signal(signal.SIGTERM, stop)
	signal.signal(signal.SIGINT, lambda *_: None)  # a handler, not SIG_IGN, so the shell doesn't inherit it

	started = time.monotonic()
	try:
		if script_variant() == 'util-linux':  # runs its -c command with $SHELL, which env sets to /bin/sh
			command = ['script', '-q', '-f', '-a', '-c', RECORD_INNER, log]
		else:  # BSD: -F flushes after every write, so the log is always current
			command = ['script', '-q', '-a', '-F', log, '/bin/sh', '-c', RECORD_INNER]
		recorder = subprocess.Popen(command, env=env)
		while True:
			try:
				rc = recorder.wait(timeout=5)
				break
			except subprocess.TimeoutExpired:
				trim(log)
	finally:
		try:
			os.remove(log)
		except OSError:
			pass
	if rc != 0 and time.monotonic() - started < 2:
		# The recorder failed to start. This process replaced the shell, so start it unrecorded rather
		# than closing the terminal.
		sys.stderr.write('shellcopy: could not start recording this terminal; plain `cy` will re-run commands instead\n')
		os.execve(shell, [shell], dict(os.environ, SHELLCOPY_RECORD='0'))
	return rc


def record_main(argv):
	parser = argparse.ArgumentParser(prog='shellcopy record', description=(
		'Run SHELL with this terminal recorded, so plain `cy` can pick from what it shows. '
		'From an rc file: shellcopy record --check && exec shellcopy record SHELL'))
	parser.add_argument('shell', nargs='?', help='the shell to run (default: $SHELL)')
	parser.add_argument('--check', action='store_true', help='only exit 0 if this terminal should be recorded, 1 if not')
	args = parser.parse_args(argv)
	if args.check:
		return 0 if why_not_record() is None else 1
	return record(args.shell)


# ---------------------------------------------------------------- shell integration

# `shellcopy init SHELL` prints these; the rc file evals them. `cy` works without them as a plain command;
# they hand shellcopy your history (so an unrecorded terminal can re-run your last command) and make
# `shellcopy record` replace the shell with a recorded one. {bin} is the shellcopy executable.
INIT_POSIX = """\
shellcopy() {{
	if [ "$1" = record ]; then
		_shellcopy_shell="${{2:-${{BASH:-}}}}"
		[ -z "$_shellcopy_shell" ] && [ -n "$ZSH_VERSION" ] && _shellcopy_shell="$(command -v zsh)"
		{bin} record --check || return 0
		exec {bin} record ${{_shellcopy_shell:+"$_shellcopy_shell"}}
	fi
	SHELLCOPY_HISTORY="$(fc -lnr -10 2>/dev/null)" {bin} "$@"
}}
alias cy=shellcopy
"""

INIT_FISH = """\
function shellcopy --description 'pick part of the terminal output with the keyboard and copy it'
    if test "$argv[1]" = record
        set -l shell $argv[2]
        test -n "$shell"; or set shell (status fish-path)
        {bin} record --check; or return 0
        exec {bin} record $shell
    end
    set -lx SHELLCOPY_HISTORY (history --max 10 | string collect)
    {bin} $argv
end
function cy --wraps shellcopy --description 'pick part of the terminal output with the keyboard and copy it'
    shellcopy $argv
end
"""

RC_LINES = {
	'posix': 'command -v shellcopy >/dev/null && eval "$(shellcopy init {shell})" && shellcopy record',
	'fish': 'status is-interactive; and type -q shellcopy; and shellcopy init fish | source; and shellcopy record',
}
# The same, for when shellcopy isn't on PATH (on macOS, ~/.local/bin usually isn't): call it by its full path.
RC_LINES_ABSOLUTE = {
	'posix': '[ -x {exe} ] && eval "$({exe} init {shell})" && shellcopy record',
	'fish': 'status is-interactive; and test -x {exe}; and {exe} init fish | source; and shellcopy record',
}


def rc_line(shell):
	kind = 'fish' if shell == 'fish' else 'posix'
	if shutil.which('shellcopy'):
		return RC_LINES[kind].format(shell=shell)
	exe = shlex.quote(_EXE or os.path.realpath(sys.argv[0]))
	return RC_LINES_ABSOLUTE[kind].format(shell=shell, exe=exe)


def init_main(argv):
	parser = argparse.ArgumentParser(prog='shellcopy init', description=(
		'Print the shell hook. Add this to ~/.bashrc or ~/.zshrc:  ' + RC_LINES['posix'].format(shell='bash') +
		'   or to ~/.config/fish/conf.d/shellcopy.fish:  ' + RC_LINES['fish']))
	parser.add_argument('shell', choices=['bash', 'zsh', 'fish', 'sh', 'ksh'])
	parser.add_argument('--rc-line', action='store_true', help='print the line to add to the rc file instead')
	args = parser.parse_args(argv)
	if args.rc_line:
		print(rc_line(args.shell))
		return 0
	executable = _EXE or shutil.which('shellcopy') or os.path.realpath(sys.argv[0])
	template = INIT_FISH if args.shell == 'fish' else INIT_POSIX
	sys.stdout.write(template.format(bin=shlex.quote(executable)))
	return 0


# Lines that earlier installs put in rc files (including bashcopy, this tool's old name), removed before adding ours.
OLD_RC_LINE = re.compile(r'^(# (shell|bash)copy|export (SHELL|BASH)COPY_HOME=.*|source "\$(SHELL|BASH)COPY_HOME/(shell|bash)copy\.sh"'
                         r'|(shell|bash)copy record( .*)?|.*shellcopy init .*)$')


def rc_files():
	"""(shell, rc file) for each of bash, zsh and fish that's installed, plus the login shell."""
	home = os.path.expanduser('~')
	login = os.path.basename(os.environ.get('SHELL', ''))
	config = os.environ.get('XDG_CONFIG_HOME') or os.path.join(home, '.config')
	files = {
		'bash': os.path.join(home, '.bashrc'),
		'zsh': os.path.join(os.environ.get('ZDOTDIR') or home, '.zshrc'),
		'fish': os.path.join(config, 'fish', 'conf.d', 'shellcopy.fish'),
	}
	return [(shell, path) for shell, path in files.items() if shell == login or shutil.which(shell)]


def strip_hook(text):
	"""Remove our lines (and the blank line before each block) from an rc file's text."""
	out = []
	for line in text.splitlines(keepends=True):
		if OLD_RC_LINE.match(line.rstrip('\n')):
			if out and not out[-1].strip():
				out.pop()
			continue
		out.append(line)
	return ''.join(out)


def setup_main(argv):
	parser = argparse.ArgumentParser(prog='shellcopy setup', description=(
		'Add the shell hook to ~/.bashrc, ~/.zshrc and fish\'s conf.d (for the shells that are installed), so plain '
		'`cy` can pick from what the terminal shows. Safe to run again.'))
	parser.add_argument('--remove', action='store_true', help='take the hook out again')
	args = parser.parse_args(argv)
	for shell, path in rc_files():
		if shell == 'fish':
			old = os.path.join(os.path.dirname(path), 'bashcopy.fish')
			for stale in ([path, old] if args.remove else [old]):
				if os.path.exists(stale):
					os.remove(stale)
					if stale == path:
						print(f'› removed the shell hook: {path}')
			if not args.remove:
				os.makedirs(os.path.dirname(path), exist_ok=True)
				with open(path, 'w') as f:
					f.write(f'# shellcopy: copy terminal output with `cy`; delete this file to uninstall\n{rc_line("fish")}\n')
				print(f'› added the shell hook to {path}')
			continue
		text = open(path).read() if os.path.exists(path) else ''
		new = strip_hook(text)
		if not args.remove:
			if new and not new.endswith('\n'):
				new += '\n'
			new += ('\n' if new else '') + f'# shellcopy\n{rc_line(shell)}  # copy terminal output with `cy`; remove to uninstall\n'
		if new != text:
			with open(path, 'w') as f:  # write in place, so a symlinked rc (dotfile managers) stays a symlink
				f.write(new)
		print(f'› {"removed the shell hook from" if args.remove else "added the shell hook to"} {path}')
	login = os.path.basename(os.environ.get('SHELL', ''))
	if not args.remove and login and login not in ('bash', 'zsh', 'fish'):
		print(f'\n› for {login}, cy already works as a command. To record terminals so plain `cy` can pick from\n'
		      f'  the screen, add the equivalent of this to its startup file:\n'
		      f'    shellcopy record --check && exec shellcopy record')
	if not args.remove:
		print('\nopen a new terminal to start using it.')
	return 0


def main():
	if sys.argv[1:2] == ['init']:
		return init_main(sys.argv[2:])
	if sys.argv[1:2] == ['setup']:
		return setup_main(sys.argv[2:])
	if sys.argv[1:2] == ['record']:
		return record_main(sys.argv[2:])
	parser = argparse.ArgumentParser(prog='shellcopy', description=__doc__,
		epilog='subcommands: `shellcopy setup` adds the shell hook to your rc files; `shellcopy record` runs your shell with this terminal recorded; `shellcopy init SHELL` prints the hook (see --help on each)')
	parser.add_argument('--version', action='version', version=f'shellcopy {__version__}')
	parser.add_argument('--print', action='store_true', help='print the selection to stdout instead of copying it')
	parser.add_argument('--ids', action='store_true', help='start in ids mode (also SHELLCOPY_MODE=ids); Tab switches modes')
	parser.add_argument('--log', help='a `script` recording of this terminal to pick from')
	args = parser.parse_args()
	try:
		lines = read_input(args.log)
		tokens = tokenize(lines)
		if not lines or not tokens:
			raise ShellcopyError('nothing on screen to copy yet (the line you typed cy on is left out); run something first, or: cmd | cy')
		result_fd = None
		if not sys.stdout.isatty():
			# stdout is captured (e.g. `x=$(cmd | shellcopy --print)`): draw on the terminal, send the result there.
			result_fd = os.dup(1)
			os.dup2(os.open('/dev/tty', os.O_RDWR), 1)
		os.environ.setdefault('ESCDELAY', '25')
		ids_mode = args.ids or os.environ.get('SHELLCOPY_MODE') == 'ids'
		selection = curses.wrapper(lambda screen: Picker(lines, tokens, screen.getmaxyx()[0], ids_mode).run(screen))
		if selection is None:
			return 1
		if args.print:
			os.write(result_fd if result_fd is not None else 1, (selection + '\n').encode())
			return 0
		tool = copy(selection)
		preview = selection.replace('\n', '⏎')
		preview = preview if len(preview) <= 60 else preview[:59] + '…'
		sys.stderr.write(f'\x1b[2mcopied with {tool}:\x1b[0m {preview}\n')
		return 0
	except Cancelled:
		return 1
	except ShellcopyError as e:
		sys.stderr.write(f'shellcopy: {e}\n')
		return 1
	except OSError as e:
		if e.filename == '/dev/tty':
			sys.stderr.write('shellcopy: needs a terminal to show the picker\n')
			return 1
		raise
	except KeyboardInterrupt:
		return 130


if __name__ == '__main__':
	sys.exit(main())
