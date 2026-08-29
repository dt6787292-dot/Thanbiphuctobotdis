import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import data, catalog
from config import GENERIC_ERROR_MSG, logger


class AdminCog(commands.Cog):
    """Toàn bộ nhóm lệnh /admin chỉ hiển thị/dùng được bởi quản trị viên Discord (Rule 2/37)."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    admin_group = app_commands.Group(
        name="admin", description="Công cụ quản trị (chỉ Admin).",
        default_permissions=discord.Permissions(administrator=True),
    )

    async def _is_admin(self, interaction: discord.Interaction) -> bool:
        return isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator

    @admin_group.command(name="them_tien", description="[Admin] Thêm tiền cho người chơi.")
    async def them_tien(self, interaction: discord.Interaction, nguoi_choi: discord.Member, so_tien: int):
        if not await self._is_admin(interaction):
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)
            return
        try:
            player = data.get_player(nguoi_choi.id)
            if not player:
                await interaction.response.send_message("❌ Người này chưa tạo nhân vật.", ephemeral=True)
                return
            data.update_player(nguoi_choi.id, money=player["money"] + so_tien)
            logger.info(f"[ADMIN] {interaction.user.id} thêm {so_tien} tiền cho {nguoi_choi.id}")
            await interaction.response.send_message(f"✅ Đã thêm 💰{so_tien} cho {nguoi_choi.mention}.", ephemeral=True)
        except Exception as e:
            logger.error(f"/admin them_tien lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @admin_group.command(name="chinh_hp", description="[Admin] Chỉnh HP hiện tại của người chơi.")
    async def chinh_hp(self, interaction: discord.Interaction, nguoi_choi: discord.Member, hp: int):
        if not await self._is_admin(interaction):
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)
            return
        try:
            player = data.get_player(nguoi_choi.id)
            if not player:
                await interaction.response.send_message("❌ Người này chưa tạo nhân vật.", ephemeral=True)
                return
            new_hp = max(0, min(hp, player["hp_max"]))
            data.update_player(nguoi_choi.id, hp=new_hp)
            logger.info(f"[ADMIN] {interaction.user.id} chỉnh HP {nguoi_choi.id} -> {new_hp}")
            await interaction.response.send_message(f"✅ HP của {nguoi_choi.mention} → {new_hp}.", ephemeral=True)
        except Exception as e:
            logger.error(f"/admin chinh_hp lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @admin_group.command(name="them_vatpham", description="[Admin] Thêm vật phẩm cho người chơi.")
    async def them_vatpham(self, interaction: discord.Interaction, nguoi_choi: discord.Member, vat_pham: str, so_luong: int = 1):
        if not await self._is_admin(interaction):
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)
            return
        try:
            if not catalog.get_item(vat_pham):
                await interaction.response.send_message("❌ ID vật phẩm không tồn tại.", ephemeral=True)
                return
            data.add_item(nguoi_choi.id, vat_pham, so_luong)
            logger.info(f"[ADMIN] {interaction.user.id} thêm vật phẩm {vat_pham}x{so_luong} cho {nguoi_choi.id}")
            await interaction.response.send_message(f"✅ Đã thêm {vat_pham} x{so_luong} cho {nguoi_choi.mention}.", ephemeral=True)
        except Exception as e:
            logger.error(f"/admin them_vatpham lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @admin_group.command(name="spawn_quy", description="[Admin] Buộc một Quỷ tái xuất hiện (hoang dã) tại địa điểm.")
    async def spawn_quy(self, interaction: discord.Interaction, ten_quy: str, dia_diem: str):
        if not await self._is_admin(interaction):
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)
            return
        try:
            gdef = catalog.get_ghost(ten_quy)
            if not gdef or not catalog.get_location(dia_diem):
                await interaction.response.send_message("❌ ID Quỷ hoặc địa điểm không hợp lệ.", ephemeral=True)
                return
            world_row = data.get_world_ghost(ten_quy)
            if world_row["state"] not in ("destroyed",):
                await interaction.response.send_message(
                    f"⚠️ {gdef['name']} hiện đang ở trạng thái '{world_row['state']}', không thể ép tái xuất hiện.",
                    ephemeral=True,
                )
                return
            data.respawn_ghost(ten_quy, dia_diem, gdef["hp_max"], gdef["power_base"])
            logger.info(f"[ADMIN] {interaction.user.id} spawn {ten_quy} tại {dia_diem}")
            await interaction.response.send_message(f"✅ {gdef['name']} đã tái xuất hiện tại {dia_diem}.", ephemeral=True)
        except Exception as e:
            logger.error(f"/admin spawn_quy lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @admin_group.command(name="reset_nhanvat", description="[Admin] Reset nhân vật của một người chơi.")
    async def reset_nhanvat(self, interaction: discord.Interaction, nguoi_choi: discord.Member):
        if not await self._is_admin(interaction):
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)
            return
        try:
            with data.get_conn() as conn:
                owned = conn.execute(
                    "SELECT ghost_id FROM world_ghosts WHERE owner_id=?", (nguoi_choi.id,)
                ).fetchall()
                for row in owned:
                    conn.execute(
                        "UPDATE world_ghosts SET state='wild', owner_id=NULL WHERE ghost_id=?", (row["ghost_id"],)
                    )
                conn.execute("DELETE FROM players WHERE user_id=?", (nguoi_choi.id,))
                conn.execute("DELETE FROM location_progress WHERE user_id=?", (nguoi_choi.id,))
                conn.execute("DELETE FROM catalog_discovered WHERE user_id=?", (nguoi_choi.id,))
                conn.execute("DELETE FROM inventory WHERE user_id=?", (nguoi_choi.id,))
            logger.info(f"[ADMIN] {interaction.user.id} reset nhân vật {nguoi_choi.id}")
            await interaction.response.send_message(f"✅ Đã reset nhân vật của {nguoi_choi.mention}.", ephemeral=True)
        except Exception as e:
            logger.error(f"/admin reset_nhanvat lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
