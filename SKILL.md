---
name: bilingual-video-sub
description: Generate and burn bilingual Chinese+English subtitles onto a local video file or a YouTube URL. Works with both vertical (9:16) and horizontal (16:9) video — styles auto-adapt. The user gets back an mp4 with hard-burned bilingual subs plus sidecar .srt files for English transcription and Chinese translation. Use this skill whenever the user asks to "下载视频并加中英字幕", "transcribe and translate this video", "生成中英双语字幕", "烧录字幕到视频", "add bilingual subs", "给视频配中文字幕", or gives a video path / YouTube URL together with any request involving subtitles, transcription, or burning captions. Handles audio extraction, phrase-level Whisper transcription, semantic cue grouping, LLM translation, and ffmpeg libass burn-in.
---

# bilingual-video-sub

End-to-end pipeline: **video (local or YouTube) → English SRT + Chinese SRT + bilingual-burned mp4**.

The LLM calling this skill (you) does the translation and semantic cue grouping directly — do NOT delegate those to external translation tools. We've tried translate-ollama and it breaks SRT timing; the quality of Claude translating each cue with full context is both better and structurally safer.

## Prerequisites

Run these checks once at the start of a task. If anything is missing, tell the user and suggest the install command — don't silently install.

```bash
command -v whisper-cli       # brew install whisper-cpp
command -v ffmpeg            # must be libass-enabled; see note below
command -v yt-dlp            # brew install yt-dlp  (only if YouTube URL)
ls ~/.local/share/whisper-models/ggml-large-v3-turbo.bin  # whisper model
ffmpeg -h filter=ass 2>&1 | grep -q "Render ASS" && echo OK || echo NO_LIBASS
```

**libass note:** Homebrew's default `ffmpeg` formula is NOT compiled with libass, so the `ass` / `subtitles` filters will be missing. If the check prints `NO_LIBASS`, install the tap build:

```bash
brew uninstall --ignore-dependencies ffmpeg
brew tap homebrew-ffmpeg/ffmpeg
brew install homebrew-ffmpeg/ffmpeg/ffmpeg
```

**Whisper model:** if missing, download once:

```bash
mkdir -p ~/.local/share/whisper-models
curl -L -o ~/.local/share/whisper-models/ggml-large-v3-turbo.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
```

`large-v3-turbo` (~1.6 GB) is the sweet spot on Apple Silicon: near-`large-v3` accuracy at roughly 4× the speed.

## Workflow

Work in `~/Downloads/` by default unless the user specifies otherwise. Use the video's basename (or YouTube ID) as the working prefix `$PREFIX`.

### 1. Obtain the video

- **YouTube URL**: `yt-dlp -f "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b" --merge-output-format mp4 -o "%(id)s.%(ext)s" "<URL>"`
- **Local path**: use as-is.

**Verify:** check that audio and video streams start at the same time — yt-dlp sometimes merges them with a small offset:

```bash
ffprobe -v quiet -print_format json \
  -show_entries stream=codec_type,start_time,start_pts "$PREFIX.mp4"
```

Both `start_time` values should be `0.000000`. If they differ, remux to align:

```bash
ffmpeg -y -i "$PREFIX.mp4" -c copy -map 0 "$PREFIX.aligned.mp4"
mv "$PREFIX.aligned.mp4" "$PREFIX.mp4"
```

### 2. Extract audio

```bash
ffmpeg -y -i "$PREFIX.mp4" -ar 16000 -ac 1 -c:a pcm_s16le "$PREFIX.wav"
```

16 kHz mono PCM is what whisper.cpp expects. Any other format forces whisper to re-resample internally and is slower.

**Verify:** confirm WAV duration matches video duration (should be <0.1s difference):

```bash
video_dur=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$PREFIX.mp4")
wav_dur=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$PREFIX.wav")
python3 -c "v=$video_dur; w=$wav_dur; d=abs(v-w); print(f'Δ={d:.3f}s'); assert d<0.1, f'Duration mismatch: {d:.3f}s'"
```

### 3. Word-level transcription

```bash
whisper-cli -m ~/.local/share/whisper-models/ggml-large-v3-turbo.bin \
  -f "$PREFIX.wav" -l en -ml 1 -sow \
  -osrt -of "$PREFIX.words"
```

- `-ml 1` = one token per "segment" (word-level)
- `-sow` = split on word boundary (not sub-word tokens)
- Output: `$PREFIX.words.srt` with precise per-word start/end timestamps.

For non-English source audio, pass `-l <code>` accordingly, and adjust the "translate to Chinese" step below into "translate into the target language."

**Verify:** cross-check Whisper's first word timestamp against silence detection — they should agree within ±0.5s:

```bash
silence_end=$(ffmpeg -i "$PREFIX.wav" -af silencedetect=noise=-30dB:d=0.5 -f null - 2>&1 \
  | grep -m1 'silence_end' | sed -n 's/.*silence_end: \([0-9.]*\).*/\1/p')
echo "Silence ends at ${silence_end}s"
```

If the first word timestamp diverges from `silence_end` by more than 0.5s, Whisper timing is unreliable — consider a different model or re-extracting the audio.

### 4. Parse words into JSON

```bash
python3 <skill-dir>/scripts/parse_words.py "$PREFIX.words.srt" > "$PREFIX.words.json"
```

You now have a flat list of `{start, end, word}` entries with timestamps in `HH:MM:SS.mmm` format.

**Verify:** spot-check first/last word:

```bash
python3 -c "
import json
words = json.load(open('$PREFIX.words.json'))
print(f'First: {words[0][\"start\"]} \"{words[0][\"word\"]}\"')
print(f'Last:  {words[-1][\"end\"]} \"{words[-1][\"word\"]}\"')
print(f'Total: {len(words)} words')
"
```

### 5. Group words into semantic cues + translate (YOU DO THIS)

This is the step where your judgement matters most — scripts can't do it well.

Read `$PREFIX.words.json`. Produce a JSON file `$PREFIX.cues.json` with this schema:

```json
{
  "video": {"width": 720, "height": 1280},
  "cues": [
    {
      "start": "00:00:00.040",
      "end":   "00:00:04.730",
      "en":    "So my question to you today is what do you practice every day?",
      "zh":    "我今天想问你的是 你每天都在练习什么？"
    }
  ]
}
```

Set `video.width` and `video.height` to the **actual** video dimensions (get them from ffprobe). This controls style auto-adaptation in Step 6.

**Critical: timestamps must come directly from words.json.** `cue.start` = first word's `start`, `cue.end` = last word's `end`. Never hand-type or estimate timestamps — this was the source of audio sync bugs in real use.

**Grouping rules** (why they matter, not just what to do):

1. **One cue = one complete sense unit.** Usually a sentence or independent clause. Don't let a clause straddle two cues; that's what makes subtitles feel "out of sync" even when the timing is technically correct — the reader's eye lands on a fragment.
2. **Cue timing comes from the word list.** `start` = first word's start, `end` = last word's end. This is why we took word-level — you get to pick the boundaries, not whisper's coarse segmenter.
3. **Cue length 1–10 seconds.** Shorter than 1 s is jarring (flashes by); longer than 10 s is too much text at once. If a sentence is too long, break at a natural sub-clause boundary (comma, "and", "because").
4. **Merge whisper artifacts.** Whisper sometimes emits odd repeats or mid-word cuts ("you'll think / Trivial thing"). Fix these in the English text when grouping — the audio is the ground truth, and you can hear it via the original video if unsure.

**Line-wrapping rules** depend on orientation:

| | Vertical (h > w) | Horizontal (h ≤ w) |
|---|---|---|
| Max Chinese lines/cue | 2 | 1 |
| Max English lines/cue | 2 | 1 |
| Max Chinese chars/line | 12 | ~20 (depends on resolution) |
| Max English chars/line | ~34 | ~50 |

- Chinese has no spaces → libass won't auto-wrap. You must insert `\N` manually **only when the line exceeds the limit**.
- **Only break if the total text exceeds the per-line limit.** If it fits in one line, don't split — a short second line reads worse than keeping it on one line.
- At most 2 lines per cue (vertical) or 1 line per cue (horizontal). If it needs more, split into two cues.

**Translation rules:**

- Translate each cue as a stand-alone unit but with awareness of surrounding cues.
- Idiomatic Chinese > literal word-by-word. Reorder clauses to match natural Chinese flow.
- Cultural references: if a Western/Indian/English-specific image would puzzle a Chinese reader, add a short inline annotation with a smaller font using ASS override: `{\fs28}（简短说明）`. Use this sparingly — only when the reader would otherwise lose the meaning.
- Preserve the speaker's rhetorical structure: parallel questions stay parallel, repetitions stay repetitions.

### 5b. Verify cues

```bash
python3 <skill-dir>/scripts/verify_cues.py "$PREFIX.words.json" "$PREFIX.cues.json"
```

For horizontal video, enforce single-line cues:

```bash
python3 <skill-dir>/scripts/verify_cues.py "$PREFIX.words.json" "$PREFIX.cues.json" \
  --max-zh-lines 1 --max-en-lines 1
```

This checks:
- Every `cue.start` matches a word's `start` in words.json
- Every `cue.end` matches a word's `end` in words.json
- Adjacent cues don't overlap
- Line counts per cue are within limits
- Cue durations are reasonable (warns on <0.5s or >10s)

**Do not skip this step.** If verify_cues.py reports errors, fix cues.json before proceeding.

### 6. Build the ASS file

```bash
python3 <skill-dir>/scripts/build_ass.py "$PREFIX.cues.json" --out-prefix "$PREFIX"
```

This writes a single `$PREFIX.ass` with both languages in each Dialogue line. Chinese is the default style (`Zh`), and English switches in via `{\rEn}` inline override. This keeps the gap between zh and en lines consistent regardless of how many lines each has.

**Auto-adaptive styles:** `build_ass.py` reads `video.width` and `video.height` from `cues.json` and picks styles accordingly:

| | Vertical (h > w) | Horizontal (h ≤ w) |
|---|---|---|
| Chinese font | STHeiti Bold, 42px | STHeiti Bold, 22px |
| English font | Helvetica Bold, 35px | Helvetica Bold, 18px |
| Chinese outline | 5px | 3px |
| English outline | 3px | 2px |
| Shadow | 2px | 1px |
| MarginV | 112 | 24 |
| Color | Yellow zh / White en | Yellow zh / White en |

**Timestamp format:** `build_ass.py` automatically converts input timestamps (e.g. `00:00:49.540`) to ASS-spec format (`0:00:49.54`). ASS uses `H:MM:SS.cc` (2-digit centiseconds), not milliseconds — see "Failure modes" for why this matters.

If the user wants different fonts/sizes/colors, edit the `_make_header()` function in `build_ass.py` or post-process the generated `.ass` file before the burn step.

**Verify:** confirm Dialogue count matches cue count:

```bash
cue_count=$(python3 -c "import json; print(len(json.load(open('$PREFIX.cues.json'))['cues']))")
dialog_count=$(grep -c '^Dialogue:' "$PREFIX.ass")
echo "Cues: $cue_count, Dialogues: $dialog_count"
[ "$cue_count" = "$dialog_count" ] && echo "✓ Match" || echo "✗ MISMATCH"
```

### 7. Burn subtitles into video

**Vertical video** (h > w):

```bash
ffmpeg -y -i "<video>" \
  -vf "scale=720:1280:flags=lanczos,ass=$PREFIX.ass:fontsdir=/System/Library/Fonts" \
  -c:v libx264 -preset medium -crf 20 -c:a aac -b:a 128k \
  "$PREFIX.subtitled.mp4"
```

**Horizontal video** (h ≤ w) — keep original resolution:

```bash
ffmpeg -y -i "<video>" \
  -vf "ass=$PREFIX.ass:fontsdir=/System/Library/Fonts" \
  -c:v libx264 -preset medium -crf 20 -c:a aac -b:a 128k \
  "$PREFIX.subtitled.mp4"
```

Notes:
- `fontsdir=/System/Library/Fonts` is required because libass's fontconfig on macOS won't otherwise find STHeiti / Hiragino Sans GB. Without it, Chinese renders as tofu boxes.
- Only one `ass=` filter (single merged file) — simpler and no filter-chain comma escaping issues.
- CRF 20 is visually lossless for social-media re-upload; drop to 23 for smaller files.

**Verify:** take 3 frame-accurate screenshots (first cue, middle cue, last cue) to spot-check subtitle content and timing:

```bash
python3 -c "
import json
cues = json.load(open('$PREFIX.cues.json'))['cues']
picks = [0, len(cues)//2, len(cues)-1]
for i in picks:
    ts = cues[i]['start']
    print(f'Cue {i+1} @ {ts}: zh={cues[i][\"zh\"][:20]}...')
" 

# Use -ss AFTER -i for frame-accurate seeking (not before, which does keyframe seek)
ffmpeg -y -i "$PREFIX.subtitled.mp4" -ss <cue1_start> -frames:v 1 -q:v 2 check_start.jpg 2>/dev/null
ffmpeg -y -i "$PREFIX.subtitled.mp4" -ss <cue_mid_start> -frames:v 1 -q:v 2 check_mid.jpg 2>/dev/null
ffmpeg -y -i "$PREFIX.subtitled.mp4" -ss <cue_last_start> -frames:v 1 -q:v 2 check_end.jpg 2>/dev/null
```

Visually confirm that the subtitle text in each screenshot matches the expected cue for that timestamp. If it doesn't, the ASS timing is off — check the ASS file for format issues.

### 8. Generate SRT sidecars

Produce `.srt` files so the user can edit the translation and re-burn without re-transcribing:

```bash
python3 -c "
import json
data = json.load(open('$PREFIX.cues.json'))
for lang in ('en','zh'):
    with open(f'$PREFIX.{lang}.srt','w') as f:
        for i,c in enumerate(data['cues'],1):
            text = c[lang].replace(r'\\N','\n')
            f.write(f'{i}\n{c[\"start\"].replace(\".\",\",\")} --> {c[\"end\"].replace(\".\",\",\")}\n{text}\n\n')
"
```

Then report the three deliverables to the user:
- `$PREFIX.subtitled.mp4` (burned-in video)
- `$PREFIX.en.srt` (English transcription, editable)
- `$PREFIX.zh.srt` (Chinese translation, editable)

And open the video: `open $PREFIX.subtitled.mp4`.

## Failure modes seen in the wild

- **Subtitles consistently late, drift grows over time** → ASS timestamp format error. ASS spec uses `H:MM:SS.cc` (2-digit centiseconds), but if you write `HH:MM:SS.mmm` (3-digit milliseconds) directly, libass misinterprets the third digit and the error accumulates. `build_ass.py` handles this conversion automatically via `_to_ass_ts()` — never write raw millisecond timestamps into ASS Dialogue lines.
- **Subtitles out of sync with audio** → cue timestamps were hand-typed instead of copied from words.json. Always use verify_cues.py to confirm alignment before building ASS.
- **Chinese renders as boxes (tofu)** → you forgot `fontsdir=/System/Library/Fonts`, or STHeiti/Hiragino Sans GB aren't present. PingFang SC is NOT reliably available via fontconfig on macOS — prefer STHeiti.
- **ffmpeg error "No option name near '...srt'"** → libass missing. See the tap install above.
- **Subtitles drift out of sync after cue 3+** → you reused whisper's coarse segment timestamps instead of word-level. Rerun step 3 with `-ml 1 -sow`.
- **Subtitles too large or off-screen on horizontal video** → `video.width`/`video.height` in cues.json is wrong, or build_ass.py was run on a cues.json with no video dimensions. Always set the actual video resolution.
- **Chinese text overflows horizontally** → no manual `\N` (libass can't wrap space-less CJK). Check the line-wrapping rules table for your video orientation.
- **Inconsistent gap between zh and en lines** → you're using two separate `.ass` files with fixed `MarginV`. Switch to the single-file merged approach (current `build_ass.py` does this) where both languages share a Dialogue line with `{\rEn}` style switch.
- **Screenshot shows wrong cue at a given time** → you used `-ss` before `-i` (keyframe seek). Always put `-ss` after `-i` for frame-accurate seeking when verifying timing.

## Don't

- Don't use `translate-ollama` or any SRT-file-level translation tool; they trash the cue structure.
- Don't use whisper's default segment-level timestamps for the final cues; they merge sentences and cut mid-phrase.
- Don't hardcode `PingFang SC` as the font — it's not in fontconfig on all macOS versions.
- Don't `--no-check-certificates` or any security-weakening flag on yt-dlp.
- Don't write raw millisecond timestamps into ASS files — always go through `build_ass.py` which converts to centisecond format.
- Don't hand-type or estimate cue timestamps — always copy from words.json and verify with verify_cues.py.
- Don't use `-ss` before `-i` when taking verification screenshots — it does keyframe seeking and may be off by seconds.
