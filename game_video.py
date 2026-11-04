"""Replay video of game_benchmark.py races (needs a run made with --save-frames, and ffmpeg).

Every decision frame is scaled 2x and gets a panel below it: the action the model chose, its probabilities, the
autopilot's action and the decision time. Each track starts with a title card and ends with its result.
One frame per decision, so with --hold 6 the video plays at 10 fps, i.e. in game time.

  python game_video.py game_runs/<run_id>                       # every model and track of the run
  python game_video.py game_runs/<run_id> --model basal-omni-1.0-mini --ffmpeg D:/ffmpeg.exe
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont

from game_benchmark import ACTIONS, FPS, safe_name

GAME_W, GAME_H = 1280, 800
PANEL_H = 160
COLORS = {'left': (59, 130, 246), 'straight': (34, 197, 94), 'right': (249, 115, 22), 'brake': (239, 68, 68)}
BG, FG, DIM = (17, 17, 20), (240, 240, 240), (140, 140, 150)


def font(size):
    for name in ('consolab.ttf', 'DejaVuSansMono-Bold.ttf', 'arialbd.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


F_BIG, F_MID, F_SMALL = font(44), font(26), font(20)


def panel(draw, model, seed, row, total, crashed=False):
    top = GAME_H
    draw.rectangle([0, top, GAME_W, top + PANEL_H], fill=BG)
    action = row['action']
    draw.text((24, top + 14), model, font=F_MID, fill=FG)
    draw.text((24, top + 50), f'track {seed}  decision {row["n"] + 1}/{total}  t={row["time"]:.1f}s', font=F_SMALL, fill=DIM)
    draw.text((24, top + 88), action.upper(), font=F_BIG, fill=COLORS.get(action, FG))
    oracle = row['oracle']
    draw.text((260, top + 100), f'autopilot: {oracle}', font=F_SMALL,
              fill=(120, 220, 120) if oracle == action else (230, 160, 90))
    probs = row.get('probabilities') or {}
    x0, bar_w = 560, 480
    for i, a in enumerate(ACTIONS):
        y = top + 16 + i * 34
        p = probs.get(a, 1.0 if a == action and not probs else 0.0)
        draw.text((x0, y), f'{a:>8}', font=F_SMALL, fill=FG if a == action else DIM)
        draw.rectangle([x0 + 120, y + 4, x0 + 120 + bar_w, y + 24], fill=(40, 40, 46))
        draw.rectangle([x0 + 120, y + 4, x0 + 120 + int(bar_w * p), y + 24], fill=COLORS[a])
        draw.text((x0 + 130 + bar_w, y), f'{100 * p:5.1f}%', font=F_SMALL, fill=FG if a == action else DIM)
    if crashed:  # the car stood still for the crash time before this frame (game rules v2+)
        draw.text((24 + draw.textlength(action.upper(), font=F_BIG) + 24, top + 96), 'CRASH', font=F_MID, fill=(239, 68, 68))
    if row.get('latency_ms') is not None:
        draw.text((260, top + 128), f'{row["latency_ms"]:.0f} ms', font=F_SMALL, fill=DIM)


def card(lines):
    img = Image.new('RGB', (GAME_W, GAME_H + PANEL_H), BG)
    draw = ImageDraw.Draw(img)
    y = (GAME_H + PANEL_H) // 2 - 40 * len(lines)
    for i, (text, f, color) in enumerate(lines):
        w = draw.textlength(text, font=f)
        draw.text(((GAME_W - w) / 2, y), text, font=f, fill=color)
        y += 90 if i == 0 else 50
    return img


def races(run_dir, model):
    """(model label, seed, rows, frames dir) for every race in the run that has saved frames."""
    found = []
    for log in sorted(glob.glob(os.path.join(run_dir, '*_s*.jsonl'))):
        name, seed = re.match(r'(.+)_s(\d+)\.jsonl$', os.path.basename(log)).groups()
        frames = log[:-len('.jsonl')]
        if (model and name != safe_name(model)) or not os.path.isdir(frames):
            continue
        with open(log, encoding='utf-8') as f:
            rows = [json.loads(line) for line in f if line.rstrip().endswith('}')]  # a stopped run may cut the last line
        found.append((model or name, int(seed), rows, frames))
    return found


def render(args, label, items, path):
    fps = FPS / args.hold
    cmd = [args.ffmpeg, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', f'{GAME_W}x{GAME_H + PANEL_H}', '-r', f'{fps:g}', '-i', '-',
           '-c:v', 'libx264', '-crf', '20', '-preset', 'medium', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    write = lambda img, n=1: [proc.stdin.write(img.tobytes()) for _ in range(n)]
    for model, seed, rows, frames in items:
        write(card([(model, F_BIG, FG), (f'track {seed}', F_MID, DIM),
                    ('decision model drives from screenshots', F_SMALL, DIM)]), round(fps * 2))
        files = sorted(os.listdir(frames))
        img = None
        for i, (row, name) in enumerate(zip(rows, files)):
            img = Image.new('RGB', (GAME_W, GAME_H + PANEL_H), BG)
            img.paste(Image.open(os.path.join(frames, name)).convert('RGB').resize((GAME_W, GAME_H), Image.NEAREST))
            # frame i is taken after decision i-1 was driven: flag a crash that happened while driving it
            crashed = i > 0 and rows[i - 1]['crashes'] > (rows[i - 2]['crashes'] if i > 1 else 0)
            panel(ImageDraw.Draw(img), model, seed, row, len(rows), crashed)
            write(img)
        if img:
            write(img, round(fps))  # hold the last frame for a second
        last = rows[-1] if rows else {}
        agree = sum(r['action'] == r['oracle'] for r in rows) / max(1, len(rows))
        write(card([(f'track {seed}: {100 * last.get("progress", 0):.0f}% of the lap', F_BIG, FG),
                    (f'{len(rows)} decisions, {last.get("time", 0) + args.hold / FPS:.1f} s of race', F_MID, DIM),
                    (f'hits {last.get("collisions", 0)}, trees {last.get("crashes", 0)}, '
                     f'agrees with autopilot {100 * agree:.0f}%', F_MID, DIM)]), round(fps * 3))
    proc.stdin.close()
    if proc.wait():
        raise SystemExit(f'ffmpeg failed for {path}')
    print(f'Wrote {path}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('run_dir')
    p.add_argument('--model', help='Only this model (default: every model in the run)')
    p.add_argument('--hold', type=int, default=6, help='Frames per decision the run used (default: 6)')
    p.add_argument('--ffmpeg', default=os.environ.get('FFMPEG') or shutil.which('ffmpeg') or 'ffmpeg')
    args = p.parse_args()
    items = races(args.run_dir, args.model)
    if not items:
        raise SystemExit(f'No races with saved frames in {args.run_dir} (run game_benchmark.py with --save-frames)')
    by_model = {}
    for item in items:
        by_model.setdefault(item[0], []).append(item)
    for label, model_items in by_model.items():
        render(args, label, model_items, os.path.join(args.run_dir, f'{safe_name(label)}.mp4'))


if __name__ == '__main__':
    main()
