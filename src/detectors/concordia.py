from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from src.detectors.base import BaseDetector
from src.models import CheckResult


class ConcordiaDetector(BaseDetector):
    async def analyze(
        self,
        html: str,
        final_url: str,
        status_code: int,
        previous_state: Optional[Dict[str, Any]] = None
    ) -> CheckResult:
        soup = BeautifulSoup(html, "html.parser")

        detected_links: List[str] = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            full_url = urljoin(final_url, href)
            if any(k in full_url.lower() for k in ["seasonal", "sws", "apply", "worker"]):
                if full_url not in detected_links:
                    detected_links.append(full_url)

        text_content = soup.get_text(separator=" ", strip=True)
        current_hash = self.calculate_hash(text_content)

        prev_hash = previous_state.get("hash") if previous_state else None
        prev_links = previous_state.get("links", []) if previous_state else []

        new_links = [l for l in detected_links if l not in prev_links]
        hash_changed = (prev_hash is not None and prev_hash != current_hash)

        is_alert = bool(new_links) and any("apply" in l.lower() or "form" in l.lower() for l in new_links)

        if is_alert:
            summary = "Обновление на сайте Concordia UK"
            details = f"Обнаружены новые ссылки для подачи заявок: {len(new_links)} шт."
        elif hash_changed:
            summary = "Текст сайта Concordia UK изменился"
            details = "Контент страницы обновлен."
        else:
            summary = "Сайт Concordia UK без изменений"
            details = "Новых регистрационных форм не зафиксировано."

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
