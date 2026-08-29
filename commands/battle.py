import time
import random

import discord
from discord import app_commands
from discord.ext import commands

from utils import data, game, catalog, quests, control
from config import GENERIC_ERROR_MSG, logger


class BattleState:
    """Trạng thái một trận Quỷ vs Quỷ (PvE, tương tác theo lượt), giữ tạm trong bộ nhớ theo user_id (Section 24)."""
    def __init__(self, user_id, player_ghost_id, player_gdef, enemy_ghost_id, enemy_gdef, enemy_hp, location_id):
        self.user_id = user_id
        self.location_id = location_id
        self.turn = 1
        self.domain_cd = 0
        self.seal_cd = 0

        self.p_gid = player_ghost_id
        self.p_def = player_gdef
        p_world = data.get_world_ghost(player_ghost_id)
        self.p_hp = p_world["hp_current"] if p_world and p_world["hp_current"] else player_gdef["hp_max"]
        self.p_hp_max = player_gdef["hp_max"]
        self.p_power = game.ghost_effective_power(p_world, player_gdef) if p_world else player_gdef["power_base"]
        self.p_domain_active = False

        self.e_gid = enemy_ghost_id
        self.e_def = enemy_gdef
        self.e_hp = enemy_hp
        self.e_hp_max = enemy_gdef["hp_max"]
        self.e_power = enemy_gdef["power_base"]
        self.e_domain_active = False

    def states(self):
        a = dict(hp=self.p_hp, hp_max=self.p_hp_max, power=self.p_power, tier=self.p_def["tier"],
                  linh_di=self.p_def["linh_di"], num_abilities=len(self.p_def["abilities"]),
                  domain_active=self.p_domain_active)
        b = dict(hp=self.e_hp, hp_max=self.e_hp_max, power=self.e_power, tier=self.e_def["tier"],
                 linh_di=self.e_def["linh_di"], num_abilities=len(self.e_def["abilities"]),
                 domain_active=self.e_domain_active)
        return a, b


ACTIVE_BATTLES: dict[int, BattleState] = {}


def render_battle_embed(bs: BattleState, log: str) -> discord.Embed:
    p_bar = game.render_bar(bs.p_hp, bs.p_hp_max)
    e_bar = game.render_bar(bs.e_hp, bs.e_hp_max)
    desc = (
        f"⚔️ **LƯỢT {bs.turn}**\n\n"
        f"{bs.p_def['icon']} **{bs.p_def['name']}** (của bạn)\n`{p_bar}` {bs.p_hp:,} / {bs.p_hp_max:,}\n\n"
        f"{bs.e_def['icon']} **{bs.e_def['name']}**\n`{e_bar}` {bs.e_hp:,} / {bs.e_hp_max:,}\n\n"
        f"{log}"
    )
    return discord.Embed(title="⚔️ QUỶ VS QUỶ", description=desc, color=0x8b0000)


class BattleView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    async def _guard(self, interaction: discord.Interaction) -> BattleState | None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Không phải trận đấu của bạn.", ephemeral=True)
            return None
        bs = ACTIVE_BATTLES.get(self.user_id)
        if not bs:
            await interaction.response.send_message("Trận đấu đã kết thúc.", ephemeral=True)
            return None
        return bs

    async def _end_check(self, interaction: discord.Interaction, bs: BattleState, log: str) -> bool:
        """Trả về True nếu trận đã kết thúc và đã gửi kết quả (chỉ dùng cho PvE)."""
        if bs.e_hp <= 0:
            data.destroy_ghost(bs.e_gid)
            gdef = bs.e_def
            reward = gdef.get("rewards", {"exp": 100, "money": 50})
            player = data.get_player(self.user_id)
            new_level, new_exp, new_hp_max, leveled = game.apply_exp(player, reward["exp"])
            data.update_player(
                self.user_id, level=new_level, exp=new_exp, hp_max=new_hp_max,
                money=player["money"] + reward["money"],
            )
            data.bump_counter(self.user_id, "kill_ghost_total", 1)
            events = [("kill_ghost", 1, None)]
            loc = catalog.get_location(bs.location_id)
            is_boss = bool(loc and loc.get("boss") == bs.e_gid)
            if is_boss:
                data.bump_location_stat(self.user_id, bs.location_id, "boss_defeated")
                events.append(("kill_boss", 1, bs.e_gid))
            notify = quests.process_and_notify(self.user_id, events)

            for item in self.children:
                item.disabled = True
            embed = render_battle_embed(
                bs, log + f"\n\n☠️ **{gdef['name']} BỊ HỦY!** +{reward['exp']} EXP, +{reward['money']} 💰{notify}"
            )
            del ACTIVE_BATTLES[self.user_id]
            await interaction.response.edit_message(embed=embed, view=self)
            return True

        if bs.p_hp <= 0:
            for item in self.children:
                item.disabled = True
            embed = render_battle_embed(bs, log + f"\n\n💀 **{bs.p_def['name']} đã gục ngã!** Bạn rút lui khỏi trận đấu.")
            data.set_ghost_state(bs.p_gid, hp_current=max(1, bs.p_hp_max // 10))
            # Trả Quỷ hoang dã về đúng trạng thái cũ (không kẹt mãi ở 'battling')
            data.set_ghost_state(bs.e_gid, state="wild", hp_current=max(1, bs.e_hp))
            del ACTIVE_BATTLES[self.user_id]
            await interaction.response.edit_message(embed=embed, view=self)
            return True
        return False

    @discord.ui.button(label="Kỹ năng", style=discord.ButtonStyle.danger, emoji="👻")
    async def skill(self, interaction: discord.Interaction, button: discord.ui.Button):
        bs = await self._guard(interaction)
        if not bs:
            return
        a, b = bs.states()
        result = game.resolve_battle_round(a, b)
        bs.e_hp -= result["damage_to_b"]
        bs.p_hp -= result["damage_to_a"]
        bs.turn += 1
        data.set_ghost_state(bs.p_gid, hp_current=max(0, bs.p_hp))
        data.set_ghost_state(bs.e_gid, hp_current=max(0, bs.e_hp))
        log = (f"{bs.p_def['name']} gây **{result['damage_to_b']:,}** sát thương.\n"
               f"{bs.e_def['name']} gây **{result['damage_to_a']:,}** sát thương.")
        control_msg = control.check_and_maybe_trigger(bs.user_id)
        if control_msg:
            log += f"\n\n{control_msg}"
        if await self._end_check(interaction, bs, log):
            return
        await interaction.response.edit_message(embed=render_battle_embed(bs, log), view=self)

    @discord.ui.button(label="Quỷ vực", style=discord.ButtonStyle.primary, emoji="🌑")
    async def domain(self, interaction: discord.Interaction, button: discord.ui.Button):
        bs = await self._guard(interaction)
        if not bs:
            return
        if bs.domain_cd > 0:
            await interaction.response.send_message(
                f"⏳ Quỷ vực đang hồi chiêu ({bs.domain_cd} lượt nữa).", ephemeral=True
            )
            return
        bs.p_domain_active = True
        bs.domain_cd = bs.p_def["quy_vuc"]["cooldown_turns"]
        log = f"🌑 **{bs.p_def['quy_vuc']['name']}** được triển khai! {bs.p_def['quy_vuc']['effect']}"
        control_msg = control.check_and_maybe_trigger(bs.user_id)
        if control_msg:
            log += f"\n\n{control_msg}"
        await interaction.response.edit_message(embed=render_battle_embed(bs, log), view=self)

    @discord.ui.button(label="Phong ấn", style=discord.ButtonStyle.secondary, emoji="🔒")
    async def seal(self, interaction: discord.Interaction, button: discord.ui.Button):
        bs = await self._guard(interaction)
        if not bs:
            return
        a, b = bs.states()
        chance = game.seal_chance(a, b, bs.p_def.get("seal_power", 1))
        success = random.random() < chance
        if success:
            data.set_ghost_state(bs.e_gid, state="sealed", hp_current=bs.e_hp, sealed_until=int(time.time()) + 3600)
            for item in self.children:
                item.disabled = True
            embed = render_battle_embed(
                bs, f"🔒 **PHONG ẤN THÀNH CÔNG!** {bs.e_def['name']} đã bị phong ấn ({chance:.0%} tỉ lệ)."
            )
            del ACTIVE_BATTLES[self.user_id]
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            bs.turn += 1
            a2, b2 = bs.states()
            result = game.resolve_battle_round(a2, b2)
            bs.p_hp -= result["damage_to_a"]
            data.set_ghost_state(bs.p_gid, hp_current=max(0, bs.p_hp))
            log = f"🔒 Phong ấn thất bại ({chance:.0%} tỉ lệ)! {bs.e_def['name']} phản công gây **{result['damage_to_a']:,}** sát thương."
            if await self._end_check(interaction, bs, log):
                return
            await interaction.response.edit_message(embed=render_battle_embed(bs, log), view=self)


def render_pvp_log_embed(attacker, defender, attacker_gdef, defender_gdef, sim: dict, seized: bool | None) -> discord.Embed:
    """Dựng embed 'nhật ký trận đấu' cho PvP tranh giành Quỷ — mô phỏng trọn vẹn 1 lượt gọi lệnh (Section 14)."""
    lines = []
    for r in sim["rounds"]:
        dom_tag_a = " 🌑" if r["a_domain"] else ""
        dom_tag_b = " 🌑" if r["b_domain"] else ""
        lines.append(
            f"**Lượt {r['turn']}**{dom_tag_a}{dom_tag_b} — "
            f"{attacker_gdef['icon']} gây {r['dmg_to_b']:,} | {defender_gdef['icon']} gây {r['dmg_to_a']:,} "
            f"— HP còn: {max(0,r['a_hp']):,} / {max(0,r['b_hp']):,}"
        )
    # Nhật ký có thể dài — Discord giới hạn description ~4096 ký tự, cắt bớt phần giữa nếu quá dài
    if len(lines) > 10:
        lines = lines[:5] + [f"_(... {len(lines) - 8} lượt tiếp theo lược bớt ...)_"] + lines[-3:]

    a_bar = game.render_bar(max(0, sim["a_hp"]), attacker_gdef["hp_max"])
    b_bar = game.render_bar(max(0, sim["b_hp"]), defender_gdef["hp_max"])

    if sim["winner"] == "a":
        if seized:
            result_line = f"🔒 **{attacker.mention} THẮNG!** Cướp quyền khống chế **{defender_gdef['name']}** thành công."
        else:
            result_line = f"⚠️ **{attacker.mention} thắng** nhưng không thể cướp quyền — tình huống đã thay đổi giữa chừng."
    else:
        result_line = f"🛡️ **{defender.mention} giữ vững quyền khống chế!** {attacker_gdef['name']} phải rút lui."

    desc = (
        f"⚔️ **NHẬT KÝ TRẬN CHIẾN** — {attacker.mention} thách đấu {defender.mention}\n\n"
        f"{attacker_gdef['icon']} **{attacker_gdef['name']}** ({attacker.display_name})\n`{a_bar}` {max(0,sim['a_hp']):,} / {attacker_gdef['hp_max']:,}\n\n"
        f"{defender_gdef['icon']} **{defender_gdef['name']}** ({defender.display_name})\n`{b_bar}` {max(0,sim['b_hp']):,} / {defender_gdef['hp_max']:,}\n\n"
        + "\n".join(lines) + f"\n\n{result_line}"
    )
    return discord.Embed(title="📜 Nhật Ký Tranh Giành Quỷ", description=desc, color=0x8b0000)


class BattleCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="chien_dau", description="Bắt đầu Quỷ vs Quỷ — với Quỷ hoang dã/Boss tại chỗ, hoặc tranh giành Quỷ của người chơi khác.")
    @app_commands.describe(doi_thu="(Tuỳ chọn) Thách đấu Quỷ chính của người chơi này để tranh giành quyền khống chế (Section 14) — mô phỏng tức thời kiểu nhật ký")
    async def chien_dau(self, interaction: discord.Interaction, doi_thu: discord.Member = None):
        try:
            player = data.get_player(interaction.user.id)
            if not player:
                await interaction.response.send_message("❌ Dùng `/batdau` trước.", ephemeral=True)
                return
            if not player["active_ghost_id"]:
                await interaction.response.send_message(
                    "❌ Bạn cần chọn Quỷ chính bằng `/thay_quy` trước khi chiến đấu.", ephemeral=True
                )
                return
            if interaction.user.id in ACTIVE_BATTLES:
                await interaction.response.send_message("⚔️ Bạn đang có một trận đấu dở dang.", ephemeral=True)
                return
            player_def = catalog.get_ghost(player["active_ghost_id"])

            if doi_thu is not None:
                # --- PvP kiểu NHẬT KÝ: mô phỏng trọn vẹn trận đấu ngay lập tức, không cần đối thủ online (Section 14) ---
                if doi_thu.id == interaction.user.id:
                    await interaction.response.send_message("❌ Không thể tự thách đấu chính mình.", ephemeral=True)
                    return
                target_player = data.get_player(doi_thu.id)
                if not target_player or not target_player["active_ghost_id"]:
                    await interaction.response.send_message("❌ Người này chưa có Quỷ chính để giao chiến.", ephemeral=True)
                    return
                target_ghost_id = target_player["active_ghost_id"]
                target_world = data.get_world_ghost(target_ghost_id)
                if not target_world or target_world["owner_id"] != doi_thu.id or target_world["state"] != "controlled":
                    await interaction.response.send_message(
                        "❌ Quỷ của người này hiện không thể bị thách đấu (đang chiến đấu/bị phong ấn/không hợp lệ).",
                        ephemeral=True,
                    )
                    return

                await interaction.response.defer()

                enemy_def = catalog.get_ghost(target_ghost_id)
                p_world = data.get_world_ghost(player["active_ghost_id"])

                a0 = dict(
                    hp=p_world["hp_current"] or player_def["hp_max"], hp_max=player_def["hp_max"],
                    power=game.ghost_effective_power(p_world, player_def), tier=player_def["tier"],
                    linh_di=player_def["linh_di"], num_abilities=len(player_def["abilities"]),
                    domain_cooldown=player_def["quy_vuc"]["cooldown_turns"],
                )
                b0 = dict(
                    hp=target_world["hp_current"] or enemy_def["hp_max"], hp_max=enemy_def["hp_max"],
                    power=game.ghost_effective_power(target_world, enemy_def), tier=enemy_def["tier"],
                    linh_di=enemy_def["linh_di"], num_abilities=len(enemy_def["abilities"]),
                    domain_cooldown=enemy_def["quy_vuc"]["cooldown_turns"],
                )
                sim = game.simulate_full_battle(a0, b0, a_domain_cd=0, b_domain_cd=0)

                data.set_ghost_state(player["active_ghost_id"], hp_current=max(1, sim["a_hp"]))
                seized = None
                if sim["winner"] == "a":
                    seized = data.seize_ghost(target_ghost_id, interaction.user.id, doi_thu.id, max(1, sim["b_hp"]))
                    data.bump_counter(interaction.user.id, "kill_ghost_total", 1)
                    notify = quests.process_and_notify(interaction.user.id, [("kill_ghost", 1, None)])
                else:
                    data.set_ghost_state(target_ghost_id, hp_current=max(1, sim["b_hp"]))
                    notify = ""

                control_msg = control.check_and_maybe_trigger(interaction.user.id)
                embed = render_pvp_log_embed(interaction.user, doi_thu, player_def, enemy_def, sim, seized)
                if notify or control_msg:
                    embed.description += (notify or "") + (f"\n\n{control_msg}" if control_msg else "")

                await interaction.followup.send(embed=embed)
                return

            # --- PvE mặc định: giao chiến với Quỷ hoang dã/boss tại khu vực hiện tại (tương tác theo lượt) ---
            wild = data.get_wild_ghosts_at(player["location_id"])
            wild = [w for w in wild if catalog.get_ghost(w["ghost_id"])]
            if not wild:
                await interaction.response.send_message(
                    "🌑 Không có Quỷ hoang dã nào tại đây để giao chiến. Thử `/khampha`.", ephemeral=True
                )
                return

            enemy_row = max(wild, key=lambda w: catalog.get_ghost(w["ghost_id"])["power_base"])
            enemy_def = catalog.get_ghost(enemy_row["ghost_id"])

            bs = BattleState(
                interaction.user.id, player["active_ghost_id"], player_def,
                enemy_row["ghost_id"], enemy_def, enemy_row["hp_current"], player["location_id"],
            )
            data.set_ghost_state(enemy_row["ghost_id"], state="battling")
            ACTIVE_BATTLES[interaction.user.id] = bs

            await interaction.response.send_message(
                embed=render_battle_embed(bs, "Trận chiến bắt đầu!"), view=BattleView(interaction.user.id)
            )
        except Exception as e:
            logger.error(f"/chien_dau lỗi: {e}")
            if interaction.response.is_done():
                await interaction.followup.send(GENERIC_ERROR_MSG, ephemeral=True)
            else:
                await interaction.response.send_message(GENERIC_ERROR_MSG, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BattleCog(bot))
