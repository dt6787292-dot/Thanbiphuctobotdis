"""
Lớp dữ liệu — một Database SQLite duy nhất dùng chung cho toàn bộ hệ thống.

Điểm mấu chốt để tuân thủ Rule 9/11/40 (Quỷ độc quyền toàn thế giới):
  claim_wild_ghost() dùng một UPDATE có điều kiện "WHERE state='wild'"
  bên trong transaction — nếu hai người chơi bấm nút khống chế cùng lúc,
  chỉ một UPDATE khớp điều kiện và thành công (rowcount=1), người còn lại
  nhận rowcount=0 => bị từ chối. Không có cửa sổ race-condition tạo bản sao.
"""
import sqlite3
import time
import contextlib
from config import DB_PATH, logger

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    user_id         INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    char_type       TEXT NOT NULL DEFAULT 'nguoi_thuong',  -- nguoi_thuong / ngu_quy_gia / di_loai / chetmay
    level           INTEGER NOT NULL DEFAULT 1,
    exp             INTEGER NOT NULL DEFAULT 0,
    hp              INTEGER NOT NULL DEFAULT 100,
    hp_max          INTEGER NOT NULL DEFAULT 100,
    money           INTEGER NOT NULL DEFAULT 100,
    linh_di         INTEGER NOT NULL DEFAULT 0,     -- % linh dị 0-100
    location_id     TEXT NOT NULL DEFAULT 'khoi_dau',
    title           TEXT NOT NULL DEFAULT '',
    ghost_slots     INTEGER NOT NULL DEFAULT 1,      -- giới hạn số Quỷ khống chế cùng lúc
    active_ghost_id TEXT,                            -- Quỷ chính hiện dùng để chiến đấu (đổi qua /thay_quy)
    created_at      INTEGER NOT NULL
);

-- Một hàng cho MỖI trong 120 Quỷ tĩnh -> đảm bảo tồn tại đúng 1 thực thể/Quỷ (Rule 9/43-1/43-2)
CREATE TABLE IF NOT EXISTS world_ghosts (
    ghost_id        TEXT PRIMARY KEY,
    state           TEXT NOT NULL DEFAULT 'wild',   -- wild / controlled / battling / sealed / destroyed
    owner_id        INTEGER,                        -- NULL nếu không ai khống chế
    location_id     TEXT,
    hp_current      INTEGER,
    power_current   INTEGER,
    tier_index       INTEGER NOT NULL DEFAULT 0,      -- mốc phá cấp hiện tại trong bậc gốc
    awakened        INTEGER NOT NULL DEFAULT 0,      -- 0/1 đã thức tỉnh
    sealed_until    INTEGER,                         -- epoch time hết phong ấn (NULL = không/ vĩnh viễn)
    last_event_at   INTEGER
);

CREATE TABLE IF NOT EXISTS catalog_discovered (
    user_id     INTEGER NOT NULL,
    ghost_id    TEXT NOT NULL,
    discovered_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, ghost_id)
);

CREATE TABLE IF NOT EXISTS location_progress (
    user_id                 INTEGER NOT NULL,
    location_id             TEXT NOT NULL,
    unlocked                INTEGER NOT NULL DEFAULT 0,
    visits                  INTEGER NOT NULL DEFAULT 0,
    successful_explorations INTEGER NOT NULL DEFAULT 0,
    boss_defeated           INTEGER NOT NULL DEFAULT 0,
    clues_found              INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, location_id)
);

CREATE TABLE IF NOT EXISTS inventory (
    user_id     INTEGER NOT NULL,
    item_id     TEXT NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, item_id)
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    initiator_id    INTEGER NOT NULL,
    target_id       INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending/confirmed_a/confirmed_b/done/cancelled
    initiator_offer TEXT NOT NULL DEFAULT '{}',        -- JSON {money, items:{item_id:qty}}
    target_offer    TEXT NOT NULL DEFAULT '{}',
    created_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS achievements (
    user_id         INTEGER NOT NULL,
    achievement_id  TEXT NOT NULL,
    earned_at       INTEGER NOT NULL,
    PRIMARY KEY (user_id, achievement_id)
);

CREATE TABLE IF NOT EXISTS player_quests (
    user_id     INTEGER NOT NULL,
    quest_id    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',  -- active / completed / claimed
    progress    INTEGER NOT NULL DEFAULT 0,
    started_at  INTEGER NOT NULL,
    completed_at INTEGER,
    PRIMARY KEY (user_id, quest_id)
);

-- Bộ đếm sự kiện lũy kế dùng để chấm điều kiện thành tựu/nhiệm vụ theo dạng "đủ N lần"
CREATE TABLE IF NOT EXISTS player_counters (
    user_id     INTEGER NOT NULL,
    counter_key TEXT NOT NULL,   -- vd: 'kill_ghost_total', 'kill_quy_binh', 'capture_ghost_total'
    value       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, counter_key)
);
"""


@contextlib.contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    logger.info("Database khởi tạo/xác nhận schema xong.")


def seed_world_ghosts(ghost_defs: dict):
    """Đảm bảo mỗi ghost_id trong data tĩnh có đúng 1 hàng world_ghosts (idempotent)."""
    now = int(time.time())
    with get_conn() as conn:
        for gid, gdef in ghost_defs.items():
            row = conn.execute("SELECT ghost_id FROM world_ghosts WHERE ghost_id=?", (gid,)).fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO world_ghosts
                       (ghost_id, state, owner_id, location_id, hp_current, power_current,
                        tier_index, awakened, sealed_until, last_event_at)
                       VALUES (?, 'wild', NULL, ?, ?, ?, 0, 0, NULL, ?)""",
                    (gid, gdef.get("spawn_location"), gdef["hp_max"], gdef["power_base"], now),
                )
    logger.info(f"Đã seed/xác nhận {len(ghost_defs)} Quỷ trong world_ghosts.")


# ---------------------------------------------------------------- players --
def get_player(user_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM players WHERE user_id=?", (user_id,)).fetchone()


def create_player(user_id: int, name: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO players (user_id, name, created_at) VALUES (?, ?, ?)",
            (user_id, name, int(time.time())),
        )
        conn.execute(
            "INSERT OR IGNORE INTO location_progress (user_id, location_id, unlocked, visits) "
            "VALUES (?, 'khoi_dau', 1, 0)",
            (user_id,),
        )


def update_player(user_id: int, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE players SET {cols} WHERE user_id=?", (*fields.values(), user_id))


# ------------------------------------------------------------ world ghosts --
def get_world_ghost(ghost_id: str):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM world_ghosts WHERE ghost_id=?", (ghost_id,)).fetchone()


def get_wild_ghosts_at(location_id: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM world_ghosts WHERE location_id=? AND state='wild'", (location_id,)
        ).fetchall()


def claim_wild_ghost(ghost_id: str, user_id: int) -> bool:
    """
    Cố gắng khống chế một Quỷ đang hoang dã. Atomic: chỉ thành công nếu
    Quỷ vẫn còn state='wild' tại thời điểm UPDATE (Rule 9/11 — độc quyền).
    Trả về True nếu khống chế thành công, False nếu Quỷ đã bị người khác lấy trước.
    """
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE world_ghosts SET state='controlled', owner_id=? "
            "WHERE ghost_id=? AND state='wild'",
            (user_id, ghost_id),
        )
        success = cur.rowcount == 1
        if success:
            conn.execute(
                "INSERT OR IGNORE INTO catalog_discovered (user_id, ghost_id, discovered_at) "
                "VALUES (?, ?, ?)",
                (user_id, ghost_id, int(time.time())),
            )
        return success


def release_ghost(ghost_id: str, owner_id: int) -> bool:
    """Thả Quỷ — chỉ chủ sở hữu hiện tại mới thả được. Quỷ về trạng thái hoang dã."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE world_ghosts SET state='wild', owner_id=NULL "
            "WHERE ghost_id=? AND owner_id=?",
            (ghost_id, owner_id),
        )
        return cur.rowcount == 1


def seize_ghost(ghost_id: str, new_owner_id: int, old_owner_id: int, hp_current: int) -> bool:
    """
    Cướp quyền khống chế theo luật chiến đấu (Section 14) — atomic: chỉ thành công
    nếu Quỷ vẫn thuộc đúng old_owner_id tại thời điểm UPDATE (không tạo bản sao,
    không cho cướp nhầm nếu tình huống đã đổi giữa chừng).
    """
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE world_ghosts SET owner_id=?, state='controlled', hp_current=? "
            "WHERE ghost_id=? AND owner_id=?",
            (new_owner_id, hp_current, ghost_id, old_owner_id),
        )
        if cur.rowcount == 1:
            conn.execute(
                "INSERT OR IGNORE INTO catalog_discovered (user_id, ghost_id, discovered_at) VALUES (?, ?, ?)",
                (new_owner_id, ghost_id, int(time.time())),
            )
            # nếu Quỷ vừa mất là Quỷ chính của chủ cũ, gỡ nó ra
            conn.execute(
                "UPDATE players SET active_ghost_id=NULL WHERE user_id=? AND active_ghost_id=?",
                (old_owner_id, ghost_id),
            )
        return cur.rowcount == 1


def destroy_ghost(ghost_id: str):
    """Quỷ HP về 0 -> bị hủy, chờ tái xuất hiện (Rule 12/13)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE world_ghosts SET state='destroyed', owner_id=NULL, last_event_at=? WHERE ghost_id=?",
            (int(time.time()), ghost_id),
        )


def respawn_ghost(ghost_id: str, location_id: str, hp_max: int, power_base: int):
    """Tái xuất hiện — vẫn cùng một thực thể (ghost_id không đổi), không tạo bản sao (Rule 13)."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE world_ghosts
               SET state='wild', owner_id=NULL, location_id=?,
                   hp_current=?, power_current=?, sealed_until=NULL, last_event_at=?
               WHERE ghost_id=? AND state='destroyed'""",
            (location_id, hp_max, power_base, int(time.time()), ghost_id),
        )


def get_owned_ghosts(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM world_ghosts WHERE owner_id=? AND state IN ('controlled','battling','sealed')",
            (user_id,),
        ).fetchall()


def set_ghost_state(ghost_id: str, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE world_ghosts SET {cols} WHERE ghost_id=?", (*fields.values(), ghost_id))


# ------------------------------------------------------------------ catalog --
def get_catalog_progress(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ghost_id FROM catalog_discovered WHERE user_id=?", (user_id,)
        ).fetchall()
        return {r["ghost_id"] for r in rows}


# ------------------------------------------------------------- inventory --
def add_item(user_id: int, item_id: str, qty: int = 1):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO inventory (user_id, item_id, quantity) VALUES (?, ?, ?)
               ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity""",
            (user_id, item_id, qty),
        )


def remove_item(user_id: int, item_id: str, qty: int = 1) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id)
        ).fetchone()
        if not row or row["quantity"] < qty:
            return False
        conn.execute(
            "UPDATE inventory SET quantity = quantity - ? WHERE user_id=? AND item_id=?",
            (qty, user_id, item_id),
        )
        return True


def get_inventory(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM inventory WHERE user_id=? AND quantity > 0", (user_id,)
        ).fetchall()


# --------------------------------------------------------- location progress --
def get_location_progress(user_id: int, location_id: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM location_progress WHERE user_id=? AND location_id=?",
            (user_id, location_id),
        ).fetchone()


def unlock_location(user_id: int, location_id: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO location_progress (user_id, location_id, unlocked, visits)
               VALUES (?, ?, 1, 0)
               ON CONFLICT(user_id, location_id) DO UPDATE SET unlocked=1""",
            (user_id, location_id),
        )


def bump_location_stat(user_id: int, location_id: str, field: str, amount: int = 1):
    assert field in ("visits", "successful_explorations", "boss_defeated", "clues_found")
    with get_conn() as conn:
        conn.execute(
            f"""INSERT INTO location_progress (user_id, location_id, {field})
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, location_id) DO UPDATE SET {field} = {field} + ?""",
            (user_id, location_id, amount, amount),
        )


def get_boss_defeated_total(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(boss_defeated),0) AS total FROM location_progress WHERE user_id=?",
            (user_id,),
        ).fetchone()
        return row["total"]


def get_locations_visited_count(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM location_progress WHERE user_id=? AND visits > 0", (user_id,)
        ).fetchone()
        return row["cnt"]


# ------------------------------------------------------------------ counters --
def bump_counter(user_id: int, counter_key: str, amount: int = 1) -> int:
    """Tăng một bộ đếm lũy kế và trả về giá trị mới (dùng để chấm nhiệm vụ/thành tựu dạng 'đủ N lần')."""
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO player_counters (user_id, counter_key, value) VALUES (?, ?, ?)
               ON CONFLICT(user_id, counter_key) DO UPDATE SET value = value + excluded.value""",
            (user_id, counter_key, amount),
        )
        row = conn.execute(
            "SELECT value FROM player_counters WHERE user_id=? AND counter_key=?", (user_id, counter_key)
        ).fetchone()
        return row["value"]


def get_counter(user_id: int, counter_key: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM player_counters WHERE user_id=? AND counter_key=?", (user_id, counter_key)
        ).fetchone()
        return row["value"] if row else 0


# --------------------------------------------------------------------- quests --
def get_player_quest(user_id: int, quest_id: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM player_quests WHERE user_id=? AND quest_id=?", (user_id, quest_id)
        ).fetchone()


def get_active_quests(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM player_quests WHERE user_id=? AND status='active'", (user_id,)
        ).fetchall()


def get_all_player_quests(user_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM player_quests WHERE user_id=?", (user_id,)).fetchall()


def accept_quest(user_id: int, quest_id: str) -> bool:
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO player_quests (user_id, quest_id, status, progress, started_at) "
                "VALUES (?, ?, 'active', 0, ?)",
                (user_id, quest_id, int(time.time())),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def set_quest_progress(user_id: int, quest_id: str, progress: int, status: str = None):
    with get_conn() as conn:
        if status:
            conn.execute(
                "UPDATE player_quests SET progress=?, status=?, completed_at=? "
                "WHERE user_id=? AND quest_id=?",
                (progress, status, int(time.time()) if status == "completed" else None, user_id, quest_id),
            )
        else:
            conn.execute(
                "UPDATE player_quests SET progress=? WHERE user_id=? AND quest_id=?",
                (progress, user_id, quest_id),
            )


def claim_quest(user_id: int, quest_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE player_quests SET status='claimed' WHERE user_id=? AND quest_id=? AND status='completed'",
            (user_id, quest_id),
        )
        return cur.rowcount == 1


def reset_daily_quest(user_id: int, quest_id: str):
    """Cho phép nhận lại nhiệm vụ hằng ngày — xoá bản ghi cũ để accept_quest tạo lại."""
    with get_conn() as conn:
        conn.execute("DELETE FROM player_quests WHERE user_id=? AND quest_id=?", (user_id, quest_id))


# ---------------------------------------------------------------- achievements --
def has_achievement(user_id: int, achievement_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM achievements WHERE user_id=? AND achievement_id=?", (user_id, achievement_id)
        ).fetchone()
        return row is not None


def grant_achievement(user_id: int, achievement_id: str) -> bool:
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO achievements (user_id, achievement_id, earned_at) VALUES (?, ?, ?)",
                (user_id, achievement_id, int(time.time())),
            )
            return True
        except sqlite3.IntegrityError:
            return False
