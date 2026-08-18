from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from src.detectors.base import BaseDetector
from src.models import CheckResult, TargetStatus


class HopsDetector(BaseDetector):
    FORM_DOMAINS = [
        "forms.gle",
        "docs.google.com/forms",
        "global-workforce.app",
        "typeform.com",
        "forms.office.com",
        "jotform.com",
        "thegateway",
    ]

    async def analyze(
        self,
        html: str,
        final_url: str,
        status_code: int,
        previous_state: Optional[Dict[str, Any]] = None
    ) -> CheckResult:
        soup = BeautifulSoup(html, "html.parser")

        found_form_links: List[str] = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            full_url = urljoin(final_url, href)
            if any(domain in full_url.lower() for domain in self.FORM_DOMAINS):
                if full_url not in found_form_links:
                    found_form_links.append(full_url)

        # Decompose scripts and styles to compute stable text hash
        for tag in soup(["script", "style", "noscript", "svg", "header", "footer"]):
            tag.decompose()

        text_content = soup.get_text(separator=" ", strip=True)
        current_hash = self.calculate_hash(text_content)

        is_initial_run = not previous_state
        prev_hash = previous_state.get("hash") if previous_state else None
        prev_links = previous_state.get("links", []) if previous_state else []

        new_links = [link for link in found_form_links if link not in prev_links] if not is_initial_run else []
        hash_changed = bool(prev_hash is not None and prev_hash != current_hash)

        is_alert = bool(new_links or hash_changed)

        if new_links:
            summary = "Обнаружены новые ссылки на регистрацию HOPS"
            details = f"На странице появились новые ссылки для подачи заявок ({len(new_links)} шт.)."
        elif hash_changed:
            summary = "Текст инструкций HOPS обновлен"
            details = "На странице изменился контент правил набора."
        else:
            summary = "Страница HOPS под наблюдением (без изменений)"
            details = "Новых регистрационных ссылок или изменений в тексте не обнаружено."

        return CheckResult(
            target_id=self.target.id,
            target_name=self.target.name,
            url=final_url,
            is_alert=is_alert,
            status_changed=(hash_changed or bool(new_links)),
            previous_state=prev_hash,
            current_state=TargetStatus.WATCHING.value,
            summary=summary,
            details=details,
            detected_links=found_form_links,
            html_hash=current_hash,
        )
