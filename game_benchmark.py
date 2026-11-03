"""Visual decision benchmark: a decision model drives a Lotus Esprit Turbo Challenge style racer (lotus_game/).

The game runs headless in a browser (Playwright). Every --hold frames it is paused, the canvas is sent as an image
to /v1/systemone with one choice question (left / straight / right / brake) and the answer is held for the next
--hold frames. Game time only moves while the car is driven, so a slow model drives the same race as a fast one;
--realtime instead keeps the previous action for as long as the decision took (a slow model reacts late).

Two servers answer /v1/systemone with images:
  --api ollama  Ollama decision models with vision (d3, d1): the image goes in "images"
  --api basal   basal-serve --mode eager --media on (basal-omni bf16; the GGUF files in Ollama are text only):
                the image goes in "media"
Baselines that need no server: --models oracle (autopilot that reads the game state) and random.

Per decision the log keeps the action, its probabilities, the autopilot's action and the car state
(game_runs/<run_id>/<model>_s<seed>.jsonl, with --save-frames also the frames and a replay GIF). The summary
of every model goes to game_results.json.
"""
import argparse
import base64
import json
import os
import random
import re
import statistics
import time
import uuid

import requests
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.join(ROOT, 'lotus_game', 'index.html')
FPS = 60

QUESTION = {
    'type': 'choice',
    'instructions': ('This is a screenshot of a racing game. You drive the red sports car at the bottom centre of the '
                     'screen. Stay on the grey road, do not hit the other cars or the trees and signs beside the road, '
                     'and drive as fast as you can. What should the driver do now?'),
    'criteria': {
        'left': 'Steer left: the road bends to the left, the red car is too far right, or a slower car ahead '
                'should be passed on its left',
        'straight': 'Keep straight at full throttle: the road ahead is straight and the red car is well placed on it',
        'right': 'Steer right: the road bends to the right, the red car is too far left, or a slower car ahead '
                 'should be passed on its right',
        'brake': 'Brake: a sharp bend or a slower car right in front is too close to take at this speed',
    },
}
ACTIONS = list(QUESTION['criteria'])
BASELINES = ('oracle', 'random')


def state_text(state, telemetry):
    text = 'Racing game, view from behind the red car.'
    if telemetry:
        side = 'left' if state['x'] < -0.15 else 'right' if state['x'] > 0.15 else 'centre'
        text += (f' Speed {state["speed_kmh"]:.0f} km/h. The red car is at the {side} of the road'
                 f'{" (off the road)" if state["offroad"] else ""}.')
    return text


def decide(args, model, image_b64, text):
    if args.api == 'basal':
        body = {'state': text, 'lang': 'en', 'media': [{'type': 'image', 'data': image_b64}],
                'questions': {'q': QUESTION}}
        if args.detail:
            body['detail'] = args.detail
    else:
        body = {'model': model, 'state': text, 'images': [image_b64], 'questions': {'q': QUESTION}}
    start = time.perf_counter()
    response = requests.post(f'{args.url}/v1/systemone', json=body, timeout=600)
    latency_ms = (time.perf_counter() - start) * 1000
    data = response.json()
    if response.status_code != 200 or 'answers' not in data:
        raise RuntimeError(data.get('error') or f'HTTP {response.status_code}')
    answer = data['answers']['q']
    return answer['choice'], answer.get('probabilities') or {}, latency_ms


def safe_name(model):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', model)


def snapshot(page, mime='image/png'):
    return page.evaluate(f'LOTUS.snapshot("{mime}", 0.85)').split(',', 1)[1]


def race(args, page, model, seed, out_dir):
    info = page.evaluate(f'LOTUS.reset({{seed: {seed}, laps: {args.laps}}})')
    state = page.evaluate('LOTUS.state()')
    log_path = os.path.join(out_dir, f'{safe_name(model)}_s{seed}.jsonl')
    frames_dir = os.path.join(out_dir, f'{safe_name(model)}_s{seed}')
    if args.save_frames:
        os.makedirs(frames_dir, exist_ok=True)
    rnd = random.Random(seed)
    previous = 'straight'
    rows = []
    with open(log_path, 'w', encoding='utf-8') as log:
        while not state['done'] and len(rows) < args.max_decisions:
            image = snapshot(page)
            if args.save_frames:
                with open(os.path.join(frames_dir, f'{len(rows):05d}.jpg'), 'wb') as f:
                    f.write(base64.b64decode(snapshot(page, 'image/jpeg')))
            oracle = page.evaluate('LOTUS.oracle()')
            row = {'n': len(rows), 'time': state['time'], 'oracle': oracle, 'probabilities': None,
                   'latency_ms': None, 'error': None}
            if model == 'oracle':
                action = oracle
            elif model == 'random':
                action = rnd.choice(ACTIONS)
            else:
                try:
                    action, row['probabilities'], row['latency_ms'] = decide(
                        args, model, image, state_text(state, args.telemetry))
                except Exception as e:  # a failed decision keeps the previous action and counts as an error
                    action, row['error'] = previous, str(e)[:500]
            if args.realtime and row['latency_ms']:
                late = round(row['latency_ms'] / 1000 * FPS)
                if late:
                    state = page.evaluate(f'LOTUS.step("{previous}", {late})')
            state = page.evaluate(f'LOTUS.step("{action}", {args.hold})')
            row.update(action=action, progress=state['progress'], speed_kmh=state['speed_kmh'], x=state['x'],
                       offroad=state['offroad'], collisions=state['collisions'], crashes=state['crashes'])
            rows.append(row)
            log.write(json.dumps(row) + '\n')
            previous = action
            if len(rows) % 50 == 0 or state['done']:
                print(f'    {len(rows):4d} decisions  t={state["time"]:5.1f}s  progress {100 * state["progress"]:5.1f}%  '
                      f'{state["speed_kmh"]:3.0f} km/h  P{state["position"]}', flush=True)
    if args.save_frames and rows:
        make_gif(frames_dir, os.path.join(out_dir, f'{safe_name(model)}_s{seed}.gif'), args.hold)
    return info, state, rows


def make_gif(frames_dir, path, hold):
    from PIL import Image
    files = sorted(os.listdir(frames_dir))
    frames = [Image.open(os.path.join(frames_dir, f)).convert('RGB').resize((320, 200)) for f in files]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=round(1000 * hold / FPS), loop=0)


def race_summary(seed, info, state, rows):
    lat = sorted(r['latency_ms'] for r in rows if r['latency_ms'] is not None)
    ok = [r for r in rows if r['error'] is None]
    finish_time = state['finish_time']
    # 100 points for the whole lap, up to 50 more for a fast finish; every hit costs points
    score = (100 * state['progress'] + (50 * (1 - finish_time / state['time_limit']) if state['finished'] else 0)
             - 2 * state['collisions'] - 5 * state['crashes'])
    return {
        'seed': seed, 'segments': info['segments'], 'finished': state['finished'], 'progress': state['progress'],
        'finish_time': finish_time, 'race_time': state['time'], 'position': state['position'],
        'avg_speed_kmh': statistics.mean(r['speed_kmh'] for r in rows) if rows else None,
        'collisions': state['collisions'], 'crashes': state['crashes'],
        'offroad_ratio': state['offroad_frames'] / max(1, state['frame']),
        'decisions': len(rows), 'errors': len(rows) - len(ok),
        'oracle_agreement': statistics.mean(r['action'] == r['oracle'] for r in ok) if ok else None,
        'actions': {a: sum(r['action'] == a for r in rows) for a in ACTIONS},
        'latency_ms_median': statistics.median(lat) if lat else None,
        'latency_ms_p95': lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else None,
        'score': score,
    }


def mean_of(races, key):
    values = [r[key] for r in races if r[key] is not None]
    return statistics.mean(values) if values else None


def model_summary(args, model, run_id, races, load_ms):
    return {
        'model': model, 'api': 'baseline' if model in BASELINES else args.api, 'run_id': run_id,
        'hold_frames': args.hold, 'realtime': args.realtime, 'telemetry': args.telemetry, 'laps': args.laps,
        'seeds': [r['seed'] for r in races], 'load_ms': load_ms,
        'finished': sum(r['finished'] for r in races), 'races': len(races),
        **{k: mean_of(races, k) for k in ('score', 'progress', 'finish_time', 'position', 'avg_speed_kmh',
                                          'collisions', 'crashes', 'offroad_ratio', 'oracle_agreement',
                                          'latency_ms_median', 'latency_ms_p95')},
        'errors': sum(r['errors'] for r in races),
        'per_seed': races,
    }


def save_results(path, summaries):
    """Keep earlier results; a model run again with the same settings replaces its old entry."""
    key = lambda s: (s['model'], s['api'], s['hold_frames'], s['realtime'], s['telemetry'], s['laps'], tuple(s['seeds']))
    data = {'models': []}
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    new_keys = {key(s) for s in summaries}
    models = [s for s in data['models'] if key(s) not in new_keys] + summaries
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'game': 'lotus_game',
                   'question': QUESTION, 'models': sorted(models, key=lambda s: -(s['score'] or 0))},
                  f, ensure_ascii=False, indent=1)


def print_table(summaries):
    print(f'\n{"model":<34}{"score":>7}{"done":>6}{"prog%":>7}{"time s":>8}{"pos":>5}{"km/h":>6}{"hits":>6}'
          f'{"trees":>6}{"off%":>6}{"=auto%":>7}{"med ms":>8}{"err":>5}')
    for s in sorted(summaries, key=lambda s: -(s['score'] or 0)):
        f = lambda v, fmt: format(v, fmt) if v is not None else '-'
        print(f'{s["model"][:33]:<34}{f(s["score"], ".1f"):>7}{s["finished"]:>3}/{s["races"]:<2}'
              f'{f(100 * s["progress"], ".1f"):>7}{f(s["finish_time"], ".1f"):>8}{f(s["position"], ".1f"):>5}'
              f'{f(s["avg_speed_kmh"], ".0f"):>6}{f(s["collisions"], ".1f"):>6}{f(s["crashes"], ".1f"):>6}'
              f'{f(100 * s["offroad_ratio"], ".1f"):>6}'
              f'{f(100 * s["oracle_agreement"] if s["oracle_agreement"] is not None else None, ".1f"):>7}'
              f'{f(s["latency_ms_median"], ".0f"):>8}{s["errors"]:>5}')


def launch(p, args):
    options = {'headless': not args.headed}
    for channel in ([args.browser] if args.browser else [None, 'msedge', 'chrome']):
        try:
            return p.chromium.launch(channel=channel, **options) if channel else p.chromium.launch(**options)
        except Exception as e:
            last = e
    raise SystemExit(f'No browser for Playwright ({last}); run "playwright install chromium" or pass --browser msedge')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--models', default='oracle',
                   help='Comma-separated models; "oracle" and "random" are baselines (default: oracle). With --api basal '
                        'the name is only a label: basal-serve answers with the model it was started with')
    p.add_argument('--api', choices=['ollama', 'basal'], default='ollama')
    p.add_argument('--url', help='Server answering /v1/systemone (default: http://localhost:11434 for ollama, '
                                 'http://127.0.0.1:8000 for basal)')
    p.add_argument('--seeds', default='1,2,3', help='Comma-separated track seeds (default: 1,2,3)')
    p.add_argument('--laps', type=int, default=1)
    p.add_argument('--hold', type=int, default=6, help='Frames (1/60 s) each decision is held (default: 6)')
    p.add_argument('--realtime', action='store_true',
                   help='Keep the previous action while the model decides (latency costs distance and control)')
    p.add_argument('--telemetry', action='store_true', help='Add speed and road position to the state text')
    p.add_argument('--detail', choices=['default', 'high'], help='basal-serve image detail (280 or 1,120 tokens)')
    p.add_argument('--max-decisions', type=int, default=3000, help='Stop a race after this many decisions')
    p.add_argument('--save-frames', action='store_true', help='Save every decision frame and a replay GIF')
    p.add_argument('--headed', action='store_true', help='Show the browser window while racing')
    p.add_argument('--browser', help='Playwright channel, e.g. msedge or chrome (default: bundled Chromium, '
                                     'then Edge, then Chrome)')
    p.add_argument('--output', default=os.path.join(ROOT, 'game_results.json'))
    args = p.parse_args()
    args.url = (args.url or ('http://127.0.0.1:8000' if args.api == 'basal' else 'http://localhost:11434')).rstrip('/')
    models = [m.strip() for m in args.models.split(',') if m.strip()]
    seeds = [int(s) for s in args.seeds.split(',')]

    run_id = time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:4]
    out_dir = os.path.join(ROOT, 'game_runs', run_id)
    os.makedirs(out_dir, exist_ok=True)
    print(f'Run {run_id}: {len(models)} models x {len(seeds)} tracks, decision every {args.hold} frames'
          f'{", realtime" if args.realtime else ""}{", telemetry" if args.telemetry else ""} -> {out_dir}')

    summaries = []
    with sync_playwright() as pw:
        browser = launch(pw, args)
        page = browser.new_page(viewport={'width': 1300, 'height': 860})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto('file:///' + GAME.replace(os.sep, '/') + '?bot=1')
        for model in models:
            load_ms = None
            if model not in BASELINES:
                # warm-up: the first call loads the model, so it is load time, not decision time
                page.evaluate('LOTUS.reset({seed: 0})')
                _, _, load_ms = decide(args, model, snapshot(page), state_text(page.evaluate('LOTUS.state()'), args.telemetry))
            print(f'\n== {model}' + (f': load {load_ms:.0f} ms' if load_ms else ''))
            races = []
            for seed in seeds:
                print(f'  track {seed}')
                info, state, rows = race(args, page, model, seed, out_dir)
                races.append(race_summary(seed, info, state, rows))
            summaries.append(model_summary(args, model, run_id, races, load_ms))
        browser.close()
        if errors:
            print('Game errors:', *errors[:5], sep='\n  ')

    print_table(summaries)
    save_results(args.output, summaries)
    print(f'\nWrote {args.output}')


if __name__ == '__main__':
    main()
