"""Conservative short bubbles; actual wrapping depends on the Kakao client."""
import unicodedata
import re

OPINION_HEADING = "【매매 의견】"


def readable_analysis(lines):
    """Labels and spacing carry hierarchy; decoration does not carry meaning."""
    cleaned, in_opinion = [], False
    for line in lines:
        if line == OPINION_HEADING:
            in_opinion = True
        text = re.sub(r"^[\U0001f000-\U0001faff\u2300-\u27ff\ufe0f\u200d]+\s*", "", line)
        if in_opinion:
            if line.startswith("🛒"):
                text = ("주식 매수\n" + text.removeprefix("주식 매수: ") if text.startswith("주식 매수:")
                        else "살 때\n" + text.removeprefix("살 때: "))
            elif line.startswith("💰"):
                text = ("보유 주식\n" + text.removeprefix("보유 주식: ") if text.startswith("보유 주식:")
                        else "팔 때\n" + text.removeprefix("팔 때: "))
            elif line.startswith("🚨"):
                text = "계획 재검토\n" + text
            elif line.startswith("📈"):
                text = "예상 수익률\n" + text
        cleaned.append(text)
    text = "【현재 상태】\n" + "\n".join(cleaned)
    status, marker, opinion = text.partition(OPINION_HEADING)
    if marker:
        # Each opinion is a complete paragraph: entry, exit, then caution.
        # Join original authored entries, preserving heading/body together.
        boundary = cleaned.index(OPINION_HEADING)
        paragraphs = [entry for entry in cleaned[boundary+1:] if entry]
        return status.rstrip() + "\n\n" + OPINION_HEADING + "\n" + "\n\n".join(paragraphs)
    return text


def chart_bubbles(text):
    """Status and opinion are authored sections, never length-based slices."""
    status, marker, opinion = text.partition(OPINION_HEADING)
    if not marker:
        return [text.strip()] if text.strip() else []
    return [status.strip(), OPINION_HEADING + "\n" + opinion.strip()]


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
