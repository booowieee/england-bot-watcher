"""
Detector for the Best Opportunity official agency website (jobopportunityuk.com).
"""
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from src.detectors.base import BaseDetector
from src.models import CheckResult


class BestOpportunityWebDetector(BaseDetector):
    """Monitors jobopportunityuk.com for new form embeds, application announcements, and links."""

    FORM_PATTERNS = [
        "forms.gle",
        "docs.google.com/forms",
        "recrutare",
        "formular",
        "apply",
    ]

    async def analyze(
        self,
        html: str,
        final_url: str,
        status_code: int,
        previous_state: Optional[Dict[str, Any]] = None
    ) -> CheckResult:
        soup = BeautifulSoup(html, "html.parser")

        # 1. Search for application links & iframe embeds
        detected_links: List[str] = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            full_url = urljoin(final_url, href)
            if any(p in full_url.lower() for p in self.FORM_PATTERNS):
                if full_url not in detected_links and not full_url.endswith("#"):
                    detected_links.append(full_url)

        for iframe in soup.find_all("iframe", src=True):
            src = iframe["src"].strip()
            full_url = urljoin(final_url, src)
            if any(p in full_url.lower() for p in self.FORM_PATTERNS):
                if full_url not in detected_links:
                    detected_links.append(full_url)

        # 2. Content Hash
        text_content = soup.get_text(separator=" ", strip=True)
        current_hash = self.calculate_hash(text_content)

        prev_hash = previous_state.get("hash") if previous_state else None
        prev_links = previous_state.get("links", []) if previous_state else []

        new_links = [l for l in detected_links if l not in prev_links]
        hash_changed = (prev_hash is not None and prev_hash != current_hash)

        is_alert = bool(new_links) or (hash_changed and any("form" in l for l in detected_links))

        if is_alert:
            summary = "🔥 ВНИМАНИЕ: Обновление на сайте Best Opportunity!"
            details = (
                "🚨 <b>На сайте jobopportunityuk.com обнаружены новые ссылки / формы!</b>\n"
                f"• Новых ссылок найдено: {len(new_links)}\n"
                f"• Всего ссылок: {len(detected_links)}"
            )
        elif hash_changed:
            summary = "Текст сайта Best Opportunity изменился."
            details = "ℹ️ Контент на главной странице обновлен."
        else:
            summary = "Сайт Best Opportunity без изменений."
            details = "Новых регистрационных форм на сайте не обнаружено."

        return CheckResult(
            target_id=self.target.id,
            target_name=self.target.name,
            url=final_url,
            is_open=is_alert,
            status_changed=(hash_changed or bool(new_links)),
            previous_state=prev_hash,
            current_state=current_hash,
            summary=summary,
            details=details,
            detected_links=detected_links,
            html_hash=current_hash,
        )
