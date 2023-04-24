from __future__ import annotations
#from typing import TYPE_CHECKING

from discord.ext import commands

from .standard import StandardModeration
from .timeout import Timeout
from .warnings import Warnings

class Moderation(StandardModeration, Timeout, Warnings, name="Moderation"):
    """
    🛡️ Tools for server moderation, as well as various utilities designed specifically for administrators and moderators.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.select_emoji = "🛡️"
        self.select_brief = "Various moderation tools."

    async def cog_check(self, ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage
        return True

async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
