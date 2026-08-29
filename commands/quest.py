import discord
from discord import app_commands
from discord.ext import commands

from utils import data, catalog, quests
from config import GENERIC_ERROR_MSG, logger

TYPE_LABELS = {
    "chinh": "📌 Chính", "phu": "🔹 Phụ", "quy": "👻 Quỷ",
    "boss": "👹 Boss", "su_kien": "🌍 Sự kiện", "hang_ngay": "📅 Hằng ngày",
}


class QuestView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=90)
        self.user_id = user_id

        for qid, qdef, row in quests.list_completed_unclaimed(user_id)[:5]:
            btn = discord.ui.Button(label=f"Nhận thưởng: {qdef['name']}", style=discord.ButtonStyle.success, emoji="🎁")
            btn.callback = self._make_claim_cb(qid, qdef)
            self.add_item(btn)

        available = quests.list_available_quests(user_id)
        active_ids = {r["quest_id"] for r in data.get_active_quests(user_id)}
        for qid, qdef in available[:5]:
            if qid in active_ids:
                continue
            btn = discord.ui.Button(label=f"Nhận nhiệm vụ: {qdef['name']}", style=discord.ButtonStyle.primary, emoji="📜")
            btn.callback = self._make_accept_cb(qid, qdef)
            self.add_item(btn)

    def _make_claim_cb(self, qid, qdef):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Không phải nhiệm vụ của bạn.", ephemeral=True)
                return
            rewards = quests.claim_and_apply(self.user_id, qid)
            if not rewards:
                await interaction.response.send_message("❌ Không thể nhận thưởng (có thể đã nhận rồi).", ephemeral=True)
                return
            item_text = ", ".join(f"{catalog.get_item(i)['name']} x{q}" for i, q in rewards.get("items", {}).items())
            msg = f"🎁 Đã nhận thưởng từ **{qdef['name']}**: +{rewards['exp']} EXP, +{rewards['money']} 💰"
            if item_text:
                msg += f", {item_text}"
            if rewards.get("title"):
                msg += f"\n🎖️ Danh hiệu mới: **{rewards['title']}**"
            await interaction.response.send_message(msg)
        return cb

    def _make_accept_cb(self, qid, qdef):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Không phải nhiệm vụ của bạn.", ephemeral=True)
                return
            ok = quests.accept(self.user_id, qid)
            if not ok:
                await interaction.response.send_message("❌ Không thể nhận nhiệm vụ này lúc này.", ephemeral=True)
                return
            await interaction.response.send_message(f"📜 Đã nhận nhiệm vụ **{qdef['name']}**: _{qdef['description']}_")
        return cb


class QuestCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="nhiemvu", description="Xem và quản lý nhiệm vụ của bạn.")
    async def nhiemvu(self, interaction: discord.Interaction):
        try:
            player = data.get_player(interaction.user.id)
            if not player:
                await interaction.response.send_message("❌ Dùng `/batdau` trước.", ephemeral=True)
                return

            lines = []

            active = quests.list_active_quests(interaction.user.id)
            if active:
                lines.append("**🟡 Đang thực hiện:**")
                for qid, qdef, row in active:
                    obj = qdef["objective"]
                    lines.append(f"{TYPE_LABELS.get(qdef['type'], '')} **{qdef['name']}** — {row['progress']}/{obj['count']}")

            completed = quests.list_completed_unclaimed(interaction.user.id)
            if completed:
                lines.append("\n**✅ Đã hoàn thành (chưa nhận thưởng):**")
                for qid, qdef, row in completed:
                    lines.append(f"{TYPE_LABELS.get(qdef['type'], '')} **{qdef['name']}**")

            available = quests.list_available_quests(interaction.user.id)
            active_ids = {r[0] for r in active}
            available = [(qid, qdef) for qid, qdef in available if qid not in active_ids]
            if available:
                lines.append("\n**🆕 Có thể nhận:**")
                for qid, qdef in available:
                    lines.append(f"{TYPE_LABELS.get(qdef['type'], '')} **{qdef['name']}** — _{qdef['description']}_")

            if not lines:
                lines.append("Hiện chưa có nhiệm vụ nào khả dụng. Hãy tiếp tục khám phá thế giới.")

            embed = discord.Embed(title="📜 Nhiệm vụ", description="\n".join(lines), color=0x36393f)
            await interaction.response.send_message(embed=embed, view=QuestView(interaction.user.id))
        except Exception as e:
            logger.error(f"/nhiemvu lỗi: {e}")
            await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(QuestCog(bot))
