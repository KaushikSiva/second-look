import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

log = logging.getLogger("second-look")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


LIVE_MODEL = env("LIVE_MODEL", "gemini-3.8-live")
TEXT_MODEL = env("TEXT_MODEL", "gemini-3.8-flash")
JEV_MODEL = env("JEV_MODEL", "jev-latest")
LIVE_VOICE = env("LIVE_VOICE", "Puck")
AGENTMAIL_INBOX = env("AGENTMAIL_INBOX", "second-look")
USER_EMAIL = env("USER_EMAIL")  # where alerts go; blank = alerts only shown in the panel


def has(name: str) -> bool:
    return bool(env(name))
