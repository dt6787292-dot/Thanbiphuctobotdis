"""
Nạp dữ liệu tĩnh (Quỷ / Địa điểm / Vật phẩm) và validate chéo lúc khởi động,
để lỗi cấu hình bị bắt ngay khi bot start thay vì lộ ra giữa gameplay.
"""
import json
import os
from config import logger, TOTAL_GHOSTS, TOTAL_LOCATIONS

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

GHOSTS = {}
LOCATIONS = {}
ITEMS = {}
QUESTS = {}
ACHIEVEMENTS = {}

# Ánh xạ ngược tên hiển thị (tiếng Việt) -> khóa nội bộ. Chỉ dùng nội bộ để
# tra cứu; mọi giao diện người chơi (menu chọn, embed...) chỉ nên hiển thị
# và nhận lại TÊN, không bao giờ lộ khóa nội bộ (ghost_id / location_id) ra
# phía người chơi.
_GHOST_ID_BY_NAME = {}
_LOCATION_ID_BY_NAME = {}

TIER_ORDER = ["quy_binh", "quy_tuong", "quy_soai", "quy_vuong", "quy_hoang", "cam_ky"]
TIER_LABELS = {
    "quy_binh": "⚪ Quỷ Binh", "quy_tuong": "🟢 Quỷ Tướng", "quy_soai": "🔵 Quỷ Soái",
    "quy_vuong": "🟣 Quỷ Vương", "quy_hoang": "🔴 Quỷ Hoàng", "cam_ky": "⚫ Cấm Kỵ",
}
RARITY_LABELS = {
    "thuong": "⚪ Thường", "hiem": "🟢 Hiếm", "rat_hiem": "🔵 Rất hiếm",
    "cuc_hiem": "🟣 Cực hiếm", "dac_biet": "🔴 Đặc biệt", "cam_ky": "⚫ Cấm kỵ",
}


def _load_json(filename):
    path = os.path.join(_DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_all():
    global GHOSTS, LOCATIONS, ITEMS, QUESTS, ACHIEVEMENTS
    global _GHOST_ID_BY_NAME, _LOCATION_ID_BY_NAME
    GHOSTS = _load_json("ghosts.json")
    LOCATIONS = _load_json("locations.json")
    ITEMS = _load_json("items.json")
    QUESTS = _load_json("quests.json")
    ACHIEVEMENTS = _load_json("achievements.json")
    _GHOST_ID_BY_NAME = {g["name"]: gid for gid, g in GHOSTS.items()}
    _LOCATION_ID_BY_NAME = {l["name"]: lid for lid, l in LOCATIONS.items()}
    _validate()
    logger.info(
        f"Đã nạp {len(GHOSTS)}/{TOTAL_GHOSTS} Quỷ, {len(LOCATIONS)}/{TOTAL_LOCATIONS} địa điểm, "
        f"{len(ITEMS)} vật phẩm, {len(QUESTS)} nhiệm vụ, {len(ACHIEVEMENTS)} thành tựu."
    )


def _validate():
    errors = []

    if len(GHOSTS) > TOTAL_GHOSTS:
        errors.append(f"Số Quỷ trong data ({len(GHOSTS)}) vượt quá TOTAL_GHOSTS={TOTAL_GHOSTS}.")
    if len(LOCATIONS) > TOTAL_LOCATIONS:
        errors.append(f"Số địa điểm trong data ({len(LOCATIONS)}) vượt quá TOTAL_LOCATIONS={TOTAL_LOCATIONS}.")

    # Tên hiển thị phải là duy nhất trong từng bộ dữ liệu, vì các menu chọn
    # (StringSelectMenu) dùng thẳng TÊN làm value để tra cứu ngược lại khóa
    # nội bộ — trùng tên sẽ khiến tra cứu sai đối tượng.
    if len(_GHOST_ID_BY_NAME) != len(GHOSTS):
        errors.append("Có tên Quỷ (name) bị trùng lặp trong ghosts.json.")
    if len(_LOCATION_ID_BY_NAME) != len(LOCATIONS):
        errors.append("Có tên địa điểm (name) bị trùng lặp trong locations.json.")

    # Mỗi ghost.spawn_location phải tồn tại trong LOCATIONS
    for gid, gdef in GHOSTS.items():
        loc = gdef.get("spawn_location")
        if loc and loc not in LOCATIONS:
            errors.append(f"Quỷ '{gid}' có spawn_location='{loc}' không tồn tại trong locations.json.")
        if gdef.get("tier") not in TIER_ORDER:
            errors.append(f"Quỷ '{gid}' có tier không hợp lệ: {gdef.get('tier')}")

    # Mỗi location.boss (nếu có) phải trỏ tới ghost tồn tại
    # Mỗi location.requires_location (nếu có) phải trỏ tới location tồn tại (chuỗi unlock tuyến tính)
    for lid, ldef in LOCATIONS.items():
        boss = ldef.get("boss")
        if boss and boss not in GHOSTS:
            errors.append(f"Địa điểm '{lid}' có boss='{boss}' không tồn tại trong ghosts.json.")
        req = ldef.get("requires_location")
        if req and req not in LOCATIONS:
            errors.append(f"Địa điểm '{lid}' có requires_location='{req}' không tồn tại.")

    # Nhiệm vụ: requires_quest phải trỏ tới quest tồn tại; objective.target (kill_boss/tier) phải hợp lệ
    for qid, qdef in QUESTS.items():
        req_q = qdef.get("requires", {}).get("requires_quest")
        if req_q and req_q not in QUESTS:
            errors.append(f"Nhiệm vụ '{qid}' có requires_quest='{req_q}' không tồn tại.")
        obj = qdef.get("objective", {})
        target = obj.get("target")
        if obj.get("event") == "kill_boss" and target and target not in GHOSTS:
            errors.append(f"Nhiệm vụ '{qid}' có objective.target='{target}' không tồn tại trong ghosts.json.")
        if obj.get("event") == "capture_ghost_tier_at_least" and target and target not in TIER_ORDER:
            errors.append(f"Nhiệm vụ '{qid}' có objective.target bậc không hợp lệ: {target}")

    for aid, adef in ACHIEVEMENTS.items():
        if adef.get("condition", {}).get("type") is None:
            errors.append(f"Thành tựu '{aid}' thiếu condition.type.")

    if errors:
        for e in errors:
            logger.error(f"[VALIDATE] {e}")
        raise RuntimeError(
            f"Phát hiện {len(errors)} lỗi tham chiếu dữ liệu tĩnh — dừng khởi động bot. "
            f"Xem log server để biết chi tiết."
        )


def get_ghost(ghost_id: str) -> dict | None:
    return GHOSTS.get(ghost_id)


def get_location(location_id: str) -> dict | None:
    return LOCATIONS.get(location_id)


def get_ghost_id_by_name(name: str) -> str | None:
    """Tra khóa nội bộ từ TÊN Quỷ hiển thị. Dùng khi nhận value từ StringSelectMenu."""
    return _GHOST_ID_BY_NAME.get(name)


def get_ghost_by_name(name: str) -> dict | None:
    return GHOSTS.get(get_ghost_id_by_name(name))


def get_location_id_by_name(name: str) -> str | None:
    """Tra khóa nội bộ từ TÊN địa điểm hiển thị. Dùng khi nhận value từ StringSelectMenu."""
    return _LOCATION_ID_BY_NAME.get(name)


def get_location_by_name(name: str) -> dict | None:
    return LOCATIONS.get(get_location_id_by_name(name))


def get_item(item_id: str) -> dict | None:
    return ITEMS.get(item_id)


def ghosts_at(location_id: str) -> dict:
    return {gid: g for gid, g in GHOSTS.items() if g.get("spawn_location") == location_id}


def location_unlock_chain(location_id: str) -> list:
    """Trả về danh sách location_id từ khởi đầu tới location_id (chuỗi phụ thuộc tuyến tính)."""
    chain = []
    cur = location_id
    seen = set()
    while cur and cur not in seen:
        chain.append(cur)
        seen.add(cur)
        cur = LOCATIONS.get(cur, {}).get("requires_location")
    return list(reversed(chain))
