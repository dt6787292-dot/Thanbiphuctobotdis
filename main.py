"""
LINH DỊ — THẦN BÍ PHỤC TÔ
Điểm khởi chạy bot Discord.
"""
import asyncio

import discord
from discord.ext import commands

from config import DISCORD_TOKEN, logger
from utils import data, catalog

COGS = [
    "commands.character",
    "commands.explore",
    "commands.ghost",
    "commands.battle",
    "commands.quest",
    "commands.inventory",
    "commands.economy",
    "commands.progress",
    "commands.admin",
    "commands.help",
]

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!linhdi-unused!", intents=intents)  # chỉ dùng slash commands


@bot.event
async def on_ready():
    logger.info(f"✅ Đăng nhập với tên {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Đã đồng bộ {len(synced)} slash command(s).")
    except Exception as e:
        logger.error(f"Lỗi đồng bộ slash commands: {e}")


async def main():
    logger.info("Đang khởi tạo dữ liệu tĩnh (Quỷ / Địa điểm / Vật phẩm)...")
    catalog.load_all()  # raise nếu dữ liệu tham chiếu sai -> dừng khởi động sớm, không để lỗi lộ ra giữa game

    logger.info("Đang khởi tạo Database...")
    data.init_db()
    data.seed_world_ghosts(catalog.GHOSTS)

    async with bot:
        for cog in COGS:
            await bot.load_extension(cog)
            logger.info(f"Đã nạp cog: {cog}")
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("❌ Thiếu DISCORD_TOKEN trong .env — không thể khởi động bot.")
    asyncio.run(main())
