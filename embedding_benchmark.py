"""Embedding model retrieval benchmark (Ollama embeddings + Qdrant).

Corpus: LibreOffice Help in English and Polish (embedding_corpus.py), ~3.1k chunks per
language. Queries: 500 per language (embedding_queries.py), each with one gold chunk.
For every model and language the corpus is embedded into its own Qdrant collection
(embbench_<lang>_<model>), the queries are embedded and searched (top 10, cosine).

Metrics: chunk level Hit@1/5/10, MRR@10, nDCG@10 (gold chunk) and page level Hit@1/5/10,
MRR@10 (any chunk of the gold page counts). `bm25` is a lexical baseline computed in
Python (no stemming), the reference point a model has to beat.

    python embedding_benchmark.py                                  # all models, both languages
    python embedding_benchmark.py --models bge-m3,embeddinggemma-2:270m --langs pl
    python embedding_benchmark.py --reindex                        # re-embed even if collection exists
"""
import argparse
import hashlib
import json
import math
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import requests
from qdrant_client import QdrantClient, models as qm

ROOT = Path(__file__).parent
DATA = ROOT / 'embedding_data'
RESULTS = ROOT / 'embedding_results.json'
RUNS = ROOT / 'embedding_runs'
TOP_K = 10

QWEN_INSTR = ('Instruct: Given a user question about LibreOffice, retrieve the help passage that answers it\n'
              'Query: ')
GEMMA = {'query': 'task: search result | query: ', 'doc': 'title: none | text: '}
NOMIC = {'query': 'search_query: ', 'doc': 'search_document: '}

# name -> query/doc prefixes recommended by each model card
MODELS = {
    'embeddinggemma-2:270m': GEMMA,
    'embeddinggemma-2:440m': GEMMA,
    'embeddinggemma-2:570m': GEMMA,
    'embeddinggemma-2:740m': GEMMA,
    'embeddinggemma:latest': GEMMA,
    'qwen3-embedding:0.6b': {'query': QWEN_INSTR, 'doc': ''},
    'qwen3-embedding:4b': {'query': QWEN_INSTR, 'doc': ''},
    'qwen3-embedding:8b': {'query': QWEN_INSTR, 'doc': ''},
    'bge-m3:latest': {'query': '', 'doc': ''},
    'snowflake-arctic-embed2:latest': {'query': 'query: ', 'doc': ''},
    'granite-embedding:278m': {'query': '', 'doc': ''},
    'nomic-embed-text-v2-moe:latest': NOMIC,
    'nomic-embed-text:latest': NOMIC,
    'paraphrase-multilingual:latest': {'query': '', 'doc': ''},
    'mxbai-embed-large:latest': {'query': 'Represent this sentence for searching relevant passages: ', 'doc': ''},
}


def slug(name):
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def load(lang):
    corpus = [json.loads(x) for x in (DATA / lang / 'corpus.jsonl').open(encoding='utf-8')]
    queries = [json.loads(x) for x in (DATA / lang / 'queries.jsonl').open(encoding='utf-8')]
    h = hashlib.sha1(''.join(c['id'] + c['text'] for c in corpus).encode()).hexdigest()[:12]
    return corpus, queries, h


def embed(url, model, texts, batch, keep_alive='10m'):
    out = []
    for i in range(0, len(texts), batch):
        for attempt in range(3):
            try:
                r = requests.post(f'{url}/api/embed', json={
                    'model': model, 'input': texts[i:i + batch], 'truncate': True, 'keep_alive': keep_alive,
                }, timeout=600)
                r.raise_for_status()
                vecs = r.json()['embeddings']
                break
            except requests.RequestException as e:
                if attempt == 2:
                    raise RuntimeError(f'{model}: embed failed: {e} {getattr(e.response, "text", "")[:300]}')
                time.sleep(3)
        bad = [j for j, v in enumerate(vecs) if not v or any(x != x for x in v[:16])]
        if bad:
            raise RuntimeError(f'{model}: {len(bad)} empty/NaN embeddings in batch at {i}')
        out.extend(vecs)
    return out


def unload(url, model):
    try:
        requests.post(f'{url}/api/generate', json={'model': model, 'keep_alive': 0}, timeout=60)
    except requests.RequestException:
        pass


def ensure_collection(qc, url, model, lang, corpus, chash, batch, reindex):
    """Create and fill the collection unless it already holds this exact corpus."""
    name = f'embbench_{lang}_{slug(model)}'
    if qc.collection_exists(name) and not reindex:
        info = qc.get_collection(name)
        meta = qc.retrieve(name, ids=[0], with_payload=True)
        if info.points_count == len(corpus) and meta and meta[0].payload.get('corpus_hash') == chash:
            return name, None
    if qc.collection_exists(name):
        qc.delete_collection(name)
    prefix = MODELS[model]['doc']
    texts = [prefix + c['text'] for c in corpus]
    embed(url, model, texts[:1], 1)  # load model, not timed
    t0 = time.time()
    vecs = embed(url, model, texts, batch)
    secs = time.time() - t0
    qc.create_collection(name, vectors_config=qm.VectorParams(size=len(vecs[0]), distance=qm.Distance.COSINE))
    for i in range(0, len(corpus), 256):
        qc.upsert(name, points=[
            qm.PointStruct(id=j, vector=vecs[j], payload={'cid': corpus[j]['id'], 'page': corpus[j]['page'],
                                                          'corpus_hash': chash, 'model': model})
            for j in range(i, min(i + 256, len(corpus)))
        ], wait=True)
    return name, {'index_seconds': round(secs, 1), 'docs_per_second': round(len(corpus) / secs, 1),
                  'dim': len(vecs[0])}


def score(ranked_cids, ranked_pages, gold, gold_page):
    r_chunk = next((i + 1 for i, c in enumerate(ranked_cids) if c == gold), None)
    r_page = next((i + 1 for i, p in enumerate(ranked_pages) if p == gold_page), None)
    return r_chunk, r_page


def metrics(rows):
    n = len(rows)
    out = {}
    for lvl in ('chunk', 'page'):
        ranks = [r[f'rank_{lvl}'] for r in rows]
        for k in (1, 5, 10):
            out[f'{lvl}_hit@{k}'] = round(100 * sum(1 for x in ranks if x and x <= k) / n, 1)
        out[f'{lvl}_mrr@10'] = round(100 * sum(1 / x for x in ranks if x) / n, 1)
    out['chunk_ndcg@10'] = round(100 * sum(1 / math.log2(r['rank_chunk'] + 1) for r in rows if r['rank_chunk']) / n, 1)
    by_style = defaultdict(list)
    for r in rows:
        by_style[r['style']].append(r['rank_chunk'])
    out['chunk_mrr@10_by_style'] = {s: round(100 * sum(1 / x for x in v if x) / len(v), 1)
                                    for s, v in sorted(by_style.items())}
    return out


def run_model(qc, url, model, lang, corpus, queries, chash, batch, reindex):
    coll, idx = ensure_collection(qc, url, model, lang, corpus, chash, batch, reindex)
    qtexts = [MODELS[model]['query'] + q['query'] for q in queries]
    t0 = time.time()
    qvecs = embed(url, model, qtexts, batch)
    q_secs = time.time() - t0
    t0 = time.time()
    res = []
    for i in range(0, len(qvecs), 64):
        res.extend(qc.query_batch_points(coll, requests=[
            qm.QueryRequest(query=v, limit=TOP_K, with_payload=['cid', 'page']) for v in qvecs[i:i + 64]]))
    s_secs = time.time() - t0
    rows = []
    for q, r in zip(queries, res):
        cids = [p.payload['cid'] for p in r.points]
        pages = [p.payload['page'] for p in r.points]
        rc, rp = score(cids, pages, q['gold'], q['gold_page'])
        rows.append({'qid': q['qid'], 'style': q['style'], 'rank_chunk': rc, 'rank_page': rp, 'top': cids[:5]})
    m = metrics(rows)
    m.update({'query_embed_ms': round(1000 * q_secs / len(queries), 1),
              'search_ms': round(1000 * s_secs / len(queries), 2), 'collection': coll})
    if idx:
        m.update(idx)
    return m, rows


def bm25(corpus, queries, k1=1.2, b=0.75):
    tok = lambda s: re.findall(r'\w+', s.lower())
    docs = [tok(c['text']) for c in corpus]
    avg = sum(map(len, docs)) / len(docs)
    df = Counter(t for d in docs for t in set(d))
    n = len(docs)
    idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
    tfs = [Counter(d) for d in docs]
    rows = []
    for q in queries:
        qt = set(tok(q['query']))
        scores = []
        for j, (tf, d) in enumerate(zip(tfs, docs)):
            s = 0.0
            for t in qt:
                if t in tf:
                    s += idf[t] * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg))
            if s:
                scores.append((s, j))
        top = [corpus[j] for _, j in sorted(scores, reverse=True)[:TOP_K]]
        rc, rp = score([c['id'] for c in top], [c['page'] for c in top], q['gold'], q['gold_page'])
        rows.append({'qid': q['qid'], 'style': q['style'], 'rank_chunk': rc, 'rank_page': rp,
                     'top': [c['id'] for c in top[:5]]})
    return metrics(rows), rows


def model_info(url, model):
    try:
        d = requests.post(f'{url}/api/show', json={'model': model}, timeout=30).json()
        det = d.get('details', {})
        ctx = next((v for k, v in d.get('model_info', {}).items() if k.endswith('.context_length')), None)
        return {'params': det.get('parameter_size'), 'quant': det.get('quantization_level'),
                'family': det.get('family'), 'context_length': ctx}
    except (requests.RequestException, ValueError):
        return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--models', default='bm25,' + ','.join(MODELS))
    ap.add_argument('--langs', default='en,pl')
    ap.add_argument('--ollama', default='http://127.0.0.1:11434')
    ap.add_argument('--qdrant', default='http://127.0.0.1:6343')
    ap.add_argument('--batch', type=int, default=16)
    ap.add_argument('--reindex', action='store_true')
    a = ap.parse_args()
    url = a.ollama.rstrip('/')
    qc = QdrantClient(url=a.qdrant, timeout=120)
    run_id = datetime.now().strftime('%Y%m%d-%H%M%S')
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results = json.loads(RESULTS.read_text(encoding='utf-8')) if RESULTS.exists() else {'results': {}}
    data = {lang: load(lang) for lang in a.langs.split(',')}
    for model in a.models.split(','):
        if model != 'bm25' and model not in MODELS:
            raise SystemExit(f'unknown model {model}; add its prefixes to MODELS')
        info = {} if model == 'bm25' else model_info(url, model)
        for lang, (corpus, queries, chash) in data.items():
            t0 = time.time()
            try:
                if model == 'bm25':
                    m, rows = bm25(corpus, queries)
                else:
                    m, rows = run_model(qc, url, model, lang, corpus, queries, chash, a.batch, a.reindex)
            except Exception as e:  # keep going with the other models
                print(f'!! {model} [{lang}] failed: {e}', flush=True)
                continue
            prev = results['results'].get(f'{model}|{lang}', {})
            if 'dim' not in m and prev.get('corpus_hash') == chash:  # collection reused: keep indexing stats
                m.update({k: prev[k] for k in ('dim', 'index_seconds', 'docs_per_second') if k in prev})
            m.update({'model': model, 'lang': lang, 'n_queries': len(queries), 'n_chunks': len(corpus),
                      'corpus_hash': chash, 'run_id': run_id, 'date': datetime.now().isoformat(timespec='seconds'),
                      **info})
            results['results'][f'{model}|{lang}'] = m
            with (run_dir / f'{slug(model)}_{lang}.jsonl').open('w', encoding='utf-8') as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + '\n')
            print(f'{model:34s} {lang}  hit@1 {m["chunk_hit@1"]:5.1f}  hit@10 {m["chunk_hit@10"]:5.1f}  '
                  f'MRR {m["chunk_mrr@10"]:5.1f}  page hit@5 {m["page_hit@5"]:5.1f}  '
                  f'idx {m.get("docs_per_second", "-")} doc/s  ({time.time() - t0:.0f}s)', flush=True)
            results.update({'updated': datetime.now().isoformat(timespec='seconds'),
                            'corpus': 'LibreOffice Help (latest), en-US + pl, 911 pages',
                            'query_generator': queries[0].get('generator'), 'top_k': TOP_K})
            RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
        if model != 'bm25':
            unload(url, model)
    print_table(results['results'])


def print_table(res):
    for lang in ('en', 'pl'):
        rows = sorted((v for v in res.values() if v['lang'] == lang), key=lambda v: -v['chunk_mrr@10'])
        if not rows:
            continue
        print(f'\n== {lang}: {rows[0]["n_queries"]} queries, {rows[0]["n_chunks"]} chunks')
        print(f'{"model":34s} {"hit@1":>6s} {"hit@5":>6s} {"hit@10":>6s} {"MRR@10":>6s} {"nDCG":>6s} '
              f'{"pgH@1":>6s} {"pgH@5":>6s} {"dim":>5s} {"doc/s":>7s} {"q ms":>6s}')
        for v in rows:
            print(f'{v["model"]:34s} {v["chunk_hit@1"]:6.1f} {v["chunk_hit@5"]:6.1f} {v["chunk_hit@10"]:6.1f} '
                  f'{v["chunk_mrr@10"]:6.1f} {v["chunk_ndcg@10"]:6.1f} {v["page_hit@1"]:6.1f} {v["page_hit@5"]:6.1f} '
                  f'{v.get("dim", "-")!s:>5s} {v.get("docs_per_second", "-")!s:>7s} {v.get("query_embed_ms", "-")!s:>6s}')


if __name__ == '__main__':
    main()
