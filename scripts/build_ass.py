#!/usr/bin/env python3
"""Build a single styled ASS subtitle file from a cue JSON.

Input JSON schema:
{
  "video": {"width": 720, "height": 1280},
  "cues": [
    {"start": "0:00:00.04", "end": "0:00:04.73",
     "en": "So my question to you today is\\Nwhat do you practice every day?",
     "zh": "我今天想问你的是\\N你每天都在练习什么？"}
  ]
}

Outputs a single .ass file with both Chinese and English in each Dialogue line,
using {\\rEn} to switch from the Zh style to the En style mid-line. This keeps
the gap between zh and en consistent regardless of how many lines each has.
"""
import json, sys, argparse

def _make_header(w, h):
    """Generate ASS header with styles adapted to the video aspect ratio."""
    if h > w:
        # Vertical video (e.g. 720x1280)
        zh_size, en_size = 42, 35
        zh_outline, en_outline = 5, 3
        shadow = 2
        margin_v = 112
        margin_lr = 30
    else:
        # Horizontal video (e.g. 854x480, 1920x1080)
        zh_size, en_size = 22, 18
        zh_outline, en_outline = 3, 2
        shadow = 1
        margin_v = 24
        margin_lr = 20

    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Zh,STHeiti,{zh_size},&H0000FFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{zh_outline},{shadow},2,{margin_lr},{margin_lr},{margin_v},1
Style: En,Helvetica,{en_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{en_outline},{shadow},2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

def _to_ass_ts(ts: str) -> str:
    """Convert 'HH:MM:SS.mmm' or 'H:MM:SS.cc' to ASS format 'H:MM:SS.cc'.

    ASS spec requires single-digit hour and exactly 2-digit centiseconds.
    Whisper/SRT timestamps use 3-digit milliseconds — the third digit must
    be truncated (rounded) to avoid libass misinterpretation.
    """
    parts = ts.split(":")
    h = int(parts[0])
    m = int(parts[1])
    sec_frac = parts[2].split(".")
    s = int(sec_frac[0])
    # Convert fractional part to centiseconds (2 digits)
    frac = sec_frac[1] if len(sec_frac) > 1 else "0"
    # Pad or truncate to exactly 3 digits, then take first 2 (centiseconds)
    frac = (frac + "000")[:3]
    cs = round(int(frac) / 10)
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build(cues, video):
    out = _make_header(video["width"], video["height"])
    for c in cues:
        zh = c.get("zh", "").strip()
        en = c.get("en", "").strip()
        if not zh and not en:
            continue
        # Zh style is the Dialogue default; switch to En with {\rEn}
        if zh and en:
            text = zh + r"\N{\rEn}" + en
        elif zh:
            text = zh
        else:
            text = r"{\rEn}" + en
        start = _to_ass_ts(c['start'])
        end = _to_ass_ts(c['end'])
        out += f"Dialogue: 0,{start},{end},Zh,,0,0,0,,{text}\n"
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cues_json")
    ap.add_argument("--out-prefix", required=True,
                    help="output path prefix; writes <prefix>.ass")
    args = ap.parse_args()

    data = json.load(open(args.cues_json))
    video = data.get("video", {"width": 720, "height": 1280})
    cues = data["cues"]

    path = f"{args.out_prefix}.ass"
    open(path, "w").write(build(cues, video))
    print(path)

if __name__ == "__main__":
    main()
