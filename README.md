# vertical-shorts-maker

Build a 1080x1920 vertical Short from still images + a voiceover, with burned-in captions — one command, no editing app, no API keys.

This is the exact workflow used to make 10-second motivation / psychology Shorts (1080x1920, 10.0s, 25-word voiceover): Ken Burns slow-zoom stills, voiceover + generated whoosh/impact sound effects, and captions burned in with ffmpeg `drawtext`.

## Why drawtext, not the subtitles filter?

On some ffmpeg builds the `subtitles` filter reads the SRT and renders **no text at all** — the video comes out clean. `drawtext` with a textfile per line and `enable='between(t,start,end)'` works everywhere, so this tool uses that.

## Install

```bash
# ffmpeg + ffprobe must be on PATH
ffmpeg -version

# Python 3.10+; numpy is only needed for the generated SFX
pip install -r requirements.txt
```

No API keys. No network. Nothing is uploaded anywhere.

## Quick start — demo with no assets

Make 3 test images and a test voiceover with ffmpeg, then build a Short:

```bash
for i in 1 2 3; do
  ffmpeg -y -f lavfi -i color=c=0x0B1220:s=1080x1920:d=1 -frames:v 1 img$i.jpg
done
ffmpeg -y -f lavfi -i "sine=frequency=220:duration=9" -c:a libmp3lame voice.mp3

python3 shorts_maker.py \
  --images img1.jpg img2.jpg img3.jpg \
  --voiceover voice.mp3 \
  --captions examples/spotlight-effect/captions.json \
  --output short.mp4

ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,duration -of default=noprint_wrappers=1 short.mp4
```

Expected: `1080x1920`, about `10` seconds.

## Real use

```bash
python3 shorts_maker.py \
  --images scene1.jpg scene2.jpg scene3.jpg \
  --voiceover voiceover.mp3 \
  --captions captions.json \
  --output my-short.mp4
```

### Captions file

JSON list. Timings are optional — without them, time is split across captions in proportion to word count, scaled to the **measured** voiceover length (ffprobe), because TTS length varies:

```json
[
  {"text": "Nobody watches you as much as you think."},
  {"text": "It's called the spotlight effect.", "start": 3.0, "end": 4.8},
  {"text": "Everyone is too busy worrying about themselves."},
  {"text": "So stop waiting. Start now."}
]
```

See `examples/spotlight-effect/captions.json` — the captions from a real 10-second Short about the spotlight effect.

## Options

| Flag | Default | What it does |
| --- | --- | --- |
| `--duration` | `10` | target length in seconds |
| `--width` / `--height` | `1080` / `1920` | output resolution |
| `--fps` | `30` | frames per second |
| `--voice-delay` | `0.10` | seconds before the voiceover starts |
| `--crf` | `20` | H.264 quality (lower = better / bigger) |
| `--audio-bitrate` | `128k` | AAC bitrate |
| `--no-sfx` | off | skip the generated whoosh / impact sounds |
| `--no-captions` | off | skip burned-in captions |
| `--font` | DejaVuSans-Bold | path to a bold .ttf font |
| `--keep-temp` | off | keep intermediate files for debugging |

Output is H.264 + AAC with `+faststart`, made for direct upload as a YouTube Short.

## How it works

1. **Ken Burns segments** — each image becomes a slow-zoom (`zoompan`) clip, split evenly across the target duration.
2. **Audio mix** — voiceover (delayed 0.1s) + generated SFX: a soft whoosh at each cut and a low impact near the end. Padded to the full duration.
3. **Caption burn** — each caption is split into 1–2 lines and burned in with `drawtext`, shown only between its start and end times.

## License

MIT — see `LICENSE`.
