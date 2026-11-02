"""End-to-end test: start an interactive shell set up by `shellcopy setup` in a pseudo-terminal, check that
the terminal gets recorded, print something, then pick a word from the screen with `cy --print`.

Usage: python3 tests/pty_test.py SHELL   (after ./install.sh; uses the real $HOME, so run it in CI or a throwaway HOME)
"""
import fcntl
import os
import pty
import re
import select
import struct
import sys
import termios
import time

shell = sys.argv[1]
ROWS, COLS = 24, 100


def run():
	pid, fd = pty.fork()
	if pid == 0:
		fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack('HHHH', ROWS, COLS, 0, 0))
		env = dict(os.environ, TERM='xterm-256color', PS1='$ ', PROMPT='$ ')
		for name in ('SHELLCOPY_LOG', 'SHELLCOPY_TTY', 'TMUX', 'TERM_PROGRAM'):
			env.pop(name, None)
		os.execvpe(shell, [shell, '-i'], env)
	fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', ROWS, COLS, 0, 0))
	output = bytearray()

	def send(data, wait):
		os.write(fd, data)
		end = time.time() + wait
		while time.time() < end:
			if select.select([fd], [], [], 0.1)[0]:
				try:
					output.extend(os.read(fd, 65536))
				except OSError:
					return

	send(b'', 4)  # shell startup, including the switch into the recorded shell
	send(b'echo "LOG=[$SHELLCOPY_LOG]"\n', 1.5)
	send(b'clear; echo alpha beta gamma\n', 1.5)
	send(b'x=$(cy --print); echo "GOT=[$x]"\n', 3)
	for key in (b'\r', b'\r', b'\x1b[1;2C', b'\r'):  # cursor on the first word, start selecting, Shift+right, copy
		send(key, 0.8)
	send(b'', 2)
	send(b'exit\n', 2)
	text = re.sub(rb'\x1b(\][^\x07\x1b]*(\x07|\x1b\\)|\[[0-9;?]*[ -/]*[@-~]|[()][A-Z0-9]|[=>])', b'', bytes(output))
	return text.decode(errors='replace').replace('\r', '')


text = run()
log = re.findall(r'LOG=\[([^\]\n]*)\]', text)
got = re.findall(r'GOT=\[([^\]\n]*)\]', text)
print(f'recording log: {log}\ncopied: {got}')
if not log or not log[-1]:
	print(text[-3000:])
	sys.exit('FAIL: the terminal was not recorded')
if 'alpha' not in got:
	print(text[-3000:])
	sys.exit('FAIL: cy --print did not return "alpha"')
print('PASS')
