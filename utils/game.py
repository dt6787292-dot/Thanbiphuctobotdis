"""
Logic gameplay cốt lõi — mọi con số (HP, damage, EXP, kết quả chiến đấu, phong ấn,
áp chế, chủ sở hữu, bậc, lực chiến) đều được CHỐT Ở ĐÂY, không phải do AI quyết định
(Rule 36/43-13).
"""
import random
import time
from utils import catalog

# --- Loại nhân vật (Section 4) ---
CHAR_TYPES = {
    "nguoi_thuong": {"label": "👤 Người thường", "base_ghost_slots": 0, "control_loss_immune": False},
    "ngu_quy_gia":  {"label": "👻 Ngự Quỷ Giả",   "base_ghost_slots": 3, "control_loss_immune": False},
    "di_loai":      {"label": "🧬 Dị Loại",       "base_ghost_slots": 5, "control_loss_immune": False},
    "chetmay":      {"label": "🛡️ Chetmay",       "base_ghost_slots": 10, "control_loss_immune": True},
}

# --- Nhân hệ số bậc — bậc quyết định phần lớn kết quả, không chỉ lực chiến thô (Rule 19/41) ---
TIER_MULTIPLIER = {
    "quy_binh": 1.0, "quy_tuong": 1.8, "quy_soai": 3.2,
    "quy_vuong": 5.5, "quy_hoang": 9.0, "cam_ky": 15.0,
}
TIER_STEP = ["quy_binh", "quy_tuong", "quy_soai", "quy_vuong", "quy_hoang", "cam_ky"]


def render_bar(current: int, maximum: int, length: int = 10) -> str:
    current = max(0, min(current, maximum))
    filled = int(round((current / maximum) * length)) if maximum > 0 else 0
    return "█" * filled + "░" * (length - filled)


# ------------------------------------------------------------------ EXP/level --
def exp_to_next_level(level: int) -> int:
    return int(100 * (level ** 1.4)) + 50


def apply_exp(player_row, exp_gain: int):
    """Trả về (new_level, new_exp, new_hp_max, leveled_up: bool)."""
    level = player_row["level"]
    exp = player_row["exp"] + exp_gain
    hp_max = player_row["hp_max"]
    leveled = False
    while exp >= exp_to_next_level(level):
        exp -= exp_to_next_level(level)
        level += 1
        hp_max += 250
        leveled = True
    return level, exp, hp_max, leveled


# ------------------------------------------------------------- Quỷ growth --
def ghost_effective_power(world_ghost_row, ghost_def) -> int:
    """Lực chiến hiện tại, đã cộng dồn theo tier_index nhưng KHÔNG vượt power_cap (Rule 20)."""
    base = ghost_def["power_base"]
    cap = ghost_def["power_cap"]
    step_gain = (cap - base) / 4  # 4 mốc nâng cấp trong 1 bậc, giống ví dụ Section 20
    power = base + step_gain * world_ghost_row["tier_index"]
    return int(min(power, cap))


def is_at_power_cap(world_ghost_row, ghost_def) -> bool:
    return ghost_effective_power(world_ghost_row, ghost_def) >= ghost_def["power_cap"]


def can_upgrade(world_ghost_row) -> bool:
    return world_ghost_row["tier_index"] < 4


def next_tier(ghost_def) -> str | None:
    idx = TIER_STEP.index(ghost_def["tier"])
    if idx + 1 < len(TIER_STEP):
        return TIER_STEP[idx + 1]
    return None  # đã ở Cấm Kỵ, không còn bậc cao hơn (Rule cam_ky breakthrough_condition)


# ------------------------------------------------------------------- Battle --
def _effective_strength(hp, hp_max, power, tier, linh_di, num_abilities, domain_active, seed_jitter=True):
    """
    Tổng hợp theo đúng thứ tự ưu tiên Section 41:
    Bậc Quỷ > Linh Dị > Quy Luật > Năng Lực > Quỷ Vực > Kỹ Năng > Lực Chiến > HP > Trạng thái.
    Bậc (tier multiplier) là hệ số NHÂN áp đảo; các yếu tố sau là cộng thêm % nhỏ hơn dần,
    để tier thấp KHÔNG mặc định thua nếu chênh lệch các yếu tố sau đủ lớn, nhưng KHÔNG thể
    spam lực chiến để vượt cấp một cách vô lý (Rule 20/41).
    """
    tier_mult = TIER_MULTIPLIER.get(tier, 1.0)
    strength = power * tier_mult

    strength *= (1 + linh_di / 200)               # Linh Dị: tối đa +50% ở linh_di=100
    strength *= (1 + min(num_abilities, 4) * 0.03)  # Năng lực: mỗi ability +3%, tối đa +12%
    if domain_active:
        strength *= 1.12                            # Quỷ vực đang kích hoạt: +12%
    strength *= (0.7 + 0.3 * (hp / hp_max if hp_max else 1))  # HP còn lại ảnh hưởng nhẹ (tối đa -30%)

    if seed_jitter:
        strength *= random.uniform(0.92, 1.08)      # biến thiên kỹ năng/quy luật/trạng thái ngẫu nhiên nhỏ
    return strength


def resolve_battle_round(a_state: dict, b_state: dict) -> dict:
    """
    a_state/b_state: {hp, hp_max, power, tier, linh_di, num_abilities, domain_active}
    Trả về dict {damage_to_a, damage_to_b, a_strength, b_strength}.
    Bên có effective_strength cao hơn gây damage lớn hơn cho bên kia, tỉ lệ theo chênh lệch,
    nhưng cả hai vẫn luôn chịu sát thương qua lại mỗi lượt (không one-shot tuyệt đối trừ chênh lệch cực lớn).
    """
    a_str = _effective_strength(**a_state)
    b_str = _effective_strength(**b_state)

    total = a_str + b_str
    a_share = a_str / total
    b_share = b_str / total

    base_dmg_pool = 0.09  # % HP tối đa đối thủ mất mỗi lượt ở mức cân bằng
    dmg_to_b = int(a_state["hp_max"] * base_dmg_pool * (0.4 + 1.2 * a_share) * random.uniform(0.9, 1.1))
    dmg_to_a = int(b_state["hp_max"] * base_dmg_pool * (0.4 + 1.2 * b_share) * random.uniform(0.9, 1.1))

    return {
        "damage_to_a": max(1, dmg_to_a),
        "damage_to_b": max(1, dmg_to_b),
        "a_strength": round(a_str),
        "b_strength": round(b_str),
    }


def simulate_full_battle(a0: dict, b0: dict, a_domain_cd: int, b_domain_cd: int, max_rounds: int = 12) -> dict:
    """
    Mô phỏng TOÀN BỘ trận đấu ngay lập tức (dùng cho PvP kiểu 'nhật ký' — Section 14),
    không cần cả hai người chơi cùng online. Mỗi bên tự dùng Kỹ năng mỗi lượt, tự kích
    hoạt Quỷ vực khi hết hồi chiêu. Trả về nhật ký từng lượt + kết quả cuối cùng.

    a0/b0: {hp, hp_max, power, tier, linh_di, num_abilities} (không cần domain_active, tự quản lý).
    Trả về: {"rounds": [...], "a_hp": int, "b_hp": int, "winner": "a"|"b"|"draw"}
    """
    a_hp, b_hp = a0["hp"], b0["hp"]
    rounds = []
    winner = "draw"

    for turn in range(1, max_rounds + 1):
        a_domain_active = a_domain_cd <= 0
        a_domain_cd = a0.get("domain_cooldown", 4) if a_domain_active else a_domain_cd - 1
        b_domain_active = b_domain_cd <= 0
        b_domain_cd = b0.get("domain_cooldown", 4) if b_domain_active else b_domain_cd - 1

        a_state = {k: v for k, v in a0.items() if k != "domain_cooldown"} | {"hp": a_hp, "domain_active": a_domain_active}
        b_state = {k: v for k, v in b0.items() if k != "domain_cooldown"} | {"hp": b_hp, "domain_active": b_domain_active}
        result = resolve_battle_round(a_state, b_state)

        b_hp = max(0, b_hp - result["damage_to_b"])
        a_hp = max(0, a_hp - result["damage_to_a"])

        rounds.append({
            "turn": turn, "dmg_to_a": result["damage_to_a"], "dmg_to_b": result["damage_to_b"],
            "a_hp": a_hp, "b_hp": b_hp, "a_domain": a_domain_active, "b_domain": b_domain_active,
        })

        if a_hp <= 0 or b_hp <= 0:
            break

    if a_hp <= 0 and b_hp <= 0:
        winner = "a" if a0["hp_max"] and (a_hp / a0["hp_max"]) >= (b_hp / b0["hp_max"]) else "b"
    elif b_hp <= 0:
        winner = "a"
    elif a_hp <= 0:
        winner = "b"
    else:
        # Hết số lượt tối đa mà chưa ai gục -> so % HP còn lại (Section 41: HP là yếu tố cuối cùng)
        winner = "a" if (a_hp / a0["hp_max"]) >= (b_hp / b0["hp_max"]) else "b"

    return {"rounds": rounds, "a_hp": a_hp, "b_hp": b_hp, "winner": winner}


def suppression_result(attacker_state: dict, defender_state: dict) -> str:
    """
    Trả về một trong: 'khong_ap_che' / 'ap_che_nhe' / 'ap_che_manh' / 'ap_che_hoan_toan' / 'phong_an'
    dựa trên chênh lệch effective strength (Section 25).
    """
    a_str = _effective_strength(**attacker_state, seed_jitter=False)
    d_str = _effective_strength(**defender_state, seed_jitter=False)
    if d_str == 0:
        ratio = 999
    else:
        ratio = a_str / d_str

    if ratio < 1.15:
        return "khong_ap_che"
    elif ratio < 1.6:
        return "ap_che_nhe"
    elif ratio < 2.5:
        return "ap_che_manh"
    elif ratio < 4.0:
        return "ap_che_hoan_toan"
    else:
        return "phong_an"


def seal_chance(sealer_state: dict, target_state: dict, seal_power: int, item_bonus: float = 0.0) -> float:
    """Tỉ lệ phong ấn thành công (Section 26), 0.0–0.95, chưa tính random roll."""
    a_str = _effective_strength(**sealer_state, seed_jitter=False)
    d_str = _effective_strength(**target_state, seed_jitter=False)
    base = 0.15 + (seal_power * 0.05)
    ratio_bonus = min(0.4, max(-0.3, (a_str - d_str) / max(d_str, 1) * 0.2))
    chance = base + ratio_bonus + item_bonus
    return max(0.03, min(0.95, chance))


# --------------------------------------------------------- Mất kiểm soát --
def control_loss_risk(char_type: str, num_ghosts: int, ghost_slots: int, linh_di: int) -> float:
    """
    Rủi ro mất kiểm soát (0.0–1.0) mỗi khi khống chế/dùng năng lực Quỷ (Section 29).
    Chetmay miễn nhiễm (Rule 12/29 — nhưng KHÔNG miễn luật độc quyền Quỷ, xử lý riêng ở data.py).
    """
    if CHAR_TYPES.get(char_type, {}).get("control_loss_immune"):
        return 0.0
    overload = max(0, num_ghosts - ghost_slots)
    risk = 0.02 + overload * 0.08 + (linh_di / 100) * 0.15
    return max(0.0, min(0.9, risk))


def roll_control_loss(char_type: str, num_ghosts: int, ghost_slots: int, linh_di: int) -> bool:
    return random.random() < control_loss_risk(char_type, num_ghosts, ghost_slots, linh_di)
