"""
Cấu hình trung tâm cho LINH DỊ — THẦN BÍ PHỤC TÔ.
Không expose config này ra người chơi (Rule 2 trong spec).
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "world.db")

TOTAL_GHOSTS = 120          # tổng số Quỷ độc nhất trong thế giới (Rule 8/43-1)
TOTAL_LOCATIONS = 38        # tổng số địa điểm khám phá (Section 6)

# Thông báo lỗi chuẩn hoá cho người chơi — KHÔNG BAO GIỜ lộ traceback/debug (Rule 2)
GENERIC_ERROR_MSG = "⚠️ Có một sự cố bất thường. Vui lòng thử lại sau."

# ---- Logging: chỉ ghi ra console/server log, không public cho người chơi ----
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("linh_di")
