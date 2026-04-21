#!/usr/bin/env python3
"""Parse whisper.cpp word-level SRT (produced by `whisper-cli -ml 1 -sow`) into
a JSON list of {start, end, word} entries. Claude reads this to group words
into semantic cues."""
import json, re, sys

def parse(path):
    content = open(path).read()
    blocks = re.split(r'\n\n+', content.strip())
    words = []
    for b in blocks:
        lines = b.strip().split('\n')
        if len(lines) < 3:
            continue
        m = re.match(r'(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)', lines[1])
        if not m:
            continue
        start = m.group(1).replace(',', '.')
        end = m.group(2).replace(',', '.')
        word = ' '.join(lines[2:]).strip()
        words.append({"start": start, "end": end, "word": word})
    return words

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: parse_words.py <words.srt>", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(parse(sys.argv[1]), ensure_ascii=False, indent=2))
