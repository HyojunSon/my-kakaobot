"""Shared nearby-line zones and geometric convergence, not breakout forecasts."""
import math
from itertools import combinations
from api.chart_service import line_values

CONVERGENCE_NOTE = "추세선 수렴 중이에요. 수렴이 끝난 뒤 방향을 정하는 움직임이 나올 수 있어요. 위·아래 어느 쪽으로 벗어나 안착하는지 확인하세요."


def line_context(drawings, df, anchor):
    empty = dict(zone_low=anchor, zone_high=anchor, zone_count=0,
                 converging=False, resistance_price=None)
    if anchor is None or df.empty:
        return empty
    dates = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(df.index)}
    last = len(df)-1
    lookback = min(20, last)
    lines = []
    for drawing in drawings:
        try:
            values = line_values(drawing, dates, last, last)
            if values is None or not math.isfinite(values[1]) or values[1] <= 0:
                continue
            prior = line_values(drawing, dates, max(0, last-1), last)
            slope = prior[1]-prior[0] if last else 0
            # Identical stored lines do not constitute multiple independent lines.
            if any(abs(values[1]-p) < anchor*1e-8 and abs(slope-s) < anchor*1e-8 for p, s in lines):
                continue
            lines.append((values[1], slope))
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    low = high = anchor
    zone = []
    for price, slope in sorted(lines, key=lambda item: (abs(item[0]-anchor), item[0])):
        new_low, new_high = min(low, price), max(high, price)
        # Full-zone width <=5%, never an unbounded chain of nearby pairs.
        if new_high/new_low <= 1.05+1e-9:
            low, high = new_low, new_high
            zone.append((price, slope))
    converging = False
    for (p1, s1), (p2, s2) in combinations(zone, 2):
        delta, speed = p1-p2, s1-s2
        if not lookback or abs(speed) < anchor*1e-8:
            continue
        crossing = -delta/speed
        past_gap = abs(delta-speed*lookback)
        # Must still be approaching, not already crossed and expanding.
        if crossing >= 0 and abs(delta) <= past_gap*.9:
            converging = True
            break
    close = float(df.Close.iloc[-1])
    resistance = min((p for p, _ in lines if p > max(high, close)*(1+1e-9)), default=None)
    return dict(zone_low=low, zone_high=high, zone_count=len(zone),
                converging=converging, resistance_price=resistance)
