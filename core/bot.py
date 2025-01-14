from __future__ import annotations

import asyncio
import aiohttp
import asyncpg
import discord
import aiofiles
import datetime
import logging
import os
import re
import sys

from discord.ext import commands
from typing_extensions import override

from typing import (
    TYPE_CHECKING,
    Any,
    List,  # noqa: F401
    Set,  # noqa: F401
    ClassVar,
    Generic,
    Generator,
    Optional,
    Tuple,  # noqa: F401
    Type,
    TypeVar,
    Union,  # noqa: F401
    overload,
)

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
else:
    try:
        import uvloop  # type: ignore
    except ImportError:
        pass
    else:
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

from constants import GITHUB, TYPING_EMOJI, COMMAND_PREVIEW_DICT
from utils import NewEmbed as Embed
from utils import NewTranslator as Translator
from utils import get_avatar_dominant_color
from utils import ENV, DataBaseOperations, Twitch

from .web import AiohttpWeb as Web
from .context import NewContext as Context
from .context import NewView as View # noqa: F401

if TYPE_CHECKING:
    from asyncpg import Connection, Pool
    from asyncpg.transaction import Transaction

if TYPE_CHECKING:
    from discord.abc import Message
    from types import TracebackType

    BE = TypeVar('BE', bound=BaseException)
    DCT = TypeVar("DCT", bound=Context)

DBT = TypeVar("DBT", bound="Dwello")

Choice = discord.app_commands.Choice

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] - %(name)s: %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S %Z%z",  # CET timezone format
)

LINKS_RE = re.compile(
    r"((http|https)\:\/\/)?[a-zA-Z0-9\.\/\?\:@\-_=#]+\.([a-zA-Z]){2,6}([a-zA-Z0-9\.\&\/\?\:@\-_=#])*",
    flags=re.IGNORECASE,
)

initial_extensions: tuple[str] = ("jishaku",)
extensions: list[str] = [
    "cogs.economy",
    "cogs.entertainment",
    "cogs.information",
    "cogs.information.help",
    "cogs.moderation",
    "cogs.guild",
    "cogs.guild.customisation",
    "cogs.todo",
    "cogs.other.owner",
    "cogs.other",
]


def col(color=None, /, *, fmt=0, bg=False):
    base = "\u001b["
    if fmt != 0:
        base += "{fmt};"
    if color is None:
        base += "{color}m"
        color = 0
    else:
        if bg is True:
            base += "4{color}m"
        else:
            base += "3{color}m"
    return base.format(fmt=fmt, color=color)


def countlines(directory: str, /, lines=0, ext=".py", skip_blank=False):
    for root, dirs, files in os.walk(directory):
        for filename in files:
            if not filename.endswith(ext):
                continue
            file = os.path.join(root, filename)
            with open(file, encoding="utf-8") as f:
                new_lines = len([i for i in f.readlines() if i.strip()]) if skip_blank else len(f.readlines())
                lines = lines + new_lines
    return lines


async def count_others(
    # to count classes and funcs (for about cmd)
    # Examples:
    # await count_others('./', '.py', 'def ')"
    # await count_others('./', '.py', 'class ')
    path: str,
    filetype: str = ".py",
    file_contains: str = "def",
    skip_venv: bool = True,
):
    line_count = 0
    for i in os.scandir(path):
        if i.is_file():
            if i.path.endswith(filetype):
                if skip_venv and re.search(r"(\\|/)?venv(\\|/)", i.path):
                    continue
                line_count += len(
                    [line for line in (await (await aiofiles.open(i.path, "r")).read()).split("\n") if file_contains in line]
                )
        elif i.is_dir():
            line_count += await count_others(i.path, filetype, file_contains)
    return line_count


# GLOBAL CHECKS
def blacklist_check(ctx: Context) -> bool:
    return not ctx.bot.is_blacklisted(ctx.author.id)


class ContextManager(Generic[DBT]):
    __slots__: tuple[str, ...] = ("bot", "timeout", "_pool", "_conn", "_tr")

    def __init__(self, bot: Dwello, *, timeout: float = 10.0) -> None:
        self.bot: DBT = bot
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


class ReactionTyping:
    def __init__(self, _bot: Dwello, _message: Message) -> None:
        self.message: Message = _message
        self.author: discord.ClientUser = _bot.user

    def __await__(self) -> Generator[None, None, None]:
        return self.message.add_reaction(TYPING_EMOJI).__await__()

    async def __aenter__(self) -> None:
        await self.message.add_reaction(TYPING_EMOJI)

    async def __aexit__(
        self,
        exc_type: Optional[Type[BE]],
        exc: Optional[BE],
        traceback: Optional[TracebackType],
    ) -> None:
        await self.message.remove_reaction(TYPING_EMOJI, self.author)


class Dwello(commands.AutoShardedBot):
    user: discord.ClientUser
    DEFAULT_PREFIXES: ClassVar[list[str]] = ["dw.", "Dw.", "dwello.", "Dwello."]
    # extend by [f"<@!{self.bot.user.id}>"] ?

    logger = logging.getLogger("logging")
    _ext_log = logging.getLogger("extensions")

    def __init__(self, pool: asyncpg.Pool, session: aiohttp.ClientSession, **kwargs) -> None:
        super().__init__(
            command_prefix=self.get_prefix,  # type: ignore
            strip_after_prefix=True,
            intents=discord.Intents.all(),
            case_insensitive=True,
            activity=discord.Streaming(
                name="Visual Studio Code",
                url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            ),
            allowed_mentions=discord.AllowedMentions.all(),
            chunk_guilds_at_startup=False,
            owner_ids={548846436570234880},
        )

        self._BotBase__cogs = commands.core._CaseInsensitiveDict()
        self.pool = pool
        self.http_session = session

        self.repo = GITHUB

        self.reply_count: int = 0
        self.commands_executed: int = 0

        self._was_ready = False
        self.test_instance = False
        self.total_lines: int = countlines("G:\My Drive\discordbot", skip_blank=True)  # noqa: W605
        # wont work on host, somehow automatically determine the directory

        self.blacklisted_users: dict[int, str] = {}
        self.bypass_cooldown_users: list[int] = []
        self.execution_times: list[float] = []

        self.cooldown: commands.CooldownMapping[discord.Message] = commands.CooldownMapping.from_cooldown(
            1,
            1.5,
            commands.BucketType.member,
        )

        # redo except db
        self.db: DataBaseOperations = DataBaseOperations(self)
        # maybe make it a pool if no funcs (that are bound to this db class) are triggered?
        self.web = Web(self)

        # Caching Variables (for now)
        # TODO: Use LRU Cache
        self.message_cache: dict[int, discord.Message] = {}

    @property
    def color(self) -> discord.Color | None:
        return self.default_color

    @property
    def colour(self) -> discord.Colour | None:
        return self.default_color
    
    @property
    def main_prefix(self) -> str:
        return self.DEFAULT_PREFIXES[0]
    
    @property
    def average_command_execution_time(self) -> float:
        _all = 0.0
        for num in self.execution_times:
            _all += num
        try:
            return _all / len(self.execution_times)
        except ZeroDivisionError:
            return 100.0

    async def setup_hook(self) -> None:
        try:
            for ext in initial_extensions:
                await self.load_extension(ext, _raise=False)

            for ext in extensions:
                await self.load_extension(ext, _raise=False)
        except Exception as e:
            raise e
        
        for command in self.walk_commands():
            if isinstance(command, commands.Command):
                command.extras["execution_times"] = [500.0]
                command.extras["times_executed"] = 0
                if (key:= command.qualified_name) in COMMAND_PREVIEW_DICT:
                    command.extras["preview"] = COMMAND_PREVIEW_DICT.get(key)

        self.tables = await self.db.create_tables()
        #self.db_data = await self.db.fetch_table_data()
        self.guild_prefixes = dict(
            await self.pool.fetch("SELECT guild_id, array_agg(prefix) FROM prefixes GROUP BY guild_id")
        )
        blacklist: list[asyncpg.Record] = await self.pool.fetch("SELECT * FROM blacklist")
        self.twitch = await Twitch.create_access_token(self)
        for record in blacklist:
            self.blacklisted_users[record["user_id"]] = record["reason"]

        self.add_check(blacklist_check)

        # Example Context Menu:
        """self.tree.add_command(
            discord.app_commands.ContextMenu(
                name="Cool Command Name",
                callback=my_cool_context_menu,
            )
        )"""

        await self.tree.set_translator(Translator(self.http_session))

        asyncio.create_task(self.web.run(port=8081))

    async def is_owner(self, user: discord.User | discord.Member) -> bool:
        """This makes jishaku usable by any of the team members or the application owner if the bot isn't in a team"""
        ids = set()

        if app := self.application:
            if app.team:
                ids = {user.id for user in app.team.members}
            elif app.owner:
                ids = {
                    app.owner.id,
                }

        return True if user.id in ids else await super().is_owner(user)

    def safe_connection(self, *, timeout: float = 10.0) -> ContextManager:
        return ContextManager(self, timeout=timeout)

    def is_blacklisted(self, user_id: int) -> bool:
        return user_id in self.blacklisted_users  # rewrite member and user and put it there as a property
    
    def autocomplete(
        self, current: Any, names_and_values: list[tuple[Any, Any]], *, choice_length: int = 5,
    ) -> list[Choice]:
        # 25 choices is max
        current: str = str(current)
        item = len(current)
        choices = []
   
        for name, value in names_and_values:
            if current.startswith(str(name).lower()[:item]):
                choices.append(Choice(name=name, value=value))
        return choices[:choice_length if choice_length < 26 else 25]
    
    def reaction_typing(self, message: Message) -> ReactionTyping:
        return ReactionTyping(self, message)

    @override
    async def get_context(self, message, *, cls: Any = Context):
        return await super().get_context(message, cls=cls)

    @override
    async def get_prefix(self, message: discord.Message) -> list[str]:
        prefixes = []
        if message.guild:
            if guild_prefixes := self.guild_prefixes.get(message.guild.id):  # type: ignore
                prefixes.extend(guild_prefixes)
            else:
                prefixes.extend(self.DEFAULT_PREFIXES)

            if await self.is_owner(message.author) and guild_prefixes:
                prefixes.extend(self.DEFAULT_PREFIXES) # ?
        else:
            prefixes.extend(self.DEFAULT_PREFIXES)

        # override or extend
        return commands.when_mentioned_or(*prefixes)(self, message)

    async def on_ready(self) -> None:
        self.logger.info(f"{col()}Python Version: {sys.version} {col()}")
        self.logger.info(f"{col()}Discord Version: {discord.__version__} {col()}")
        self.logger.info(f"{col(2, bg=True)}Logged in as {self.user} {col()}")
        self._was_ready = True

        if self.user.id == 1125762669056630915:
            self.DEFAULT_PREFIXES: list[str] = ["t.", "dt.", "Dt.", "beta.", "Beta."]
            self.test_instance = True

        if not hasattr(self, "uptime"):
            self.uptime = datetime.datetime.now(datetime.timezone.utc)

        if not hasattr(self, "default_color"):
            self.default_color = await get_avatar_dominant_color(self.user)
            Embed.bot_dominant_colour = self.default_color

    @override
    async def load_extension(self, name: str, *, package: str | None = None, _raise: bool = True) -> None:
        self._ext_log.info(f"{col(7)}Attempting to load {col(7, fmt=4)}{name}{col()}")
        try:
            await super().load_extension(name, package=package)
            self._ext_log.info(f"{col(2)}Loaded extension {col(2, fmt=4)}{name}{col()}")

        except Exception as e:
            self._ext_log.error(f"Failed to load extension {name}", exc_info=e)
            if _raise:
                raise e

    @override
    async def unload_extension(self, name: str, *, package: str | None = None, _raise: bool = True) -> None:
        self._ext_log.info(f"{col(7)}Attempting to unload extension {col(7, fmt=4)}{name}{col()}")
        try:
            await super().unload_extension(name, package=package)
            self._ext_log.info(f"{col(2)}Unloaded extension {col(2, fmt=4)}{name}{col()}")

        except Exception as e:
            self._ext_log.error(f"Failed to unload extension {name}", exc_info=e)
            if _raise:
                raise e

    @override
    async def reload_extension(self, name: str, *, package: str | None = None, _raise: bool = True) -> None:
        self._ext_log.info(f"{col(7)}Attempting to reload extension {col(7, fmt=4)}{name}{col()}")
        try:
            await super().reload_extension(name, package=package)
            self._ext_log.info(f"{col(2)}Reloaded extension {col(2, fmt=4)}{name}{col()}")

        except Exception as e:
            self._ext_log.error(f"Failed to reload extension {name}", exc_info=e)
            if _raise:
                raise e

    @overload
    async def get_or_fetch_message(
        self,
        channel: ...,
        message: ...,
    ) -> discord.Message | None:
        ...

    @overload
    async def get_or_fetch_message(
        self,
        channel: ...,
        message: ...,
        *,
        partial: bool = ...,
        force_fetch: bool = ...,
        dm_allowed: bool = ...,
    ) -> discord.Message | discord.PartialMessage | None:
        ...

    @overload
    async def get_or_fetch_message(
        self,
        channel: str | int,
    ) -> discord.Message | None:
        ...

    async def get_or_fetch_message(
        self,
        channel: str | int | discord.PartialMessageable,
        message: int | str | None = None,
        *,
        partial: bool = False,
        force_fetch: bool = False,
        dm_allowed: bool = False,
    ) -> discord.Message | discord.PartialMessage | None:
        if message is None:
            dummy_message = str(channel)
            if link := LINKS_RE.match(dummy_message):
                dummy_message_id = int(link.string.split("/")[-1])
                if dummy_message_id in self.message_cache:
                    return self.message_cache[dummy_message_id]

                dummy_channel_id = int(link.string.split("/")[-2])
                dummy_channel = await self.getch(self.get_channel, self.fetch_channel, dummy_channel_id)
                if dummy_channel is not None and force_fetch:
                    msg = await dummy_channel.fetch_message(dummy_message_id)
                    if msg:
                        self.message_cache[msg.id] = msg
                    return msg

            try:
                return self.message_cache[int(dummy_message)]
            except (ValueError, KeyError):
                return None

        message = int(message)

        channel_id = int(channel) if isinstance(channel, int | str) else channel.id
        channel = await self.getch(self.get_channel, self.fetch_channel, channel_id)

        if channel is None:
            return None

        if isinstance(channel, discord.DMChannel) and not dm_allowed:
            raise ValueError("DMChannel is not allowed")

        if force_fetch:
            msg = await channel.fetch_message(message)  # type: ignore
            self.message_cache[message] = msg
            return msg

        if msg := self._connection._get_message(message):
            self.message_cache[message] = msg
            return msg

        if partial:
            return channel.get_partial_message(message)  # type: ignore

        try:
            msg = self.message_cache[message]
            return msg
        except KeyError:
            async for msg in channel.history(  # type: ignore
                limit=1,
                before=discord.Object(message + 1),
                after=discord.Object(message - 1),
            ):
                self.message_cache[message] = msg
                return msg

        return None

    async def getch(self, get_function, fetch_function, *args, **kwargs) -> Any:
        if args[0] <= 0:
            return None

        return get_function(*args, **kwargs) or await fetch_function(*args, **kwargs)


async def runner():
    credentials = {
        "user": ENV["pg_username"],
        "password": ENV["pg_password"],
        "database": ENV["pg_name"],
        "host": ENV["pg_host"],
        "port": ENV["pg_port"],
    }

    async with asyncpg.create_pool(**credentials) as pool, aiohttp.ClientSession() as session, Dwello(pool, session) as bot:
        await bot.start(ENV["token"])


def run():
    asyncio.run(runner())
