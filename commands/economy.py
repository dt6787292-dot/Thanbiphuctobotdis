import discord
from discord import app_commands
from discord.ext import commands

from utils import data, catalog
from config import GENERIC_ERROR_MSG, logger

SHOP_ITEMS = [iid for iid, i in catalog.ITEMS.items() if i["price"] > 0]


async def shop_item_autocomplete(interaction: discord.Interaction, current: str):
    choices = []
    for iid in SHOP_ITEMS:
        idef = catalog.get_item(iid)
        label = f"{idef['icon']} {idef['name']} — 💰{idef['price']}"
        if current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label, value=iid))
    return choices[:25]


async def owned_item_autocomplete(interaction: discord.Interaction, current: str):
    inv = data.get_inventory(interaction.user.id)
    choices = []
    for row in inv:
        idef = catalog.get_item(row["item_id"])
        if not idef or idef["price"] <= 0:
            continue
        label = f"{idef['icon']} {idef['name']} (x{row['quantity']})"
        if current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label, value=row["item_id"]))
    return choices[:25]


class TradeConfirmView(discord.ui.View):
    """Giao dịch vật phẩm/tiền — KHÔNG BAO GIỜ cho Quỷ vào trade (Rule 32)."""
    def __init__(self, initiator_id: int, target_id: int, offer_item: str, offer_qty: int, ask_money: int):
        super().__init__(timeout=120)
        self.initiator_id = initiator_id
        self.target_id = target_id
        self.offer_item = offer_item
        self.offer_qty = offer_qty
        self.ask_money = ask_money
        self.confirmed_initiator = False
        self.confirmed_target = False

    async def _finalize(self, interaction: discord.Interaction):
        if not data.remove_item(self.initiator_id, self.offer_item, self.offer_qty):
            await interaction.response.edit_message(content="❌ Giao dịch thất bại: người gửi không còn đủ vật phẩm.", embed=None, view=None)
            return
        target = data.get_player(self.target_id)
        if target["money"] < self.ask_money:
            data.add_item(self.initiator_id, self.offer_item, self.offer_qty)  # hoàn trả
            await interaction.response.edit_message(content="❌ Giao dịch thất bại: người nhận không đủ tiền.", embed=None, view=None)
            return
        data.update_player(self.target_id, money=target["money"] - self.ask_money)
        initiator = data.get_player(self.initiator_id)
        data.update_player(self.initiator_id, money=initiator["money"] + self.ask_money)
        data.add_item(self.target_id, self.offer_item, self.offer_qty)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ Giao dịch hoàn tất!", view=self)

    @discord.ui.button(label="Xác nhận", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.initiator_id:
            self.confirmed_initiator = True
        elif interaction.user.id == self.target_id:
            self.confirmed_target = True
        else:
            await interaction.response.send_message("Bạn không thuộc giao dịch này.", ephemeral=True)
            return

        if self.confirmed_initiator and self.confirmed_target:
            await self._finalize(interaction)
        else:
            waiting = "người nhận" if self.confirmed_initiator else "người gửi"
            await interaction.response.edit_message(
                content=f"✅ Đã xác nhận. Đang chờ {waiting} xác nhận lần 2...", view=self
            )

    @discord.ui.button(label="Hủy", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.initiator_id, self.target_id):
            await interaction.response.send_message("Bạn không thuộc giao dịch này.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="🚫 Giao dịch đã bị hủy.", view=self)


class EconomyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="shop", description="Xem cửa hàng vật phẩm.")
    async def shop(self, interaction: discord.Interaction):
        try:
            lines = []
            for iid in SHOP_ITEMS:
                idef = catalog.get_item(iid)
                lines.append(f"{idef['icon']} **{idef['name']}** — 💰{idef['price']} — _{idef['effect']}_")
            await interaction.response.send_message(
                embed=discord.Embed(title="💰 Cửa hàng", description="\n".join(lines), color=0x2e8b57)
            )
        except Exception as e:
            logger.error(f"/shop lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="mua", description="Mua một vật phẩm từ cửa hàng.")
    @app_commands.autocomplete(vat_pham=shop_item_autocomplete)
    async def mua(self, interaction: discord.Interaction, vat_pham: str, so_luong: int = 1):
        try:
            idef = catalog.get_item(vat_pham)
            if not idef or idef["price"] <= 0:
                await interaction.response.send_message("❌ Vật phẩm không có trong cửa hàng.", ephemeral=True)
                return
            if so_luong < 1:
                await interaction.response.send_message("❌ Số lượng không hợp lệ.", ephemeral=True)
                return
            player = data.get_player(interaction.user.id)
            cost = idef["price"] * so_luong
            if player["money"] < cost:
                await interaction.response.send_message(f"❌ Bạn không đủ tiền (cần 💰{cost}).", ephemeral=True)
                return
            data.update_player(interaction.user.id, money=player["money"] - cost)
            data.add_item(interaction.user.id, vat_pham, so_luong)
            await interaction.response.send_message(f"✅ Đã mua {idef['icon']} **{idef['name']}** x{so_luong} với 💰{cost}.")
        except Exception as e:
            logger.error(f"/mua lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="ban", description="Bán một vật phẩm (50% giá gốc).")
    @app_commands.autocomplete(vat_pham=owned_item_autocomplete)
    async def ban(self, interaction: discord.Interaction, vat_pham: str, so_luong: int = 1):
        try:
            idef = catalog.get_item(vat_pham)
            if not idef:
                await interaction.response.send_message("❌ Vật phẩm không tồn tại.", ephemeral=True)
                return
            if not data.remove_item(interaction.user.id, vat_pham, so_luong):
                await interaction.response.send_message("❌ Bạn không có đủ số lượng vật phẩm này.", ephemeral=True)
                return
            earn = int(idef["price"] * 0.5) * so_luong
            player = data.get_player(interaction.user.id)
            data.update_player(interaction.user.id, money=player["money"] + earn)
            await interaction.response.send_message(f"✅ Đã bán {idef['icon']} **{idef['name']}** x{so_luong}, nhận 💰{earn}.")
        except Exception as e:
            logger.error(f"/ban lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="giaodich", description="Đề nghị trao đổi vật phẩm lấy tiền với người chơi khác.")
    @app_commands.describe(nguoi_nhan="Người bạn muốn giao dịch", vat_pham="Vật phẩm bạn muốn gửi đi", gia="Số tiền yêu cầu")
    @app_commands.autocomplete(vat_pham=owned_item_autocomplete)
    async def giaodich(self, interaction: discord.Interaction, nguoi_nhan: discord.Member, vat_pham: str, so_luong: int, gia: int):
        try:
            if nguoi_nhan.id == interaction.user.id:
                await interaction.response.send_message("❌ Không thể giao dịch với chính mình.", ephemeral=True)
                return
            if not data.get_player(nguoi_nhan.id):
                await interaction.response.send_message("❌ Người nhận chưa tạo nhân vật.", ephemeral=True)
                return
            idef = catalog.get_item(vat_pham)
            inv_row = next((r for r in data.get_inventory(interaction.user.id) if r["item_id"] == vat_pham), None)
            if not idef or not inv_row or inv_row["quantity"] < so_luong:
                await interaction.response.send_message("❌ Bạn không có đủ vật phẩm này.", ephemeral=True)
                return

            view = TradeConfirmView(interaction.user.id, nguoi_nhan.id, vat_pham, so_luong, gia)
            await interaction.response.send_message(
                content=(
                    f"💱 **Đề nghị giao dịch**\n{interaction.user.mention} gửi {idef['icon']} **{idef['name']}** x{so_luong} "
                    f"đổi lấy 💰{gia} từ {nguoi_nhan.mention}.\n\nCả hai bên cần bấm **Xác nhận**."
                ),
                view=view,
            )
        except Exception as e:
            logger.error(f"/giaodich lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCog(bot))
