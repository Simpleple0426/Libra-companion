"""Regression tests for independent config, data and release paths."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class StorageLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backend = self.root / 'backend'
        (self.backend / 'infrastructure').mkdir(parents=True)
        source = Path(__file__).resolve().parents[1] / 'infrastructure' / 'paths.py'
        shutil.copy2(source, self.backend / 'infrastructure' / 'paths.py')
        (self.root / 'config').mkdir()

    def inspect(self, **overrides):
        env = {k: v for k, v in os.environ.items() if not k.startswith('LIBRA_')}
        env.update(overrides, PYTHONDONTWRITEBYTECODE='1')
        return subprocess.run([sys.executable, '-B', '-c',
            'import json; from infrastructure import paths as p; '
            'print(json.dumps({k:str(getattr(p,k)) for k in '
            '("RUNTIME_ROOT","CONFIG_ROOT","BACKUP_ROOT","LOG_ROOT","ENV_PATH")}))'],
            cwd=self.backend, env=env, text=True, capture_output=True, timeout=20)

    def test_default_data_is_outside_backend(self):
        result = self.inspect()
        self.assertEqual(result.returncode, 0, result.stderr)
        paths = json.loads(result.stdout)
        self.assertEqual(Path(paths['RUNTIME_ROOT']), self.root / 'data')
        self.assertEqual(Path(paths['LOG_ROOT']), self.root / 'logs')

    def test_dotenv_loaded_before_paths_and_process_environment_wins(self):
        (self.root / 'config' / '.env').write_text('LIBRA_RUNTIME_DIR=persistent\nLIBRA_BACKUP_DIR=snapshots\n')
        first = self.inspect()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(Path(json.loads(first.stdout)['RUNTIME_ROOT']), self.root / 'persistent')
        second = self.inspect(LIBRA_RUNTIME_DIR=str(self.root / 'production'))
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(Path(json.loads(second.stdout)['RUNTIME_ROOT']), self.root / 'production')

    def test_external_config_survives_release_location_change(self):
        config = self.root / 'server-config'
        config.mkdir()
        data = self.root / 'server-data'
        (config / '.env').write_text('LIBRA_RUNTIME_DIR=' + data.as_posix() + '\n')
        result = self.inspect(LIBRA_CONFIG_DIR=str(config))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(json.loads(result.stdout)['RUNTIME_ROOT']), data)
        next_backend = self.root / 'next-release' / 'backend'
        shutil.copytree(self.backend, next_backend)
        self.backend = next_backend
        result = self.inspect(LIBRA_CONFIG_DIR=str(config))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(json.loads(result.stdout)['RUNTIME_ROOT']), data)

    def test_legacy_and_incomplete_layouts_fail_closed(self):
        old = self.backend / 'libra.db'
        old.touch()
        self.assertNotEqual(self.inspect().returncode, 0)
        old.unlink()
        (self.root / 'data').mkdir()
        (self.root / 'data' / 'libra.db').touch()
        self.assertNotEqual(self.inspect().returncode, 0)


if __name__ == '__main__':
    unittest.main()
