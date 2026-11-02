"""Put shellcopy's pure-Python dependencies (pyte, wcwidth) into a vendor/ folder next to shellcopy.py, which
adds that folder to its import path. Needs only python3: no pip, no venv, no sudo.

Usage: python3 -I packaging/vendor-deps.py VENDOR_DIR
Keep these pins in sync with the resources in packaging/homebrew/shellcopy.rb.
"""
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request

DEPS = [
	('pyte', 'https://files.pythonhosted.org/packages/ab/ab/b599762933eba04de7dc5b31ae083112a6c9a9db15b01d3109ad797559d9/pyte-0.8.2.tar.gz',
	 '5af970e843fa96a97149d64e170c984721f20e52227a2f57f0a54207f08f083f'),
	('wcwidth', 'https://files.pythonhosted.org/packages/ea/01/e5ac23733628a6bbb91913a765fcf55ee8070d8d991bc88fdaaf805052c7/wcwidth-0.9.4.tar.gz',
	 'fd8d57d3cdfe570e3265c8fab1885c24e34ef40889c0759c0c304a19e9835954'),
]


def download(url):
	"""urllib first; curl when Python can't verify HTTPS (python.org's macOS installer ships without certificates)."""
	try:
		with urllib.request.urlopen(url, timeout=60) as response:
			return response.read()
	except (urllib.error.URLError, OSError) as error:
		try:
			return subprocess.run(['curl', '-fsSL', url], capture_output=True, check=True).stdout
		except (OSError, subprocess.CalledProcessError):
			sys.exit(f'vendor-deps: could not download {url}: {error}')


def main(vendor):
	staging = vendor + '.tmp'
	shutil.rmtree(staging, ignore_errors=True)
	os.makedirs(staging)
	for package, url, sha256 in DEPS:
		data = download(url)
		if hashlib.sha256(data).hexdigest() != sha256:
			sys.exit(f'vendor-deps: checksum mismatch for {url}')
		with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
			# Only the package's own folder, e.g. pyte-0.8.2/pyte/... -> vendor/pyte/...
			members = []
			for member in archive.getmembers():
				parts = member.name.split('/')
				if len(parts) > 2 and parts[1] == package and (member.isfile() or member.isdir()) and '..' not in parts:
					member.name = '/'.join(parts[1:])
					members.append(member)
			if not members:
				sys.exit(f'vendor-deps: no {package}/ folder in {url}')
			kwargs = {'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}
			archive.extractall(staging, members=members, **kwargs)
	shutil.rmtree(vendor, ignore_errors=True)
	os.rename(staging, vendor)


if __name__ == '__main__':
	main(sys.argv[1])
