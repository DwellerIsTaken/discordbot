from __future__ import annotations

from typing import TYPE_CHECKING

from discord import Message

from .botconfig import BotConfig
from .events import Events
from .tasks import Tasks

if TYPE_CHECKING:
    from core import Dwello


class Other(Events, Tasks, BotConfig):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.message_cache: dict[int, Message] = {}

    """Other Class"""


async def setup(bot: Dwello) -> None:
    await bot.add_cog(Other(bot))
