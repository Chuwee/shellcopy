"""On WSL: copy() should put text, accents and symbols included, into the Windows clipboard.
Usage (inside WSL): python3 tests/wsl_clipboard_test.py"""
import os
import subprocess
import sys

sys.argv = sys.argv[:1]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import shellcopy  # noqa: E402

assert shellcopy.on_wsl(), 'FAIL: not detected as WSL'
text = 'café → naïve 42'
tool = shellcopy.copy(text)
back = subprocess.run(['powershell.exe', '-NoProfile', '-Command', '[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard'],
                      capture_output=True).stdout.decode('utf-8', errors='replace').strip()
print(f'copied with {tool}: {text!r}; Windows clipboard has: {back!r}')
sys.exit(0 if back == text else 'FAIL: the Windows clipboard does not match')
