from __future__ import annotations

import os
from pathlib import Path

SEASON = os.getenv("SEASON", "2026/27")
PREDICTION_REPO = os.getenv("PREDICTION_REPO", "yapayforzeka1/Haftalik-Mac-Tahmini")
PREDICTION_BRANCH = os.getenv("PREDICTION_BRANCH", "main")
PREDICTION_FILE = os.getenv("PREDICTION_FILE", "match_predictions.json")
PREDICTION_REPO_TOKEN = os.getenv("PREDICTION_REPO_TOKEN", "")
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")
FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"
COMPETITION_CODE = os.getenv("COMPETITION_CODE", "CL")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
MIN_CONSENSUS_AI = int(os.getenv("MIN_CONSENSUS_AI", "3"))
REPORT_DELAY_MINUTES = int(os.getenv("REPORT_DELAY_MINUTES", "60"))

ANALYSIS_TELEGRAM_BOT_TOKEN = os.getenv("ANALYSIS_TELEGRAM_BOT_TOKEN", "")
ANALYSIS_TELEGRAM_CHAT_ID = os.getenv("ANALYSIS_TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
REPORT_DIR = Path(os.getenv("REPORT_DIR", "reports"))
WEEKLY_REPORTS_FILE = DATA_DIR / "weekly_reports.json"
SEASON_PERFORMANCE_FILE = DATA_DIR / "season_performance.json"
PERFORMANCE_STATE_FILE = DATA_DIR / "performance_state.json"

TERMINAL_STATUSES = {
    "FINISHED",
    "POSTPONED",
    "CANCELLED",
    "SUSPENDED",
    "ABANDONED",
}

MODEL_ORDER = [
    "Gemini 3.6 Flash",
    "Mistral Small Latest",
    "Groq Qwen 3.6 27B",
    "Cohere Command A+",
    "Groq GPT-OSS 120B",
]

MODEL_SHORT = {
    "Gemini 3.6 Flash": "GEMINI",
    "Mistral Small Latest": "MISTRAL",
    "Groq Qwen 3.6 27B": "QWEN",
    "Cohere Command A+": "COHERE",
    "Groq GPT-OSS 120B": "GPT-OSS",
}
