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
from src.browser import capture_screenshots
from src.notifier import TelegramNotifier


async def run_test_mode():
    logger.info("Running diagnostic test mode")
    print("=" * 60)
    print("SWS MONITOR BOT - DIAGNOSTICS")
    print("=" * 60)

    notifier = TelegramNotifier()
    if notifier.is_configured:
        print(f"Telegram configured. Chat ID: {Config.TELEGRAM_CHAT_ID}")
        print("Sending test alert...")
        await notifier.send_alert(
            title="Тестовое оповещение",
            target_name="Диагностика",
            url="https://forms.gle/kkdrh8aNPQNHQkCk8",
            details="Проверка системы оповещений завершена.",
            detected_links=["https://jobopportunityuk.com/"],
        )
    else:
        print("Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
    await notifier.close()

    print("\nTesting multi-chunk screenshot engine...")
    test_url = "https://forms.gle/kkdrh8aNPQNHQkCk8"
    screenshots = await capture_screenshots(test_url, "test_target", max_chunks=2)
    if screenshots:
        print(f"Captured {len(screenshots)} screenshot slice(s):")
        for s in screenshots:
            print(f"  - {s}")
    else:
        print("Screenshot capture disabled or failed.")

    print("\nTesting target detectors...")
    engine = MonitoringEngine()
    import aiohttp
    connector = aiohttp.TCPConnector(limit=10)
    engine._session = aiohttp.ClientSession(connector=connector)
    engine.notifier = TelegramNotifier(session=engine._session)

    try:
        results = await engine.run_cycle()
        for r in results:
            print(f"\n[{r.target_name}]")
            print(f"  URL: {r.url}")
            print(f"  Status: {r.current_state}")
            print(f"  Summary: {r.summary}")
            if r.detected_links:
                print(f"  Links: {len(r.detected_links)}")
    finally:
        await engine.notifier.close()
        if engine._session and not engine._session.closed:
            await engine._session.close()

    print("\n" + "=" * 60)
    print("Diagnostics completed.")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="SWS Application Monitor Bot")
    parser.add_argument("--test", action="store_true", help="Run diagnostics and exit")
    args = parser.parse_args()

    if args.test:
        asyncio.run(run_test_mode())
        return

    engine = MonitoringEngine()

    def shutdown_handler(sig, frame):
        logger.info(f"Received signal {sig}, initiating shutdown...")
        engine.stop()

    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, shutdown_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        asyncio.run(engine.start())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("SWS Monitor Bot stopped.")


if __name__ == "__main__":
    main()
