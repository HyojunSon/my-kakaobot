"""Conservative short bubbles; actual wrapping depends on the Kakao client."""
import unicodedata


def short_bubbles(text, max_chars=350, max_rows=12, columns=42):
    chunks, current, chars, rows = [], [], 0, 0
    for line in text.splitlines():
        # Account for Korean text wrapping, not only explicit newlines.
        width = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in line)
        line_rows = max(1, (width+columns-1)//columns)
        if current and (chars+len(line)+1 > max_chars or rows+line_rows > max_rows):
            chunks.append("\n".join(current))
            current, chars, rows = [], 0, 0
        current.append(line)
        chars += len(line)+1
        rows += line_rows
    if current:
        chunks.append("\n".join(current))
    return chunks
