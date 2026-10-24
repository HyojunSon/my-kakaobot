"""Explainable triangle/wedge similarity checks; never probability forecasts."""
import math
from itertools import combinations
import numpy as np
from api.chart_service import line_values

PATTERN_NAMES = dict(ascending="상승 삼각수렴", descending="하락 삼각수렴",
                     symmetrical="대칭 삼각수렴", rising_wedge="상승 쐐기", falling_wedge="하락 쐐기")


def _pivots(values, low=False):
    points = [i for i in range(2, len(values)-2)
              if values[i] == (min(values[i-2:i+3]) if low else max(values[i-2:i+3]))]
    spaced = []
    for i in points:
        if not spaced or i-spaced[-1] >= 4:
            spaced.append(i)
    return spaced


def _kind(upper_slope, lower_slope, flat):
    if upper_slope >= lower_slope:
        return None
    if abs(upper_slope) <= flat and lower_slope > flat:
        return "ascending"
    if upper_slope < -flat and abs(lower_slope) <= flat:
        return "descending"
    if upper_slope < -flat and lower_slope > flat:
        return "symmetrical"
    if upper_slope > flat and lower_slope > flat:
        return "rising_wedge"
    if upper_slope < -flat and lower_slope < -flat:
        return "falling_wedge"
    return None


def detect_pattern(df, drawings=()):
    """Fit using history before the two most recent bars; check them separately.

    Requires actual alternating price contacts, narrowing boundaries, and
    containment. Stored line geometry alone is not enough. Candidate horizons
    and tolerances are initial heuristics, not calibrated hit-rate estimates.
    """
    if len(df) < 26 or not {"High", "Low", "Close"}.issubset(df.columns):
        return None
    close, high, low = (df[k].to_numpy(dtype=float) for k in ("Close", "High", "Low"))
    if not all(np.isfinite(v).all() for v in (close[-100:], high[-100:], low[-100:])):
        return None
    if np.any(low[-100:] <= 0):
        return None
    dates = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(df.index)}
    end = len(df)-3
    candidates = []
    for window in (24, 40, 60, 90):
        start = end-window+1
        if start < 0:
            continue
        h, l, c = high[start:end+1], low[start:end+1], close[start:end+1]
        previous = np.r_[close[max(0, start-1)], c[:-1]]
        atr = float(np.median(np.maximum(h-l, np.maximum(abs(h-previous), abs(l-previous)))))
        scale = max(atr, float(np.median(c))*.002)
        tolerance = max(scale*.35, float(np.median(c))*.003)
        ups, downs = _pivots(h), _pivots(l, low=True)
        if len(ups) < 2 or len(downs) < 2:
            continue
        boundaries = []
        for d in drawings:
            try:
                values = line_values(d, dates, start, end)
                if values is None or not all(math.isfinite(v) and v > 0 for v in values):
                    continue
                slope = (values[1]-values[0])/(window-1)
                boundaries.append((values[0], slope, "saved"))
            except (KeyError, ValueError, TypeError, OverflowError):
                continue
        # Discover candidates even when no manual triangle has been drawn.
        for prices, points in ((h, ups), (l, downs)):
            slope, intercept = np.polyfit(points, prices[points], 1)
            boundaries.append((float(intercept), float(slope), "candles"))
        unique = []
        for item in boundaries:
            if not any(abs(item[0]-v[0]) < tolerance*.1 and
                       abs(item[1]-v[1])*window < tolerance*.1 for v in unique):
                unique.append(item)
        for first, second in combinations(unique, 2):
            upper, lower = (first, second) if first[0] > second[0] else (second, first)
            kind = _kind(upper[1], lower[1], scale*.5/window)
            if kind is None:
                continue
            x = np.arange(window)
            top, bottom = upper[0]+upper[1]*x, lower[0]+lower[1]*x
            initial_width, final_width = top[0]-bottom[0], top[-1]-bottom[-1]
            if (bottom.min() <= 0 or final_width <= tolerance or initial_width <= 0
                    or final_width/initial_width > .8):
                continue
            apex = initial_width/(lower[1]-upper[1])
            if not window-1 < apex <= window*3:
                continue
            contained = np.mean((c >= bottom-tolerance) & (c <= top+tolerance))
            if contained < .85 or np.mean(h <= top+tolerance) < .75 or np.mean(l >= bottom-tolerance) < .75:
                continue
            upper_hits = [i for i in ups if abs(h[i]-top[i]) <= tolerance]
            lower_hits = [i for i in downs if abs(l[i]-bottom[i]) <= tolerance]
            if len(upper_hits) < 2 or len(lower_hits) < 2:
                continue
            # Same-bar touches cannot establish ordering of price swings.
            overlap = set(upper_hits) & set(lower_hits)
            events = sorted([(i, "u") for i in upper_hits if i not in overlap]
                            + [(i, "l") for i in lower_hits if i not in overlap])
            alternating = sum(a[1] != b[1] for a, b in zip(events, events[1:]))
            if alternating < 3:
                continue
            now_x, prev_x = window+1, window
            top_now, bottom_now = upper[0]+upper[1]*now_x, lower[0]+lower[1]*now_x
            top_prev, bottom_prev = upper[0]+upper[1]*prev_x, lower[0]+lower[1]*prev_x
            if top_now <= bottom_now or bottom_now <= 0:
                continue
            clearance = max(scale*.25, close[-1]*.002)
            if close[-1] > top_now+clearance:
                state = "up_holding" if close[-2] > top_prev+clearance else "up_attempt"
            elif close[-1] < bottom_now-clearance:
                state = "down_holding" if close[-2] < bottom_prev-clearance else "down_attempt"
            elif close[-2] > top_prev+clearance:
                state = "failed_up"
            elif close[-2] < bottom_prev-clearance:
                state = "failed_down"
            else:
                state = "forming"
            if close[-1] > top_now*1.15 or close[-1] < bottom_now*.85:
                continue
            volume_contracting = False
            breakout_volume_ratio = None
            if "Volume" in df:
                v = df.Volume.to_numpy(dtype=float)
                first_volume = float(np.mean(v[start:start+window//2]))
                second_volume = float(np.mean(v[start+window//2:end+1]))
                volume_contracting = first_volume > 0 and second_volume < first_volume*.8
                average = float(np.mean(v[-21:-1]))
                if average > 0 and math.isfinite(float(v[-1])):
                    breakout_volume_ratio = float(v[-1])/average
            score = contained*3+alternating*.25+(1-final_width/initial_width)
            score += min(len(upper_hits)+len(lower_hits), 10)*.1
            candidates.append(dict(kind=kind, name=PATTERN_NAMES[kind], state=state,
                                   upper=top_now, lower=bottom_now, window=window,
                                   upper_touches=len(upper_hits), lower_touches=len(lower_hits),
                                   start_date=df.index[start].strftime("%Y-%m-%d"),
                                   formation_end=df.index[end].strftime("%Y-%m-%d"),
                                   source="saved" if upper[2] == lower[2] == "saved" else "candles_or_mixed",
                                   volume_contracting=bool(volume_contracting),
                                   breakout_volume_ratio=breakout_volume_ratio, score=score))
    return max(candidates, key=lambda item: item["score"], default=None)


def pattern_messages(pattern, index=False):
    if pattern is None:
        return [], []
    price = (lambda p: f"{p:,.2f}pt") if index else (lambda p: f"{p:,.0f}원")
    status = [f"차트 패턴: {pattern['name']}과 유사",
              f"패턴 하단 {price(pattern['lower'])} / 상단 {price(pattern['upper'])}"]
    if pattern["volume_contracting"]:
        status.append("수렴 과정에서 거래량도 줄고 있어요.")
    bias = dict(ascending="저점이 높아져 상단 돌파를 시도할 수 있어요.",
                descending="고점이 낮아져 하단 이탈에 주의할 구간이에요.",
                symmetrical="매수·매도 힘이 좁혀지는 중이라 아직 방향을 정하기 어려워요.",
                rising_wedge="상승 폭이 좁아져 아래로 밀리는 경우를 경계하세요.",
                falling_wedge="하락 폭이 좁아져 위로 반등하는 경우를 살펴볼 수 있어요.")[pattern["kind"]]
    scenario = {
        "forming": bias + " 상단 위 안착 시 상승 연장, 하단 이탈 시 추가 하락 가능성을 살펴보세요.",
        "up_attempt": "상단을 넘는 움직임이에요. 마감과 재접촉에서 버티면 상승이 이어질 수 있고, 다시 안으로 밀리면 돌파 실패에 주의하세요.",
        "down_attempt": "하단을 벗어나는 움직임이에요. 회복하지 못하면 하락이 이어질 수 있어요. 다시 구간 안에 들어오는지도 확인하세요.",
        "up_holding": "이전 일봉이 상단을 넘었고 현재도 위에 있어요. 상단을 다시 지키면 상승 연장, 구간 안으로 돌아오면 돌파 실패를 살펴보세요.",
        "down_holding": "이전 일봉이 하단을 이탈했고 현재도 아래에 있어요. 하단 회복 전까지 추가 하락에 주의하세요.",
        "failed_up": "상단을 넘었던 가격이 구간 안으로 돌아왔어요. 돌파 실패 가능성이 있어 상승을 단정하지 마세요.",
        "failed_down": "하단을 이탈했던 가격이 구간 안으로 회복했어요. 하락을 단정하지 말고 회복 유지 여부를 확인하세요.",
    }[pattern["state"]]
    if pattern["state"] in {"up_attempt", "down_attempt", "up_holding", "down_holding"}:
        ratio = pattern["breakout_volume_ratio"]
        scenario += " 거래량 증가도 동반됐어요." if ratio is not None and ratio >= 1.5 else " 거래량 증가 여부도 함께 확인하세요."
    return status, ["패턴별 전망\n"+scenario+" 패턴이 맞거나 예상대로 움직인다는 보장은 없어요."]
