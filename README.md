# 👻 LINH DỊ — THẦN BÍ PHỤC TÔ (bot Discord)

Bot Discord MMORPG linh dị viết bằng `discord.py` (slash commands), theo Master
Specification V1.0. Dùng SQLite làm database duy nhất cho toàn bộ hệ thống.

## 1. Cài đặt

```bash
cd linh-di-bot
python3 -m venv venv && source venv/bin/activate      # khuyến khích
pip install -r requirements.txt
cp .env.example .env
```

Mở `.env` và điền:
```
DISCORD_TOKEN=token_bot_discord_cua_ban
GEMINI_API_KEY=api_key_gemini_cua_ban
GEMINI_MODEL=gemini-1.5-flash
```

Nếu để trống `GEMINI_API_KEY`, bot vẫn chạy bình thường — mọi mô tả tường thuật
sẽ dùng văn bản fallback tĩnh thay vì gọi Gemini.

## 2. Chạy bot

```bash
python3 main.py
```

Log khởi động sẽ hiển thị số Quỷ/địa điểm/vật phẩm đã nạp, và **mỗi lần gọi
Gemini API thành công sẽ được ghi log** dạng:
```
[INFO] linh_di: ✅ Gemini API call thành công [context=khampha_ghost] (134 ký tự).
```
(chỉ hiện trong log server, không hiển thị cho người chơi — đúng Rule 2 của spec.)

## 3. Cấu trúc thư mục

```
linh-di-bot/
├── main.py                 # entrypoint, nạp cogs + đồng bộ slash command
├── config.py                # cấu hình + logger (không expose ra người chơi)
├── data/
│   ├── ghosts.json          # 20 Quỷ mẫu / 120, đủ cả 6 bậc & 6 độ hiếm
│   ├── locations.json       # 17 địa điểm mẫu / 38, chuỗi mở khóa tuyến tính
│   ├── items.json           # vật phẩm
│   └── world.db              # SQLite, tự tạo khi chạy lần đầu
├── utils/
│   ├── data.py               # lớp DB — đảm bảo 1 Quỷ = 1 chủ sở hữu (atomic claim)
│   ├── catalog.py            # nạp + validate chéo dữ liệu tĩnh lúc khởi động
│   ├── game.py                # EXP/level, HP bar, công thức chiến đấu theo bậc
│   └── ai.py                  # gọi Gemini (chỉ sinh văn bản tường thuật) + log
└── commands/                 # mỗi file = 1 cog slash command nhóm theo spec
```

## 4. Mở rộng lên đủ 120 Quỷ / 38 địa điểm

`data/ghosts.json` và `data/locations.json` đã đúng schema mà
`utils/catalog.py` validate (spawn_location phải tồn tại, boss phải trỏ tới
ghost hợp lệ, requires_location tạo thành chuỗi tuyến tính...). Chỉ cần thêm
đối tượng mới theo đúng khuôn hiện có — bot sẽ tự seed vào `world_ghosts` khi
khởi động lại (idempotent, không tạo bản sao Quỷ đã tồn tại).

## 5. Cập nhật mới: Nhiệm vụ / Thành tựu / Mất kiểm soát

- `data/quests.json` — 10 nhiệm vụ mẫu (chính có chuỗi mở khoá tuần tự,
  phụ, quỷ, boss, hằng ngày). `utils/quests.py` là engine chấm điểm theo
  sự kiện gameplay thật (capture_ghost, kill_ghost, kill_boss,
  explore_success, loot_item, visit_location_distinct...), đã gắn vào
  `commands/explore.py` và `commands/battle.py`. Lệnh `/nhiemvu` xem +
  nhận nhiệm vụ + nhận thưởng qua nút bấm.
- `data/achievements.json` — 7 thành tựu mẫu, tự động chấm sau mỗi sự
  kiện liên quan (không cần lệnh riêng), có thể tặng danh hiệu.
  `/thanhtich` hiển thị đẹp có icon/mô tả.
- `utils/control.py` — Mất kiểm soát (Section 29) giờ thực sự roll và
  áp dụng hậu quả (mất % HP, có thể mất quyền khống chế 1 Quỷ ngẫu
  nhiên) tại 2 điểm: ngay sau khi khống chế Quỷ mới, và sau khi dùng
  Kỹ năng/Quỷ vực trong chiến đấu. Chetmay miễn nhiễm hoàn toàn (đã
  test).

## 8. Cập nhật mới nhất: PvP tranh giành Quỷ + fix daily quest

- **PvP tranh giành Quỷ (Section 14):** `/chien_dau doi_thu:@ai_do` giờ cho
  phép thách đấu Quỷ chính của người chơi khác. Thắng (đưa HP đối thủ về 0)
  → cướp quyền khống chế thật sự qua `data.seize_ghost()` (atomic, tự gỡ
  `active_ghost_id` của người bị cướp, tự thêm vào Bách Khoa của người
  thắng). Thua → Quỷ bạn lui về hồi phục, Quỷ đối thủ trở lại trạng thái
  `controlled` bình thường (không bị kẹt "đang chiến đấu" mãi — đây cũng là
  một lỗi đã sửa ở nhánh PvE cũ). Đã test atomic (không cho cướp 2 lần từ
  tình huống đã đổi).
- **Fix nhiệm vụ hằng ngày:** trước đây có thể nhận lại ngay sau khi claim;
  giờ khoá đúng theo ngày UTC (`utils/quests.py::_quest_available`), đã test
  claim → không nhận lại được cùng ngày → nhận lại được khi sang ngày mới.
- HP của Quỷ đối thủ (cả hoang dã lẫn PvP) giờ được ghi lại vào DB sau mỗi
  lượt thay vì chỉ tính trong bộ nhớ tạm.

## 11. Cập nhật mới nhất: mở rộng dữ liệu + PvP chuyển hẳn sang kiểu Nhật Ký

- **Dữ liệu:** 20 → **36 Quỷ** (đủ 6 bậc, có thêm nhánh bản đồ mới), 17 → **25
  địa điểm** (thêm 8 địa điểm rẽ nhánh từ các khu đã có — Chợ Đêm, Cầu Sông
  Cũ, Hầm Metro, Tòa Nhà Văn Phòng, Đảo Hoang, Mỏ Than, Thành Cổ Đổ Nát, Vực
  Sâu Không Đáy — giống ví dụ "nhiều lối đi từ 1 khu vực" ở Section 7). Đã
  validate chéo lại toàn bộ, không lỗi tham chiếu.
- **PvP giờ là "nhật ký" (log) thay vì tương tác trực tiếp:** `/chien_dau
  doi_thu:@ai_đó` không còn dùng nút bấm theo lượt — toàn bộ trận được
  `utils/game.py::simulate_full_battle()` mô phỏng NGAY LẬP TỨC (tối đa 12
  lượt tự động, mỗi bên tự đánh Kỹ năng + tự kích hoạt Quỷ vực khi hết hồi
  chiêu), rồi trả về **một embed "Nhật Ký Trận Chiến"** liệt kê từng lượt +
  kết quả cuối. Không cần người bị thách phải online. Thắng → cướp quyền
  khống chế atomic qua `seize_ghost()`; thua → Quỷ tấn công rút lui, HP cả
  2 bên được lưu lại thật vào DB. Đã test cả 2 chiều (mạnh thắng yếu, yếu
  thua mạnh) + cướp quyền thành công.
- PvE (`/chien_dau` không kèm đối thủ) **không đổi** — vẫn tương tác theo
  lượt với nút Kỹ năng/Quỷ vực/Phong ấn như cũ.

## 12. Những gì đã implement đầy đủ so với spec

- Nhân vật, loại nhân vật (Người thường/Ngự Quỷ Giả/Dị Loại/Chetmay)
- Khám phá theo tỉ lệ sự kiện riêng từng địa điểm + AI tường thuật
- Di chuyển với chuỗi mở khóa tuyến tính (đánh bại boss trước mới mở khu tiếp theo)
- **Quỷ độc quyền toàn thế giới** — khống chế bằng UPDATE có điều kiện atomic,
  chống race-condition khi 2 người bấm nút cùng lúc
- Bách khoa toàn thư (ẩn thông tin Quỷ chưa khám phá)
- Quỷ vs Quỷ theo lượt: Kỹ năng / Quỷ vực / Phong ấn, HP hiển thị trực quan
- Công thức chiến đấu ưu tiên **Bậc > Linh Dị > Năng lực > Quỷ vực > Lực chiến > HP**
  (Quỷ Binh lực chiến cao vẫn thua Quỷ Vương lực chiến thấp hơn — đã kiểm chứng)
- Giới hạn nâng cấp theo bậc + điều kiện thức tỉnh (không spam nâng cấp vượt cấp)
- Kho đồ, sử dụng vật phẩm, shop mua/bán
- Giao dịch vật phẩm 2 lần xác nhận, **không cho phép trade Quỷ** (Rule 32)
- Bảng xếp hạng, admin tools (gated theo quyền Administrator của Discord)
- Toàn bộ lỗi kỹ thuật được che bằng thông báo chung, không lộ traceback/debug

## 13. Những phần vẫn còn thiếu / đơn giản hoá

- Còn 84/120 Quỷ và 13/38 địa điểm chưa soạn — theo đúng schema hiện có,
  chỉ cần thêm object mới vào `data/ghosts.json` / `data/locations.json`.
- PvP nhật ký mô phỏng cả trận bằng công thức có sẵn (không cho phép người
  bị thách can thiệp/phản ứng theo thời gian thực) — đây là lựa chọn thiết
  kế bạn yêu cầu, không phải hạn chế kỹ thuật.
- Chưa test thật với Discord token/Gemini key thật (không có mạng trong môi
  trường build này để chạy bot live) — cần bạn tự chạy `python3 main.py`
  với `.env` thật để xác nhận lần cuối.
