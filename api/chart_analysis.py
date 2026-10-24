"""Deterministic scenarios from user drawings; no model or external AI."""
import math
from api.chart_service import chart_data, line_values


def analyze_chart(stock, snapshot):
    df, drawings = chart_data(stock, snapshot)
    return analysis_text(stock, drawings, df)


def index_market_guide(lines, df, supports, resistances, levels, skipped):
    """Index levels guide stock exposure, never orders for the index itself."""
    import pandas as pd
    close = float(df.Close.iloc[-1])
    point = lambda value: f"{value:,.2f}pt"
    # The common introduction describes the same candles, using index terms.
    lines = [line.replace("차트 리포트", "시장 리포트").replace("최신 가격", "현재 지수") for line in lines]
    lines[0] = lines[0].replace("📋 ", "📋 시장 리포트 · ", 1)
    lines[1] = lines[1].replace("💰 ", "💰 지수 ", 1)
    summary = "🔎 시장 회복 확인 후 주식 매수를 살펴보세요"
    support = supports[0] if supports else None
    resistance = resistances[0] if resistances else None
    event = min(levels, key=lambda item: abs(close-item[0]))[1] if levels else ""
    if "선 아래로 내려왔어요" in event:
        summary = "🚨 시장 약세 신호 · 새 매수는 신중하게"
    elif resistance is not None and (resistance/close-1)*100 <= 1:
        summary = "🟡 상승이 막힐 수 있어요 · 추격 매수 주의"
    elif support is not None and (close/support-1)*100 <= 1:
        summary = "🟢 시장이 버티는지 먼저 확인하세요"
    if event:
        lines.append(event.replace("가격", "지수"))
    lines.append("🟢 지지선: " + (point(support) if support is not None else "그려둔 선에서 찾지 못했어요"))
    lines.append("🔴 저항선: " + (point(resistance) if resistance is not None else "그려둔 선에서 찾지 못했어요"))
    if support is not None:
        lines.append(f"🛒 주식 매수: {point(support)} 위 마감·관심종목 회복 확인 후 나누어 살지 판단하세요.")
    else:
        lines.append("🛒 주식 매수: 선이 부족해요. 시장·관심종목 회복부터 확인하세요.")
    if resistance is not None:
        lines.append(f"💰 보유 주식: {point(resistance)}에서 밀리고 종목도 약해지면 일부 줄일지 살펴보세요.")
    else:
        lines.append("💰 보유 주식: 위쪽 선이 없어 개별 종목의 흐름으로 판단하세요.")
    if support is not None and len(df) >= 15:
        previous = df.Close.shift(1)
        tr = pd.concat([df.High-df.Low, (df.High-previous).abs(), (df.Low-previous).abs()], axis=1).max(axis=1)
        atr = float(tr.iloc[-14:].mean())
        if math.isfinite(atr) and atr > 0:
            caution = support-max(atr*.5, support*.01)
            if caution > 0:
                lines.append(f"🚨 {point(caution)} 아래 마감 시 새 매수는 멈추고 계획 재검토. 개별 주식의 매도 가격은 아니에요.")
    if skipped:
        lines.append(f"날짜나 지수를 확인할 수 없는 선 {skipped}개는 제외했어요.")
    lines.insert(2, summary)
    lines.append("※ 장중 변동·손실 가능. 지수와 개별 종목은 다르게 움직여요.")
    return "\n".join(lines)


def analysis_text(stock, drawings, df):
    import pandas as pd
    if df.empty or len(df) < 2:
        return f"📋 {stock['name']} 차트 리포트\n\n📂 분석 대기\n분석에 필요한 일봉이 부족합니다."
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
    direction = "🔺" if change > 0 else ("🔻" if change < 0 else "▪️")
    summary = "🔎 서두르지 말고 지켜보세요"
    lines = [f"📋 {stock['name']} ({stock['code']}) · {df.index[-1]:%m/%d}",
             f"💰 {price(close)} {direction}{change:+.2f}% · 최근 {lookback}일 {move:+.2f}%"]
    if len(df) >= 21:
        average = float(df.Volume.iloc[-21:-1].mean())
        if average > 0:
            lines.append(f"📊 거래량: 이전 20일 평균의 {float(df.Volume.iloc[-1])/average:.2f}배")
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
                event = "📈 가격이 선 위로 올라왔어요. 다음 마감까지 유지되는지 확인하세요."
            elif previous >= prev_line and close < now_line*.998:
                event = "📉 가격이 선 아래로 내려왔어요. 회복 여부를 확인하세요."
            elif float(df.Low.iloc[-1]) <= now_line <= float(df.High.iloc[-1]):
                event = ("🟢 선에 닿은 뒤 위에 있어요. 하락을 멈출지 확인하세요."
                         if close >= now_line else "🔴 선에 닿은 뒤 아래에 있어요. 상승이 막힐지 확인하세요.")
            levels.append((now_line, event))
        except (KeyError, ValueError, TypeError, OverflowError):
            skipped += 1
    supports = sorted({v for v,e in levels if v <= close}, reverse=True)
    resistances = sorted({v for v,e in levels if v > close})
    if index:
        return index_market_guide(lines, df, supports, resistances, levels, skipped)
    # Share the screener's historical support identity, even just below it.
    from api.recommendations import check_symbol
    candidate, _, _ = check_symbol(stock, drawings, df=df)
    recovery = candidate is not None and candidate["position"] == "below"
    if candidate is not None and candidate.get("support_status") == "awaiting_confirmation":
        lines.append("🔎 지지선 접근 후보 · 반등은 아직 확인되지 않았어요.")
    if candidate is not None:
        support = candidate["support_price"]
        supports = [support]
        resistances = sorted({v for v, _ in levels if v > max(support, close)})
    if recovery:
        lines.append("🟠 지지선 소폭 이탈 · 다시 회복하는지 확인하세요.")
    if levels:
        nearest = min(levels, key=lambda item: abs(close-item[0]))
        if nearest[1] and not recovery:
            lines.append(nearest[1])
        lines.append("🟢 지지선: " + (price(supports[0]) if supports else "확인할 선 없음"))
        lines.append("🔴 저항선: " + (price(resistances[0]) if resistances else "확인할 선 없음"))
    else:
        lines.append("📂 참고할 수 있는 차트 선이 없어요.")
    if recovery:
        support = candidate["support_price"]
        summary = "🟠 지지선 회복을 확인하고 매수를 살펴보세요"
        lines.append(f"🛒 {price(support)} 부근까지 회복하며 올라올 때 매수를 살펴보세요. 선 아래에서 미리 사기보다 위에 안착하는지 확인하세요.")
        if resistances:
            target = resistances[0]
            lines.append(f"💰 안착 후 {price(target)} 부근에서 나누어 수익실현할지 살펴보세요.")
            lines.append(f"📈 지지선 매수 → 저항선 매도 예상 +{(target/support-1)*100:.1f}% (비용 제외·보장 아님)")
        else:
            lines.append("위쪽 저항선이 없어 매도 목표와 예상 수익률은 계산을 보류해요.")
        lines.append("🚨 회복하지 못하거나 다시 밀리면 매수 계획을 재검토하세요.")
    elif supports and len(df) >= 15:
        prev_close = df.Close.shift(1)
        tr = pd.concat([df.High-df.Low, (df.High-prev_close).abs(), (df.Low-prev_close).abs()], axis=1).max(axis=1)
        atr = float(tr.iloc[-14:].mean())
        support = supports[0]
        if not math.isfinite(atr) or atr <= 0:
            lines.append("최근 가격 움직임을 충분히 확인할 수 없어, 사고팔 가격을 제안하기 어려워요.")
        else:
            width = min(atr*.25, support*.01)
            lower, upper = support-width, support+width
            invalid = support-max(atr*.5, support*.01)
            target = resistances[0] if resistances else None
            if lower > 0 and invalid > 0 and target is not None and target > upper:
                ratio = (target-upper)/(upper-invalid)
                if ratio >= 1.5:
                    summary = "🟢 가격이 버티는지 먼저 확인하세요"
                    lines.append(f"🛒 사고 싶다면 {price(lower)}~{price(upper)} 부근을 살펴보세요. 닿았다고 바로 사지 말고, 하락을 멈추고 그 위로 회복해 마감하는지 확인하세요.")
                    lines.append(f"💰 팔 때: {price(target)}에서 상승이 막히면 나누어 팔지 살펴보세요.")
                    lines.append(f"🚨 {price(invalid)} 아래로 장을 마치면 위 매수 계획을 다시 세워야 해요.")
                    if close > upper:
                        summary = "⏳ 지금 바로 사기보다, 아래 안내한 가격까지 내려오는지 기다려 보세요."
                else:
                    summary = "🟡 새로 사기보다 기다리는 편을 생각해 보세요"
                    lines.append("🛒 살 때: 오를 여유에 비해 하락 위험이 커 보여요. 서두르지 마세요.")
                    lines.append(f"💰 팔 때: {price(target)}에서 막히면 나누어 팔지 살펴보세요.")
            else:
                lines.append("그려둔 선만으로는 사고팔 가격을 정하기 어려워요. 위아래에서 가격을 막아줄 만한 선이 더 필요해요.")
    else:
        lines.append("가격을 받쳐줄 만한 선이나 과거 기록이 부족해, 지금은 사고팔 가격을 제안하기 어려워요.")
    if not levels:
        lines.append("HTS에서 그려둔 선을 추가하면 더 자세히 살펴볼 수 있어요.")
    if skipped:
        lines.append(f"날짜나 가격을 확인할 수 없는 선 {skipped}개는 제외했어요.")
    lines.insert(2, summary)
    lines.append("※ 장중 수치는 변해요. 선·가격 기반 참고 정보이며 손실이 날 수 있어요.")
    return "\n".join(lines)
