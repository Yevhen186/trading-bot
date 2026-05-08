import requests
from groq import Groq

# ─── НАЛАШТУВАННЯ ─────────────────────────────────────────
GROQ_API_KEY = "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"  # твій повний ключ
NEWSDATA_API_KEY = "pub_89153c8fb8c546449659fcba5b105707"
NEWS_COUNT = 10
# ──────────────────────────────────────────────────────────


def get_fear_greed() -> dict:
    """Отримує Fear & Greed Index"""
    url = "https://api.alternative.me/fng/"
    response = requests.get(url, timeout=10)
    data = response.json()["data"][0]
    return {
        "value": int(data["value"]),
        "classification": data["value_classification"]
    }


def get_crypto_news() -> list:
    """Отримує крипто-новини через NewsData.io"""
    url = "https://newsdata.io/api/1/news"
    params = {
        "apikey": NEWSDATA_API_KEY,
        "q": "crypto OR bitcoin OR ethereum",
        "language": "en",
        "category": "business,technology",
        "size": NEWS_COUNT
    }
    response = requests.get(url, params=params, timeout=10)
    data = response.json()

    news = []
    if data.get("status") == "success":
        for article in data.get("results", []):
            title = article.get("title", "")
            if title:
                news.append(title.strip())

    return news


def analyze_sentiment(news: list, fng: dict) -> dict:
    """AI аналізує настрій новин"""
    client = Groq(api_key=GROQ_API_KEY)

    news_text = "\n".join([f"- {title}" for title in news]) if news else "- Новини недоступні"

    prompt = f"""Ти — крипто-аналітик який оцінює настрій ринку на основі новин.

FEAR & GREED INDEX: {fng['value']}/100 ({fng['classification']})
Шкала: 0-25 Extreme Fear, 26-45 Fear, 46-55 Neutral, 56-75 Greed, 76-100 Extreme Greed

ОСТАННІ НОВИНИ:
{news_text}

Проаналізуй і дай відповідь УКРАЇНСЬКОЮ МОВОЮ:

1. НАСТРІЙ: BULLISH / BEARISH / NEUTRAL
2. Fear & Greed: що означає поточне значення {fng['value']} для ринку
3. Ключові теми з новин (2-3 речення)
4. Важливі ризики або можливості
5. Загальний висновок для трейдера (1 речення)"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=600
    )

    analysis = response.choices[0].message.content

    # Визначаємо настрій для Orchestrator
    if "BULLISH" in analysis.upper():
        sentiment_signal = "BULLISH"
    elif "BEARISH" in analysis.upper():
        sentiment_signal = "BEARISH"
    else:
        sentiment_signal = "NEUTRAL"

    return {
        "signal": sentiment_signal,
        "analysis": analysis
    }


def run_news_agent() -> dict:
    print("\n📰 Отримую крипто-новини...")

    try:
        news = get_crypto_news()
        print(f"✅ Знайдено {len(news)} новин з NewsData.io")
        for i, title in enumerate(news[:3], 1):
            print(f"   {i}. {title[:80]}...")
    except Exception as e:
        print(f"⚠️ Новини недоступні: {e}")
        news = []

    print("😱 Отримую Fear & Greed Index...")
    fng = get_fear_greed()
    print(f"✅ Fear & Greed: {fng['value']}/100 ({fng['classification']})")

    print("🤖 AI аналізує настрій ринку...\n")
    result = analyze_sentiment(news, fng)

    print("═" * 55)
    print("  📰 NEWS AGENT — АНАЛІЗ НОВИН")
    print("═" * 55)
    print(result["analysis"])
    print("═" * 55)
    print(f"\n  🎯 Сигнал для Orchestrator: {result['signal']}")
    print("═" * 55)

    return {
        "fear_greed_value": fng["value"],
        "fear_greed_label": fng["classification"],
        "news_count": len(news),
        "signal": result["signal"],
        "analysis": result["analysis"]
    }


if __name__ == "__main__":
    run_news_agent()