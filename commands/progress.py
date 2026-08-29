import discord
from discord import app_commands
from discord.ext import commands

from utils import data, catalog
from utils.data import get_conn
from config import GENERIC_ERROR_MSG, logger

LEADERBOARDS = {
    "manh_nhat": ("👑 Người chơi mạnh nhất", "SELECT name, level, money FROM players ORDER BY level DESC, money DESC LIMIT 10"),
    "nhieu_quy": ("👻 Sở hữu nhiều Quỷ nhất",
                  """SELECT p.name AS name, COUNT(w.ghost_id) AS cnt FROM players p
                     JOIN world_ghosts w ON w.owner_id = p.user_id AND w.state IN ('controlled','battling','sealed')
                     GROUP BY p.user_id ORDER BY cnt DESC LIMIT 10"""),
    "kham_pha": ("🗺️ Khám phá nhiều địa điểm nhất",
                 """SELECT p.name AS name, COUNT(DISTINCT lp.location_id) AS cnt FROM players p
                    JOIN location_progress lp ON lp.user_id = p.user_id AND lp.visits > 0
                    GROUP BY p.user_id ORDER BY cnt DESC LIMIT 10"""),
}


class ProgressCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="thanhtich", description="Xem thành tựu của bạn.")
    async def thanhtich(self, interaction: discord.Interaction):
        try:
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT achievement_id, earned_at FROM achievements WHERE user_id=?",
                    (interaction.user.id,),
                ).fetchall()
            if not rows:
                await interaction.response.send_message("🏆 Bạn chưa có thành tựu nào. Hãy tiếp tục khám phá!", ephemeral=True)
                return
            lines = []
            for r in rows:
                adef = catalog.ACHIEVEMENTS.get(r["achievement_id"])
                if adef:
                    lines.append(f"{adef.get('icon','🏆')} **{adef['name']}** — _{adef['description']}_")
                else:
                    lines.append(f"🏆 {r['achievement_id']}")
            desc = "\n".join(lines)
            await interaction.response.send_message(embed=discord.Embed(title="🏆 Thành tựu", description=desc, color=0xdaa520))
        except Exception as e:
            logger.error(f"/thanhtich lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="danhhieu", description="Xem danh hiệu hiện tại của bạn.")
    async def danhhieu(self, interaction: discord.Interaction):
        try:
            player = data.get_player(interaction.user.id)
            if not player:
                await interaction.response.send_message("❌ Dùng `/batdau` trước.", ephemeral=True)
                return
            title = player["title"] or "(chưa có danh hiệu)"
            await interaction.response.send_message(f"🎖️ Danh hiệu hiện tại: **{title}**")
        except Exception as e:
            logger.error(f"/danhhieu lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)

    @app_commands.command(name="top", description="Xem bảng xếp hạng thế giới.")
    @app_commands.choices(bang=[app_commands.Choice(name=v[0], value=k) for k, v in LEADERBOARDS.items()])
    async def top(self, interaction: discord.Interaction, bang: app_commands.Choice[str]):
        try:
            label, query = LEADERBOARDS[bang.value]
            with get_conn() as conn:
                rows = conn.execute(query).fetchall()
            if not rows:
                await interaction.response.send_message("Chưa có dữ liệu xếp hạng.", ephemeral=True)
                return
            lines = []
            for i, r in enumerate(rows, start=1):
                extra = r["level"] if "level" in r.keys() else r["cnt"]
                lines.append(f"**{i}.** {r['name']} — {extra}")
            await interaction.response.send_message(embed=discord.Embed(title=label, description="\n".join(lines), color=0x1e90ff))
        except Exception as e:
            logger.error(f"/top lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ProgressCog(bot))
