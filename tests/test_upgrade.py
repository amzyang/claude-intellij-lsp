import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile


UPGRADE = Path(__file__).resolve().parents[1] / 'scripts/upgrade.py'
OLD, NEW = '271.1000.0', '271.2000.0'
TERMS = b'Test agreement\n'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def files(build, terms):
    return {'product-info.json': json.dumps({'productCode': 'ILS', 'buildNumber': build}).encode(),
            'EULA.txt': terms, 'bin/intellij-server': b'test launcher', 'bin/lsp-router': b'test router'}


class UpgradeCLI(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / 'test home'
        self.home.mkdir()
        self.store = self.home / '.local/share/intellij-server'
        self.old = self.store / OLD / 'intellij-server-2027.1'
        for name, data in files(OLD, TERMS).items():
            p = self.old / name
            p.parent.mkdir(exist_ok=True, parents=True)
            p.write_bytes(data)
            if name.startswith('bin/'):
                p.chmod(0o755)
        self.initial = dict(server_bin=str(self.old / 'bin'), accepted_eula_hash=digest(TERMS)[:16])
        self.config = self.home / 'options.json'
        self.config.write_text(json.dumps(self.initial))
        tools = self.home / 'tools'
        tools.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(tools) + os.pathsep + os.environ['PATH'])
        stubs = {
            'claude': """import sys, json
from pathlib import Path
p = Path.home() / 'options.json'
assert sys.argv[1:4] == ['plugin', 'configure', 'intellij-lsp@intellij-lsp-marketplace']
if '--values-stdin' in sys.argv:
    assert not (Path.home() / 'deny-write').exists()
    p.write_text(json.dumps({**json.loads(p.read_text()), **json.load(sys.stdin)}))
else:
    print(json.dumps({'inputs': json.loads(p.read_text())}))
""",
            'curl': """import sys, shutil
from pathlib import Path
args = sys.argv[1:]
url = next(a for a in args if a.startswith('https://'))
home = Path.home()
if url.endswith('/server_bundles.lua'):
    sys.stdout.buffer.write((home / 'manifest').read_bytes())
else:
    assert url == (home / 'url').read_text(), url
    with (home / 'downloads').open('a') as f: print(url, file=f)
    shutil.copyfile(home / 'archive', args[args.index('-o') + 1])
"""}
        for name, src in stubs.items():
            p = tools / name
            p.write_text(f'#!{sys.executable}\n' + src)
            p.chmod(0o755)
        self.release()

    def release(self, terms=TERMS, *, build=NEW, omit=None, bad_digest=False):
        entries = files(build, terms)
        if omit:
            del entries[omit]
        buf = io.BytesIO()
        if platform.system() == 'Darwin':
            ext = 'sit'
            with zipfile.ZipFile(buf, 'w') as z:
                for name, data in entries.items():
                    info = zipfile.ZipInfo('intellij-server-2027.1/' + name)
                    info.create_system = 3
                    info.external_attr = (0o100755 if name.startswith('bin/') else 0o100644) << 16
                    z.writestr(info, data)
        else:
            ext = 'tar.gz'
            with tarfile.open(fileobj=buf, mode='w:gz') as tar:
                for name, data in entries.items():
                    info = tarfile.TarInfo('intellij-server-2027.1/' + name)
                    info.mode = 0o755 if name.startswith('bin/') else 0o644
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
        data = buf.getvalue()
        (self.home / 'archive').write_bytes(data)
        checksum = digest(b'not the archive' if bad_digest else data)
        table = '\n'.join(f"  {osname} = {{\n    aarch64 = '{checksum}',\n    x86_64 = '{checksum}',\n  }}," for osname in ('macos', 'linux'))
        (self.home / 'manifest').write_text(f"M.version = '{build}'\nM.sha256 = {{\n{table}\n}}\n")
        suffix = '-aarch64' if platform.machine().lower() in ('arm64','aarch64') else ''
        (self.home / 'url').write_text(f'https://download.jetbrains.com/language-server/intellij-server/{build}/intellij-server-{build}{suffix}.{ext}')

    def cli(self, *args, ok=True):
        run = subprocess.run([sys.executable, '-I', str(UPGRADE), *args], env=self.env,
                             capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode == 0, ok, run.stdout + run.stderr)
        return run.stdout + run.stderr

    def test_check_does_not_download_or_change_options(self):
        msg = self.cli('--check')
        self.assertIn(OLD, msg)
        self.assertIn(NEW, msg)
        self.assertFalse((self.home / 'downloads').exists())
        self.assertEqual(json.loads(self.config.read_text()), self.initial)

    def test_upgrade_switches_both_launchers_and_repeat_is_no_op(self):
        self.cli()
        saved = json.loads(self.config.read_text())
        bin_dir = self.store / NEW / 'intellij-server-2027.1/bin'
        self.assertEqual(saved, dict(server_bin=str(bin_dir), accepted_eula_hash=digest(TERMS)[:16]))
        for name in ('lsp-router','intellij-server'):
            self.assertTrue(os.access(bin_dir / name, os.X_OK))
            self.assertTrue((self.old / 'bin' / name).exists())
        (self.home / 'deny-write').touch()
        self.cli()
        self.assertEqual(len((self.home / 'downloads').read_text().splitlines()), 1)

    def test_new_terms_require_explicit_matching_hash_then_reuse_verified_bundle(self):
        terms = b'Changed agreement\n'
        self.release(terms)
        msg = self.cli(ok=False)
        self.assertIn('EULA.txt', msg)
        self.assertIn(digest(terms)[:16], msg)
        self.cli('--accept-eula', digest(TERMS)[:16], ok=False)
        self.assertEqual(json.loads(self.config.read_text()), self.initial)
        self.cli('--accept-eula', digest(terms)[:16])
        self.assertEqual(json.loads(self.config.read_text())['accepted_eula_hash'], digest(terms)[:16])
        self.assertEqual(len((self.home / 'downloads').read_text().splitlines()), 1)

    def test_bad_checksum_never_installs(self):
        self.release(bad_digest=True)
        self.assertIn('SHA-256', self.cli(ok=False))
        self.assertFalse((self.store / NEW).exists())
        self.assertEqual(json.loads(self.config.read_text()), self.initial)

    def test_incomplete_bundle_never_selected(self):
        self.release(omit='bin/lsp-router')
        self.cli(ok=False)
        self.assertFalse((self.store / NEW).exists())
        self.assertEqual(json.loads(self.config.read_text()), self.initial)

    def test_stale_manifest_cannot_downgrade(self):
        self.release(build='270.9000.0')
        self.cli()
        self.assertFalse((self.home / 'downloads').exists())
        self.assertEqual(json.loads(self.config.read_text()), self.initial)


if __name__ == '__main__':
    unittest.main()
