"""Export benchmark ratings to a single JSON file for the static browser (browse.html).

Scores come from one judge (evaluation_results.evaluator). Model sizes come from Ollama /api/tags;
models no longer installed get an estimate from model_metadata (parameters x quantization bits).
"""
import argparse
import json
import re
import statistics
from datetime import datetime, timezone

import mysql.connector
import requests
from db_env import add_db_args

DIMENSIONS = ['accuracy', 'completeness', 'clarity', 'domain_expertise', 'helpfulness']

# Approximate bits per weight of common GGUF quantizations (used only when the file size is unknown)
QUANT_BITS = {
    'F32': 32, 'F16': 16, 'BF16': 16, 'Q8_0': 8.5, 'Q6_K': 6.6, 'Q5_K_M': 5.7, 'Q5_K_S': 5.5, 'Q5_0': 5.5,
    'Q4_K_M': 4.9, 'Q4_K_S': 4.6, 'Q4_0': 4.5, 'Q4_1': 5.0, 'Q3_K_M': 3.9, 'Q3_K_S': 3.5, 'Q2_K': 2.8,
    'MXFP4': 4.3, 'IQ4_XS': 4.3, 'IQ3_M': 3.7, 'IQ2_M': 2.7,
}
KV_OVERHEAD_GB = 1.5  # runtime buffers + a modest KV cache at default context


def parse_params_b(text):
    """'20.9B' / '751M' / '7B' -> billions of parameters, or None."""
    if not text:
        return None
    m = re.match(r'\s*([\d.]+)\s*([KMBT])', str(text).strip(), re.I)
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2).upper()
    return value * {'K': 1e-6, 'M': 1e-3, 'B': 1.0, 'T': 1e3}[unit]


def estimate_size_bytes(params_b, quant):
    if not params_b:
        return None
    bits = QUANT_BITS.get((quant or '').upper(), 4.9)
    return int(params_b * 1e9 * bits / 8)


def median(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 1) if values else None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    add_db_args(p)
    p.add_argument('--ollama', default='http://192.168.1.250:11434')
    p.add_argument('--evaluator', default='anthropic/claude-haiku-5-5')
    p.add_argument('--output', default='results.json')
    args = p.parse_args()

    conn = mysql.connector.connect(host=args.host, port=args.port, user=args.user,
                                   password=args.password, database=args.database)
    cur = conn.cursor(dictionary=True)

    installed = {}
    try:
        for m in requests.get(f'{args.ollama}/api/tags', timeout=15).json().get('models', []):
            installed[m['name']] = m
    except requests.exceptions.RequestException as e:
        print(f'Ollama not reachable ({e}); sizes will be estimated')

    cur.execute('SELECT model_name, parameters, quantization, context_length, architecture FROM model_metadata')
    metadata = {r['model_name']: r for r in cur.fetchall()}

    cur.execute(
        """
        SELECT br.id, br.model, br.prompt_id, br.success, br.eval_count, br.eval_duration, p.category,
               er.overall_score, er.accuracy_score, er.completeness_score, er.clarity_score,
               er.domain_expertise_score, er.helpfulness_score
        FROM benchmark_results br
        JOIN prompts p ON p.id = br.prompt_id
        LEFT JOIN evaluation_results er ON er.benchmark_result_id = br.id AND er.evaluator = %s
        """, (args.evaluator,))
    rows = cur.fetchall()
    cur.execute('SELECT category, COUNT(*) AS n FROM prompts GROUP BY category ORDER BY category')
    categories = cur.fetchall()
    conn.close()

    per_model = {}
    for r in rows:
        m = per_model.setdefault(r['model'], {'failed': 0, 'scores': [], 'cat': {}, 'dim': {d: [] for d in DIMENSIONS}, 'tps': []})
        if not r['success']:
            m['failed'] += 1
            continue
        if r['eval_count'] and r['eval_duration']:
            m['tps'].append(r['eval_count'] / (r['eval_duration'] / 1e9))
        if r['overall_score'] is None:
            continue
        m['scores'].append(r['overall_score'])
        m['cat'].setdefault(r['category'], []).append(r['overall_score'])
        for d in DIMENSIONS:
            if r[f'{d}_score'] is not None:
                m['dim'][d].append(r[f'{d}_score'])

    models = []
    for name, m in sorted(per_model.items()):
        if not m['scores']:
            continue
        meta = metadata.get(name, {})
        if (meta.get('architecture') or '').lower() in ('clip', 'mmproj'):
            # a vision projector's row (old model_metadata.py bug), not the language model: don't size from it
            meta = {k: v for k, v in meta.items() if k not in ('architecture', 'parameters')}
        tag = installed.get(name)
        details = (tag or {}).get('details', {})
        params_b = parse_params_b(details.get('parameter_size')) or parse_params_b(meta.get('parameters'))
        quant = details.get('quantization_level') or meta.get('quantization')
        if tag:
            size_bytes, estimated = tag['size'], False
        else:
            size_bytes, estimated = estimate_size_bytes(params_b, quant), True
        models.append({
            'name': name,
            'family': details.get('family') or meta.get('architecture'),
            'params_b': round(params_b, 2) if params_b else None,
            'quantization': quant,
            'context_length': details.get('context_length') or meta.get('context_length'),
            'size_bytes': size_bytes,
            'size_estimated': estimated,
            'installed': bool(tag),
            'min_memory_gb': round(size_bytes / 1e9 + KV_OVERHEAD_GB, 1) if size_bytes else None,
            'overall': round(sum(m['scores']) / len(m['scores']), 3),
            'rated': len(m['scores']),
            'failed': m['failed'],
            'categories': {c: {'avg': round(sum(v) / len(v), 3), 'n': len(v)} for c, v in sorted(m['cat'].items())},
            'dimensions': {d: round(sum(v) / len(v), 3) for d, v in m['dim'].items() if v},
            'tokens_per_second': median(m['tps']),
        })

    out = {
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'evaluator': args.evaluator,
        'dimensions': DIMENSIONS,
        'categories': [{'name': c['category'], 'prompts': c['n']} for c in categories],
        'models': models,
    }
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=float)  # MySQL AVG/DECIMAL columns come back as Decimal
    unknown = [m['name'] for m in models if not m['size_bytes']]
    print(f"Wrote {args.output}: {len(models)} models, {len(categories)} categories; "
          f"{sum(m['size_estimated'] for m in models)} sizes estimated; no size: {unknown}")


if __name__ == '__main__':
    main()
