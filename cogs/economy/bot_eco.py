from __future__ import annotations

from discord.ext import commands
import discord
import asyncpg

from .shared import SharedEcoUtils

from typing import Any, Optional

from utils import BaseCog, DwelloContext
import text_variables as tv
from bot import Dwello

class BotEcoUtils:

    def __init__(self, bot: Dwello):
        self.bot = bot

    async def balance_check(self, ctx: DwelloContext, amount: int, name: str) -> Optional[bool]:
        async with self.bot.pool.acquire() as conn:
            conn: asyncpg.Connection
            async with conn.transaction():

                row = await conn.fetchrow("SELECT money FROM users WHERE user_id = $1 AND guild_id = $2 AND event_type = $3", ctx.author.id, not None if str(name) == 'bot' else ctx.guild.id, name)

                money = int(row[0]) if row else None

                if money < amount:
                    return await ctx.reply(embed = discord.Embed(title = "Permission denied", description="You don't have enough currency to execute this action!", color = tv.color))

        return True

class Bot_Economy(BaseCog):

    def __init__(self, bot: Dwello, *args: Any, **kwargs: Any):
        super().__init__(bot, *args, **kwargs)
        self.be: BotEcoUtils = BotEcoUtils(self.bot)
        self.se: SharedEcoUtils = SharedEcoUtils(self.bot)

    @commands.hybrid_command(name = "work", description = "A boring job with a basic income. Gives some of the bot's currency in return.")
    async def work_bot(self, ctx: DwelloContext):

        return await self.se.work(ctx, "bot")