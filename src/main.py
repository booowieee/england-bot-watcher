import argparse
import asyncio
import signal
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.config import Config
from src.logger import logger
from src.engine import MonitoringEngine
from src.browser import ScreenshotEngine
from src.notifier import TelegramNotifier


async def run_test_mode():
    logger.info("Running in diagnostic test mode")
    print("=" * 60)
    print("SWS MONITOR BOT - DIAGNOSTICS & TEST RUN")
    print("=" * 60)

    notifier = TelegramNotifier()
    if notifier.is_configured:
        print(f"Telegram Configured: Token detected, Chat ID = {Config.TELEGRAM_CHAT_ID}")
        print("Sending test alert...")
        await notifier.send_alert(
            title="Тестовое оповещение",
            target_name="Диагностический модуль",
            url="https://forms.gle/kkdrh8aNPQNHQkCk8",
            details="Проверка системы оповещений завершена успешно.",
            detected_links=["https://jobopportunityuk.com/"]
        )
    else:
        print("Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")

    print("\nTesting Playwright Screenshot Engine...")
    test_url = "https://forms.gle/kkdrh8aNPQNHQkCk8"
    screenshot = await ScreenshotEngine.capture(test_url, "test_target")
    if screenshot:
        print(f"Screenshot created: {screenshot}")
    else:
        print("Screenshot capture disabled or failed.")

    print("\nTesting Live Target Fetchers & Detectors...")
    engine = MonitoringEngine()
    import aiohttp
    async with aiohttp.ClientSession() as session:
        results = await engine.run_cycle(session)
        for r in results:
            status_label = "OPEN" if r.is_open else "CLOSED"
            print(f"\n[{r.target_name}]")
            print(f"  URL: {r.url}")
            print(f"  Status: {status_label}")
            print(f"  Summary: {r.summary}")
            if r.detected_links:
                print(f"  Links Found: {len(r.detected_links)}")

    print("\n" + "=" * 60)
    print("All diagnostic checks completed successfully.")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="SWS Application Monitor Bot")
    parser.add_argument("--test", action="store_true", help="Run diagnostic test and exit")
    args = parser.parse_args()

    if args.test:
        asyncio.run(run_test_mode())
        return

    engine = MonitoringEngine()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown_handler(sig, frame):
        logger.info(f"Received shutdown signal ({sig}). Stopping engine...")
        engine.stop()
        loop.stop()

    try:
        if hasattr(signal, "SIGINT"):
            signal.signal(signal.SIGINT, shutdown_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, shutdown_handler)
    except Exception:
        pass

    try:
        loop.run_until_complete(engine.start())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("SWS Monitor Bot stopped.")


if __name__ == "__main__":
    main()
