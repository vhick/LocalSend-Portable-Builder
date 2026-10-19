import configparser
import importlib.util
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import zipfile

SRC = Path(__file__).resolve().parents[1] / 'builder'
spec = importlib.util.spec_from_file_location('package', SRC / 'build_portable.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class TestPortableBuilder(unittest.TestCase):
    def test_version_valid(self):
        self.assertEqual(mod.validate_version('1.18.2'), '1.18.2')

    def test_version_invalid(self):
        for v in ('v1.18.2', '../x', 'main', '1.2.3-beta', '1.0.0;echo hi'):
            with self.subTest(v=v), self.assertRaises(ValueError): mod.validate_version(v)

    def test_pinned_digests(self):
        self.assertEqual(mod.PINNED[('1.18.2','x64')], '737aab1829d901e1d798cddd1e5fdc06ba9dfcc9ea50cfe3805e047005d5e71a')
        self.assertEqual(len(mod.PINNED[('1.18.2','arm64')]), 64)

    def test_version_metadata(self):
        parser = configparser.ConfigParser()
        parser.read_string(mod.appinfo('1.18.2'))
        self.assertEqual(parser['Details']['Name'], 'LocalSend Portable')
        self.assertEqual(parser['Details']['Category'], 'Internet')
        self.assertEqual(parser['Control']['Start'], 'LocalSendPortable.exe')
        self.assertEqual(parser['Version']['PackageVersion'], '1.18.2.0')

    def test_archive_path_traversal(self):
        for filename in ('../out.txt','C:/evil.txt', '/absolute.txt','safe/../../bad.txt'):
            with self.subTest(name=filename):
                stream = BytesIO()
                with zipfile.ZipFile(stream, 'w') as z: z.writestr(filename, 'x')
                stream.seek(0)
                with zipfile.ZipFile(stream) as z, self.assertRaises(ValueError):
                    mod.safe_members(z)

    def test_settings_excluded_and_flutter_runtime_kept(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / 'upstream.zip'
            dest = Path(td) / 'App' / 'LocalSend'
            essentials = ('localsend_app.exe','flutter_windows.dll','rust_lib_localsend_app.dll',
                          'data/flutter_assets/AssetManifest.bin')
            with zipfile.ZipFile(archive, 'w') as z:
                for f in essentials: z.writestr(f, 'binary_placeholder')
                z.writestr('settings.json','{"flutter.someKey": true}')
                z.writestr('data/flutter_assets/assets/CHANGELOG.md','sample')
            mod.unpack_official_zip(archive, dest)
            for name in essentials: self.assertTrue((dest / name).is_file())
            self.assertFalse((dest / 'settings.json').exists())
            self.assertTrue((dest / 'data/flutter_assets/assets/CHANGELOG.md').is_file())

    def test_reject_incomplete_build(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / 'upstream.zip'
            with zipfile.ZipFile(z, 'w') as f: f.writestr('localsend_app.exe','bin')
            with self.assertRaises(RuntimeError): mod.unpack_official_zip(z, Path(td) / 'App')

    def test_reject_missing_launcher(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / 'a.zip'
            with zipfile.ZipFile(file,'w') as z: z.writestr('LocalSendPortable/App/AppInfo/appinfo.ini', 'x')
            with self.assertRaises(AssertionError): mod.verify_archive(file)

    def test_launcher_has_hardlink_and_nonntfs_fallback(self):
        source = (SRC / 'LocalSendPortable.cs').read_text(encoding='utf-8')
        for required in ('CreateHardLink', 'Data\\\\Settings\\\\settings.json',
                         'SyncFallback', 'File.Delete(live)', 'process.WaitForExit(1000)',
                         'Data\\Received Files', 'Mutex', 'settings.json'):
            with self.subTest(text=required): self.assertIn(required, source)

    def test_launcher_has_no_system_registrations(self):
        source = (SRC / 'LocalSendPortable.cs').read_text(encoding='utf-8').lower()
        self.assertNotIn('registry.setvalue', source)
        self.assertNotIn('netsh advfirewall', source)
        self.assertNotIn('reg add ', source)

    def test_uses_official_downloads(self):
        source = (SRC / 'build_portable.py').read_text()
        self.assertIn('https://api.github.com/repos/', source)
        self.assertIn('https://raw.githubusercontent.com/localsend/localsend/', source)
        self.assertIn('asset.get("digest")', source)

    def test_builder_workflow_manual(self):
        source = (SRC.parent / '.github/workflows/build-localsend-portable.yml').read_text()
        self.assertIn('workflow_dispatch:', source)
        self.assertIn('retention-days: 3', source)
        self.assertNotIn('schedule:', source)

if __name__ == '__main__':
    unittest.main()
