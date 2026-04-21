#!/usr/bin/env python3
"""Verify cues.json timestamps align precisely with words.json.

Checks:
  1. Every cue.start matches some word's start in words.json
  2. Every cue.end matches some word's end in words.json
  3. Adjacent cues don't overlap
  4. Each cue has at most max_lines of Chinese + English
  5. Cue duration is within 1–10 seconds
"""
import json, sys, argparse


def ts_to_ms(ts: str) -> int:
    """Convert 'HH:MM:SS.mmm' to milliseconds."""
    parts = ts.split(":")
    h, m = int(parts[0]), int(parts[1])
    sec_parts = parts[2].split(".")
    s = int(sec_parts[0])
    ms = int(sec_parts[1]) if len(sec_parts) > 1 else 0
    return h * 3600000 + m * 60000 + s * 1000 + ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("words_json", help="path to words.json")
    ap.add_argument("cues_json", help="path to cues.json")
    ap.add_argument("--max-zh-lines", type=int, default=1,
                    help="max Chinese lines per cue (default 1)")
    ap.add_argument("--max-en-lines", type=int, default=1,
                    help="max English lines per cue (default 1)")
    args = ap.parse_args()

    words = json.load(open(args.words_json))
    data = json.load(open(args.cues_json))
    cues = data["cues"]

    word_starts = {w["start"] for w in words}
    word_ends = {w["end"] for w in words}

    errors = []
    warnings = []

    for i, cue in enumerate(cues):
        label = f"Cue {i+1}"

        # Check start aligns with a word start
        if cue["start"] not in word_starts:
            errors.append(f"{label}: start '{cue['start']}' not found in words.json starts")

        # Check end aligns with a word end
        if cue["end"] not in word_ends:
            errors.append(f"{label}: end '{cue['end']}' not found in words.json ends")

        # Check duration
        dur_ms = ts_to_ms(cue["end"]) - ts_to_ms(cue["start"])
        if dur_ms <= 0:
            errors.append(f"{label}: non-positive duration ({dur_ms}ms)")
        elif dur_ms < 500:
            warnings.append(f"{label}: very short duration ({dur_ms}ms)")
        elif dur_ms > 10000:
            warnings.append(f"{label}: long duration ({dur_ms/1000:.1f}s)")

        # Check line counts
        zh = cue.get("zh", "")
        en = cue.get("en", "")
        zh_lines = zh.count(r"\N") + 1 if zh else 0
        en_lines = en.count(r"\N") + 1 if en else 0
        if zh_lines > args.max_zh_lines:
            errors.append(f"{label}: Chinese has {zh_lines} lines (max {args.max_zh_lines})")
        if en_lines > args.max_en_lines:
            errors.append(f"{label}: English has {en_lines} lines (max {args.max_en_lines})")

        # Check no overlap with previous cue
        if i > 0:
            prev_end = ts_to_ms(cues[i-1]["end"])
            cur_start = ts_to_ms(cue["start"])
            if prev_end > cur_start:
                errors.append(
                    f"Cue {i}/{i+1}: overlap — prev ends at {cues[i-1]['end']}, "
                    f"cur starts at {cue['start']}")

    # Report
    if warnings:
        print(f"⚠ {len(warnings)} warning(s):")
        for w in warnings:
            print(f"  {w}")

    if errors:
        print(f"\n✗ {len(errors)} error(s):")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print(f"\n✓ All {len(cues)} cues verified — timestamps align with words.json")
        sys.exit(0)


if __name__ == "__main__":
    main()
