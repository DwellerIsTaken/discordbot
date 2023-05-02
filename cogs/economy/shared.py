from __future__ import annotations

import datetime
import discord
import asyncpg
import re

from typing import Optional, Tuple, Union

import text_variables as tv

from utils import DwelloContext
from bot import Dwello

class SharedEcoUtils:

    def __init__(self, bot: Dwello):
        self.bot = bot

    async def fetch_basic_job_data_by_username(self, ctx: DwelloContext, member: discord.Member = None) -> Optional[Tuple[Optional[str], Optional[int], Union[str, None], Optional[int]]]:
        async with self.bot.pool.acquire() as conn:
            conn: asyncpg.Connection
            async with conn.transaction():

                if not member:
                    member = ctx.author

                record = await conn.fetchrow("SELECT job_id FROM users WHERE user_id = $1 AND guild_id = $2 AND event_type = 'server'", member.id, member.guild.id)

                if not (record[0] if record else None):
                    return await ctx.reply(embed=discord.Embed(description="The job isn't yet set.", color=tv.color), ephemeral = True) # ephemeral:  if member == ctx.author else False

                data = await conn.fetchrow("SELECT name, salary, description FROM jobs WHERE id = $1 AND guild_id = $2", record[0], member.guild.id)

                if not data:
                    raise TypeError
                
                name, salary, description, job_id = str(data[0]), int(data[1]), str(data[2]) if data[2] else None, int(record[0])

        return name, salary, description, job_id
    
    async def add_currency(self, member: discord.Member, amount: int, name: str) -> Optional[int]:
        async with self.bot.pool.acquire() as conn:
            conn: asyncpg.Connection
            async with conn.transaction():
                
                row = await conn.fetchrow("SELECT money FROM users WHERE user_id = $1 AND guild_id = $2 AND event_type = $3", member.id, not None if str(name) == 'bot' else member.guild.id, name)
                # DOESNT FETCH CORRECTLY
                
                money = row[0]
                balance = int(money) + int(amount)

                await conn.execute("UPDATE users SET money = $1 WHERE user_id = $2 AND guild_id = $3 AND event_type = $4", balance, member.id, not None if str(name) == 'bot' else member.guild.id, name)

                return balance

    async def work(self, ctx: DwelloContext, name: str) -> Optional[discord.Message]:
        async with self.bot.pool.acquire() as conn:
            conn: asyncpg.Connection
            async with conn.transaction():

                worked = await conn.fetchrow("SELECT worked FROM users WHERE user_id = $1 AND event_type = $2", ctx.author.id, name)
                worked = bool(worked[0]) if worked[0] else False

                date = str(datetime.datetime.now())
                date = re.split('-| ', date)

                my_datetime = datetime.datetime(int(date[0]), int(date[1]), int(date[2]) + 1, 10, 00, tzinfo = None) # UTC tzinfo = pytz.utc 9, 00
                
                limit_embed = discord.Embed(title = "→ \U0001d5e6\U0001d5fc\U0001d5ff\U0001d5ff\U0001d606 ←", description=f"Your have already worked{' *on this server* ' if str(name) == 'server' else ' '}today!\nYour next workday begins {discord.utils.format_dt(my_datetime, style ='R')}",color=tv.color)
                #limit_embed.set_footer(text = "Your next workday begins in")
                #limit_embed.timestamp = discord.utils.format_dt(my_datetime) # loop.EcoLoop.my_datetime1

                if worked == True:
                    return await ctx.reply(embed = limit_embed)

                try:
                    job_name, salary, description, job_id = await self.fetch_basic_job_data_by_username(ctx)
                
                except TypeError:
                    return

                amount = salary if str(name) == 'server' else 250
                if not amount:
                    return await ctx.reply("You are unemployed.")

                balance = await self.add_currency(ctx.author, amount, name)

                string = f"Your current balance: {balance}"

                embed = discord.Embed(title="→ \U0001d5e6\U0001d5ee\U0001d5f9\U0001d5ee\U0001d5ff\U0001d606 ←", description = f"Your day was very successful. Your salary for today is *{amount}*.",color=tv.color) # 𝗦𝗮𝗹𝗮𝗿𝘆
                embed.timestamp = discord.utils.utcnow()
                embed.set_footer(text=string)

                await conn.execute("UPDATE users SET worked = $1 WHERE user_id = $2 AND event_type = $3", 1, ctx.author.id, name)

        return await ctx.reply(embed=embed, mention_author=False)