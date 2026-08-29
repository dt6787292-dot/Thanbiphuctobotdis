import discord
from discord import app_commands
from discord.ext import commands

HELP_TEXT = """
👤 **Nhân vật**
`/batdau` `/thongtin`

🗺️ **Khám phá**
`/khampha` `/di_chuyen`

👻 **Quỷ**
`/quy` `/bachkhoa` `/nguyquy` `/khongche` `/tha_quy` `/thay_quy` `/thuc_tinh`

⚔️ **Chiến đấu**
`/chien_dau`

📜 **Nhiệm vụ**
`/nhiemvu`

🎒 **Vật phẩm**
`/kho` `/sudung`

💰 **Kinh tế**
`/shop` `/mua` `/ban` `/giaodich`

🏆 **Tiến trình**
`/thanhtich` `/danhhieu` `/top`
"""


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Xem danh sách lệnh của Linh Dị.")
    async def help_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=discord.Embed(title="ℹ️ Hướng dẫn — LINH DỊ", description=HELP_TEXT, color=0x2b2d31)
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
