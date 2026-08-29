"""
Mất kiểm soát (Section 29) — được roll tại 2 điểm gameplay thật:
  1. Ngay sau khi khống chế thêm một Quỷ (nguyên nhân "khống chế quá nhiều Quỷ").
  2. Ngay sau khi dùng Kỹ năng/Quỷ vực trong chiến đấu (nguyên nhân "sử dụng năng lực quá mức").
Chetmay miễn nhiễm hoàn toàn (game.control_loss_risk trả về 0 cho char_type='chetmay').
"""
import random

from utils import data, game
from config import logger


def check_and_maybe_trigger(user_id: int) -> str | None:
    """Roll rủi ro mất kiểm soát; nếu trúng, áp dụng hậu quả và trả về text mô tả. None nếu không có gì xảy ra."""
    player = data.get_player(user_id)
    if not player:
        return None

    owned = data.get_owned_ghosts(user_id)
    if not game.roll_control_loss(player["char_type"], len(owned), player["ghost_slots"], player["linh_di"]):
        return None

    hp_loss_pct = random.uniform(0.10, 0.25)
    hp_loss = max(1, int(player["hp_max"] * hp_loss_pct))
    new_hp = max(1, player["hp"] - hp_loss)
    data.update_player(user_id, hp=new_hp)
    lines = [f"⚠️ **MẤT KIỂM SOÁT!** Linh dị phản phệ, bạn mất {hp_loss:,} HP ({new_hp:,}/{player['hp_max']:,})."]

    if owned and random.random() < 0.30:
        victim = random.choice(owned)
        if data.release_ghost(victim["ghost_id"], user_id):
            lines.append(f"👻 Một Quỷ đã thoát khỏi quyền khống chế của bạn và trở về hoang dã trong lúc hỗn loạn.")

    logger.info(f"[CONTROL_LOSS] user={user_id} char_type={player['char_type']} owned={len(owned)}")
    return "\n".join(lines)
