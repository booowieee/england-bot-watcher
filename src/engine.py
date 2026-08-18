import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
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


class MonitoringEngine:
    def __init__(self):
        self.state_file = Config.STATE_FILE
        self.state: Dict[str, Any] = self._load_state()
        self.notifier = TelegramNotifier()
        self.last_heartbeat: datetime = datetime.utcnow()
        self.is_running: bool = False

        self.detectors: Dict[str, BaseDetector] = {}
        for target in Config.TARGETS:
            if not target.enabled:
                continue
            if target.target_type == TargetType.GOOGLE_FORM:
                self.detectors[target.id] = GoogleFormsDetector(target)
            elif target.target_type == TargetType.HOPS_INSTRUCTIONS:
                self.detectors[target.id] = HopsDetector(target)
            elif target.target_type == TargetType.BEST_OPP_WEB:
                self.detectors[target.id] = BestOpportunityWebDetector(target)
            elif target.target_type == TargetType.CONCORDIA_WEB:
                self.detectors[target.id] = ConcordiaDetector(target)

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.is_file():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to read state file: {e}")
        return {}

    def _save_state(self) -> None:
        try:
            temp_file = self.state_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.state_file)
        except Exception as e:
            logger.error(f"Failed to persist state file: {e}")

    async def check_target(self, target: TargetConfig, session: aiohttp.ClientSession) -> CheckResult:
        detector = self.detectors.get(target.id)
        if not detector:
            raise ValueError(f"No detector registered for target {target.id}")

        headers = {**Config.DEFAULT_HEADERS, **target.custom_headers}
        previous_target_state = self.state.get(target.id, {})

        try:
            logger.debug(f"Checking target [{target.name}] at {target.url}")
            async with session.get(
                target.url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=True
            ) as resp:
                final_url = str(resp.url)
                status_code = resp.status
                html = await resp.text(errors="ignore")

                return await detector.analyze(
                    html=html,
                    final_url=final_url,
                    status_code=status_code,
                    previous_state=previous_target_state
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

        if should_alert:
            logger.info(f"Triggering alert for [{result.target_name}]")
            screenshot_path = await ScreenshotEngine.capture(result.url, result.target_id)
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
            "last_checked": datetime.utcnow().isoformat(),
            "last_error": result.error,
        }
        self._save_state()

    async def run_cycle(self, session: aiohttp.ClientSession) -> List[CheckResult]:
        tasks = []
        for target in Config.TARGETS:
            if target.enabled and target.id in self.detectors:
                tasks.append(self.check_target(target, session))

        results = await asyncio.gather(*tasks, return_exceptions=False)
        for res in results:
            await self.process_check_result(res)

        return results

    async def check_heartbeat(self) -> None:
        if Config.HEARTBEAT_INTERVAL_HOURS <= 0:
            return

        now = datetime.utcnow()
        if now - self.last_heartbeat >= timedelta(hours=Config.HEARTBEAT_INTERVAL_HOURS):
            summary_lines = []
            for tid, tdata in self.state.items():
                status_str = "OPEN" if tdata.get("is_open") else "CLOSED"
                summary_lines.append(f"<b>{tdata.get('name')}:</b> {status_str}")

            await self.notifier.send_heartbeat("\n".join(summary_lines))
            self.last_heartbeat = now

    async def start(self) -> None:
        self.is_running = True
        logger.info(f"Engine started. Polling interval: {Config.CHECK_INTERVAL_SECONDS}s")

        async with aiohttp.ClientSession() as session:
            logger.info("Running baseline target inspection...")
            results = await self.run_cycle(session)
            for r in results:
                logger.info(f"[{r.target_name}] Baseline: {r.current_state}")

            while self.is_running:
                try:
                    await asyncio.sleep(Config.CHECK_INTERVAL_SECONDS)
                    logger.debug("Executing scheduled inspection cycle...")
                    await self.run_cycle(session)
                    await self.check_heartbeat()
                except asyncio.CancelledError:
                    logger.info("Engine received cancellation signal.")
                    break
                except Exception as e:
                    logger.error(f"Unexpected cycle error: {e}", exc_info=True)
                    await asyncio.sleep(10)

    def stop(self) -> None:
        self.is_running = False
        logger.info("Engine stopping...")
