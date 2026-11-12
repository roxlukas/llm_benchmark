"""Build the retrieval corpus for the embedding benchmark.

Source: LibreOffice Help (https://help.libreoffice.org/latest/), the same 911 pages in
English (en-US) and Polish (pl). The page list comes from each language's contents.js.
Pages are split into chunks at h1/h2 headings; long sections are cut at paragraph
boundaries, tiny ones merged with the next. Each chunk starts with "page title — section".

    python embedding_corpus.py                 # download (cached) + chunk both languages
    python embedding_corpus.py --langs pl      # one language
"""
import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = 'https://help.libreoffice.org/latest'
LANGS = {'en': 'en-US', 'pl': 'pl'}
DATA = Path(__file__).parent / 'embedding_data'
MAX_CHARS = 1500
MIN_CHARS = 250
DROP_CLASSES = {'xapian-omega-search', 'relatedtopics'}


def page_list(code):
    js = requests.get(f'{BASE}/{code}/contents.js', timeout=30).text
    seen, out = set(), []
    for m in re.finditer(rf'href="{re.escape(code)}/(text/[^"?]+)[^"]*">([^<]*)</a>', js):
        path = m.group(1)
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def fetch(code, path, raw_dir):
    dst = raw_dir / path
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        try:
            r = requests.get(f'{BASE}/{code}/{path}', timeout=30)
            r.raise_for_status()
            dst.write_bytes(r.content)
            return dst
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
    return None


def block_text(el):
    if el.name == 'table':
        rows = []
        for tr in el.find_all('tr'):
            cells = [c.get_text(' ', strip=True) for c in tr.find_all(['td', 'th'])]
            cells = [c for c in cells if c]
            if cells:
                rows.append(' | '.join(cells))
        return '\n'.join(rows)
    return el.get_text(' ', strip=True)


def sections(html):
    """Yield (title, heading, [paragraphs]) per h1/h2 section of a help page."""
    soup = BeautifulSoup(html, 'html.parser')
    area = soup.find(id='DisplayArea')
    if area is None:
        return None, []
    for tag in area.find_all(['noscript', 'script', 'meta', 'style']):
        tag.decompose()
    for tag in area.find_all('div', class_=lambda c: c and DROP_CLASSES & set(c.split() if isinstance(c, str) else c)):
        tag.decompose()
    h1 = area.find('h1')
    title = h1.get_text(' ', strip=True) if h1 else ''
    secs, heading, paras = [], title, []
    for el in area.find_all(recursive=False):
        if el.name in ('h1', 'h2'):
            if paras:
                secs.append((heading, paras))
            heading, paras = el.get_text(' ', strip=True), []
            continue
        t = block_text(el)
        t = re.sub(r'[ \t ]+', ' ', t).strip()
        if t:
            paras.append(t)
    if paras:
        secs.append((heading, paras))
    return title, secs


def chunk_page(path, html):
    title, secs = sections(html)
    if not secs:
        return []
    pieces = []  # (heading, text)
    for heading, paras in secs:
        buf = ''
        for p in paras:
            if len(p) > MAX_CHARS:  # very long table/paragraph: hard split on lines
                lines, p_parts, cur = p.split('\n'), [], ''
                for ln in lines:
                    if cur and len(cur) + len(ln) > MAX_CHARS:
                        p_parts.append(cur)
                        cur = ''
                    cur = f'{cur}\n{ln}' if cur else ln[:MAX_CHARS * 2]
                p_parts.append(cur)
            else:
                p_parts = [p]
            for part in p_parts:
                if buf and len(buf) + len(part) + 1 > MAX_CHARS:
                    pieces.append((heading, buf))
                    buf = ''
                buf = f'{buf}\n{part}' if buf else part
        if buf:
            pieces.append((heading, buf))
    merged = []
    for heading, text in pieces:
        if merged and len(merged[-1][1]) < MIN_CHARS and len(merged[-1][1]) + len(text) <= MAX_CHARS:
            h0, t0 = merged[-1]
            merged[-1] = (h0, f'{t0}\n{heading}\n{text}' if heading != h0 else f'{t0}\n{text}')
        else:
            merged.append((heading, text))
    out = []
    for i, (heading, text) in enumerate(merged):
        head = title if (not heading or heading == title) else f'{title} — {heading}'
        out.append({'id': f'{path}#{i}', 'page': path, 'title': title, 'section': heading,
                    'text': f'{head}\n{text}'})
    return out


def build(lang, workers):
    code = LANGS[lang]
    raw_dir = DATA / 'raw' / lang
    paths = page_list(code)
    print(f'[{lang}] {len(paths)} pages in contents.js')
    with ThreadPoolExecutor(workers) as ex:
        files = list(ex.map(lambda p: fetch(code, p, raw_dir), paths))
    chunks, missing = [], 0
    for path, f in zip(paths, files):
        if f is None:
            missing += 1
            continue
        chunks.extend(chunk_page(path, f.read_text(encoding='utf-8', errors='replace')))
    out = DATA / lang / 'corpus.jsonl'
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', encoding='utf-8') as fh:
        for c in chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + '\n')
    lens = sorted(len(c['text']) for c in chunks)
    print(f'[{lang}] {len(chunks)} chunks from {len(paths) - missing} pages ({missing} failed), '
          f'chars median {lens[len(lens) // 2]}, max {lens[-1]} -> {out}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--langs', default='en,pl')
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    for lang in a.langs.split(','):
        build(lang, a.workers)


if __name__ == '__main__':
    main()
