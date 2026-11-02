"""Benchmark for decision models (Ollama capability "decision", endpoint /v1/systemone).

Runs every item of decision_data/*.json as a single typed question and stores the answer,
probabilities and wall-clock decision time in decision_results. --report prints per-model metrics:
accuracy, macro-F1, calibration (ECE, Brier, log loss), latency, injection robustness, PL/EN split
and option-order consistency.
"""
import argparse
import glob
import json
import math
import os
import statistics
import time
import uuid
from collections import defaultdict

import mysql.connector
import requests
from db_env import add_db_args

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'decision_data')
ECE_BINS = 10
EPS = 1e-6  # log loss clip

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS decision_runs (
        run_id VARCHAR(32) NOT NULL,
        model VARCHAR(100) NOT NULL,
        ollama_version VARCHAR(20),
        load_ms DOUBLE,
        size_vram BIGINT,
        order_check TINYINT DEFAULT 0,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        finished_at TIMESTAMP NULL,
        PRIMARY KEY (run_id, model)
    )""",
    """CREATE TABLE IF NOT EXISTS decision_results (
        id INT AUTO_INCREMENT PRIMARY KEY,
        run_id VARCHAR(32) NOT NULL,
        model VARCHAR(100) NOT NULL,
        task_id VARCHAR(64) NOT NULL,
        item_id VARCHAR(80) NOT NULL,
        question_type VARCHAR(10) NOT NULL,
        lang VARCHAR(5),
        difficulty VARCHAR(10),
        variant VARCHAR(20),
        option_order VARCHAR(10) DEFAULT 'original',
        expected VARCHAR(64),
        predicted VARCHAR(64),
        correct TINYINT,
        p_expected DOUBLE,
        confidence DOUBLE,
        score_value DOUBLE,
        probabilities JSON,
        latency_ms DOUBLE,
        input_tokens INT,
        error TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX (run_id, model),
        INDEX (task_id)
    )""",
]


def load_tasks(data_dir, only=None):
    tasks = []
    for path in sorted(glob.glob(os.path.join(data_dir, '*.json'))):
        with open(path, encoding='utf-8') as f:
            task = json.load(f)
        if only and task['id'] not in only:
            continue
        tasks.append(task)
    return tasks


def decision_models(ollama):
    names = [m['name'] for m in requests.get(f'{ollama}/api/tags', timeout=30).json()['models']]
    found = []
    for name in sorted(names):
        show = requests.post(f'{ollama}/api/show', json={'model': name}, timeout=30).json()
        if 'decision' in (show.get('capabilities') or []):
            found.append(name)
    return found


def build_question(task, reverse=False):
    question = {'type': task['type'], 'instructions': task['instructions']}
    if task['type'] == 'choice':
        items = list(task['criteria'].items())
        question['criteria'] = dict(reversed(items) if reverse else items)
    elif task['type'] == 'score':
        question['criteria'] = task['criteria']  # an ordered scale is never reversed
    return question


def parse_answer(task, item, answer):
    """-> (expected, predicted, correct, p_expected, confidence, score_value, probabilities)"""
    qtype = task['type']
    if qtype == 'choice':
        probs = answer.get('probabilities') or {}
        expected, predicted = item['answer'], answer.get('choice')
        return (expected, predicted, int(predicted == expected), probs.get(expected),
                answer.get('confidence'), None, probs)
    if qtype == 'noul':
        p_true = answer.get('noul')
        expected = 'true' if item['answer'] else 'false'
        predicted = 'true' if p_true >= 0.5 else 'false'
        p_expected = p_true if item['answer'] else 1 - p_true
        return (expected, predicted, int(predicted == expected), p_expected, None, None,
                {'true': p_true, 'false': 1 - p_true})
    # score: argmax level is the prediction, 'score' is the expected value on the 0..n-1 scale
    probs = answer.get('probabilities') or {}
    expected = str(item['answer'])
    predicted = max(probs, key=probs.get) if probs else None
    return (expected, predicted, int(predicted == expected), probs.get(expected),
            answer.get('confidence'), answer.get('score'), probs)


def decide(systemone, model, state, question):
    body = {'model': model, 'state': state, 'questions': {'q': question}}
    start = time.perf_counter()
    response = requests.post(f'{systemone}/v1/systemone', json=body, timeout=600)
    latency_ms = (time.perf_counter() - start) * 1000
    data = response.json()
    if response.status_code != 200 or 'answers' not in data:
        raise RuntimeError(data.get('error') or f'HTTP {response.status_code}')
    return data['answers']['q'], latency_ms, (data.get('usage') or {}).get('input_tokens')


def busy_models(ollama, model):
    """Other models loaded in Ollama; they share the GPU and skew decision time."""
    loaded = requests.get(f'{ollama}/api/ps', timeout=30).json().get('models') or []
    return [m['name'] for m in loaded if m['name'] != model]


def run(args, conn):
    tasks = load_tasks(args.data_dir, args.tasks)
    if not tasks:
        raise SystemExit(f'No task files in {args.data_dir}')
    models = [m.strip() for m in args.models.split(',')] if args.models else decision_models(args.ollama)
    version = requests.get(f'{args.ollama}/api/version', timeout=30).json().get('version')
    run_id = time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:4]
    n_items = sum(len(t['items'][:args.limit] if args.limit else t['items']) for t in tasks)
    print(f'Run {run_id}: {len(models)} models x {n_items} items from {len(tasks)} tasks (Ollama {version})')

    cur = conn.cursor()
    for model in models:
        others = busy_models(args.ollama, model)
        if others:
            print(f'Warning: other models loaded ({", ".join(others)}); decision times will be inflated')

        # Warm-up: the first call loads the model, so it is reported as load time, not decision time
        task = tasks[0]
        _, load_ms, _ = decide(args.systemone_url, model, task['items'][0]['state'], build_question(task))
        loaded = requests.get(f'{args.ollama}/api/ps', timeout=30).json().get('models') or []
        size_vram = next((m.get('size_vram') for m in loaded if m['name'] == model), None)
        cur.execute('INSERT INTO decision_runs (run_id, model, ollama_version, load_ms, size_vram, order_check) '
                    'VALUES (%s, %s, %s, %s, %s, %s)',
                    (run_id, model, version, load_ms, size_vram, int(args.order_check)))
        conn.commit()
        print(f'\n== {model}: load {load_ms:.0f} ms, VRAM {size_vram / 2**30 if size_vram else 0:.2f} GiB')

        for task in tasks:
            orders = ['original', 'reversed'] if args.order_check and task['type'] == 'choice' else ['original']
            items = task['items'][:args.limit] if args.limit else task['items']
            correct = 0
            for order in orders:
                question = build_question(task, reverse=order == 'reversed')
                for item in items:
                    row = dict(expected=None, predicted=None, correct=None, p_expected=None, confidence=None,
                               score_value=None, probabilities=None, latency_ms=None, input_tokens=None, error=None)
                    try:
                        answer, row['latency_ms'], row['input_tokens'] = decide(args.systemone_url, model, item['state'], question)
                        (row['expected'], row['predicted'], row['correct'], row['p_expected'], row['confidence'],
                         row['score_value'], probs) = parse_answer(task, item, answer)
                        row['probabilities'] = json.dumps(probs)
                    except Exception as e:  # keep going; failures count against accuracy in the report
                        row['error'] = str(e)[:1000]
                    if order == 'original':
                        correct += row['correct'] or 0
                    cur.execute(
                        'INSERT INTO decision_results (run_id, model, task_id, item_id, question_type, lang, difficulty, '
                        'variant, option_order, expected, predicted, correct, p_expected, confidence, score_value, '
                        'probabilities, latency_ms, input_tokens, error) '
                        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                        (run_id, model, task['id'], item['id'], task['type'], item.get('lang'), item.get('difficulty'),
                         item.get('variant', 'standard'), order, row['expected'], row['predicted'], row['correct'],
                         row['p_expected'], row['confidence'], row['score_value'], row['probabilities'],
                         row['latency_ms'], row['input_tokens'], row['error']))
                conn.commit()
            print(f'  {task["id"]:<28} {correct}/{len(items)}')

        cur.execute('UPDATE decision_runs SET finished_at = NOW() WHERE run_id = %s AND model = %s', (run_id, model))
        conn.commit()
    return run_id


# ---------- report ----------

def macro_f1(pairs):
    labels = {e for e, _ in pairs}
    scores = []
    for label in labels:
        tp = sum(1 for e, p in pairs if e == label and p == label)
        fp = sum(1 for e, p in pairs if e != label and p == label)
        fn = sum(1 for e, p in pairs if e == label and p != label)
        scores.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
    return statistics.mean(scores) if scores else None


def ece(rows):
    """Expected calibration error of the top probability vs. being right."""
    bins = defaultdict(list)
    for r in rows:
        top = max(r['probs'].values())
        bins[min(int(top * ECE_BINS), ECE_BINS - 1)].append((top, r['correct']))
    n = len(rows)
    return sum(len(b) / n * abs(statistics.mean(c for c, _ in b) - statistics.mean(k for _, k in b))
               for b in bins.values()) if n else None


def brier(rows):
    """Multi-class Brier score: sum over classes of (p - y)^2, averaged over items."""
    return statistics.mean(sum((p - (k == r['expected'])) ** 2 for k, p in r['probs'].items()) for r in rows) if rows else None


def short(model):
    """hf.co/Remek/basal-2.0-mini-GGUF:Q8_0 -> basal-2.0-mini:Q8_0 (report columns only)"""
    return model.split('/')[-1].replace('-GGUF', '')


def model_info(model):
    """Runtime and quantization shown by decisions.html. hf.co/... names carry the quantization after ':';
    '...:bf16-eager' models are served by basal-serve --mode eager, everything else by Ollama."""
    tag = model.split(':', 1)[1] if ':' in model else ''
    if tag.endswith('-eager'):
        return {'runtime': 'basal-serve', 'quantization': tag[:-len('-eager')]}
    return {'runtime': 'ollama', 'quantization': tag if model.startswith('hf.co/') and tag else None}


def pct(x):
    return f'{100 * x:5.1f}' if x is not None else '    -'


def load_rows(conn, run_id=None):
    cur = conn.cursor(dictionary=True)
    if run_id:
        cur.execute('SELECT run_id, model, load_ms, size_vram FROM decision_runs WHERE run_id = %s', (run_id,))
    else:  # latest finished run of every model
        cur.execute('SELECT r.run_id, r.model, r.load_ms, r.size_vram FROM decision_runs r '
                    'JOIN (SELECT model, MAX(run_id) AS run_id FROM decision_runs WHERE finished_at IS NOT NULL '
                    'GROUP BY model) l ON l.model = r.model AND l.run_id = r.run_id')
    runs = cur.fetchall()
    rows = defaultdict(list)
    for run in runs:
        cur.execute('SELECT * FROM decision_results WHERE run_id = %s AND model = %s', (run['run_id'], run['model']))
        for r in cur.fetchall():
            r['probs'] = {k: float(v) for k, v in json.loads(r['probabilities']).items()} if r['probabilities'] else {}
            rows[run['model']].append(r)
    return runs, rows


def summarize(run, rows):
    orig = [r for r in rows if r['option_order'] == 'original']
    ok = [r for r in orig if r['error'] is None and r['probs']]
    acc = lambda rs: statistics.mean(r['correct'] or 0 for r in rs) if rs else None
    lat = sorted(r['latency_ms'] for r in ok)
    by_task = {}
    for task_id in sorted({r['task_id'] for r in orig}):
        t = [r for r in orig if r['task_id'] == task_id]
        tok = [r for r in t if r['error'] is None]
        entry = {'n': len(t), 'accuracy': acc(t), 'macro_f1': macro_f1([(r['expected'], r['predicted']) for r in tok])}
        if t[0]['question_type'] == 'score':
            diffs = [abs(int(r['predicted']) - int(r['expected'])) for r in tok]
            entry['mae'] = statistics.mean(diffs) if diffs else None
            entry['within_1'] = statistics.mean(d <= 1 for d in diffs) if diffs else None
        by_task[task_id] = entry
    reversed_rows = {(r['task_id'], r['item_id']): r['predicted'] for r in rows if r['option_order'] == 'reversed'}
    pairs = [(r['predicted'], reversed_rows[(r['task_id'], r['item_id'])]) for r in ok
             if (r['task_id'], r['item_id']) in reversed_rows]
    return {
        'model': run['model'], 'display_name': short(run['model']), **model_info(run['model']),
        'run_id': run['run_id'], 'items': len(orig), 'errors': len(orig) - len(ok),
        'accuracy': acc(orig),
        'macro_f1': statistics.mean(v['macro_f1'] for v in by_task.values() if v['macro_f1'] is not None) if by_task else None,
        'ece': ece(ok), 'brier': brier(ok),
        'log_loss': statistics.mean(-math.log(max(r['p_expected'] or 0, EPS)) for r in ok) if ok else None,
        'latency_ms_median': statistics.median(lat) if lat else None,
        'latency_ms_p95': lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else None,
        'load_ms': run['load_ms'], 'size_vram': run['size_vram'],
        'accuracy_standard': acc([r for r in orig if r['variant'] != 'injection']),
        'accuracy_injection': acc([r for r in orig if r['variant'] == 'injection']),
        'accuracy_pl': acc([r for r in orig if r['lang'] == 'pl']),
        'accuracy_en': acc([r for r in orig if r['lang'] == 'en']),
        'accuracy_hard': acc([r for r in orig if r['difficulty'] == 'hard']),
        'order_consistency': statistics.mean(a == b for a, b in pairs) if pairs else None,
        'tasks': by_task,
    }


def tasks_meta(data_dir, task_ids):
    """Display name and question type of every task that has results (names live in decision_data/<id>.json)."""
    by_id = {t['id']: t for t in load_tasks(data_dir)}
    return {t: {'name': by_id[t]['name'], 'type': by_id[t]['type']} if t in by_id else {'name': t, 'type': None}
            for t in task_ids}


def report(conn, run_id, output, data_dir=DATA_DIR):
    runs, rows = load_rows(conn, run_id)
    if not runs:
        raise SystemExit('No finished decision runs in the database')
    summaries = sorted((summarize(run, rows[run['model']]) for run in runs), key=lambda s: -(s['accuracy'] or 0))
    print(f'\n{"model":<32}{"acc%":>6}{"F1%":>6}{"ECE":>7}{"Brier":>7}{"med ms":>8}{"p95 ms":>8}'
          f'{"inj%":>6}{"PL%":>6}{"EN%":>6}{"hard%":>6}{"order%":>7}{"err":>5}')
    for s in summaries:
        print(f'{short(s["model"]):<32}{pct(s["accuracy"]):>6}{pct(s["macro_f1"]):>6}{s["ece"] or 0:7.3f}{s["brier"] or 0:7.3f}'
              f'{s["latency_ms_median"] or 0:8.0f}{s["latency_ms_p95"] or 0:8.0f}{pct(s["accuracy_injection"]):>6}'
              f'{pct(s["accuracy_pl"]):>6}{pct(s["accuracy_en"]):>6}{pct(s["accuracy_hard"]):>6}'
              f'{pct(s["order_consistency"]):>7}{s["errors"]:>5}')
    tasks = sorted({t for s in summaries for t in s['tasks']})
    print(f'\n{"accuracy % per task":<28}' + ''.join(f'{short(s["model"])[:15]:>16}' for s in summaries))
    for t in tasks:
        print(f'{t:<28}' + ''.join(f'{pct(s["tasks"].get(t, {}).get("accuracy")):>16}' for s in summaries))
    with open(output, 'w', encoding='utf-8') as f:
        json.dump({'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'tasks': tasks_meta(data_dir, tasks),
                   'models': summaries}, f, ensure_ascii=False, indent=1, default=float)
    print(f'\nWrote {output}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_db_args(p)
    p.add_argument('--ollama', default='http://192.168.1.250:11434')
    p.add_argument('--systemone-url', help='Server answering /v1/systemone, e.g. basal-serve in front of Ollama '
                   '(default: --ollama); load time and VRAM are still read from --ollama')
    p.add_argument('--models', help='Comma-separated models (default: every model with the decision capability)')
    p.add_argument('--tasks', help='Comma-separated task ids (default: all files in decision_data)')
    p.add_argument('--data-dir', default=DATA_DIR)
    p.add_argument('--limit', type=int, help='Items per task (for a quick test)')
    p.add_argument('--order-check', action='store_true',
                   help='Run choice tasks a second time with options in reverse order to measure consistency')
    p.add_argument('--report', action='store_true', help='Only print metrics of the latest run of every model')
    p.add_argument('--run-id', help='Report this run instead of the latest per model')
    p.add_argument('--output', default='decision_results.json', help='Summary JSON written by the report')
    args = p.parse_args()
    args.systemone_url = (args.systemone_url or args.ollama).rstrip('/')
    if args.tasks:
        args.tasks = {t.strip() for t in args.tasks.split(',')}

    conn = mysql.connector.connect(host=args.host, port=args.port, user=args.user, password=args.password,
                                   database=args.database, charset='utf8mb4')
    cur = conn.cursor()
    for statement in SCHEMA:
        cur.execute(statement)
    conn.commit()
    try:
        run_id = None if args.report else run(args, conn)
        report(conn, args.run_id or run_id, args.output, args.data_dir)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
