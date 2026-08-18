"""
Specialized detector for Google Forms status (Closed vs Open).
"""
import re
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
from src.detectors.base import BaseDetector
from src.models import CheckResult, FormStatus
from src.logger import logger


class GoogleFormsDetector(BaseDetector):
    """Detects whether a Google Form has opened and is accepting responses."""

    CLOSED_MARKERS = [
        "closedform",
        "nu mai acceptă răspunsuri",
        "nu se mai acceptă răspunsuri",
        "formularul nu mai acceptă",
        "no longer accepting responses",
        "is no longer accepting",
        "больше не принимает ответы",
        "форма закрыта",
    ]

    async def analyze(
        self,
        html: str,
        final_url: str,
        status_code: int,
        previous_state: Optional[Dict[str, Any]] = None
    ) -> CheckResult:
        html_lower = html.lower()
        url_lower = final_url.lower()

        # Check for closed form markers in URL and HTML content
        is_closed_by_url = "closedform" in url_lower
        is_closed_by_text = any(marker in html_lower for marker in self.CLOSED_MARKERS)

        # Check for active form input elements
        soup = BeautifulSoup(html, "html.parser")
        has_input_fields = bool(
            soup.find("input", {"type": "text"}) or
            soup.find("textarea") or
            soup.find("div", {"role": "listitem"}) or
            soup.find("div", {"role": "radiogroup"})
        )

        # Determine current status
        if is_closed_by_url or (is_closed_by_text and not has_input_fields):
            current_status = FormStatus.CLOSED
        elif has_input_fields or ("viewform" in url_lower and not is_closed_by_text):
            current_status = FormStatus.OPEN
        else:
            current_status = FormStatus.UNKNOWN

        is_open = (current_status == FormStatus.OPEN)
        prev_status_str = previous_state.get("status") if previous_state else None

        # Detect status transition (e.g. CLOSED -> OPEN)
        status_changed = False
        if prev_status_str and prev_status_str != current_status.value:
            status_changed = True

        # Alert if newly opened or if it's the very first run and the form is already open
        is_alert = (status_changed and is_open) or (prev_status_str is None and is_open)

        summary = f"Статус Google Form: {current_status.value}"
        if is_open:
            details = (
                "🔥 <b>ВНИМАНИЕ! АНКЕТА ОТКРЫТА И ПРИНИМАЕТ ЗАЯВКИ!</b>\n"
                "• Страница редиректит на рабочую форму (<code>/viewform</code>).\n"
                "• На форме обнаружены активные поля для ввода данных."
            )
        else:
            details = (
                "🔒 Форма в данный момент закрыта (<code>/closedform</code>).\n"
                "• Прием ответов отключен администратором Best Opportunity."
            )

        html_hash = self.calculate_hash(html)

        return CheckResult(
            target_id=self.target.id,
            target_name=self.target.name,
            url=final_url,
            is_open=is_open,
            status_changed=status_changed,
            previous_state=prev_status_str,
            current_state=current_status.value,
            summary=summary,
            details=details,
            detected_links=[],
            html_hash=html_hash,
        )
