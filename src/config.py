import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv
from src.models import TargetConfig, TargetType

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    ADMIN_CHAT_ID: str = os.getenv("TELEGRAM_ADMIN_ID", "").strip() or os.getenv("TELEGRAM_CHAT_ID", "").strip()

    CHECK_INTERVAL_SECONDS: int = int(os.getenv("CHECK_INTERVAL_SECONDS", "45"))
    HEARTBEAT_INTERVAL_HOURS: int = int(os.getenv("HEARTBEAT_INTERVAL_HOURS", "12"))

    ENABLE_SCREENSHOTS: bool = os.getenv("ENABLE_SCREENSHOTS", "true").lower() in ("true", "1", "yes")
    DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "false").lower() in ("true", "1", "yes")

    ENABLE_WAYBACK_ARCHIVE: bool = os.getenv("ENABLE_WAYBACK_ARCHIVE", "true").lower() in ("true", "1", "yes")
    WAYBACK_INTERVAL_HOURS: int = int(os.getenv("WAYBACK_INTERVAL_HOURS", "12"))

    DATA_DIR: Path = BASE_DIR / "data"
    STATE_FILE: Path = DATA_DIR / "monitor_state.json"
    WHITELIST_FILE: Path = DATA_DIR / "whitelist.json"
    SCREENSHOTS_DIR: Path = DATA_DIR / "screenshots"
    LOGS_DIR: Path = BASE_DIR / "logs"

    DEFAULT_HEADERS: dict = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8,ro;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    TARGETS: List[TargetConfig] = [
        TargetConfig(
            id="best_opp_form",
            name="Best Opportunity Google Form",
            url="https://forms.gle/kkdrh8aNPQNHQkCk8",
            target_type=TargetType.GOOGLE_FORM,
            enabled=True,
        ),
        TargetConfig(
            id="best_opp_web",
            name="Best Opportunity Website",
            url="https://www.jobopportunityuk.com/",
            target_type=TargetType.BEST_OPP_WEB,
            enabled=True,
        ),
        TargetConfig(
            id="hops_instructions",
            name="HOPS Labour Solutions Instructions",
            url="https://www.hopslaboursolutions.com/recruitment-instructions",
            target_type=TargetType.HOPS_INSTRUCTIONS,
            enabled=True,
        ),
        TargetConfig(
            id="concordia_web",
            name="Concordia UK Portal",
            url="https://www.concordia.org.uk/",
            target_type=TargetType.CONCORDIA_WEB,
            enabled=True,
        ),
    ]


for directory in (Config.DATA_DIR, Config.SCREENSHOTS_DIR, Config.LOGS_DIR):
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
