import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import data, game, catalog, quests, control
from utils.ai import generate_narrative
from config import GENERIC_ERROR_MSG, logger

ENCOUNTER_ICONS = {
    "ghost": "👻 Gặp Quỷ", "npc": "👤 Gặp NPC", "item": "🎒 Nhặt vật phẩm",
    "event": "🌑 Sự kiện linh dị", "secret": "🏚️ Địa điểm bí mật",
}


def player_can_access(user_id: int, location_id: str) -> tuple[bool, str]:
    """Rule bổ sung: người chưa từng khống chế Quỷ nào chỉ được khám phá tại khoi_dau."""
    loc = catalog.get_location(location_id)
    if not loc:
        return False, "Địa điểm không tồn tại."

    if location_id != "khoi_dau":
        discovered = data.get_catalog_progress(user_id)
        owned = data.get_owned_ghosts(user_id)
        if not discovered and not owned:
            return False, "Bạn cần khống chế được một Quỷ tại **Con Hẻm Khởi Đầu** trước đã."

    if loc["requires_location"]:
        prog = data.get_location_progress(user_id, location_id)
        if not prog or not prog["unlocked"]:
            prereq_prog = data.get_location_progress(user_id, loc["requires_location"])
            if loc["requires_boss"] and (not prereq_prog or not prereq_prog["boss_defeated"]):
                prereq_name = catalog.get_location(loc["requires_location"])["name"]
                return False, f"Bạn cần hạ Boss tại **{prereq_name}** trước khi vào đây."
            if not prereq_prog or not prereq_prog["unlocked"]:
                return False, "Khu vực này chưa được mở khóa."
    return True, ""


async def _resolve_capture(interaction: discord.Interaction, user_id: int, ghost_id: str, view: discord.ui.View):
    """Logic khống chế dùng chung cho mọi giao diện (nút đơn lẻ hoặc StringSelectMenu)."""
    gdef = catalog.get_ghost(ghost_id)
    success = data.claim_wild_ghost(ghost_id, user_id)
    if not success:
        await interaction.response.edit_message(
            content=f"❌ Quá chậm! **{gdef['name']}** đã bị người chơi khác khống chế mất rồi.",
            embed=None, view=None,
        )
        return

    player = data.get_player(user_id)
    if player["char_type"] == "nguoi_thuong":
        data.update_player(
            user_id, char_type="ngu_quy_gia",
            ghost_slots=game.CHAR_TYPES["ngu_quy_gia"]["base_ghost_slots"],
        )

    data.bump_counter(user_id, "capture_ghost_total", 1)
    notify = quests.process_and_notify(user_id, [
        ("capture_ghost", 1, None),
        ("capture_ghost_tier_at_least", 1, gdef["tier"]),
    ])
    control_msg = control.check_and_maybe_trigger(user_id)

    embed = discord.Embed(
        title=f"🔒 Đã khống chế {gdef['icon']} {gdef['name']}!",
        description=(
            f"{gdef['name']} giờ đã thuộc quyền khống chế của bạn.\n"
            f"Bậc: {catalog.TIER_LABELS.get(gdef['tier'])}  |  "
            f"Độ hiếm: {catalog.RARITY_LABELS.get(gdef['rarity'])}"
            f"{notify}"
            + (f"\n\n{control_msg}" if control_msg else "")
        ),
        color=0x8a2be2,
    )
    for item in view.children:
        item.disabled = True
    await interaction.response.edit_message(embed=embed, view=view)


class KhongCheView(discord.ui.View):
    """Dùng khi chỉ có đúng một Quỷ hoang dã cụ thể (vd. chạm trán ngẫu nhiên lúc /khampha)."""
    def __init__(self, user_id: int, ghost_id: str):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.ghost_id = ghost_id

    @discord.ui.button(label="Khống chế Quỷ", style=discord.ButtonStyle.danger, emoji="🔒")
    async def khong_che(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Đây không phải cuộc khám phá của bạn.", ephemeral=True)
            return
        try:
            await _resolve_capture(interaction, self.user_id, self.ghost_id, self)
        except Exception as e:
            logger.error(f"khong_che button lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)


class KhongCheSelectView(discord.ui.View):
    """Khi có từ 2 Quỷ hoang dã trở lên tại cùng khu vực: người chơi chọn bằng
    TÊN Quỷ qua StringSelectMenu (label = value = tên hiển thị). Khóa nội bộ
    (ghost_id) chỉ dùng bên trong để tra dữ liệu, không lộ ra Discord."""
    def __init__(self, user_id: int, wild_ghosts: list):
        super().__init__(timeout=60)
        self.user_id = user_id
        self._ghost_id_by_name = {}
        options = []
        for wg in wild_ghosts[:25]:
            gdef = catalog.get_ghost(wg["ghost_id"])
            if not gdef:
                continue
            self._ghost_id_by_name[gdef["name"]] = wg["ghost_id"]
            options.append(discord.SelectOption(label=gdef["name"], value=gdef["name"], emoji=gdef["icon"]))
        self.select_ghost.options = options
        self.selected_ghost_id = wild_ghosts[0]["ghost_id"] if wild_ghosts else None

    @discord.ui.select(placeholder="Chọn Quỷ để khống chế...", min_values=1, max_values=1)
    async def select_ghost(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Đây không phải cuộc khám phá của bạn.", ephemeral=True)
            return
        chosen_name = select.values[0]
        self.selected_ghost_id = self._ghost_id_by_name.get(chosen_name)
        gdef = catalog.get_ghost(self.selected_ghost_id)
        embed = discord.Embed(
            title=f"🌑 {gdef['icon']} {gdef['name']} đang lởn vởn tại đây",
            description=f"HP: {data.get_world_ghost(self.selected_ghost_id)['hp_current']:,} / {gdef['hp_max']:,}",
            color=0x4b0082,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Khống chế Quỷ", style=discord.ButtonStyle.danger, emoji="🔒")
    async def khong_che(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Đây không phải cuộc khám phá của bạn.", ephemeral=True)
            return
        if not self.selected_ghost_id:
            await interaction.response.send_message("Hãy chọn một Quỷ trước.", ephemeral=True)
            return
        try:
            await _resolve_capture(interaction, self.user_id, self.selected_ghost_id, self)
        except Exception as e:
            logger.error(f"khong_che (select) button lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)


class DiChuyenView(discord.ui.View):
    """Chọn khu vực để di chuyển tới bằng StringSelectMenu: label = value = TÊN
    khu vực. location_id chỉ dùng nội bộ để tra `catalog`/cập nhật DB, tra
    ngược qua `catalog.get_location_id_by_name`, không bao giờ gửi lên Discord."""
    def __init__(self, user_id: int, destination_ids: list):
        super().__init__(timeout=60)
        self.user_id = user_id
        options = []
        for lid in destination_ids[:25]:
            ok, _ = player_can_access(user_id, lid)
            if not ok:
                continue
            ldef = catalog.get_location(lid)
            options.append(discord.SelectOption(label=ldef["name"], value=ldef["name"], emoji=ldef["icon"]))
        if options:
            self.select_destination.options = options
        else:
            self.remove_item(self.select_destination)

    @discord.ui.select(placeholder="Chọn khu vực để di chuyển tới...", min_values=1, max_values=1)
    async def select_destination(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Không phải cuộc di chuyển của bạn.", ephemeral=True)
            return
        try:
            dest_name = select.values[0]
            ldef = catalog.get_location_by_name(dest_name)
            loc_id = catalog.get_location_id_by_name(dest_name)
            ok, reason = player_can_access(self.user_id, loc_id)
            if not ok:
                await interaction.response.send_message(f"❌ {reason}", ephemeral=True)
                return
            data.update_player(self.user_id, location_id=loc_id)
            data.unlock_location(self.user_id, loc_id)
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(f"🚶 Bạn đã di chuyển tới **{ldef['name']}**.")
        except Exception as e:
            logger.error(f"di_chuyen select lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)


class ExploreCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="khampha", description="Khám phá khu vực hiện tại của bạn.")
    async def khampha(self, interaction: discord.Interaction):
        try:
            player = data.get_player(interaction.user.id)
            if not player:
                await interaction.response.send_message("❌ Dùng `/batdau` trước.", ephemeral=True)
                return

            location_id = player["location_id"]
            ok, reason = player_can_access(interaction.user.id, location_id)
            if not ok:
                await interaction.response.send_message(f"❌ {reason}", ephemeral=True)
                return

            await interaction.response.defer()

            loc = catalog.get_location(location_id)
            prior_progress = data.get_location_progress(interaction.user.id, location_id)
            is_new_location = not prior_progress or not prior_progress["visits"]
            data.bump_location_stat(interaction.user.id, location_id, "visits")
            if is_new_location:
                quests.on_event(interaction.user.id, "visit_location_distinct")

            rates = loc["encounter_rate"]
            roll = random.random()
            cumulative = 0.0
            outcome = "event"
            for etype, rate in rates.items():
                cumulative += rate
                if roll <= cumulative:
                    outcome = etype
                    break

            if outcome == "ghost":
                wild = data.get_wild_ghosts_at(location_id)
                candidates = [g for g in wild if g["ghost_id"] in catalog.ghosts_at(location_id)]
                if not candidates:
                    outcome = "item"  # không còn Quỷ hoang dã tại chỗ -> fallback
                else:
                    wg = random.choice(candidates)
                    gdef = catalog.get_ghost(wg["ghost_id"])
                    narrative = await generate_narrative(
                        f"Người chơi đang khám phá '{loc['name']}' và chạm trán Quỷ '{gdef['name']}' "
                        f"({gdef['quy_luat']}). Viết 2-3 câu mô tả không khí rùng rợn của cuộc chạm trán.",
                        fallback=f"Một luồng linh dị lạnh lẽo áp sát... {gdef['icon']} **{gdef['name']}** hiện ra trước mắt bạn.",
                        context="khampha_ghost",
                    )
                    embed = discord.Embed(
                        title=f"👻 Chạm trán: {gdef['icon']} {gdef['name']}",
                        description=(
                            f"{narrative}\n\n"
                            f"Bậc: {catalog.TIER_LABELS.get(gdef['tier'])} | "
                            f"Độ hiếm: {catalog.RARITY_LABELS.get(gdef['rarity'])}\n"
                            f"HP: {wg['hp_current']:,} / {gdef['hp_max']:,}"
                        ),
                        color=0x4b0082,
                    )
                    data.bump_location_stat(interaction.user.id, location_id, "successful_explorations")
                    notify = quests.process_and_notify(interaction.user.id, [("explore_success", 1, None)])
                    if notify:
                        embed.description += notify
                    await interaction.followup.send(
                        embed=embed, view=KhongCheView(interaction.user.id, wg["ghost_id"])
                    )
                    return

            if outcome == "item":
                item_id = random.choice(list(catalog.ITEMS.keys()))
                idef = catalog.get_item(item_id)
                data.add_item(interaction.user.id, item_id, 1)
                narrative = await generate_narrative(
                    f"Người chơi khám phá '{loc['name']}' và nhặt được vật phẩm '{idef['name']}'. "
                    f"Viết 1-2 câu mô tả không khí lúc tìm thấy.",
                    fallback=f"Trong góc tối, bạn tìm thấy {idef['icon']} **{idef['name']}**.",
                    context="khampha_item",
                )
                data.bump_location_stat(interaction.user.id, location_id, "successful_explorations")
                notify = quests.process_and_notify(interaction.user.id, [
                    ("explore_success", 1, None), ("loot_item", 1, None),
                ])
                embed = discord.Embed(
                    title="🎒 Nhặt được vật phẩm!",
                    description=f"{narrative}\n\n**{idef['icon']} {idef['name']}** đã vào túi đồ.{notify}",
                    color=0x2e8b57,
                )
                await interaction.followup.send(embed=embed)
                return

            if outcome == "npc":
                narrative = await generate_narrative(
                    f"Người chơi khám phá '{loc['name']}' và gặp một NPC bí ẩn liên quan tới thế giới linh dị. "
                    f"Viết 2-3 câu hội thoại/mô tả ngắn, gợi mở nhưng không tiết lộ số liệu game.",
                    fallback="Một bóng người lặng lẽ đứng trong sương, quan sát bạn rồi biến mất không dấu vết.",
                    context="khampha_npc",
                )
                await interaction.followup.send(embed=discord.Embed(
                    title="👤 Gặp NPC bí ẩn", description=narrative, color=0x708090
                ))
                return

            if outcome == "secret":
                data.unlock_location(interaction.user.id, location_id)
                data.bump_location_stat(interaction.user.id, location_id, "clues_found")
                data.bump_location_stat(interaction.user.id, location_id, "successful_explorations")
                narrative = await generate_narrative(
                    f"Người chơi tìm ra một địa điểm/manh mối bí mật tại '{loc['name']}'.",
                    fallback="Sau bức tường nứt, bạn phát hiện một lối đi không ai để ý tới.",
                    context="khampha_secret",
                )
                notify = quests.process_and_notify(interaction.user.id, [("explore_success", 1, None)])
                await interaction.followup.send(embed=discord.Embed(
                    title="🏚️ Phát hiện bí mật!", description=narrative + notify, color=0xdaa520
                ))
                return

            # event (mặc định / nguy hiểm / thế giới)
            narrative = await generate_narrative(
                f"Người chơi khám phá '{loc['name']}' và một sự kiện linh dị bất thường xảy ra.",
                fallback="Không khí đột ngột lạnh buốt, và bạn cảm nhận được một luồng linh dị đang theo dõi mình.",
                context="khampha_event",
            )
            await interaction.followup.send(embed=discord.Embed(
                title="🌑 Sự kiện linh dị", description=narrative, color=0x483d8b
            ))
        except Exception as e:
            logger.error(f"/khampha lỗi: {e}")
            if interaction.response.is_done():
                await interaction.followup.send(GENERIC_ERROR_MSG, ephemeral=True)
            else:
                await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="di_chuyen", description="Di chuyển tới khu vực khác.")
    async def di_chuyen(self, interaction: discord.Interaction):
        try:
            player = data.get_player(interaction.user.id)
            if not player:
                await interaction.response.send_message("❌ Dùng `/batdau` trước.", ephemeral=True)
                return

            current = catalog.get_location(player["location_id"])
            destinations = [
                lid for lid, ldef in catalog.LOCATIONS.items()
                if ldef.get("requires_location") == player["location_id"]
            ]

            desc_lines = [f"🗺️ **{current['name']}**\n\nCó thể đi tới:\n"]
            any_available = False
            for lid in destinations:
                ldef = catalog.get_location(lid)
                ok, reason = player_can_access(interaction.user.id, lid)
                label = f"{ldef['icon']} {ldef['name']}"
                if ok:
                    any_available = True
                    desc_lines.append(f"✅ {label}")
                else:
                    desc_lines.append(f"🔒 {label} — _{reason}_")

            if not any_available:
                desc_lines.append("\n_(Hiện chưa có lối đi mới nào mở ra từ đây.)_")

            embed = discord.Embed(title="📍 Di chuyển", description="\n".join(desc_lines), color=0x36393f)
            view = DiChuyenView(interaction.user.id, destinations) if any_available else None
            await interaction.response.send_message(embed=embed, view=view)
        except Exception as e:
            logger.error(f"/di_chuyen lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ExploreCog(bot))
