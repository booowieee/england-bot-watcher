import asyncio
import json
import shutil
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Dict, Any, List
import aiohttp
from src.config import Config
from src.logger import logger
from src.models import TargetConfig, TargetType, CheckResult, TargetStatus
from src.browser import ScreenshotEngine
from src.notifier import TelegramNotifier
from src.archiver import WaybackArchiver
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
        self.last_wayback_archive: datetime = datetime.now(UTC)
        self.is_running: bool = False
        self._stop_event: asyncio.Event | None = None
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
        self.screenshot_engine = ScreenshotEngine()
        self.archiver = WaybackArchiver()
        self.notifier: TelegramNotifier | None = None
        self._poller_task: asyncio.Task | None = None

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

    def _get_target_type(self, target_id: str) -> TargetType | None:
        for target in Config.TARGETS:
            if target.id == target_id:
                return target.target_type
        return None

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
                is_alert=False,
                status_changed=False,
                previous_state=None,
                current_state=TargetStatus.ERROR.value,
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
                is_alert=False,
                status_changed=False,
                previous_state=previous_target_state.get("status"),
                current_state=TargetStatus.ERROR.value,
                summary=f"Connection error: {type(e).__name__}",
                details=str(e),
                error=str(e),
            )

    async def process_check_result(self, result: CheckResult, is_baseline: bool = False) -> None:
        target_state = self.state.get(result.target_id, {})
        prev_status = target_state.get("status")
        target_type = self._get_target_type(result.target_id)

        # Never trigger alerts during baseline startup (except if Google Form is actively OPEN)
        if is_baseline:
            result.is_alert = (
                target_type == TargetType.GOOGLE_FORM
                and result.current_state == TargetStatus.OPEN.value
            )
        else:
            # Handle form open/close transitions for Google Forms targets
            if target_type == TargetType.GOOGLE_FORM:
                if result.current_state == TargetStatus.OPEN.value and prev_status == TargetStatus.CLOSED.value:
                    result.is_alert = True
                elif result.current_state == TargetStatus.CLOSED.value and prev_status == TargetStatus.OPEN.value:
                    logger.info(f"[{result.target_name}] form closed.")
                    await self.notifier.send_resolved(result.target_name, result.url)

        if result.is_alert:
            logger.info(f"Alert triggered for [{result.target_name}]")
            screenshots = await self.screenshot_engine.capture_chunks(result.url, result.target_id)
            result.screenshots = screenshots

            try:
                alert_title = "АНКЕТА ОТКРЫТА" if result.current_state == TargetStatus.OPEN.value else "ОБНОВЛЕНИЕ НА САЙТЕ"
                await self.notifier.send_alert(
                    title=alert_title,
                    target_name=result.target_name,
                    url=result.url,
                    details=result.details,
                    screenshots=screenshots,
                    detected_links=result.detected_links,
                )
            finally:
                for path in screenshots:
                    try:
                        Path(path).unlink(missing_ok=True)
                    except Exception:
                        pass

        self.state[result.target_id] = {
            "name": result.target_name,
            "url": result.url,
            "status": result.current_state,
            "hash": result.html_hash,
            "links": result.detected_links,
            "last_checked": datetime.now(UTC).isoformat(),
            "last_error": result.error,
        }
        self._save_state()

    async def run_cycle(self, is_baseline: bool = False) -> List[CheckResult]:
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
            await self.process_check_result(res, is_baseline=is_baseline)
            valid_results.append(res)

        return valid_results

    def get_status_report(self) -> str:
        lines = ["<b>SWS Watcher: Текущий статус целей</b>\n"]
        for target in Config.TARGETS:
            if not target.enabled:
                continue
            data = self.state.get(target.id, {})
            status = data.get("status", TargetStatus.WATCHING.value)
            last_checked = data.get("last_checked", "—")
            if last_checked != "—":
                try:
                    dt = datetime.fromisoformat(last_checked)
                    last_checked = dt.strftime("%H:%M:%S UTC")
                except Exception:
                    pass

            lines.append(
                f"<b>{target.name}</b>\n"
                f"- Статус: <code>{status}</code>\n"
                f"- Проверено: {last_checked}\n"
                f"- URL: <code>{target.url}</code>\n"
            )

        lines.append(f"<i>Интервал проверки: {Config.CHECK_INTERVAL_SECONDS}с. Все сервисы активны.</i>")
        return "\n".join(lines)

    async def run_manual_visual_check_for(self, chat_id: str | None = None) -> None:
        """Executes on-demand check with human-readable viewport screenshots for each target."""
        logger.info(f"Executing visual check requested by chat {chat_id or 'broadcast'}...")

        for target in Config.TARGETS:
            if not target.enabled or target.id not in self.detectors:
                continue

            res = await self.check_target(target)
            screenshots = await self.screenshot_engine.capture_chunks(target.url, target.id)

            try:
                if chat_id:
                    details = f"<b>Статус:</b> <code>{res.current_state}</code>\n{res.summary}"
                    title = f"Отчет проверки: {target.name}"
                    inline_keyboard = {"inline_keyboard": [[{"text": "Открыть анкету", "url": res.url}]]}

                    if not screenshots:
                        await self.notifier._send_message_to(chat_id, f"<b>{title}</b>\n\n{details}", inline_keyboard)
                    else:
                        total = len(screenshots)
                        for i, photo_path in enumerate(screenshots):
                            part_label = f" (Часть {i+1}/{total})" if total > 1 else ""
                            part_caption = f"<b>{title}</b>{part_label}\n<b>Цель:</b> {target.name}\n\n{details}" if i == 0 else f"<b>{target.name}</b>{part_label}"
                            markup = inline_keyboard if (i == total - 1) else None
                            await self.notifier._send_photo_to(chat_id, photo_path, part_caption, markup)
                else:
                    await self.notifier.send_alert(
                        title=f"Отчет проверки: {target.name}",
                        target_name=target.name,
                        url=res.url,
                        details=f"<b>Статус:</b> <code>{res.current_state}</code>\n{res.summary}",
                        screenshots=screenshots,
                        detected_links=res.detected_links,
                    )
            finally:
                for path in screenshots:
                    try:
                        Path(path).unlink(missing_ok=True)
                    except Exception:
                        pass

        completion_msg = "<b>Ручная проверка завершена.</b>\nВсе ресурсы проверены, актуальные снимки страниц отправлены выше."
        if chat_id:
            await self.notifier._send_message_to(chat_id, completion_msg)
        else:
            await self.notifier.send_heartbeat(completion_msg)

    async def run_manual_archive(self, chat_id: str | None = None) -> None:
        """Executes manual archival of all targets to Wayback Machine and reports results."""
        target_cid = chat_id or self.notifier.admin_chat_id
        await self.notifier._send_message_to(target_cid, "⏳ Отправляю страницы на архивацию в Wayback Machine (web.archive.org)...")

        results = await self.archiver.archive_targets(Config.TARGETS, self._session)
        lines = ["<b>Результаты архивации в Wayback Machine:</b>\n"]
        for name, snap_url in results.items():
            if snap_url:
                lines.append(f"• <b>{name}</b>:\n  <code>{snap_url}</code>\n")
            else:
                lines.append(f"• <b>{name}</b>: <i>Ошибка отправки</i>\n")

        lines.append("<i>Снимки сохранены в глобальном веб-архиве.</i>")
        await self.notifier._send_message_to(target_cid, "\n".join(lines))

    async def check_wayback_archival(self) -> None:
        """Scheduled daily/twice-daily archival task."""
        if not Config.ENABLE_WAYBACK_ARCHIVE or Config.WAYBACK_INTERVAL_HOURS <= 0:
            return

        now = datetime.now(UTC)
        if now - self.last_wayback_archive >= timedelta(hours=Config.WAYBACK_INTERVAL_HOURS):
            logger.info("Executing scheduled Wayback Machine archival for all targets...")
            try:
                await self.archiver.archive_targets(Config.TARGETS, self._session)
                self.last_wayback_archive = now
                logger.info("Scheduled Wayback Machine archival completed.")
            except Exception as e:
                logger.error(f"Error during scheduled Wayback archival: {e}")

    async def check_heartbeat(self) -> None:
        if Config.HEARTBEAT_INTERVAL_HOURS <= 0:
            return

        now = datetime.now(UTC)
        if now - self.last_heartbeat >= timedelta(hours=Config.HEARTBEAT_INTERVAL_HOURS):
            summary_lines = []
            for tid, tdata in self.state.items():
                status_str = tdata.get("status", TargetStatus.WATCHING.value)
                summary_lines.append(f"<b>{tdata.get('name')}:</b> {status_str}")

            await self.notifier.send_heartbeat("\n".join(summary_lines))
            self.last_heartbeat = now

    def _cleanup_old_screenshots(self) -> None:
        if Config.SCREENSHOTS_DIR.is_dir():
            for p in Config.SCREENSHOTS_DIR.glob("*.png"):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

    async def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep that can be interrupted immediately by stop_event."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def start(self) -> None:
        self.is_running = True
        self._stop_event = asyncio.Event()
        self._cleanup_old_screenshots()

        connector = aiohttp.TCPConnector(limit=20, limit_per_host=5, ttl_dns_cache=300)
        self._session = aiohttp.ClientSession(connector=connector)
        self.notifier = TelegramNotifier(session=self._session)

        if not self.notifier.is_configured:
            logger.warning("Telegram credentials missing. Bot will monitor but cannot send notifications.")

        if Config.ENABLE_SCREENSHOTS:
            await self.screenshot_engine.initialize()

        self._poller_task = asyncio.create_task(self.notifier.start_polling(self))
        logger.info(f"Engine started. Polling interval: {Config.CHECK_INTERVAL_SECONDS}s")

        try:
            logger.info("Running silent baseline inspection...")
            results = await self.run_cycle(is_baseline=True)
            for r in results:
                logger.info(f"[{r.target_name}] Baseline: {r.current_state}")

            while self.is_running:
                try:
                    await self._interruptible_sleep(Config.CHECK_INTERVAL_SECONDS)
                    if not self.is_running:
                        break
                    logger.debug("Executing inspection cycle...")
                    await self.run_cycle(is_baseline=False)
                    await self.check_heartbeat()
                    await self.check_wayback_archival()
                except asyncio.CancelledError:
                    logger.info("Engine received cancellation signal.")
                    raise
                except Exception as e:
                    logger.error(f"Cycle error: {e}", exc_info=True)
                    await self._interruptible_sleep(10)
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        if self._poller_task and not self._poller_task.done():
            self._poller_task.cancel()
            try:
                await self._poller_task
            except asyncio.CancelledError:
                pass

        await self.screenshot_engine.close()
        await self.notifier.close()
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("Engine resources released.")

    def stop(self) -> None:
        self.is_running = False
        if self._stop_event:
            self._stop_event.set()
        logger.info("Engine stopping...")
