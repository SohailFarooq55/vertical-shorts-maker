#!/usr/bin/env python3
"""
vertical-shorts-maker — build a 1080x1920 vertical Short from stills + voiceover.

Takes 2-4 still images, a voiceover (mp3/wav), and a captions file, and
produces a finished 10-second Short:

  1. Ken Burns slow-zoom (zoompan) segments, one per image
  2. Voiceover + generated whoosh / impact SFX, padded to the target length
  3. Captions burned in with ffmpeg drawtext

Why drawtext and not the subtitles filter?
-------------------------------------------
On some ffmpeg builds the `subtitles` filter renders no text at all
(verified on Ubuntu 24.04 / ffmpeg 6.x: the SRT is read, the video comes
out clean, no captions). drawtext with a textfile per line and
`enable='between(t,start,end)'` works everywhere, so this tool uses that.

Usage:
    python3 shorts_maker.py \
        --images img1.jpg img2.jpg img3.jpg \
        --voiceover voice.mp3 \
        --captions captions.json \
        --output short.mp4

    python3 shorts_maker.py --images a.jpg b.jpg --voiceover v.mp3 \
        --captions captions.json --output short.mp4 --duration 15 --no-sfx

Captions file (JSON) — timings are optional. Without them, time is
split across captions in proportion to word count, scaled to the
*measured* voiceover length (ffprobe), because TTS length varies:

    [
      {"text": "Nobody watches you as much as you think."},
      {"text": "It's called the spotlight effect.", "start": 3.0, "end": 4.8}
    ]

Requirements: ffmpeg + ffprobe on PATH, Python 3.10+, numpy (SFX only).
No API keys, no network, no uploads.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

import numpy as np

DEFAULT_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def run(cmd, **kwargs):
    print(" ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kwargs)


def check_tools():
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            sys.exit(f"error: {tool} not found on PATH — install ffmpeg first")


def probe_duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        text=True,
    )
    return float(out.strip())


def find_font(explicit=None):
    candidates = [explicit] if explicit else []
    candidates += [
        DEFAULT_FONT,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def load_captions(path, voice_duration, voice_delay):
    with open(path, encoding="utf-8") as f:
        caps = json.load(f)
    if not isinstance(caps, list) or not caps:
        sys.exit("error: captions file must be a non-empty JSON list")

    # Fill in missing timings by word count, over the measured voice length.
    words = [len(str(c.get("text", "")).split()) for c in caps]
    total_words = sum(words) or 1
    t = voice_delay
    for cap, w in zip(caps, words):
        if "start" not in cap or "end" not in cap:
            dur = voice_duration * w / total_words
            cap["start"] = round(t, 3)
            cap["end"] = round(t + dur, 3)
        t = cap["end"]
    return caps


def split_lines(text, width=28):
    """Split a caption into at most 2 lines, roughly balanced."""
    lines = textwrap.wrap(text, width=width)
    if len(lines) <= 2:
        return lines
    # Too long: re-wrap wider so it still fits on 2 lines.
    return textwrap.wrap(text, width=40)[:2]


def make_sfx(path, duration, cut_times, seed=7):
    """Whoosh at each cut + a low impact near the end. Silent if numpy fails."""
    sr = 44100
    tt = np.arange(int(sr * duration)) / sr
    audio = np.zeros_like(tt)
    rng = np.random.default_rng(seed)
    for ws in cut_times:
        n = int(0.5 * sr)
        noise = rng.standard_normal(n) * 0.05
        env = np.hanning(n)
        idx = int(ws * sr)
        if idx + n <= len(audio):
            audio[idx:idx + n] += noise * env
    idx = int(max(0.0, duration - 0.6) * sr)
    n = int(0.6 * sr)
    t2 = np.arange(n) / sr
    if idx + n <= len(audio):
        audio[idx:idx + n] += 0.35 * np.sin(2 * np.pi * 55 * t2) * np.exp(-t2 * 3)
    audio = np.clip(audio, -0.9, 0.9)
    import wave
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((audio * 32767).astype(np.int16).tobytes())


def main():
    p = argparse.ArgumentParser(description="Build a vertical Short from stills + voiceover.")
    p.add_argument("--images", nargs="+", required=True, help="2-4 still images, in order")
    p.add_argument("--voiceover", required=True, help="voiceover audio (mp3/wav)")
    p.add_argument("--captions", required=True, help="captions JSON file")
    p.add_argument("--output", required=True, help="output mp4, e.g. short.mp4")
    p.add_argument("--duration", type=float, default=10.0, help="target length in seconds (default 10)")
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1920)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--voice-delay", type=float, default=0.10, help="seconds before voiceover starts")
    p.add_argument("--crf", type=int, default=20, help="H.264 CRF (default 20)")
    p.add_argument("--audio-bitrate", default="128k")
    p.add_argument("--font", default=None, help="path to a .ttf bold font")
    p.add_argument("--no-sfx", action="store_true", help="skip generated whoosh/impact SFX")
    p.add_argument("--no-captions", action="store_true", help="skip burned-in captions")
    p.add_argument("--keep-temp", action="store_true", help="keep intermediate files for debugging")
    args = p.parse_args()

    check_tools()
    for img in args.images:
        if not os.path.exists(img):
            sys.exit(f"error: image not found: {img}")
    if not os.path.exists(args.voiceover):
        sys.exit(f"error: voiceover not found: {args.voiceover}")
    if not os.path.exists(args.captions):
        sys.exit(f"error: captions file not found: {args.captions}")

    voice_duration = probe_duration(args.voiceover)
    print(f"voiceover: {voice_duration:.2f}s (measured with ffprobe)")
    if voice_duration + args.voice_delay > args.duration:
        print(f"warning: voiceover ({voice_duration:.2f}s + {args.voice_delay}s delay) "
              f"is longer than --duration {args.duration}s; it will be cut off")

    caps = [] if args.no_captions else load_captions(args.captions, voice_duration, args.voice_delay)
    for i, c in enumerate(caps, 1):
        print(f"caption {i}: {c['start']:.2f} --> {c['end']:.2f}  {c['text']}")

    tmp = tempfile.mkdtemp(prefix="shorts-maker-")
    try:
        # 1. Ken Burns segments, one per image, split evenly across duration.
        n = len(args.images)
        seg_durs = [args.duration / n] * n
        seg_durs[-1] += args.duration - sum(seg_durs)  # absorb rounding
        seg_files, cut_times = [], []
        t_cut = 0.0
        for i, (img, dur_s) in enumerate(zip(args.images, seg_durs)):
            frames = int(dur_s * args.fps)
            vf = (
                f"scale={args.width}:{args.height}:force_original_aspect_ratio=increase,"
                f"crop={args.width}:{args.height},"
                f"zoompan=z='min(zoom+0.0012,1.15)':x='iw/2-(iw/zoom/2)':"
                f"y='ih/2-(ih/zoom/2)':d={frames}:s={args.width}x{args.height}:fps={args.fps}"
            )
            out = os.path.join(tmp, f"seg{i}.mp4")
            run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-vf", vf,
                 "-t", str(dur_s), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-r", str(args.fps), out])
            seg_files.append(out)
            t_cut += dur_s
            if i < n - 1:
                cut_times.append(round(t_cut, 2))

        concat = os.path.join(tmp, "concat.txt")
        with open(concat, "w", encoding="utf-8") as f:
            for s in seg_files:
                f.write(f"file '{s}'\n")
        video_only = os.path.join(tmp, "video-only.mp4")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat,
             "-c", "copy", video_only])

        # 2. Mix voiceover + SFX, pad to target duration.
        sfx = os.path.join(tmp, "sfx.wav")
        if args.no_sfx:
            inputs = ["-i", video_only, "-i", args.voiceover]
            filt = (f"[1:a]adelay={int(args.voice_delay * 1000)}|{int(args.voice_delay * 1000)}[vo];"
                    f"[vo]apad=whole_dur={args.duration}[a]")
        else:
            make_sfx(sfx, args.duration, cut_times)
            inputs = ["-i", video_only, "-i", args.voiceover, "-i", sfx]
            filt = (f"[1:a]adelay={int(args.voice_delay * 1000)}|{int(args.voice_delay * 1000)}[vo];"
                    f"[2:a]volume=0.6[sfx];[vo][sfx]amix=inputs=2:duration=first:"
                    f"dropout_transition=0,apad=whole_dur={args.duration}[a]")
        with_audio = os.path.join(tmp, "with-audio.mp4")
        run(["ffmpeg", "-y", *inputs, "-filter_complex", filt,
             "-map", "0:v", "-map", "[a]", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-t", str(args.duration), with_audio])

        # 3. Burn captions with drawtext (see module docstring for why).
        if not caps:
            run(["ffmpeg", "-y", "-i", with_audio, "-c:v", "libx264",
                 "-pix_fmt", "yuv420p", "-crf", str(args.crf), "-c:a", "copy",
                 "-movflags", "+faststart", args.output])
        else:
            font = find_font(args.font)
            if not font:
                sys.exit("error: no bold TTF font found — pass --font /path/to/font.ttf")
            fontsize = 56 if args.height >= 1920 else 44
            y1 = args.height - 500
            y2 = args.height - 420
            filters, prev = [], "0:v"
            for i, cap in enumerate(caps):
                lines = split_lines(cap["text"])
                ys = [y1, y2] if len(lines) > 1 else [y1 + 40]
                for j, (line, y) in enumerate(zip(lines, ys)):
                    tf = os.path.join(tmp, f"cap{i}_{j}.txt")
                    with open(tf, "w", encoding="utf-8") as f:
                        f.write(line)
                    out = f"v{i}{j}"
                    filters.append(
                        f"[{prev}]drawtext=fontfile={font}:fontsize={fontsize}:"
                        f"fontcolor=white:borderw=2:bordercolor=black:"
                        f"box=1:boxcolor=black@0.6:boxborderw=24:"
                        f"x=(w-text_w)/2:y={y}:textfile={tf}:"
                        f"enable='between(t,{cap['start']},{cap['end']})'[{out}]"
                    )
                    prev = out
            run(["ffmpeg", "-y", "-i", with_audio, "-filter_complex", ";".join(filters),
                 "-map", f"[{prev}]", "-map", "0:a", "-c:v", "libx264",
                 "-pix_fmt", "yuv420p", "-crf", str(args.crf), "-c:a", "copy",
                 "-movflags", "+faststart", "-t", str(args.duration), args.output])

        size_mb = os.path.getsize(args.output) / 1e6
        print(f"done: {args.output} ({args.width}x{args.height}, {args.duration}s, {size_mb:.1f} MB)")
    finally:
        if args.keep_temp:
            print(f"temp files kept in {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
