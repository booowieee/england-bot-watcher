from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
from src.detectors.base import BaseDetector
from src.models import CheckResult, TargetStatus


class GoogleFormsDetector(BaseDetector):
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

        is_closed_by_url = "closedform" in url_lower
        is_closed_by_text = any(marker in html_lower for marker in self.CLOSED_MARKERS)

        soup = BeautifulSoup(html, "html.parser")
        has_input_fields = bool(
            soup.find("input", {"type": "text"}) or
            soup.find("textarea") or
            soup.find("div", {"role": "listitem"}) or
            soup.find("div", {"role": "radiogroup"})
        )

        if is_closed_by_url or (is_closed_by_text and not has_input_fields):
            current_status = TargetStatus.CLOSED
        elif has_input_fields or ("viewform" in url_lower and not is_closed_by_text):
            current_status = TargetStatus.OPEN
        else:
            current_status = TargetStatus.WATCHING

        prev_status_str = previous_state.get("status") if previous_state else None
        status_changed = bool(prev_status_str and prev_status_str != current_status.value)
        is_alert = (current_status == TargetStatus.OPEN and prev_status_str != TargetStatus.OPEN.value)

        summary = f"Статус формы: {current_status.value}"
        if current_status == TargetStatus.OPEN:
            details = (
                "<b>Форма открыта и принимает заявки.</b>\n"
                "- Обнаружен редирект на /viewform.\n"
                "- Найдены активные поля ввода."
            )
        else:
            details = (
                "Форма закрыта (/closedform).\n"
                "- Прием ответов отключен администратором."
            )

        html_hash = self.calculate_hash(html)

        return CheckResult(
            target_id=self.target.id,
            target_name=self.target.name,
            url=final_url,
            is_alert=is_alert,
            status_changed=status_changed,
            previous_state=prev_status_str,
            current_state=current_status.value,
            summary=summary,
            details=details,
            detected_links=[],
            html_hash=html_hash,
        )
