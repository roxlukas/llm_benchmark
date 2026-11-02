import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import publish_to_site as pub

LLM = {'generated_at': '2026-11-02T00:00:00Z', 'categories': [], 'models': [
    {'name': 'm1', 'overall': 4.0, 'rated': 3, 'categories': {}, 'dimensions': {}}]}
DEC = {'generated_at': '2026-11-02T00:00:00', 'models': [
    {'model': 'd1', 'items': 270, 'accuracy': 0.8, 'tasks': {}}]}


def git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def write(self, obj):
        path = self.tmp / 'f.json'
        path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding='utf-8')
        return path

    def test_valid(self):
        data = pub.validate(self.write(DEC), pub.TARGETS['decisions'])
        self.assertEqual(len(data['models']), 1)

    def test_rejects_nan(self):
        with self.assertRaises(pub.PublishError):
            pub.validate(self.write('{"generated_at": "x", "models": [{"model": "a", "accuracy": NaN}]}'), pub.TARGETS['decisions'])

    def test_rejects_missing_keys(self):
        with self.assertRaises(pub.PublishError):
            pub.validate(self.write({'generated_at': 'x', 'models': [{'model': 'd1'}]}), pub.TARGETS['decisions'])
        with self.assertRaises(pub.PublishError):
            pub.validate(self.write({'models': DEC['models']}), pub.TARGETS['decisions'])

    def test_rejects_empty_and_invalid(self):
        with self.assertRaises(pub.PublishError):
            pub.validate(self.write({'generated_at': 'x', 'models': []}), pub.TARGETS['decisions'])
        with self.assertRaises(pub.PublishError):
            pub.validate(self.write('{oops'), pub.TARGETS['decisions'])

    def test_fewer_models_than_published(self):
        path = self.write(DEC)
        with self.assertRaises(pub.PublishError):
            pub.validate(path, pub.TARGETS['decisions'], published_models=2)
        pub.validate(path, pub.TARGETS['decisions'], published_models=2, allow_fewer=True)
        pub.validate(path, pub.TARGETS['decisions'], published_models=1)


class PublishTests(unittest.TestCase):
    """Real git (bare origin + site checkout), gh stubbed."""

    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.origin, self.site, self.here = root / 'origin.git', root / 'site', root / 'bench'
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(self.origin)], check=True)
        subprocess.run(['git', 'clone', '-q', str(self.origin), str(self.site)], check=True, capture_output=True)
        for k, v in (('user.name', 't'), ('user.email', 't@t'), ('commit.gpgsign', 'false')):
            git(self.site, 'config', k, v)
        (self.site / 'README').write_text('x')
        git(self.site, 'add', '.')
        git(self.site, 'commit', '-q', '-m', 'init')
        git(self.site, 'push', '-q', 'origin', 'HEAD:main')
        self.here.mkdir()
        self.put('results.json', LLM)
        self.put('decision_results.json', DEC)
        real = pub.run

        def fake(cmd, cwd=None, check=True):
            return 'https://example.test/pr/1' if cmd[0] == 'gh' else real(cmd, cwd=cwd, check=check)
        patches = [mock.patch.object(pub, 'HERE', self.here), mock.patch.object(pub, 'run', fake)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def put(self, name, obj):
        (self.here / name).write_text(json.dumps(obj), encoding='utf-8')

    def args(self, **kw):
        base = dict(site_dir=str(self.site), only=None, refresh=False, dry_run=False, allow_fewer_models=False)
        base.update(kw)
        return mock.Mock(**base)

    def pushed_files(self):
        branch = git(self.origin, 'branch', '--list', 'benchmark-results-*').split()[-1]
        return branch, git(self.origin, 'ls-tree', '-r', '--name-only', branch).split()

    def test_publishes_branch_and_pr(self):
        self.assertEqual(pub.publish(self.args()), 'https://example.test/pr/1')
        _, files = self.pushed_files()
        self.assertIn('wwwroot/llm-benchmark/results.json', files)
        self.assertIn('wwwroot/llm-benchmark/decision_results.json', files)
        self.assertNotIn('benchmark-results', git(self.site, 'worktree', 'list'))   # temp worktree removed
        self.assertEqual(git(self.site, 'status', '--short'), '')                    # working copy untouched

    def test_only_one_file(self):
        pub.publish(self.args(only='decisions'))
        _, files = self.pushed_files()
        self.assertIn('wwwroot/llm-benchmark/decision_results.json', files)
        self.assertNotIn('wwwroot/llm-benchmark/results.json', files)

    def test_dry_run_pushes_nothing(self):
        self.assertIsNone(pub.publish(self.args(dry_run=True)))
        self.assertEqual(git(self.origin, 'branch', '--list', 'benchmark-results-*'), '')

    def test_unchanged_files_publish_nothing(self):
        pub.publish(self.args())
        branch, _ = self.pushed_files()
        git(self.origin, 'update-ref', 'refs/heads/main', branch)   # "merge" the PR
        self.assertIsNone(pub.publish(self.args()))

    def test_refuses_fewer_models_than_published(self):
        self.put('decision_results.json', dict(DEC, models=DEC['models'] * 2))
        pub.publish(self.args(only='decisions'))
        branch, _ = self.pushed_files()
        git(self.origin, 'update-ref', 'refs/heads/main', branch)
        self.put('decision_results.json', DEC)                       # back to 1 model
        with self.assertRaises(pub.PublishError):
            pub.publish(self.args(only='decisions'))
        self.assertTrue(pub.publish(self.args(only='decisions', allow_fewer_models=True)))


if __name__ == '__main__':
    unittest.main()
