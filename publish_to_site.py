"""Publish benchmark results to the aitransformation.pl site repository as a pull request.

Copies results.json (LLM browser) and/or decision_results.json (decision-model browser) into
wwwroot/llm-benchmark/ of the site checkout, on a new branch cut from origin/main in a temporary
git worktree (your working copy of the site is not touched), pushes it and opens a PR with gh.

  python publish_to_site.py --site-dir C:\\htdocs\\aitransformation.pl            # both files
  python publish_to_site.py --site-dir ... --only decisions --refresh            # regenerate first
  python publish_to_site.py --site-dir ... --dry-run                             # validate and show the diff only

--site-dir can also come from the SITE_REPO environment variable (or SITE_REPO in .env).
Files are checked before publishing: valid JSON, required fields, and no fewer models than the
published copy (override with --allow-fewer-models).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

try:  # SITE_REPO may live in .env next to the other settings
    from dotenv import load_dotenv
    load_dotenv(HERE / '.env')
except ImportError:
    pass
TARGET_DIR = Path('wwwroot') / 'llm-benchmark'

# name on the site -> (producer command, required top-level keys, required keys of every model)
TARGETS = {
    'llm': {
        'file': 'results.json',
        'refresh': [sys.executable, 'export_json.py'],
        'top': ('generated_at', 'categories', 'models'),
        'model': ('name', 'overall', 'rated', 'categories', 'dimensions'),
        'label': 'LLM',
    },
    'decisions': {
        'file': 'decision_results.json',
        'refresh': [sys.executable, 'decision_benchmark.py', '--report'],
        'top': ('generated_at', 'models'),
        'model': ('model', 'items', 'accuracy', 'tasks'),
        'label': 'decision models',
    },
}


class PublishError(Exception):
    pass


def run(cmd, cwd=None, check=True):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8')
    if check and result.returncode != 0:
        raise PublishError(f'{" ".join(map(str, cmd))} failed:\n{result.stderr.strip() or result.stdout.strip()}')
    return result.stdout.strip()


def validate(path, spec, published_models=None, allow_fewer=False):
    """Return the parsed file or raise PublishError."""
    try:
        text = path.read_text(encoding='utf-8')
    except OSError as e:
        raise PublishError(f'{path}: {e}')
    if 'NaN' in text or 'Infinity' in text:
        raise PublishError(f'{path.name}: contains NaN/Infinity, which browsers cannot parse as JSON')
    try:
        data = json.loads(text)
    except ValueError as e:
        raise PublishError(f'{path.name}: invalid JSON ({e})')
    missing = [k for k in spec['top'] if k not in data]
    if missing:
        raise PublishError(f'{path.name}: missing top-level keys {missing}')
    models = data['models']
    if not isinstance(models, list) or not models:
        raise PublishError(f'{path.name}: no models')
    for i, m in enumerate(models):
        absent = [k for k in spec['model'] if k not in m]
        if absent:
            raise PublishError(f'{path.name}: model #{i} ({m.get("name") or m.get("model")}) lacks {absent}')
    if published_models is not None and len(models) < published_models and not allow_fewer:
        raise PublishError(f'{path.name}: {len(models)} models, the published copy has {published_models} '
                           f'(use --allow-fewer-models if that is intended)')
    return data


def published_model_count(site_dir, filename):
    """Models in the copy on origin/main (None if the file is not published yet)."""
    rel = (TARGET_DIR / filename).as_posix()
    result = subprocess.run(['git', 'show', f'origin/main:{rel}'], cwd=site_dir, capture_output=True, text=True, encoding='utf-8')
    if result.returncode != 0:
        return None
    try:
        return len(json.loads(result.stdout)['models'])
    except (ValueError, KeyError):
        return None


def publish(args):
    site_dir = Path(args.site_dir).resolve()
    if not (site_dir / '.git').exists():
        raise PublishError(f'{site_dir} is not a git checkout of the site repository')
    selected = [args.only] if args.only else list(TARGETS)

    if args.refresh:
        for name in selected:
            print(f'Regenerating {TARGETS[name]["file"]} ...')
            run(TARGETS[name]['refresh'], cwd=HERE)

    run(['git', 'fetch', '-q', 'origin', 'main'], cwd=site_dir)
    sources = {}
    for name in selected:
        spec = TARGETS[name]
        path = HERE / spec['file']
        data = validate(path, spec, published_model_count(site_dir, spec['file']), args.allow_fewer_models)
        sources[name] = (path, data)
        print(f'{spec["file"]}: {len(data["models"])} models, generated {data["generated_at"]}')

    branch = f'benchmark-results-{time.strftime("%Y%m%d-%H%M%S")}'
    work = Path(tempfile.mkdtemp(prefix='site-publish-'))
    try:
        run(['git', 'worktree', 'add', '-q', '-b', branch, str(work), 'origin/main'], cwd=site_dir)
        (work / TARGET_DIR).mkdir(parents=True, exist_ok=True)
        for name, (path, _) in sources.items():
            shutil.copyfile(path, work / TARGET_DIR / path.name)
        run(['git', 'add', str(TARGET_DIR)], cwd=work)
        stat = run(['git', 'diff', '--cached', '--stat'], cwd=work)
        if not stat:
            print('Nothing changed compared to origin/main, nothing to publish.')
            return None
        print(stat)
        if args.dry_run:
            print('Dry run: no commit, push or PR.')
            return None
        labels = ' and '.join(TARGETS[n]['label'] for n in sources)
        message = f'Update benchmark results ({labels})'
        run(['git', 'commit', '-q', '-m', message], cwd=work)
        run(['git', 'push', '-q', '-u', 'origin', branch], cwd=work)
        body = ('Automated data update from llm_benchmark (publish_to_site.py).\n\n'
                + '\n'.join(f'- {p.name}: {len(d["models"])} models, generated {d["generated_at"]}' for p, d in sources.values()))
        url = run(['gh', 'pr', 'create', '--base', 'main', '--head', branch, '--title', message, '--body', body], cwd=work)
        print(f'Opened {url}')
        return url
    finally:
        run(['git', 'worktree', 'remove', '--force', str(work)], cwd=site_dir, check=False)
        run(['git', 'worktree', 'prune'], cwd=site_dir, check=False)
        run(['git', 'branch', '-D', branch], cwd=site_dir, check=False)   # the PR branch lives on origin
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--site-dir', default=os.environ.get('SITE_REPO'), help='Checkout of aitransformation.pl (default: $SITE_REPO)')
    p.add_argument('--only', choices=sorted(TARGETS), help='Publish just one of the files (default: both)')
    p.add_argument('--refresh', action='store_true', help='Regenerate the JSON from the database first')
    p.add_argument('--dry-run', action='store_true', help='Validate and show the diff, do not commit, push or open a PR')
    p.add_argument('--allow-fewer-models', action='store_true', help='Publish even if the file has fewer models than the published copy')
    args = p.parse_args(argv)
    if not args.site_dir:
        p.error('--site-dir or the SITE_REPO environment variable is required')
    try:
        publish(args)
    except PublishError as e:
        print(f'Error: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
