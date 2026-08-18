import asyncio
import json
import shutil
from datetime import datetime, UTC, timedelta
from typing import Dict, Any, List
import aiohttp
from src.config import Config
from src.logger import logger
from src.models import TargetConfig, TargetType, CheckResult
from src.browser import ScreenshotEngine
from src.notifier import TelegramNotifier
from src.detectors import (
    BaseDetector,
    GoogleFormsDetector,
    HopsDetector,
    BestOpportunityWebDetector,
    ConcordiaDetector,
)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0
CONCURRENT_LIMIT = 4


class MonitoringEngine:
    def __init__(self):
        self.state_file = Config.STATE_FILE
        self.state: Dict[str, Any] = self._load_state()
        self.last_heartbeat: datetime = datetime.now(UTC)
        self.is_running: bool = False
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
        self.screenshot_engine = ScreenshotEngine()
        self.notifier: TelegramNotifier | None = None

        self.detectors: Dict[str, BaseDetector] = {}
        for target in Config.TARGETS:
            if not target.enabled:
                continue
            detector_map = {
                TargetType.GOOGLE_FORM: GoogleFormsDetector,
                TargetType.HOPS_INSTRUCTIONS: HopsDetector,
                TargetType.BEST_OPP_WEB: BestOpportunityWebDetector,
                TargetType.CONCORDIA_WEB: ConcordiaDetector,
            }
            cls = detector_map.get(target.target_type)
            if cls:
                self.detectors[target.id] = cls(target)

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.is_file():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.error("State file corrupted, attempting backup recovery.")
                backup = self.state_file.with_suffix(".json.bak")
                if backup.is_file():
                    try:
                        with open(backup, "r", encoding="utf-8") as f:
                            return json.load(f)
                    except Exception:
                        logger.error("Backup state also corrupted. Starting fresh.")
            except Exception as e:
                logger.error(f"Failed to read state file: {e}")
        return {}

    def _save_state(self) -> None:
        try:
            backup = self.state_file.with_suffix(".json.bak")
            if self.state_file.is_file():
                shutil.copy2(self.state_file, backup)

            temp_file = self.state_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.state_file)
        except Exception as e:
            logger.error(f"Failed to persist state: {e}")

    async def _fetch_with_retry(
        self,
        url: str,
        headers: dict,
    ) -> tuple[str, str, int]:
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                async with self._semaphore:
                    async with self._session.get(
                        url,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=20),
                        allow_redirects=True,
                    ) as resp:
                        final_url = str(resp.url)
                        status_code = resp.status
                        html = await resp.text(errors="ignore")
                        return html, final_url, status_code
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"Retry {attempt + 1}/{MAX_RETRIES} for {url}: {e}")
                    await asyncio.sleep(delay)
        raise last_error

    async def check_target(self, target: TargetConfig) -> CheckResult:
        detector = self.detectors.get(target.id)
        if not detector:
            return CheckResult(
                target_id=target.id,
                target_name=target.name,
                url=target.url,
                is_open=False,
                status_changed=False,
                previous_state=None,
                current_state="NO_DETECTOR",
                summary=f"No detector registered for {target.id}",
                details="Target skipped.",
                error=f"Missing detector for type {target.target_type}",
            )

        headers = {**Config.DEFAULT_HEADERS, **target.custom_headers}
        previous_target_state = self.state.get(target.id, {})

        try:
            logger.debug(f"Checking [{target.name}]")
            html, final_url, status_code = await self._fetch_with_retry(target.url, headers)

            return await detector.analyze(
                html=html,
                final_url=final_url,
                status_code=status_code,
                previous_state=previous_target_state,
            )
        except Exception as e:
            logger.error(f"Error checking [{target.name}]: {e}")
            return CheckResult(
                target_id=target.id,
                target_name=target.name,
                url=target.url,
                is_open=False,
                status_changed=False,
                previous_state=previous_target_state.get("status"),
                current_state="ERROR",
                summary=f"Connection error: {type(e).__name__}",
                details=str(e),
                error=str(e),
            )

    async def process_check_result(self, result: CheckResult) -> None:
        target_state = self.state.get(result.target_id, {})
        prev_is_open = target_state.get("is_open", False)

        should_alert = False
        alert_title = ""

        if result.is_open and not prev_is_open:
            should_alert = True
            alert_title = "Анкета открыта для приема заявок"
        elif result.status_changed and result.is_open:
            should_alert = True
            alert_title = "Обновление регистрационной формы"
        elif not result.is_open and prev_is_open:
            logger.info(f"[{result.target_name}] closed, sending resolved notification.")
            await self.notifier.send_resolved(result.target_name, result.url)

        if should_alert:
            logger.info(f"Alert triggered for [{result.target_name}]")
            screenshot_path = await self.screenshot_engine.capture(result.url, result.target_id)
            result.screenshot_path = screenshot_path

            await self.notifier.send_alert(
                title=alert_title,
                target_name=result.target_name,
                url=result.url,
                details=result.details,
                screenshot_path=screenshot_path,
                detected_links=result.detected_links,
            )

        self.state[result.target_id] = {
            "name": result.target_name,
            "url": result.url,
            "status": result.current_state,
            "is_open": result.is_open,
            "hash": result.html_hash,
            "links": result.detected_links,
            "last_checked": datetime.now(UTC).isoformat(),
            "last_error": result.error,
        }
        self._save_state()

    async def run_cycle(self) -> List[CheckResult]:
        tasks = []
        for target in Config.TARGETS:
            if target.enabled and target.id in self.detectors:
                tasks.append(self.check_target(target))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_results = []
        for res in results:
            if isinstance(res, Exception):
                logger.error(f"Unhandled exception in check cycle: {res}")
                continue
            await self.process_check_result(res)
            valid_results.append(res)

        return valid_results

    async def check_heartbeat(self) -> None:
        if Config.HEARTBEAT_INTERVAL_HOURS <= 0:
            return

        now = datetime.now(UTC)
        if now - self.last_heartbeat >= timedelta(hours=Config.HEARTBEAT_INTERVAL_HOURS):
            summary_lines = []
            for tid, tdata in self.state.items():
                status_str = "OPEN" if tdata.get("is_open") else "CLOSED"
                summary_lines.append(f"<b>{tdata.get('name')}:</b> {status_str}")

            await self.notifier.send_heartbeat("\n".join(summary_lines))
            self.last_heartbeat = now

    async def start(self) -> None:
        self.is_running = True
        connector = aiohttp.TCPConnector(limit=20, limit_per_host=5, ttl_dns_cache=300)
        self._session = aiohttp.ClientSession(connector=connector)
        self.notifier = TelegramNotifier(session=self._session)

        if Config.ENABLE_SCREENSHOTS:
            await self.screenshot_engine.initialize()

        logger.info(f"Engine started. Polling interval: {Config.CHECK_INTERVAL_SECONDS}s")

        try:
            logger.info("Running baseline inspection...")
            results = await self.run_cycle()
            for r in results:
                logger.info(f"[{r.target_name}] Baseline: {r.current_state}")

            while self.is_running:
                try:
                    await asyncio.sleep(Config.CHECK_INTERVAL_SECONDS)
                    logger.debug("Executing inspection cycle...")
                    await self.run_cycle()
                    await self.check_heartbeat()
                except asyncio.CancelledError:
                    logger.info("Engine received cancellation signal.")
                    raise
                except Exception as e:
                    logger.error(f"Cycle error: {e}", exc_info=True)
                    await asyncio.sleep(10)
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        await self.screenshot_engine.close()
        await self.notifier.close()
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("Engine resources released.")

    def stop(self) -> None:
        self.is_running = False
        logger.info("Engine stopping...")
