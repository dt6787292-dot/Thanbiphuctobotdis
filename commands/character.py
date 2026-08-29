import discord
from discord import app_commands
from discord.ext import commands

from utils import data, game, catalog
from config import GENERIC_ERROR_MSG, logger


class CharacterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="batdau", description="Tạo nhân vật và bắt đầu hành trình linh dị.")
    async def batdau(self, interaction: discord.Interaction):
        try:
            existing = data.get_player(interaction.user.id)
            if existing:
                await interaction.response.send_message(
                    f"👤 Bạn đã có nhân vật **{existing['name']}** rồi. Dùng `/thongtin` để xem chi tiết.",
                    ephemeral=True,
                )
                return

            data.create_player(interaction.user.id, interaction.user.display_name)
            embed = discord.Embed(
                title="🌑 Chào mừng đến với LINH DỊ — THẦN BÍ PHỤC TÔ",
                description=(
                    f"Nhân vật **{interaction.user.display_name}** đã được tạo.\n\n"
                    "Bạn hiện là 👤 **Người thường** — chưa thể khống chế Quỷ.\n"
                    "Hãy dùng `/khampha` tại **Con Hẻm Khởi Đầu** để bắt đầu và tìm cơ hội "
                    "trở thành Ngự Quỷ Giả."
                ),
                color=0x2b2d31,
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.error(f"/batdau lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="thongtin", description="Xem thông tin nhân vật của bạn.")
    async def thongtin(self, interaction: discord.Interaction):
        try:
            player = data.get_player(interaction.user.id)
            if not player:
                await interaction.response.send_message(
                    "❌ Bạn chưa có nhân vật. Dùng `/batdau` trước.", ephemeral=True
                )
                return

            owned = data.get_owned_ghosts(interaction.user.id)
            char_meta = game.CHAR_TYPES.get(player["char_type"], game.CHAR_TYPES["nguoi_thuong"])

            hp_bar = game.render_bar(player["hp"], player["hp_max"])
            linh_di_bar = game.render_bar(player["linh_di"], 100)

            desc = (
                f"**Tên:** {player['name']}\n"
                f"**Loại nhân vật:** {char_meta['label']}\n"
                f"**Cấp độ:** {player['level']}  |  **EXP:** {player['exp']} / {game.exp_to_next_level(player['level'])}\n"
                f"**Tiền:** 💰 {player['money']}\n"
                f"**Danh hiệu:** {player['title'] or '(chưa có)'}\n\n"
                f"**HP** `{hp_bar}` {player['hp']:,} / {player['hp_max']:,}\n"
                f"**Linh Dị** `{linh_di_bar}` {player['linh_di']}%\n\n"
                f"**Quỷ đang khống chế:** {len(owned)} / {char_meta['base_ghost_slots'] or 0}\n"
            )
            if owned:
                # Chỉ hiển thị TÊN Quỷ cho người chơi — ghost_id là khóa nội bộ,
                # không bao giờ để lộ ra giao diện game.
                names = ", ".join(
                    f"👻 {catalog.get_ghost(g['ghost_id'])['name']}" for g in owned[:5]
                )
                desc += f"↳ {names}" + (" ..." if len(owned) > 5 else "")

            embed = discord.Embed(title=f"📋 Hồ sơ: {player['name']}", description=desc, color=0x6b2d5c)
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.error(f"/thongtin lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CharacterCog(bot))
