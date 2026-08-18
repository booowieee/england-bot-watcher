# England SWS Watcher

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker--Compose-latest-2496ED?logo=docker&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-Chromium-2EAD33?logo=playwright&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot_API-26A5E4?logo=telegram&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

Асинхронный сервис мониторинга сайтов визовых операторов UK Seasonal Worker Scheme с мгновенной отправкой уведомлений со скриншотом в Telegram при открытии регистрационных форм.

---

## Возможности

- Асинхронный опрос целевых ресурсов через `asyncio` + `aiohttp` с пулом соединений и retry (exponential backoff)
- Специализированные детекторы для Google Forms, Best Opportunity, HOPS Labour Solutions и Concordia UK
- Скриншоты через headless Playwright Chromium (singleton, resource blocking)
- Уведомления в Telegram с inline-кнопкой перехода к анкете, plaintext fallback при ошибках парсинга
- Уведомления о закрытии формы (`RESOLVED`)
- Периодический heartbeat-отчет о статусе
- Атомарная персистенция состояния с автоматическим бэкапом
- Graceful shutdown по `SIGINT` / `SIGTERM`

---

## Архитектура

```mermaid
graph TD
    subgraph Scheduler ["Планировщик"]
        Loop["Asyncio Event Loop"]
    end

    subgraph Engine ["Ядро мониторинга"]
        Semaphore["Semaphore (max 4)"]
        HTTP["HTTP Client (aiohttp + TCPConnector)"]
        Retry["Retry (exponential backoff)"]
        Detectors["Детекторы"]
        State["State (JSON + backup)"]
    end

    subgraph Verification ["Скриншотер"]
        Browser["Playwright Chromium (singleton)"]
    end

    subgraph Notifications ["Оповещения"]
        Telegram["Telegram Bot API"]
        Fallback["Plaintext Fallback"]
    end

    Loop --> Semaphore
    Semaphore --> HTTP
    HTTP --> Retry
    Retry --> Detectors
    Detectors <--> State
    Detectors -->|Изменение статуса| Browser
    Browser --> Telegram
    Telegram -->|HTTP 400| Fallback
```

Подробное описание компонентов, детекторов и механизмов отказоустойчивости: [docs/architecture.md](./docs/architecture.md).

---

## Стек

| Категория | Технология | Назначение |
|-----------|-----------|------------|
| Язык | Python 3.12+ | Асинхронная логика мониторинга |
| HTTP | aiohttp | Неблокирующий клиент с пулом соединений |
| Браузер | Playwright Chromium | Headless-скриншоты с блокировкой тяжелых ресурсов |
| Парсинг | BeautifulSoup4 | Анализ DOM и извлечение ссылок |
| Оповещения | Telegram Bot API | Доставка алертов с фото и inline-кнопками |
| Контейнеризация | Docker Compose | Изоляция, автоперезапуск, volume-монтирование |

---

## Отслеживаемые ресурсы

| Ресурс | URL | Логика детекции |
|--------|-----|-----------------|
| Best Opportunity Form | `forms.gle/kkdrh8aNPQNHQkCk8` | Редирект `/closedform` -> `/viewform`, проверка полей ввода |
| Best Opportunity Web | `jobopportunityuk.com` | Новые ссылки на формы, изменение iframe, хэш страницы |
| HOPS Instructions | `hopslaboursolutions.com/recruitment-instructions` | Ссылки на регистрацию, regex по странам и датам |
| Concordia UK | `concordia.org.uk` | Изменение ссылок на форму набора |

---

## Быстрый старт

**Клонирование и установка:**
```bash
git clone https://github.com/booowieee/england-bot-watcher.git
cd england-bot-watcher

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium
```

**Конфигурация:**
```bash
cp .env.example .env
# Заполнить TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID
```

**Диагностика:**
```bash
python -m src.main --test
```

**Запуск:**
```bash
python -m src.main
```

---

## Docker Compose

```bash
docker compose up -d --build    # сборка и запуск
docker compose logs -f          # логи
docker compose down             # остановка
```

---

## Структура проекта

```text
england-bot-watcher/
├── docs/
│   └── architecture.md
├── data/
│   ├── monitor_state.json
│   └── screenshots/
├── logs/
├── src/
│   ├── detectors/
│   │   ├── base.py
│   │   ├── google_forms.py
│   │   ├── hops_detector.py
│   │   ├── best_opp_web.py
│   │   └── concordia.py
│   ├── browser.py
│   ├── config.py
│   ├── engine.py
│   ├── logger.py
│   ├── models.py
│   ├── notifier.py
│   └── main.py
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── LICENSE
└── README.md
```

---

## Лицензия

MIT License. См. [LICENSE](LICENSE).
