from __future__ import annotations

from discord.ext import commands

from .help import MyHelp
from .weather import Weather
from .user_info import UserInfo

class Information(MyHelp, UserInfo, Weather, name="Information"):
    """
    📚 Includes commands and tools that provide information to users, such as server and user statistics, weather updates, news feeds, and other relevant information.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.select_emoji = "📚"
        self.select_brief = "Commands for providing information and data to users."

async def setup(bot: commands.Bot):
    await bot.add_cog(Information(bot))
