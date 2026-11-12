"""Generate retrieval queries for the embedding benchmark.

One query per sampled help page: a random content chunk of the page is shown to a local
LLM (default mistral-small3.2:24b in Ollama - not from any family of tested embedders),
which writes a question in the corpus language that the chunk answers. The chunk is the
gold passage (its page is the gold page). Query styles are mixed: a natural question that
describes the goal without the feature's name, a short search phrase, and a how-to question.

    python embedding_queries.py --langs en,pl --n 500
"""
import argparse
import json
import random
import re
import time
from pathlib import Path

import requests

DATA = Path(__file__).parent / 'embedding_data'

STYLES = {
    'goal': {
        'en': 'a natural question from a user who describes what they want to achieve or what problem they have, '
              'WITHOUT using the exact name of the function, command, menu or dialog from the passage',
        'pl': 'naturalne pytanie użytkownika, który opisuje, co chce osiągnąć albo jaki ma problem, '
              'BEZ użycia dokładnej nazwy funkcji, polecenia, menu ani okna dialogowego z fragmentu',
    },
    'keyword': {
        'en': 'a short search phrase of 3-7 words, like typed into a search box (not a full sentence)',
        'pl': 'krótka fraza wyszukiwania z 3-7 słów, jak wpisana w wyszukiwarkę (nie pełne zdanie)',
    },
    'howto': {
        'en': 'a specific "how do I ..." / "what does ..." question about a detail that this passage explains',
        'pl': 'konkretne pytanie typu "jak ..." / "co robi ..." o szczegół, który wyjaśnia ten fragment',
    },
}

PROMPT = {
    'en': """You build a test set for a search engine over the LibreOffice Help documentation.

Passage (from the page "{title}"):
<<<
{text}
>>>

Write ONE query in English: {style}.
Rules:
- The passage must answer it, and it should point to this passage rather than to other LibreOffice help pages.
- Do not copy whole sentences or the heading from the passage; paraphrase.
- Do not mention "the passage", "the text" or "the documentation".
Reply with JSON only: {{"query": "..."}}""",
    'pl': """Tworzysz zestaw testowy dla wyszukiwarki w dokumentacji (Pomocy) LibreOffice.

Fragment (ze strony "{title}"):
<<<
{text}
>>>

Napisz JEDNO zapytanie po polsku: {style}.
Zasady:
- Fragment musi na nie odpowiadać, a zapytanie powinno wskazywać na ten fragment, a nie na inne strony pomocy LibreOffice.
- Nie przepisuj całych zdań ani nagłówka z fragmentu; parafrazuj.
- Nie wspominaj o "fragmencie", "tekście" ani "dokumentacji".
- Pisz poprawną polszczyzną.
Odpowiedz wyłącznie JSON-em: {{"query": "..."}}""",
}


def eligible(chunk):
    body = chunk['text'].split('\n', 1)[-1]
    if len(body) < 300:
        return False
    lines = [ln for ln in body.split('\n') if ln.strip()]
    # skip link lists / tables of contents: mostly short lines
    short = sum(len(ln) < 60 for ln in lines)
    return short / max(1, len(lines)) < 0.7


def generate(url, model, prompt, timeout=300):
    for attempt in range(3):
        try:
            r = requests.post(f'{url}/api/chat', json={
                'model': model, 'stream': False, 'format': 'json', 'think': False,
                'messages': [{'role': 'user', 'content': prompt}],
                'options': {'temperature': 0.7, 'num_ctx': 4096, 'seed': attempt},
            }, timeout=timeout)
            r.raise_for_status()
            q = json.loads(r.json()['message']['content']).get('query', '').strip()
            if 8 <= len(q) <= 300:
                return q
        except (requests.RequestException, ValueError, KeyError):
            time.sleep(2)
    return None


def word_overlap(q, text):
    qw = set(re.findall(r'\w{4,}', q.lower()))
    tw = set(re.findall(r'\w{4,}', text.lower()))
    return round(len(qw & tw) / max(1, len(qw)), 3)


def build(lang, n, url, model, seed):
    corpus = [json.loads(x) for x in (DATA / lang / 'corpus.jsonl').open(encoding='utf-8')]
    by_page = {}
    for c in corpus:
        if eligible(c):
            by_page.setdefault(c['page'], []).append(c)
    rnd = random.Random(seed)
    pages = sorted(by_page)
    rnd.shuffle(pages)
    out_path = DATA / lang / 'queries.jsonl'
    done = {}
    if out_path.exists():  # resume
        for x in out_path.open(encoding='utf-8'):
            q = json.loads(x)
            done[q['gold_page']] = q
    print(f'[{lang}] {len(by_page)} pages with eligible chunks, {len(done)} queries already done')
    style_names = list(STYLES)
    with out_path.open('a', encoding='utf-8') as fh:
        made = len(done)
        for i, page in enumerate(pages):
            if made >= n:
                break
            chunk = rnd.choice(by_page[page])
            style = style_names[i % len(style_names)]
            if page in done:
                continue
            prompt = PROMPT[lang].format(title=chunk['title'], text=chunk['text'][:2500],
                                         style=STYLES[style][lang])
            t0 = time.time()
            q = generate(url, model, prompt)
            if not q:
                print(f'  skip {chunk["id"]}: no valid query')
                continue
            rec = {'qid': f'{lang}-{made:04d}', 'query': q, 'style': style, 'gold': chunk['id'],
                   'gold_page': page, 'overlap': word_overlap(q, chunk['text']), 'generator': model}
            fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
            fh.flush()
            made += 1
            if made % 25 == 0:
                print(f'  [{lang}] {made}/{n} ({time.time() - t0:.1f}s) {style}: {q}', flush=True)
    print(f'[{lang}] {made} queries -> {out_path}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--langs', default='en,pl')
    ap.add_argument('--n', type=int, default=500)
    ap.add_argument('--ollama', default='http://127.0.0.1:11434')
    ap.add_argument('--model', default='mistral-small3.2:24b')
    ap.add_argument('--seed', type=int, default=2026)
    a = ap.parse_args()
    for lang in a.langs.split(','):
        build(lang, a.n, a.ollama.rstrip('/'), a.model, a.seed)


if __name__ == '__main__':
    main()
