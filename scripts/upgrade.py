"""Upgrade the JetBrains server selected by the installed IntelliJ LSP plugin."""
import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
from pathlib import Path


CONFIGURE = ['claude', 'plugin', 'configure', 'intellij-lsp@intellij-lsp-marketplace']
MANIFEST = 'https://raw.githubusercontent.com/JetBrains/intellij-lsp.nvim/main/lua/intellij-lsp/server_bundles.lua'
CDN = 'https://download.jetbrains.com/language-server/intellij-server'
BUILD = r'[0-9]+(?:\.[0-9]+)+'


def fetch(url, *args):
    return subprocess.check_output(['curl', '-q', '-fsSL', '--proto', '=https', '--proto-redir', '=https',
                                    '--connect-timeout', '15', '--max-time', '600', *args, url])


def latest():
    system = {'Darwin': 'macos', 'Linux': 'linux'}.get(platform.system())
    arch = {'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86_64': 'x86_64'}.get(platform.machine().lower())
    if not system or not arch:
        raise SystemExit(f'Unsupported platform: {platform.system()} {platform.machine()}')
    text = fetch(MANIFEST).decode()
    version = re.search(rf"^M\.version\s*=\s*'({BUILD})'", text, re.M)
    hashes = re.search(r'^M\.sha256\s*=\s*\{(.*?)^\}', text, re.M | re.S)
    block = re.search(rf'\b{system}\s*=\s*\{{([^}}]+)\}}', hashes[1]) if hashes else None
    checksum = re.search(rf"\b{arch}\s*=\s*'([a-f0-9]{{64}})'", block[1]) if block else None
    if not version or not checksum:
        raise SystemExit('Cannot read the build or platform SHA-256 from the JetBrains manifest.')
    build = version[1]
    suffix = '-aarch64' if arch == 'aarch64' else ''
    ext = 'sit' if system == 'macos' else 'tar.gz'
    return build, checksum[1], f'{CDN}/{build}/intellij-server-{build}{suffix}.{ext}'


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def bundle_info(root):
    meta = json.loads((root / 'product-info.json').read_bytes())
    if meta.get('productCode') != 'ILS' or not re.fullmatch(BUILD, meta.get('buildNumber', '')):
        raise SystemExit(f'Not an IntelliJ Server distribution: {root}')
    for name in ('intellij-server', 'lsp-router'):
        path = root / 'bin' / name
        if not path.is_file() or not os.access(path, os.X_OK):
            raise SystemExit(f'Missing executable: {path}')
    return meta['buildNumber'], sha256(root / 'EULA.txt')[:16]


def checked_root(directory, build):
    candidates = list(directory.glob('*/product-info.json'))
    if len(candidates) != 1 or bundle_info(candidates[0].parent)[0] != build:
        raise SystemExit(f'Unexpected bundle layout or build in {directory}; not activating it.')
    return candidates[0].parent


def install(store, build, checksum, url):
    dest = store / build
    receipt = '.archive-sha256'
    if dest.exists():
        if not (dest / receipt).is_file() or (dest / receipt).read_text().strip() != checksum:
            raise SystemExit(f'Existing directory has no matching download receipt; not replacing it: {dest}')
        return checked_root(dest, build)
    with tempfile.TemporaryDirectory(prefix='.upgrade-', dir=store) as tmp:
        archive = Path(tmp) / 'bundle'
        fetch(url, '-o', str(archive))
        if sha256(archive) != checksum:
            raise SystemExit('JetBrains archive SHA-256 mismatch; current configuration unchanged.')
        unpacked = Path(tmp) / 'extracted'
        unpacked.mkdir()
        if platform.system() == 'Darwin':
            subprocess.run(['/usr/bin/ditto', '-x', '-k', archive, unpacked], check=True, timeout=300)
        else:
            subprocess.run(['tar', '--no-same-owner', '-xzf', archive, '-C', unpacked], check=True, timeout=300)
        root = checked_root(unpacked, build)
        (unpacked / receipt).write_text(checksum + '\n')
        unpacked.rename(dest)
        return dest / root.name


def upgrade(release, store, check, accepted):
    build, checksum, url = release
    options = json.loads(subprocess.check_output([*CONFIGURE, '--json'], timeout=30))['inputs']
    if not options.get('server_bin') or not options.get('accepted_eula_hash'):
        raise SystemExit('Configure an existing server and its accepted EULA before upgrading.')
    active = Path(options['server_bin']).parent
    current, terms = bundle_info(active)
    print(f'Configured: {current}\nJetBrains:  {build}', flush=True)
    if check:
        return
    if tuple(map(int, current.split('.'))) > tuple(map(int, build.split('.'))):
        print('Configured build is newer. No downgrade.')
        return
    if current == build and options['accepted_eula_hash'] == terms:
        print('Already current. No changes.')
        return
    target = active if current == build else install(store, build, checksum, url)
    terms = sha256(target / 'EULA.txt')[:16]
    if terms != options['accepted_eula_hash'] and accepted != terms:
        raise SystemExit(f'Not activated. Review {target / "EULA.txt"}.\nIf you accept it, rerun with --accept-eula {terms}.')
    subprocess.run([*CONFIGURE, '--values-stdin'], input=json.dumps({'server_bin': str(target / 'bin'),
                   'accepted_eula_hash': terms}), text=True, check=True, timeout=30)
    print(f'Activated: {target / "bin"}\nPrevious:  {active / "bin"}\nReload the plugin in Claude Code: /reload-plugins')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='report configured and upstream builds without installing')
    mode.add_argument('--accept-eula', metavar='HASH', help='confirm the specific EULA you have reviewed and accepted')
    args = parser.parse_args()
    release = latest()
    store = Path.home() / '.local/share/intellij-server'
    if args.check:
        return upgrade(release, store, True, None)
    store.mkdir(parents=True, exist_ok=True)
    with (store / '.upgrade.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another server upgrade is in progress.') from None
        upgrade(release, store, False, args.accept_eula)


if __name__ == '__main__':
    main()
