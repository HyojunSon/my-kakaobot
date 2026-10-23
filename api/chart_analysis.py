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
    summary = "🔎 시장 방향을 더 확인하며 주식 매수를 서두르지 마세요"
    support = supports[0] if supports else None
    resistance = resistances[0] if resistances else None
    event = min(levels, key=lambda item: abs(close-item[0]))[1] if levels else ""
    if "선 아래로 내려왔어요" in event:
        summary = "🚨 시장이 약해지는 신호 · 새 매수보다 위험 관리부터"
    elif resistance is not None and (resistance/close-1)*100 <= 1:
        summary = "🟡 상승이 막힐 수 있는 지수대 · 급하게 따라 사지 마세요"
    elif support is not None and (close/support-1)*100 <= 1:
        summary = "🟢 시장이 버티는지 확인할 구간 · 반등 확인이 먼저예요"
    lines.extend(["", "【 🧭 시장이 버틸지 볼 지수대 】"])
    if event:
        lines.append(event.replace("가격", "지수"))
    lines.append("🟢 하락을 멈출지 볼 곳: " + (point(support) if support is not None else "그려둔 선에서 찾지 못했어요"))
    lines.append("🔴 상승이 막힐지 볼 곳: " + (point(resistance) if resistance is not None else "그려둔 선에서 찾지 못했어요"))
    lines.extend(["", "【 🛒 주식을 더 사고 싶으신가요? 】"])
    if support is not None:
        lines.append(f"지수가 {point(support)} 부근에서 하락을 멈추고 다시 올라, 선 위에서 장을 마치는지 살펴보세요.")
        lines.append("그런 모습을 확인하면 관심종목도 함께 회복하는지 보고, 매수를 나누어 진행할지 생각해 볼 수 있어요.")
    else:
        lines.append("시장이 어디서 버틸지 확인할 선이 부족해요. 새로 살 주식은 서두르지 말고 시장과 해당 종목의 회복을 함께 확인하세요.")
    lines.extend(["", "【 💰 보유 주식을 줄여야 할까요? 】"])
    if resistance is not None:
        lines.append(f"지수가 {point(resistance)} 부근에서 더 오르지 못하고 밀리면, 보유 종목도 약해지는지 확인하세요.")
        lines.append("함께 약해진다면 일부를 나누어 팔아 주식에 넣은 돈을 줄일지 살펴보세요. 지수만 보고 모든 종목을 팔 필요는 없어요.")
    else:
        lines.append("그려둔 선만으로는 상승이 막힐 지수대를 찾기 어려워요. 보유 종목의 흐름과 감당할 손실을 기준으로 판단하세요.")
    if support is not None and len(df) >= 15:
        previous = df.Close.shift(1)
        tr = pd.concat([df.High-df.Low, (df.High-previous).abs(), (df.Low-previous).abs()], axis=1).max(axis=1)
        atr = float(tr.iloc[-14:].mean())
        if math.isfinite(atr) and atr > 0:
            caution = support-max(atr*.5, support*.01)
            if caution > 0:
                lines.extend(["", "【 🚨 시장이 예상과 달라진다면 】",
                    f"지수가 {point(caution)} 아래에서 장을 마치면, 시장이 버틸 것이라는 예상은 다시 살펴봐야 해요.",
                    "새 매수는 잠시 멈추고 보유 종목의 하락과 현금 여유를 점검하세요. 이 지수대는 개별 주식의 매도 가격이 아니에요."])
    if skipped:
        lines.append(f"날짜나 지수를 확인할 수 없는 선 {skipped}개는 제외했어요.")
    lines[3:3] = [summary, ""]
    lines.extend(["", "━" * 16, "※ 장중 지수·거래량은 계속 바뀌어요. 그려둔 선의 위치로 판단한 시장 참고 정보예요.",
                  "지수와 개별 종목은 다르게 움직일 수 있으며, 반등이나 수익을 보장하지 않아요."])
    return "\n".join(lines)


def analysis_text(stock, drawings, df):
    import pandas as pd
    if df.empty or len(df) < 2:
        return f"📋 {stock['name']} 차트 리포트\n\n📂 분석 대기\n분석에 필요한 일봉이 부족합니다."
    close = float(df.Close.iloc[-1])
    if not math.isfinite(close) or close <= 0:
        raise ValueError("Invalid close")
    index = stock["code"] in {"KOSPI", "KOSDAQ"}
    name = stock["name"]
    last_char = ord(name[-1]) if name else 0
    particle = ("을" if (last_char-0xAC00) % 28 else "를") if 0xAC00 <= last_char <= 0xD7A3 else "을(를)"
    object_name = name + particle
    price = lambda v: f"{v:,.2f}pt" if index else f"{v:,.0f}원"
    last = len(df)-1
    dates = {d.strftime("%Y-%m-%d"): i for i,d in enumerate(df.index)}
    previous = float(df.Close.iloc[-2])
    change = (close/previous-1)*100 if previous > 0 else 0
    lookback = min(5, last)
    base = float(df.Close.iloc[-1-lookback])
    move = (close/base-1)*100 if base > 0 else 0
    direction = "🔺" if change > 0 else ("🔻" if change < 0 else "▪️")
    summary = "🔎 지금은 서두르지 말고 조금 더 지켜보세요"
    lines = [f"📋 {stock['name']} 차트 리포트", f"{stock['code']}  ·  {df.index[-1]:%Y.%m.%d} 일봉", "━" * 16,
             f"💰 최신 가격  {price(close)}",
             f"{direction} 전 거래일보다  {change:+.2f}%",
             "", "【 📊 시장 흐름 】", f"• 최근 {lookback}거래일  {move:+.2f}%"]
    if len(df) >= 21:
        average = float(df.Volume.iloc[-21:-1].mean())
        if average > 0:
            lines.append(f"• 거래량  이전 20일 평균의 {float(df.Volume.iloc[-1])/average:.2f}배")
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
                event = "📈 가격이 선 위로 올라왔어요. 다음 거래일에도 선 위에서 장을 마치는지 살펴보세요."
            elif previous >= prev_line and close < now_line*.998:
                event = "📉 가격이 선 아래로 내려왔어요. 다시 선 위로 올라와 장을 마치는지 살펴보세요."
            elif float(df.Low.iloc[-1]) <= now_line <= float(df.High.iloc[-1]):
                event = ("🟢 가격이 선에 닿은 뒤 그 위에 있어요. 이 부근에서 하락을 멈출지 지켜보세요."
                         if close >= now_line else "🔴 가격이 선에 닿은 뒤 그 아래에 있어요. 이 부근에서 상승이 막힐지 지켜보세요.")
            levels.append((now_line, event))
        except (KeyError, ValueError, TypeError, OverflowError):
            skipped += 1
    supports = sorted({v for v,e in levels if v <= close}, reverse=True)
    resistances = sorted({v for v,e in levels if v > close})
    if index:
        return index_market_guide(lines, df, supports, resistances, levels, skipped)
    lines.extend(["", "【 🧭 핵심 가격대 】"])
    if levels:
        nearest = min(levels, key=lambda item: abs(close-item[0]))
        if nearest[1]:
            lines.append(nearest[1])
        lines.append("🟢 하락을 멈출지 볼 가격: " + (price(supports[0]) + f"\n   현재 가격보다 {(1-supports[0]/close)*100:.2f}% 아래" if supports else "그려둔 선에서 찾지 못했어요"))
        lines.append("🔴 상승이 막힐지 볼 가격: " + (price(resistances[0]) + f"\n   현재 가격보다 {(resistances[0]/close-1)*100:.2f}% 위" if resistances else "그려둔 선에서 찾지 못했어요"))
    else:
        lines.append("📂 참고할 수 있는 차트 선이 없어요.")
    lines.extend(["", "【 💬 어떻게 사고팔면 좋을까요? 】"])
    if supports and len(df) >= 15:
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
                    summary = "🟢 가격이 버티는 모습을 확인한 뒤 결정하세요"
                    lines.append(f"🛒 {object_name} 사고 싶으신가요?\n{price(lower)}~{price(upper)} 부근을 살펴보세요.\n이 가격대에 닿았다고 바로 사기보다는, 가격이 버티고 다시 올라 이 가격대 위에서 장을 마치는지 확인하세요.")
                    lines.append(f"\n💰 {object_name} 얼마에 팔아야 할지 모르겠나요?\n{price(target)} 부근에서 상승이 막히는지 살펴보세요.\n이미 보유 중이라면 한 번에 전부 팔기보다 나누어 파는 방법을 생각해 볼 수 있어요.")
                    lines.append(f"\n🚨 이런 경우에는 계획을 다시 세워야 해요\n가격이 {price(invalid)} 아래로 떨어진 채 장을 마치면, 이 부근에서 버틸 것이라는 예상과 달라진 거예요.\n위 매수 계획을 그대로 따르지 말고 다시 판단해야 해요.")
                    lines.append(f"\n⚖️ 위 가격대의 가장 높은 가격에 샀다고 가정하면, 목표까지의 상승 폭은 계획을 다시 볼 가격까지의 하락 폭의 약 {ratio:.1f}배예요. 수수료는 제외했어요.")
                    if close > upper:
                        summary = "⏳ 지금은 기다렸다가 가격이 내려오면 살펴보세요"
                        lines.append("\n⏳ 현재 가격은 위 매수 가격대보다 높아요. 급하게 따라 사기보다 다시 가까워질 때 살펴보세요.")
                else:
                    summary = "🟡 지금 새로 사기보다는 기다리는 편을 생각해 보세요"
                    lines.append(f"🛒 {object_name} 사고 싶으신가요?\n계산한 가격대에서는 오를 수 있는 폭이 감수할 하락 폭의 1.5배보다 작아요. 지금은 서두르지 않는 편이 좋아요.")
                    lines.append(f"\n💰 이미 보유하고 계신가요?\n{price(target)} 부근에서 더 오르지 못하는지 살펴보고, 나누어 파는 방법을 생각해 보세요.")
            else:
                lines.append("그려둔 선만으로는 사고팔 가격을 정하기 어려워요. 위아래에서 가격을 막아줄 만한 선이 더 필요해요.")
    else:
        lines.append("가격을 받쳐줄 만한 선이나 과거 기록이 부족해, 지금은 사고팔 가격을 제안하기 어려워요.")
    if not levels:
        lines.append("HTS에서 그려둔 선을 추가하면 더 자세히 살펴볼 수 있어요.")
    if skipped:
        lines.append(f"날짜나 가격을 확인할 수 없는 선 {skipped}개는 제외했어요.")
    lines[3:3] = [summary, ""]
    lines.extend(["", "━" * 16, "※ 장이 열려 있으면 가격과 거래량은 계속 바뀌어요.",
                  "차트 선과 가격 움직임으로 살펴본 참고 정보예요. 예상과 다르게 움직이거나 손실이 날 수 있어요."])
    return "\n".join(lines)
