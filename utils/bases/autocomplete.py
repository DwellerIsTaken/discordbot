from __future__ import annotations

from discord.app_commands import Choice
from discord.ext import commands
import discord

from typing import List, Optional

class AutoComplete:

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def choice_autocomplete(self, interaction: discord.Interaction, current: str, table: str, name: str, value: str, all: Optional[bool]) -> List[Choice]:

        records = self.bot.db_data
        table_ = records[table]
        print(table_)

        choices = []
        item = len(current)

        if all is True:
            choices.append(Choice(name = "all", value = True))

        for record in table_:
            name_ = record[name]
            value_ = record[value]
            print(name_, value_)

            if value_ is None:
                if name_ is None:
                    continue

            if current:
                pass

            if current.startswith(str(name_).lower()[:int(item)]):
                choices.append(Choice(name = str(name_), value = int(value_)))
                pass
                
            elif current.startswith(str(value_)[:int(item)]):
                choices.append(Choice(name = str(name_), value = int(value_)))
                pass

        if len(choices) > 5:
            return choices[:5]

        print(choices)
        return choices

