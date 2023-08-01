from __future__ import annotations

# HERE WE CAN CONSTRUCT EMBED BASED ON GUILD CONFIG

import datetime

import discord

from typing import TYPE_CHECKING, Any, Callable, ClassVar, Iterable, LiteralString, Optional, Sequence, Tuple, TypeVar, Union  # noqa: F401, E501

if TYPE_CHECKING:
    from discord.types.embed import Embed as EmbedData, EmbedType  # noqa: F401
    
class NewEmbed(discord.Embed):
    bot_dominant_colour: ClassVar[Optional[Union[int, discord.Colour]]] = None

    # someone fix pls
    def __init__(
        self,
        *,
        colour: Optional[Union[int, discord.Colour]] = None,
        color: Optional[Union[int, discord.Colour]] = None,
        title: Optional[Any] = None,
        type: EmbedType = 'rich',
        url: Optional[Any] = None,
        description: Optional[Any] = None,
        timestamp: Optional[datetime.datetime] = None,
    ):
        if not any((colour, color)):
            self.colour = self.bot_dominant_colour
        else: # db guild config color check
            self.colour = colour if colour is not None else color
        
        super().__init__(
            colour=self.colour,
            title=title,
            type=type,
            url=url,
            description=description,
            timestamp=timestamp,
        )