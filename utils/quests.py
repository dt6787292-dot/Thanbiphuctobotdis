"""
Engine Nhiệm vụ (Section 33) + Thành tựu (Section 35) — chấm điểm dựa trên
sự kiện gameplay thật (event-driven), không phải AI quyết định (đúng Rule 36).

Các nơi gọi on_event(...):
  - commands/explore.py : "explore_success", "loot_item", "visit_location_distinct"
  - commands/ghost.py / explore.py (KhongCheView) : "capture_ghost", "capture_ghost_tier_at_least"
  - commands/battle.py  : "kill_ghost", "kill_boss"
"""
import time

from utils import data, catalog
from config import logger


def _utc_date_str(epoch: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(epoch))


def _today_str() -> str:
    return _utc_date_str(int(time.time()))


# ------------------------------------------------------------------- Quests --
def _quest_available(user_id: int, quest_id: str, qdef: dict, player_row) -> bool:
    req = qdef.get("requires", {})
    if player_row["level"] < req.get("min_level", 1):
        return False
    req_quest = req.get("requires_quest")
    if req_quest:
        prev = data.get_player_quest(user_id, req_quest)
        if not prev or prev["status"] != "claimed":
            return False

    existing = data.get_player_quest(user_id, quest_id)
    if existing is None:
        return True
    if qdef.get("repeatable") and existing["status"] == "claimed":
        # Nhiệm vụ hằng ngày chỉ nhận lại được sau khi sang ngày mới (UTC)
        if not existing["completed_at"]:
            return True
        return _utc_date_str(existing["completed_at"]) != _today_str()
    return False


def list_available_quests(user_id: int) -> list[tuple[str, dict]]:
    player = data.get_player(user_id)
    return [
        (qid, qdef) for qid, qdef in catalog.QUESTS.items()
        if _quest_available(user_id, qid, qdef, player)
    ]


def list_active_quests(user_id: int) -> list[tuple[str, dict, object]]:
    rows = data.get_active_quests(user_id)
    return [(r["quest_id"], catalog.QUESTS[r["quest_id"]], r) for r in rows if r["quest_id"] in catalog.QUESTS]


def list_completed_unclaimed(user_id: int) -> list[tuple[str, dict, object]]:
    rows = data.get_all_player_quests(user_id)
    return [
        (r["quest_id"], catalog.QUESTS[r["quest_id"]], r)
        for r in rows if r["status"] == "completed" and r["quest_id"] in catalog.QUESTS
    ]


def accept(user_id: int, quest_id: str) -> bool:
    qdef = catalog.QUESTS.get(quest_id)
    if not qdef:
        return False
    player = data.get_player(user_id)
    if not _quest_available(user_id, quest_id, qdef, player):
        return False
    if qdef.get("repeatable"):
        existing = data.get_player_quest(user_id, quest_id)
        if existing and existing["status"] == "claimed":
            data.reset_daily_quest(user_id, quest_id)
    return data.accept_quest(user_id, quest_id)


def _apply_rewards(user_id: int, rewards: dict):
    from utils import game  # tránh import vòng ở module-level
    player = data.get_player(user_id)
    new_level, new_exp, new_hp_max, leveled = game.apply_exp(player, rewards.get("exp", 0))
    data.update_player(
        user_id, level=new_level, exp=new_exp, hp_max=new_hp_max,
        money=player["money"] + rewards.get("money", 0),
    )
    for item_id, qty in rewards.get("items", {}).items():
        data.add_item(user_id, item_id, qty)
    if rewards.get("title"):
        data.update_player(user_id, title=rewards["title"])


def claim_and_apply(user_id: int, quest_id: str) -> dict | None:
    qdef = catalog.QUESTS.get(quest_id)
    if not qdef or not data.claim_quest(user_id, quest_id):
        return None
    _apply_rewards(user_id, qdef["rewards"])
    return qdef["rewards"]


def _target_matches(obj: dict, event: str, target: str) -> bool:
    if not obj.get("target"):
        return True
    if event == "capture_ghost_tier_at_least":
        # "target" trong quest là bậc TỐI THIỂU yêu cầu -> mọi Quỷ bậc >= đều tính
        try:
            return catalog.TIER_ORDER.index(target) >= catalog.TIER_ORDER.index(obj["target"])
        except ValueError:
            return False
    return obj["target"] == target


def on_event(user_id: int, event: str, *, amount: int = 1, target: str = None) -> list[str]:
    """
    Cập nhật tiến độ mọi nhiệm vụ ACTIVE khớp event (và target nếu nhiệm vụ có target).
    Trả về danh sách quest_id vừa HOÀN THÀNH (chưa claim) trong lần gọi này.
    """
    newly_completed = []
    for row in data.get_active_quests(user_id):
        qdef = catalog.QUESTS.get(row["quest_id"])
        if not qdef:
            continue
        obj = qdef["objective"]
        if obj["event"] != event or not _target_matches(obj, event, target):
            continue

        new_progress = row["progress"] + amount
        if new_progress >= obj["count"]:
            data.set_quest_progress(user_id, row["quest_id"], obj["count"], status="completed")
            newly_completed.append(row["quest_id"])
        else:
            data.set_quest_progress(user_id, row["quest_id"], new_progress)
    return newly_completed


def process_and_notify(user_id: int, events: list[tuple]) -> str:
    """
    events: list các tuple (event, amount, target) — target có thể None.
    Chạy on_event cho từng cái, rồi check_achievements 1 lần, trả về đoạn text
    thông báo (rỗng nếu không có gì mới) để nối vào embed/message hiện có.
    """
    completed_ids = []
    for ev in events:
        event, amount, target = (ev + (None,))[:3] if len(ev) < 3 else ev
        completed_ids.extend(on_event(user_id, event, amount=amount, target=target))

    lines = []
    for qid in completed_ids:
        qdef = catalog.QUESTS[qid]
        lines.append(f"📜 Nhiệm vụ **{qdef['name']}** đã hoàn thành! Dùng `/nhiemvu` để nhận thưởng.")

    for aid, adef in check_achievements(user_id):
        lines.append(f"🏆 Đạt thành tựu: **{adef['name']}**!" + (f" (danh hiệu: {adef['title_reward']})" if adef.get("title_reward") else ""))

    return ("\n\n" + "\n".join(lines)) if lines else ""


# --------------------------------------------------------------- Achievements --
def _achievement_condition_met(user_id: int, cond: dict) -> bool:
    ctype, value = cond["type"], cond["value"]
    if ctype == "capture_ghost_total_ge":
        return data.get_counter(user_id, "capture_ghost_total") >= value
    if ctype == "kill_ghost_total_ge":
        return data.get_counter(user_id, "kill_ghost_total") >= value
    if ctype == "ghosts_owned_ge":
        return len(data.get_owned_ghosts(user_id)) >= value
    if ctype == "boss_defeated_total_ge":
        return data.get_boss_defeated_total(user_id) >= value
    if ctype == "locations_visited_ge":
        return data.get_locations_visited_count(user_id) >= value
    if ctype == "level_ge":
        player = data.get_player(user_id)
        return player and player["level"] >= value
    if ctype == "bachkhoa_discovered_all":
        return len(data.get_catalog_progress(user_id)) >= len(catalog.GHOSTS)
    return False


def check_achievements(user_id: int) -> list[tuple[str, dict]]:
    """Kiểm tra toàn bộ thành tựu chưa đạt, cấp phát cái nào đủ điều kiện. Trả về danh sách vừa đạt."""
    newly_earned = []
    for aid, adef in catalog.ACHIEVEMENTS.items():
        if data.has_achievement(user_id, aid):
            continue
        if _achievement_condition_met(user_id, adef["condition"]):
            if data.grant_achievement(user_id, aid):
                if adef.get("title_reward"):
                    data.update_player(user_id, title=adef["title_reward"])
                newly_earned.append((aid, adef))
                logger.info(f"[ACHIEVEMENT] user={user_id} đạt '{aid}'")
    return newly_earned
