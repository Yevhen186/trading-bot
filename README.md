# Trading Bot — автоматизований крипто-аналізатор

Навчальний проєкт. Бот аналізує ринок ETH/USDT кожні 4 години
і надсилає звіт у Telegram. Розгорнутий на Railway і працює 24/7.

![Приклад звіту в Telegram]<img width="1749" height="1027" alt="image" src="https://github.com/user-attachments/assets/49e18731-c3ce-43b6-853e-8018f8e74f08" />


## Що це і навіщо

Я будував цей проєкт щоб навчитись працювати з API,
розгортати Python-додатки в хмарі та інтегрувати AI в реальні задачі.

Бот не торгує реальними грошима — використовує Binance Testnet.

## Як це працює

Кожні 4 години запускається аналіз у два етапи:

**1. TA Agent** — технічний аналіз по індикаторах:
- RSI — перегрітість ринку
- EMA 20 / EMA 50 — напрямок тренду
- Обсяг торгів — підтвердження сигналу
- ATR — рівень волатильності

**2. News Agent** — аналіз настрою ринку:
- Отримує свіжі крипто-новини через NewsData.io
- Читає Fear & Greed Index
- LLM (Groq / Llama 3.3) аналізує новини і визначає BULLISH / BEARISH / NEUTRAL

**3. Orchestrator** — збирає голоси агентів:
- Якщо обидва агенти згодні — генерує сигнал BUY або SELL
- Розраховує параметри угоди (вхід, стоп-лос, тейк-профіт)
- Формує підсумковий звіт через LLM і надсилає в Telegram

**4. Execution Agent** — виконує ордери на Binance Testnet
і записує всі угоди в Google Sheets.

## Технології

- Python 3.11
- Binance API (Testnet)
- Groq API / Llama 3.3 70B
- NewsData.io
- Google Sheets API
- Telegram Bot API
- Railway (хмарний деплой)

## Структура файлів
├── orchestrator.py       # Main coordinator, voting logic
├── ta_agent_v2.py        # Technical analysis agent
├── news_agent.py         # News sentiment agent
├── execution_agent.py    # Order execution + Google Sheets
├── telegram_notify.py    # Telegram notifications
├── scheduler.py          # Runs analysis every 4 hours
├── requirements.txt      # Dependencies
└── .env.example          # Required environment variables
## Environment Variables

All secrets are stored as environment variables. See `.env.example` for the full list.

## Status

Deployed and running on Railway. The bot sends analysis reports to Telegram
every 4 hours automatically.
