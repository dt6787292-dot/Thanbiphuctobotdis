import discord
from discord import app_commands
from discord.ext import commands

from utils import data, game, catalog
from config import GENERIC_ERROR_MSG, logger


def ghost_choice_autocomplete(owned_only_current_user=True):
    async def autocomplete(interaction: discord.Interaction, current: str):
        owned = data.get_owned_ghosts(interaction.user.id)
        choices = []
        for row in owned:
            gdef = catalog.get_ghost(row["ghost_id"])
            if not gdef:
                continue
            label = f"{gdef['icon']} {gdef['name']}"
            if current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label, value=row["ghost_id"]))
        return choices[:25]
    return autocomplete


class GhostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="quy", description="Xem thông tin một Quỷ trong Bách Khoa Toàn Thư.")
    @app_commands.describe(ten_quy="Tên hoặc ID của Quỷ")
    async def quy(self, interaction: discord.Interaction, ten_quy: str):
        try:
            gdef = catalog.get_ghost(ten_quy)
            if not gdef:
                matches = [gid for gid, g in catalog.GHOSTS.items() if ten_quy.lower() in g["name"].lower()]
                if not matches:
                    await interaction.response.send_message("❌ Không tìm thấy Quỷ nào khớp.", ephemeral=True)
                    return
                gdef = catalog.get_ghost(matches[0])
                ten_quy = matches[0]

            discovered = ten_quy in data.get_catalog_progress(interaction.user.id)
            world_row = data.get_world_ghost(ten_quy)

            if not discovered:
                embed = discord.Embed(
                    title=f"❓ {gdef['icon']} {gdef['name']}",
                    description="HP: ❓\nNăng lực: ❓\nQuy luật: ❓\nQuỷ vực: ❓\n\n_Bạn cần khám phá để biết thêm._",
                    color=0x2f3136,
                )
            else:
                state_label = {
                    "wild": "🌑 Hoang dã", "controlled": "🔒 Đã khống chế", "battling": "⚔️ Đang chiến đấu",
                    "sealed": "🔒 Bị phong ấn", "destroyed": "☠️ Bị hủy",
                }.get(world_row["state"] if world_row else "wild", "❓")
                owner_line = f"<@{world_row['owner_id']}>" if world_row and world_row["owner_id"] else "Không có"
                embed = discord.Embed(
                    title=f"{gdef['icon']} {gdef['name']}",
                    description=(
                        f"**Bậc:** {catalog.TIER_LABELS.get(gdef['tier'])}\n"
                        f"**Độ hiếm:** {catalog.RARITY_LABELS.get(gdef['rarity'])}\n"
                        f"**HP tối đa:** {gdef['hp_max']:,}\n"
                        f"**Lực chiến gốc:** {gdef['power_base']:,} (giới hạn {gdef['power_cap']:,})\n"
                        f"**Linh dị:** {gdef['linh_di']}\n"
                        f"**Năng lực:** {', '.join(gdef['abilities'])}\n"
                        f"**Quy luật:** {gdef['quy_luat']}\n"
                        f"**Quỷ vực:** {gdef['quy_vuc']['name']} — {gdef['quy_vuc']['effect']}\n\n"
                        f"**Trạng thái thế giới:** {state_label}\n**Người khống chế:** {owner_line}"
                    ),
                    color=0x8a2be2,
                )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.error(f"/quy lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="bachkhoa", description="Xem tiến độ Bách Khoa Toàn Thư Quỷ.")
    async def bachkhoa(self, interaction: discord.Interaction):
        try:
            discovered = data.get_catalog_progress(interaction.user.id)
            total = len(catalog.GHOSTS)
            pct = int(len(discovered) / total * 100) if total else 0
            bar = game.render_bar(len(discovered), total, length=10)

            lines = []
            for i, (gid, gdef) in enumerate(catalog.GHOSTS.items(), start=1):
                if gid in discovered:
                    lines.append(f"{i}. {gdef['icon']} {gdef['name']}")
                else:
                    lines.append(f"{i}. ❓ Chưa phát hiện")

            desc = f"Đã phát hiện: **{len(discovered)} / {total}**\n`{bar}` {pct}%\n\n" + "\n".join(lines[:25])
            if total > 25:
                desc += f"\n_...và {total - 25} Quỷ khác._"
            embed = discord.Embed(title="📚 BÁCH KHOA TOÀN THƯ QUỶ", description=desc, color=0x36393f)
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.error(f"/bachkhoa lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="nguyquy", description="Quản lý các Quỷ bạn đang khống chế.")
    async def nguyquy(self, interaction: discord.Interaction):
        try:
            player = data.get_player(interaction.user.id)
            if not player:
                await interaction.response.send_message("❌ Dùng `/batdau` trước.", ephemeral=True)
                return
            owned = data.get_owned_ghosts(interaction.user.id)
            if not owned:
                await interaction.response.send_message(
                    "Bạn chưa khống chế Quỷ nào. Dùng `/khampha` để tìm Quỷ hoang dã.", ephemeral=True
                )
                return

            char_meta = game.CHAR_TYPES.get(player["char_type"])
            lines = []
            for row in owned:
                gdef = catalog.get_ghost(row["ghost_id"])
                power = game.ghost_effective_power(row, gdef)
                active = " ⭐" if row["ghost_id"] == player["active_ghost_id"] else ""
                lines.append(
                    f"{gdef['icon']} **{gdef['name']}**{active} — {catalog.TIER_LABELS.get(gdef['tier'])} | "
                    f"HP {row['hp_current']:,}/{gdef['hp_max']:,} | Lực chiến {power:,}"
                )
            desc = (
                f"Slot: {len(owned)} / {char_meta['base_ghost_slots']}\n\n" + "\n".join(lines) +
                "\n\n_Dùng `/thay_quy`, `/tha_quy`, `/thuc_tinh` để quản lý._"
            )
            await interaction.response.send_message(
                embed=discord.Embed(title="👻 Ngự Quỷ", description=desc, color=0x4b0082)
            )
        except Exception as e:
            logger.error(f"/nguyquy lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="khongche", description="Xem và khống chế Quỷ hoang dã tại khu vực hiện tại.")
    async def khongche(self, interaction: discord.Interaction):
        try:
            player = data.get_player(interaction.user.id)
            if not player:
                await interaction.response.send_message("❌ Dùng `/batdau` trước.", ephemeral=True)
                return
            wild = data.get_wild_ghosts_at(player["location_id"])
            if not wild:
                await interaction.response.send_message(
                    "🌑 Hiện không có Quỷ hoang dã nào tại đây. Hãy thử `/khampha`.", ephemeral=True
                )
                return

            from commands.explore import KhongCheView, KhongCheSelectView  # tái sử dụng view + logic độc quyền

            if len(wild) == 1:
                wg = wild[0]
                gdef = catalog.get_ghost(wg["ghost_id"])
                embed = discord.Embed(
                    title=f"🌑 {gdef['icon']} {gdef['name']} đang lởn vởn tại đây",
                    description=f"HP: {wg['hp_current']:,} / {gdef['hp_max']:,}",
                    color=0x4b0082,
                )
                await interaction.response.send_message(
                    embed=embed, view=KhongCheView(interaction.user.id, wg["ghost_id"])
                )
            else:
                # Nhiều hơn một Quỷ hoang dã tại khu vực: cho người chơi chọn
                # bằng TÊN Quỷ qua StringSelectMenu thay vì mặc định lấy con đầu tiên.
                first = catalog.get_ghost(wild[0]["ghost_id"])
                embed = discord.Embed(
                    title=f"🌑 {first['icon']} {first['name']} đang lởn vởn tại đây",
                    description=f"HP: {wild[0]['hp_current']:,} / {first['hp_max']:,}",
                    color=0x4b0082,
                )
                await interaction.response.send_message(
                    embed=embed, view=KhongCheSelectView(interaction.user.id, wild)
                )
        except Exception as e:
            logger.error(f"/khongche lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="tha_quy", description="Thả một Quỷ đang khống chế, trả nó về trạng thái hoang dã.")
    @app_commands.autocomplete(ten_quy=ghost_choice_autocomplete())
    async def tha_quy(self, interaction: discord.Interaction, ten_quy: str):
        try:
            ok = data.release_ghost(ten_quy, interaction.user.id)
            if not ok:
                await interaction.response.send_message("❌ Bạn không khống chế Quỷ này.", ephemeral=True)
                return
            gdef = catalog.get_ghost(ten_quy)
            await interaction.response.send_message(
                f"🌑 Bạn đã thả **{gdef['name']}**. Nó đã trở về trạng thái hoang dã."
            )
        except Exception as e:
            logger.error(f"/tha_quy lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="thay_quy", description="Đặt một Quỷ làm Quỷ chính để chiến đấu.")
    @app_commands.autocomplete(ten_quy=ghost_choice_autocomplete())
    async def thay_quy(self, interaction: discord.Interaction, ten_quy: str):
        try:
            owned_ids = {g["ghost_id"] for g in data.get_owned_ghosts(interaction.user.id)}
            if ten_quy not in owned_ids:
                await interaction.response.send_message("❌ Bạn không khống chế Quỷ này.", ephemeral=True)
                return
            data.update_player(interaction.user.id, active_ghost_id=ten_quy)
            gdef = catalog.get_ghost(ten_quy)
            await interaction.response.send_message(f"⭐ **{gdef['name']}** giờ là Quỷ chính của bạn.")
        except Exception as e:
            logger.error(f"/thay_quy lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="thuc_tinh", description="Thức tỉnh một Quỷ để mở năng lực/quỷ vực mới.")
    @app_commands.autocomplete(ten_quy=ghost_choice_autocomplete())
    async def thuc_tinh(self, interaction: discord.Interaction, ten_quy: str):
        try:
            world_row = data.get_world_ghost(ten_quy)
            if not world_row or world_row["owner_id"] != interaction.user.id:
                await interaction.response.send_message("❌ Bạn không khống chế Quỷ này.", ephemeral=True)
                return
            if world_row["awakened"]:
                await interaction.response.send_message("✨ Quỷ này đã thức tỉnh rồi.", ephemeral=True)
                return
            if not game.is_at_power_cap(world_row, catalog.get_ghost(ten_quy)):
                await interaction.response.send_message(
                    "⚠️ Quỷ cần đạt giới hạn lực chiến của bậc hiện tại trước khi có thể thức tỉnh.",
                    ephemeral=True,
                )
                return
            data.set_ghost_state(ten_quy, awakened=1)
            gdef = catalog.get_ghost(ten_quy)
            await interaction.response.send_message(
                f"✨ **{gdef['name']}** đã THỨC TỈNH! Năng lực và Quỷ vực của nó trở nên mạnh mẽ hơn."
            )
        except Exception as e:
            logger.error(f"/thuc_tinh lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GhostCog(bot))
