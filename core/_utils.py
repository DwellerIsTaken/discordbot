from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

import asyncpg

if TYPE_CHECKING:
    from asyncpg import Connection, Pool
    from asyncpg.transaction import Transaction
    from .bot import Dwello

import string
from string import Template

import discord
from aiohttp import web
from discord.app_commands import Choice

import constants as cs  # noqa: E402
from utils import ENV, DataBaseOperations, Twitch  # noqa: F401, E402

T = TypeVar("T")


class AiohttpWeb:
    def __init__(self, bot: Dwello):
        self.bot = bot
        self.app: web.Application = web.Application()
        self.app.router.add_post("/api/post", self.handle_post)

    async def handle_post(self, request):
        print(request)
        data = await request.json()
        print(data)

        await self.bot.twitch.twitch_to_discord(data)
        return web.json_response({"message": f"data received by aiohttp: {data}"})

    async def run(self, port: int = 8081):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, "localhost", port)

        try:
            await self.bot.loop.create_task(site.start())

        except Exception as e:
            print(f"Failed to start web server: {e}")


class LevellingUtils:
    def __init__(self, bot: Dwello):
        self.bot = bot

    async def create_user(self, user_id: int, guild_id: int) -> None:
        async with self.bot.pool.acquire() as conn:
            conn: asyncpg.Connection
            async with conn.transaction():
                query: str = (
                    """
                    INSERT INTO users(user_id, guild_id, event_type) VALUES($1, $2, 'server'), ($1, $2, 'bot') 
                    ON CONFLICT (user_id, guild_id, event_type) DO NOTHING
                    """
                )
                await conn.execute(
                    query,
                    user_id,
                    guild_id,
                )

    async def increase_xp(self, message: discord.Message, rate: int = 5) -> None:
        async with self.bot.pool.acquire() as conn:
            conn: asyncpg.Connection
            async with conn.transaction():
                if message.author.bot or not message.guild:
                    return

                await self.create_user(message.author.id, message.guild.id)

                records = await conn.fetch(
                    "SELECT * FROM users WHERE user_id = $1 AND guild_id = $2",
                    message.author.id,
                    message.guild.id,
                )

                if records:
                    xp, level, messages, total_xp = (
                        records[0]["xp"],
                        records[0]["level"],
                        records[0]["messages"],
                        records[0]["total_xp"],
                    )
                else:
                    xp, level, messages, total_xp = 0, 0, 0, 0

                level_formula = int(level * (level * 10))

                if xp >= level_formula:
                    new_level = int(level + 1)

                    new_level_formula = int(new_level * (new_level * 10))

                    xp_till_next_level = int(new_level_formula - 0)

                    # xp until next level
                    level_embed_dis = f"*Your new level is: {new_level}*\n*Xp until your next level: {xp_till_next_level}*" 

                    level_embed = discord.Embed(
                        title="Congratulations with your new level!",
                        description=string.Template(level_embed_dis).safe_substitute(member=message.author.name),
                        color=cs.RANDOM_COLOR,
                    )

                    level_embed.set_thumbnail(url=f"{message.author.display_avatar}")
                    level_embed.set_author(
                        name=f"{message.author.name}",
                        icon_url=f"{message.author.display_avatar}",
                    )
                    level_embed.set_footer(text=f"{message.guild.name}")
                    level_embed.timestamp = discord.utils.utcnow()

                    # async with suppress(discord.HTTPException): await message.author.send(embed=level_embed)

                    """try:
                        await message.author.send(embed=level_embed)

                    except discord.HTTPException:
                        pass"""
                    
                    query = "UPDATE users SET xp = $1, total_xp = $2, level = $3, messages = $4 WHERE user_id = $5 AND guild_id = $6"  # noqa: E501

                    await conn.execute(
                        query,
                        xp * 0,
                        total_xp + rate,
                        new_level,
                        messages + 1,
                        message.author.id,
                        message.guild.id,
                    )

                await conn.execute(
                    "UPDATE users SET xp = $1, total_xp = $2, messages = $3 WHERE user_id = $4 AND guild_id = $5",
                    xp + rate,
                    total_xp + rate,
                    messages + 1,
                    message.author.id,
                    message.guild.id,
                )

    async def get_user_data(
        self,
        user_id: int,
        guild_id: int,
    ) -> list[dict[str, Any]]:
        async with self.bot.pool.acquire() as conn:
            conn: asyncpg.Connection
            async with conn.transaction():
                await self.create_user(user_id, guild_id)

                records = await conn.fetch(
                    "SELECT * FROM users WHERE user_id = $1 AND guild_id = $2",
                    user_id,
                    guild_id,
                )
                results = [dict(record) for record in records]
        return results

    async def get_rank(
        self,
        user_id: int,
        guild_id: int,
    ) -> int:
        async with self.bot.pool.acquire() as conn:
            conn: asyncpg.Connection
            async with conn.transaction():
                await self.create_user(user_id, guild_id)

                records = await conn.fetch(
                    "SELECT * FROM users WHERE guild_id = $1 ORDER BY total_xp DESC",
                    guild_id,
                )

                rank = 0
                for record in records:
                    rank += 1
                    if record["user_id"] == user_id:
                        break

        return rank


class AutoComplete:
    def __init__(self, bot: Dwello):
        self.bot = bot

    async def choice_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
        table: str,
        name: str,
        value: str | None = None,
        all: bool = False,
    ) -> list[Choice]:
        """
        :Actually yea. The data type of the value needs to match the annotation
        :Forgot about that
        :job_name: str, value (s) must be strings.
        """

        records = self.bot.db_data
        table_ = records[table]

        choices = []
        item = len(current)

        if not value:
            value = name

        if all:
            choices.append(Choice(name="all", value="all"))

        for record in table_:
            name_ = record[name]
            value_ = record[value]

            if value_ is None and name_ is None:
                continue

            if current.startswith(str(name_).lower()[:item]):
                choices.append(Choice(name=str(name_), value=str(value_)))
            elif current.startswith(str(value_)[:item]):
                choices.append(Choice(name=str(name_), value=str(value_)))
        return choices[:5] if len(choices) > 5 else choices


class ContextManager(Generic[T]):
    if TYPE_CHECKING:
        from .bot import Dwello

    __slots__: tuple[str, ...] = ("bot", "timeout", "_pool", "_conn", "_tr")

    def __init__(self, bot: Dwello, *, timeout: float = 10.0) -> None:
        self.bot = bot
        self.timeout: float = timeout
        self._pool: Pool = bot.pool
        self._conn: Connection | None = None
        self._tr: Transaction | None = None

    async def acquire(self) -> Connection:
        return await self.__aenter__()

    async def release(self) -> None:
        return await self.__aexit__(None, None, None)

    async def __aenter__(self) -> Connection:
        self._conn = conn = await self._pool.acquire(timeout=self.timeout)  # type: ignore
        conn: Connection
        self._tr = conn.transaction()
        await self._tr.start()
        return conn  # type: ignore

    async def __aexit__(self, exc_type, exc, tb):
        if exc and self._tr:
            await self._tr.rollback()

        elif not exc and self._tr:
            await self._tr.commit()

        if self._conn is not None:
            await self._pool.release(self._conn)


LOADABLE_EXTENSIONS = [
    "jishaku",
    # "cogs.economy",  # TODO: Fix cogs
    # "cogs.entertainment",
    # "cogs.information",
    # "cogs.moderation",
    # "cogs.information.help",
    # "cogs.guild",
    # "cogs.other",
    # "utils.error",
]


class ListenersFunctions:
    def __init__(self, bot: Dwello):
        self.bot = bot

    async def bot_join(self, guild: discord.Guild) -> None:
        async with self.bot.pool.acquire() as conn:
            conn: asyncpg.Connection
            async with conn.transaction():
                counter_names = ["all", "member", "bot", "category"]
                event_types = ["welcome", "leave", "twitch"]
                # counter_names = [counter if counter is not None else 'Not Specified' for counter in counter_names]
                await conn.executemany(
                    "INSERT INTO server_data(guild_id, counter_name, event_type) VALUES($1, $2, $3)",
                    [(guild.id, "Disabled", event) for event in event_types],
                )
                return await conn.executemany(
                    "INSERT INTO server_data(guild_id, counter_name, event_type) VALUES($1, $2, $3)",
                    [(guild.id, counter, "counter") for counter in counter_names],
                )
                # ADD SOME WELCOME MESSAGE FROM BOT OR SMTH

    async def join_leave_event(self, member: discord.Member, name: Literal["welcome", "leave"]) -> discord.Message | None:
        async with self.bot.pool.acquire() as conn:
            conn: asyncpg.Connection
            async with conn.transaction():
                await self.bot.otherutils.exe_sql(member.guild)

                # adjust counters too in this event

                result = await conn.fetchrow(
                    "SELECT channel_id FROM server_data WHERE guild_id = $1 AND event_type = $2",
                    member.guild.id,
                    name,
                )

                if not (result[0] if result else None):
                    return

                send_channel = discord.utils.get(member.guild.channels, id=int(result[0]))  # type: ignore

                guild = member.guild

                second_result = await conn.fetchrow(
                    "SELECT message_text FROM server_data WHERE guild_id = $1 AND event_type = $2",
                    guild.id,
                    name,
                )

                if str(name) == "welcome":
                    member_welcome_embed = discord.Embed(
                        title="You have successfully joined the guild!",
                        description=(
                            f"```Guild joined: {guild.name}\nMember joined: {member}\n"
                            f"Guild id: {guild.id}\nMember id: {member.id}```"
                        ),
                        color=discord.Color.random(),
                    )
                    member_welcome_embed.set_thumbnail(
                        url=guild.icon.url if guild.icon else self.bot.user.display_avatar.url  # type: ignore
                    )
                    member_welcome_embed.set_author(
                        name=member.name,
                        icon_url=member.display_avatar.url
                        if member.display_avatar
                        else self.bot.user.display_avatar.url,  # type: ignore
                    )
                    member_welcome_embed.set_footer(text=cs.FOOTER)
                    member_welcome_embed.timestamp = discord.utils.utcnow()

                    try:
                        await member.send(embed=member_welcome_embed)

                    except discord.HTTPException as e:
                        print(e)

                    if not second_result[0]:  # type: ignore
                        _message = (
                            f"You are the __*{len(list(member.guild.members))}th*__ user on this server.\n"
                            "I hope that you will enjoy your time on this server. Have a good day!"
                        )

                    _title = f"Welcome to {member.guild.name}!"

                elif str(name) == "leave":
                    if not second_result[0]:
                        _message = "If you left, you had a reason to do so. Farewell, dweller!"

                    _title = f"Goodbye {member}!"

                if second_result[0]:
                    _message = Template(second_result[0]).safe_substitute(
                        members=len(list(member.guild.members)),
                        mention=member.mention,
                        user=member.name,
                        guild=member.guild.name,
                        space="\n",
                    )

                _embed = discord.Embed(title=_title, description=_message, color=discord.Color.random())
                _embed.set_thumbnail(url=member.display_avatar.url)
                _embed.set_author(name=member.name, icon_url=member.display_avatar.url)
                _embed.set_footer(text=cs.FOOTER)
                _embed.timestamp = discord.utils.utcnow()

        return await send_channel.send(embed=_embed)


class OtherUtils:
    def __init__(self, bot: Dwello) -> None:
        self.bot = bot

    async def exe_sql(self, guild: discord.Guild) -> None:
        async with self.bot.pool.acquire() as conn:
            conn: asyncpg.Connection
            async with conn.transaction():
                query: str = (
                    """
                    SELECT channel_id, counter_name FROM server_data WHERE guild_id = $1 AND channel_id IS NOT NULL 
                    AND event_type = 'counter' AND counter_name != 'category'
                    """
                )
                channels = await conn.fetch(
                    query,
                    guild.id,
                )

                bot_counter_ = sum(member.bot for member in guild.members)
                member_counter_ = len(guild.members) - bot_counter_  # type: ignore

                counters = ["all", "member", "bot"]

                for row in channels:
                    channel_id, event_type = int(row["channel_id"]), str(row["counter_name"])

                    if event_type in counters:
                        channel: discord.VoiceChannel = self.bot.get_channel(channel_id)  # type: ignore

                        try:
                            name = None
                            if event_type == counters[0]:
                                name = f"\N{BAR CHART} All counter: {guild.member_count}"
                            elif event_type == counters[1]:
                                name = f"\N{BAR CHART} Member counter: {member_counter_}"
                            elif event_type == counters[2]:
                                name = f"\N{BAR CHART} Bot counter: {bot_counter_}"
                            if name and channel:
                                await channel.edit(name=name)

                        except Exception as e:  # handle type error
                            print(e, "exe_sql (utils/other.py)")
