"""
Specialized detector for HOPS Labour Solutions recruitment instructions and flash registration windows.
"""
import re
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from src.detectors.base import BaseDetector
from src.models import CheckResult
from src.logger import logger


class HopsDetector(BaseDetector):
    """Monitors HOPS recruitment instructions for country updates, flash windows, and registration links."""

    KEYWORD_TRIGGERS = [
        r"\bmoldova\b",
        r"\bмолдова\b",
        r"\bмолдави[ияе]\b",
        r"регистрация откроется",
        r"online registration will open",
        r"recruitment window",
        r"apply now",
        r"new intake",
        r"season 2026",
        r"season 2027",
    ]

    FORM_DOMAINS = [
        "forms.gle",
        "docs.google.com/forms",
        "global-workforce.app",
        "typeform.com",
        "forms.office.com",
        "jotform.com",
    ]

    async def analyze(
        self,
        html: str,
        final_url: str,
        status_code: int,
        previous_state: Optional[Dict[str, Any]] = None
    ) -> CheckResult:
        soup = BeautifulSoup(html, "html.parser")
        html_lower = html.lower()

        # 1. Extract all application / external form links
        found_form_links: List[str] = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            full_url = urljoin(final_url, href)
            if any(domain in full_url.lower() for domain in self.FORM_DOMAINS):
                if full_url not in found_form_links:
                    found_form_links.append(full_url)

        # 2. Check for high-priority keyword triggers
        matched_keywords: List[str] = []
        for pattern in self.KEYWORD_TRIGGERS:
            if re.search(pattern, html_lower, re.IGNORECASE):
                matched_keywords.append(pattern.replace(r"\b", ""))

        # 3. Hash calculation
        text_content = soup.get_text(separator=" ", strip=True)
        current_hash = self.calculate_hash(text_content)

        prev_hash = previous_state.get("hash") if previous_state else None
        prev_links = previous_state.get("links", []) if previous_state else []

        # 4. Determine changes
        new_links = [link for link in found_form_links if link not in prev_links]
        hash_changed = (prev_hash is not None and prev_hash != current_hash)

        # Alert conditions:
        # - New registration form link appeared
        # - Specific mention of Moldova or new registration announcement appeared
        is_alert = False
        alert_reasons = []

        if new_links:
            is_alert = True
            alert_reasons.append(f"Обнаружены новые ссылки на регистрацию: {len(new_links)} шт.")

        if "moldova" in matched_keywords or "молдова" in matched_keywords:
            if not previous_state or "moldova" not in previous_state.get("matched_keywords", []):
                is_alert = True
                alert_reasons.append("⚡ Обнаружено упоминание Молдовы в правилах набора!")

        if hash_changed and not is_alert:
            # Text was updated without new form links
            summary = "Текст инструкций HOPS обновлен."
            details = (
                "ℹ️ <b>На странице HOPS изменился контент.</b>\n"
                "• Хэш страницы обновился. Новых прямых ссылок пока нет."
            )
        elif is_alert:
            summary = "🔥 ВНИМАНИЕ: Изменение в HOPS Labour Solutions!"
            details = (
                f"🚨 <b>{summary}</b>\n"
                f"• {chr(10).join(alert_reasons)}\n"
                f"• Ключевые слова: {', '.join(matched_keywords)}"
            )
        else:
            summary = "Страница HOPS без критических изменений."
            details = "Инструкции HOPS на прежнем уровне. Новых регистрационных ссылок не найдено."

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
            detected_links=found_form_links,
            html_hash=current_hash,
        )
