import discord
from discord import app_commands
from discord.ext import commands

from utils import data, catalog, game
from config import GENERIC_ERROR_MSG, logger


async def item_autocomplete(interaction: discord.Interaction, current: str):
    inv = data.get_inventory(interaction.user.id)
    choices = []
    for row in inv:
        idef = catalog.get_item(row["item_id"])
        if not idef:
            continue
        label = f"{idef['icon']} {idef['name']} (x{row['quantity']})"
        if current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label, value=row["item_id"]))
    return choices[:25]


class InventoryCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="kho", description="Xem túi đồ của bạn.")
    async def kho(self, interaction: discord.Interaction):
        try:
            inv = data.get_inventory(interaction.user.id)
            if not inv:
                await interaction.response.send_message("🎒 Túi đồ của bạn trống.", ephemeral=True)
                return
            lines = []
            for row in inv:
                idef = catalog.get_item(row["item_id"])
                if not idef:
                    continue
                lines.append(f"{idef['icon']} **{idef['name']}** x{row['quantity']} — _{idef['effect']}_")
            await interaction.response.send_message(
                embed=discord.Embed(title="🎒 Kho đồ", description="\n".join(lines), color=0x36393f)
            )
        except Exception as e:
            logger.error(f"/kho lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="sudung", description="Sử dụng một vật phẩm trong túi đồ.")
    @app_commands.autocomplete(vat_pham=item_autocomplete)
    async def sudung(self, interaction: discord.Interaction, vat_pham: str):
        try:
            idef = catalog.get_item(vat_pham)
            if not idef:
                await interaction.response.send_message("❌ Vật phẩm không tồn tại.", ephemeral=True)
                return
            if not data.remove_item(interaction.user.id, vat_pham, 1):
                await interaction.response.send_message("❌ Bạn không có vật phẩm này.", ephemeral=True)
                return

            player = data.get_player(interaction.user.id)
            msg = f"Bạn đã dùng **{idef['name']}**."
            if idef["type"] == "hoi_hp":
                heal = 1500 if vat_pham == "thuoc_hoi_hp_nho" else 5000
                new_hp = min(player["hp_max"], player["hp"] + heal)
                data.update_player(interaction.user.id, hp=new_hp)
                msg += f" Hồi {heal:,} HP → {new_hp:,}/{player['hp_max']:,}."
            else:
                msg += f" Hiệu ứng: {idef['effect']}"

            await interaction.response.send_message(f"✅ {msg}")
        except Exception as e:
            logger.error(f"/sudung lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(InventoryCog(bot))
