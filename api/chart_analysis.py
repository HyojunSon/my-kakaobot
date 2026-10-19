"""Deterministic scenarios from user drawings; no model or external AI."""
import math
from api.chart_service import chart_data, line_values


def analyze_chart(stock, snapshot):
    df, drawings = chart_data(stock, snapshot)
    return analysis_text(stock, drawings, df)


def analysis_text(stock, drawings, df):
    import pandas as pd
    if df.empty or len(df) < 2:
        return f"{stock['name']}: 분석에 필요한 일봉이 부족합니다."
    close = float(df.Close.iloc[-1])
    if not math.isfinite(close) or close <= 0:
        raise ValueError("Invalid close")
    index = stock["code"] in {"KOSPI", "KOSDAQ"}
    price = lambda v: f"{v:,.2f}pt" if index else f"{v:,.0f}원"
    last = len(df)-1
    dates = {d.strftime("%Y-%m-%d"): i for i,d in enumerate(df.index)}
    previous = float(df.Close.iloc[-2])
    change = (close/previous-1)*100 if previous > 0 else 0
    lookback = min(5, last)
    base = float(df.Close.iloc[-1-lookback])
    move = (close/base-1)*100 if base > 0 else 0
    lines = [f"{stock['name']} ({stock['code']}) 규칙 분석",
             f"{df.index[-1]:%Y-%m-%d} 일봉 {price(close)} · 전일 대비 {change:+.2f}%",
             f"최근 {lookback}거래일 {move:+.2f}% · 제공처 최신 일봉 기준(장중 미확정 가능)"]
    if len(df) >= 21:
        average = float(df.Volume.iloc[-21:-1].mean())
        if average > 0:
            lines.append(f"거래량: 이전 20일 평균의 {float(df.Volume.iloc[-1])/average:.2f}배(장중은 누적치)")
    levels = []
    skipped = 0
    for drawing in drawings:
        try:
            values = line_values(drawing, dates, last-1, last)
            if values is None or not all(math.isfinite(v) and v > 0 for v in values):
                skipped += 1
                continue
            prev_line, now_line = values
            event = ""
            # Require a 0.2% clearance to avoid treating tiny crossings as breaks.
            if previous <= prev_line and close > now_line*1.002:
                event = "상향 돌파 후보: 다음 종가 유지 확인"
            elif previous >= prev_line and close < now_line*.998:
                event = "하향 이탈 후보: 다음 종가 회복 여부 확인"
            elif float(df.Low.iloc[-1]) <= now_line <= float(df.High.iloc[-1]):
                event = "선 접촉 후 위에서 마감/거래 중: 지지 후보" if close >= now_line else "선 접촉 후 아래에서 마감/거래 중: 저항 후보"
            levels.append((now_line, event))
        except (KeyError, ValueError, TypeError, OverflowError):
            skipped += 1
    supports = sorted({v for v,e in levels if v <= close}, reverse=True)
    resistances = sorted({v for v,e in levels if v > close})
    if levels:
        nearest = min(levels, key=lambda item: abs(close-item[0]))
        if nearest[1]:
            lines.append(nearest[1])
        lines.append("지지 후보: " + (price(supports[0]) if supports else "저장선에서 확인되지 않음"))
        lines.append("저항 후보: " + (price(resistances[0]) if resistances else "저장선에서 확인되지 않음"))
    if supports and len(df) >= 15:
        prev_close = df.Close.shift(1)
        tr = pd.concat([df.High-df.Low, (df.High-prev_close).abs(), (df.Low-prev_close).abs()], axis=1).max(axis=1)
        atr = float(tr.iloc[-14:].mean())
        support = supports[0]
        if not math.isfinite(atr) or atr <= 0:
            lines.append("가격 제안 보류: 변동성 데이터 부족")
        else:
            width = min(atr*.25, support*.01)
            lower, upper = support-width, support+width
            invalid = support-max(atr*.5, support*.01)
            target = resistances[0] if resistances else None
            if lower > 0 and invalid > 0 and target is not None and target > upper:
                ratio = (target-upper)/(upper-invalid)
                if ratio >= 1.5:
                    lines.append(f"매수 검토: {price(lower)}~{price(upper)} 접촉 후 종가 회복 확인 시")
                    lines.append(f"매도 검토: {price(target)} 부근 분할 정리 · 예상 손익비 {ratio:.1f}배(수수료 제외)")
                    lines.append(f"무효화: {price(invalid)} 아래 종가 마감 시 지지 시나리오 재검토")
                    if close > upper:
                        lines.append("현재는 매수 구간 밖: 추격보다 재접근 대기")
                else:
                    lines.append("신규 매수 관망: 가까운 저항 대비 손익비가 1.5배 미만")
                    lines.append(f"보유분 매도 검토: 저항 {price(target)} 부근 반응 확인")
            else:
                lines.append("매수·매도 가격 제안 보류: 상하단 저장선으로 유효한 구간을 만들 수 없음")
    else:
        lines.append("매수·매도 가격 제안 보류: 유효한 지지선 또는 과거 일봉 부족")
    if not levels:
        lines.append("분석 가능한 HTS 저장선이 없습니다.")
    if skipped:
        lines.append(f"날짜·가격 확인 불가 선 {skipped}개 제외")
    lines.append("선의 위치·캔들 기반 조건부 시나리오이며 지지·저항이나 수익을 보장하지 않습니다.")
    return "\n".join(lines)
