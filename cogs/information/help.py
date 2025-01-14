from __future__ import annotations

import asyncio
import contextlib
import datetime
import difflib
import inspect
import io
import re
import random
import itertools
import os
import time
import traceback
from typing import Any, TypeVar

import discord
import psutil
import pygit2
from discord import Interaction, app_commands
from discord.enums import ButtonStyle
from discord.ext import commands
#from discord.http import Route
from discord.ui import Select, button, select
from typing_extensions import override

import constants as cs
from core import Context, Dwello, Embed
from utils import DefaultPaginator, Idea, Guild, create_codeblock, resize_from_url

from .news import NewsViewer

SVT = TypeVar("SVT", bound="SourceView")
IPT = TypeVar("IPT", bound="IdeaPaginator")

newline = "\n"


async def setup(bot: Dwello) -> None:
    await bot.add_cog(About(bot))


def average_execution_time(command: commands.Command) -> float:
    """To get the average execution time of any command."""
    # implement into help command for individual commands (thus not groups)
    # for groups you could have like average time by combining average times of all
    # commands within that groups and getting their average
    return round(sum(num for num in command.extras["execution_times"]) / len(command.extras["execution_times"]), 3)

class HelpCentre(discord.ui.View):
    def __init__(
        self,
        ctx: Context,
        other_view: discord.ui.View,
    ) -> None:
        super().__init__()
        self.embed = None
        self.ctx = ctx
        self.bot: Dwello = self.ctx.bot
        self.other_view = other_view

    @discord.ui.button(emoji="\N{HOUSE BUILDING}", label="Go Back", style=discord.ButtonStyle.blurple)
    async def go_back(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(embed=self.embed, view=self.other_view)
        self.stop()

    async def start(self, interaction: discord.Interaction):
        embed = Embed(
            title="Here is a guide on how to understand this help command",
            description="\n__**Do not not include these brackets when running a command!**__"
            "\n__**They are only there to indicate the argument type**__",
        )
        embed.add_field(
            name="`<argument>`",
            value="Means that this argument is __**required**__",
            inline=False,
        )
        embed.add_field(
            name="`[argument]`",
            value="Means that this argument is __**optional**__",
            inline=False,
        )
        embed.add_field(
            name="`[argument='default']`",
            value="Means that this argument is __**optional**__ and has a default value",
            inline=False,
        )
        embed.add_field(
            name="`[argument]...` or `[argument...]`",
            value="Means that this argument is __**optional**__ and can take __**multiple entries**__",
            inline=False,
        )
        embed.add_field(
            name="`<argument>...` or `<argument...>`",
            value="Means that this argument is __**required**__ and can take __**multiple entries**__",
            inline=False,
        )
        embed.add_field(
            name="`[X|Y|Z]`",
            value="Means that this argument can be __**either X, Y or Z**__",
            inline=False,
        )
        embed.set_footer(text="To continue browsing the help menu, press \N{HOUSE BUILDING}Go Back")
        embed.set_author(name="About this Help Command", icon_url=self.bot.user.display_avatar.url)
        self.embed = interaction.message.embeds[0]
        self.add_item(discord.ui.Button(label="Support Server", url="https://discord.gg/8FKNF8pC9u"))
        """self.add_item(
            discord.ui.Button(
                label="Invite Me",
                url=discord.utils.oauth_url(
                    self.bot.user.id,
                    permissions=discord.Permissions(294171045078),
                    scopes=("applications.commands", "bot"),
                ),
            )
        )"""  # Later
        await interaction.response.edit_message(embed=embed, view=self)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user and interaction.user == self.ctx.author:
            return True
        await interaction.response.defer()
        return False


class HelpView(discord.ui.View):
    def __init__(
        self,
        ctx: Context,
        data: dict[commands.Cog, list[commands.Command | discord.app_commands.Command]],
        help_command: commands.HelpCommand,
    ) -> None:
        super().__init__()
        self.ctx = ctx
        self.bot: Dwello = self.ctx.bot
        self.data = data
        self.current_page = 0
        self.help_command = help_command
        self.message: discord.Message | None = None
        self.main_embed = self.build_main_page()
        self.embeds: list[Embed] = [self.main_embed]
        self.owner_cmds: list[commands.Command] = self.construct_owner_commands()

    @select(placeholder="Select a category", row=0)
    async def category_select(self, interaction: Interaction, select: Select):
        if select.values[0] == "index":
            self.current_page = 0
            self.embeds = [self.main_embed]
            self._update_buttons()
            return await interaction.response.edit_message(embed=self.main_embed, view=self)

        if cog := self.bot.get_cog(select.values[0]):
            self.embeds = self.build_embeds(cog)
            self.current_page = 0
            self._update_buttons()
            return await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)
        else:
            return await interaction.response.send_message(
                "Somehow, that category was not found? \N{THINKING FACE}", ephemeral=True
            )

    def construct_owner_commands(self) -> list[commands.Command]:
        owner_cmds: list[commands.Command] = []
        hidden_cmds: list[commands.Command] = []

        for cog, comm in self.data.items():
            for cmd in comm:
                if cog.qualified_name == "Owner":
                    owner_cmds.append(cmd)
                else:
                    if isinstance(cmd, app_commands.Command):
                        continue
                    if cmd.hidden:
                        hidden_cmds.append(cmd)

        return owner_cmds + hidden_cmds

    def clean_command_count(self, cog: commands.Cog, commands: list[commands.Command | app_commands.Command]) -> int:
        if cog.qualified_name == "Owner":
            return len(self.owner_cmds)

        count = 0
        for command in commands:
            if isinstance(command, app_commands.Command):
                count += 1
                continue
            if not command.hidden:
                count += 1

        return count

    def build_embeds(self, cog: commands.Cog) -> list[Embed]:
        embeds = []

        for cog_, comm in self.data.items():
            if cog_ != cog:
                continue

            owner = False
            if cog_.qualified_name == "Owner":
                comm = self.owner_cmds
                owner = True

            description_clean: str = (
                " ".join(cog.description.splitlines()) if cog.description else "No description provided."
            )  # noqa: E501
            embed: Embed = Embed(
                title=f"{cog.qualified_name} commands [{self.clean_command_count(cog_, comm)}]",
                description=description_clean,
            )
            embed.set_footer(text="For more info on a command run `dw.help [command]`")
            # maybe another embed build for slash cause cant use that with owner cmds
            for cmd in comm:
                name = f"`{cmd.name}`"
                value = "See help for this command in an NSFW channel." if cmd.extras.get("nsfw", False) else None
                if isinstance(cmd, app_commands.Command):
                    if not value:
                        desc = cmd.description or cmd.description or "No help given..."
                else:
                    if cmd.hidden and not owner:
                        continue
                    if not value:
                        name = f"`{cmd.name}{f' {cmd.signature}`' if cmd.signature else '`'}"
                        desc = cmd.short_doc or cmd.description or "No help given..."
                if not value:
                    parent = f"\n> Parent: `{cmd.parent}`" if cmd.parent else ""
                    value = (f"> {desc} {parent}")[:1024]

                embed.add_field(name=name, value=value, inline=False)

                if len(embed.fields) == 5:
                    embeds.append(embed)
                    embed = Embed(
                        title=f"{cog.qualified_name} commands [{len(comm)}]",
                        description=description_clean,
                    )

            if len(embed.fields) > 0:
                embeds.append(embed)

            return embeds
        return embeds

    def build_select(self) -> None:
        self.category_select.options = []
        self.category_select.add_option(label="Main Page", value="index", emoji="\N{HOUSE BUILDING}")
        for cog, comm in self.data.items():
            if cog.qualified_name == "Owner":
                comm = self.owner_cmds
            if not comm:
                continue
            emoji = getattr(cog, "select_emoji", None)
            label = f"{cog.qualified_name} ({self.clean_command_count(cog, comm)})"
            brief = getattr(cog, "select_brief", None)
            self.category_select.add_option(label=label, value=cog.qualified_name, emoji=emoji, description=brief)

    def build_main_page(self) -> Embed:
        embed: Embed = Embed(
            title="Dwello Help Menu",
            description=(
                "Hello, I'm Dwello! I'm still in development, but you can use me.\n" "My prefixes are: `dw.`, `dwello.`."
            ),
        )
        embed.add_field(
            name="Getting Help",
            inline=False,
            value="Use `dw.help <command>` for more info on a command."
            "\nThere is also `dw.help <command> [subcommand]`."
            "\nUse `dw.help <category>` for more info on a category."
            "\nYou can also use the menu below to view a category.",
        )
        embed.add_field(
            name="Getting Support",
            inline=False,
            value="To get help or __**suggest features**__, you can join my"
            "\nsupport server: **__<https://discord.gg/8FKNF8pC9u>__**"
            "\n\N{INCOMING ENVELOPE} You can also DM me for help if you prefer to,"
            "\nbut please join the support server for suggestions.",
        )
        embed.add_field(
            name="Who Am I?",
            inline=False,
            value="I'm Dwello, a multipurpose discordbot. You can use me to play games, moderate "
            "\nyour server, mess with some images and more!"
            "\nCheck out all my features using the dropdown below.",
        )
        embed.add_field(
            name="Support Dwello",
            value="Add patreon later.",
            inline=False,
        )
        embed.add_field(
            name="\t",
            value="Invaluable assistance: <:github:1100906448030011503> [LeoCx1000](https://github.com/leoCx1000).",
            inline=False,
        )
        embed.set_author(name=self.bot.user.name, icon_url=self.bot.user.display_avatar.url)
        return embed

    @button(emoji="\N{BLACK QUESTION MARK ORNAMENT}", label="help", row=1, style=discord.ButtonStyle.green)
    async def help(self, interaction: Interaction, _):
        view = HelpCentre(self.ctx, self)
        await view.start(interaction)  # make better buttons later

    @button(label="<", row=1)
    async def previous(self, interaction: Interaction, _):
        self.current_page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @button(emoji="🗑", row=1, style=discord.ButtonStyle.red)
    async def _end(self, interaction: Interaction, _):
        if interaction.message:
            await interaction.message.delete(delay=0)
        """if self.ctx.channel.permissions_for(self.ctx.me).add_reactions:
            await self.ctx.message.add_reaction(random.choice(constants.DONE))"""

    @button(label=">", row=1)  # emoji
    async def next(self, interaction: Interaction, _):
        self.current_page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(emoji="\N{NEWSPAPER}", label="news", row=1, style=discord.ButtonStyle.green)
    async def vote(self, interaction: Interaction, _):
        news = await self.bot.pool.fetch("SELECT * FROM news ORDER BY news_id DESC")
        await NewsViewer.from_interaction(interaction, news, embed=self.embeds[self.current_page], old_view=self)

    def _update_buttons(self) -> None:
        styles = {True: discord.ButtonStyle.gray, False: discord.ButtonStyle.blurple}
        page = self.current_page
        total = len(self.embeds) - 1
        self.next.disabled = page == total
        self.previous.disabled = page == 0
        self.next.style = styles[page == total]
        self.previous.style = styles[page == 0]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user == self.ctx.author:
            return True
        await interaction.response.defer()
        return False

    async def on_timeout(self) -> None:
        self.clear_items()
        with contextlib.suppress(discord.errors.NotFound):
            await self.message.edit(view=self)

    async def start(self) -> discord.Message | None:
        self.build_select()
        self._update_buttons()
        self.message = await self.ctx.send(embed=self.main_embed, view=self)


class MyHelp(commands.HelpCommand):
    def __init__(self, **options) -> None:
        super().__init__(**options)
        self.context: Context

    @override
    def get_bot_mapping(self):
        """Retrieves the bot mapping passed to :meth:`send_bot_help`."""
        bot = self.context.bot
        ignored_cogs = [
            "CommandErrorHandler",
            "Other",
            "Jishaku",
        ]
        if not self.context.is_bot_owner:
            ignored_cogs.append("Owner")

        mapping = {}

        for cog in sorted(bot.cogs.values(), key=lambda c: len(c.get_commands()), reverse=True):
            if cog.qualified_name in ignored_cogs:
                continue

            commands_list: list[commands.Command | discord.app_commands.Command] = []
            for command in cog.walk_commands():
                if isinstance(command, commands.Group):
                    subcommands = command.commands
                    while (
                        isinstance(subcommands, list)
                        and len(subcommands) == 1
                        and isinstance(subcommands[0], commands.Group)
                    ):
                        subcommands = subcommands[0].commands

                    if isinstance(subcommands, list):
                        commands_list.extend(subcommands)
                    elif isinstance(subcommands, commands.Command):
                        commands_list.append(subcommands)
                else:
                    commands_list.append(command)

            for app_command in cog.walk_app_commands():
                allowed = 1
                for i in commands_list:
                    if app_command.name == i.name and not isinstance(i, commands.Group):
                        allowed = 0
                if allowed:
                    commands_list.append(app_command)

            mapping[cog] = commands_list

        return mapping

    def get_minimal_command_signature(self, command):
        if isinstance(command, commands.Group):
            return f"[G] {self.context.clean_prefix}{command.qualified_name} {command.signature}"
        return f"(c) {self.context.clean_prefix}{command.qualified_name} {command.signature}"

    async def send_bot_help(self, mapping):
        view = HelpView(self.context, data=mapping, help_command=self)
        await view.start()

    async def send_command_help(self, command: commands.Command):
        desc = " ".join((command.short_doc or command.description or "No help given...").splitlines())
        embed = Embed(
            title=f"`{self.context.clean_prefix}{command}`",
            description="**Description:**\n" + desc.replace("%PRE%", self.context.clean_prefix),
        )
        # command.help basically default to docstring if its empty, so might aswell keep it that way
        # or could get help string from the cmd dict instead and set it in bot.py
        # instead of writing the docstrings
        # endgoal is the same so idk
        embed.add_field(
            name="Command usage:",
            value=f"```css\n{self.get_minimal_command_signature(command)}\n```",
            inline=False,
        )
        embed.add_field(
            name="Average execution time:",
            value=f"```css\n{average_execution_time(command)}ms\n```",
            inline=False,
        )
        embed.add_field(
            name="Times executed:",
            value=f"```css\n{command.extras['times_executed']}\n```",
            inline=False,
        )
        with contextlib.suppress(KeyError): # any guild-related exceptions (orm i mean)
            if (await Guild.get(self.context.guild.id, self.context.bot)).cmd_preview:
                preview = None # maybe store extention in a dict too
                if (_url:= command.extras["preview"]): # add previews to most commands ig
                    async with self.context.bot.reaction_typing(self.context.message):
                        extension = re.search(r'\.([^.?/]+)(?:\?|$)', _url) # takes too long | find the fastest way or make a customisation option   # noqa: E501
                        preview = await asyncio.to_thread(resize_from_url, _url, (700, 350), extension.group(0))
                        embed.set_image(url=f"attachment://{preview.filename}")
        if command.aliases:
            embed.description = f'{embed.description}\n\n**Aliases:**\n`{"`, `".join(command.aliases)}`'
        try:
            await command.can_run(self.context)
        except BaseException as e:
            try:
                if isinstance(e, commands.CheckAnyFailure):
                    for e in e.errors:
                        if not isinstance(e, commands.NotOwner):
                            raise e
                raise e
            except commands.MissingPermissions as error:
                embed.add_field(
                    name="Permissions you're missing:",
                    value=", ".join(error.missing_permissions).replace("_", " ").replace("guild", "server").title(),
                    inline=False,
                )
            except commands.BotMissingPermissions as error:
                embed.add_field(
                    name="Permissions i'm missing:",
                    value=", ".join(error.missing_permissions).replace("_", " ").replace("guild", "server").title(),
                    inline=False,
                )
            except commands.NotOwner:
                embed.add_field(name="Rank you are missing:", value="Bot owner", inline=False)
            except commands.PrivateMessageOnly:
                embed.add_field(
                    name="Cant execute this here:",
                    value="Can only be executed in DMs.",
                    inline=False,
                )
            except commands.NoPrivateMessage:
                embed.add_field(
                    name="Cant execute this here:",
                    value="Can only be executed in a server.",
                    inline=False,
                )
            except commands.DisabledCommand:
                embed.add_field(
                    name="Cant execute this command:",
                    value="This command is currently disabled.",
                    inline=False,
                )
            except commands.NSFWChannelRequired:
                embed.add_field(
                    name="Cant execute this here:",
                    value="This command can only be used in an NSFW channel.",
                    inline=False,
                )
            except Exception as exc:
                embed.add_field(
                    name="Cant execute this command:",
                    value="Unknown/unhandled reason.",
                    inline=False,
                )
                print(f"{command} failed to execute: {exc}")
        finally:
            await self.context.send(file=preview, embed=embed)

    async def send_cog_help(self, cog: commands.Cog):
        if entries := cog.get_commands():
            data = [self.get_minimal_command_signature(entry) for entry in entries]
            description_clean: str = (
                " ".join(cog.description.splitlines()) if cog.description else "No description provided."
            )  # noqa: E501
            embed = Embed(
                title=f"`{cog.qualified_name}` category commands",
                description="**Description:**\n" + description_clean.replace("%PRE%", self.context.clean_prefix),
            )
            embed.description = (
                f"{embed.description}\n\n**Commands:**\n```css\n{newline.join(data)}\n```\n"
                f"`[G] - Group` These have sub-commands.\n`(C) - Command` These do not have sub-commands."
            )
            await self.context.send(embed=embed)
        else:
            await self.context.send(f"No commands found in {cog.qualified_name}")

    async def send_group_help(self, group: commands.Group):
        embed = Embed(
            title=f"`{self.context.clean_prefix}{group}`",
            description="**Description:**\n"
            + (group.short_doc or group.description or "No help given...").replace("%PRE%", self.context.clean_prefix),
        )
        embed.add_field(
            name="Group usage:",
            value=f"```css\n{self.get_minimal_command_signature(group)}\n```",
        )
        if group.aliases:
            embed.description = f'{embed.description}\n\n**Aliases:**\n`{"`, `".join(group.aliases)}`'
        if group.commands:
            subgroups: list[commands.Group] = []
            subcommands: list[commands.Command] = []
            for c in group.commands:
                if isinstance(c, commands.Group):
                    subgroups.append(c)
                else:
                    subcommands.append(c)

            if subcommands:
                c_formatted = "\n".join([self.get_minimal_command_signature(command) for command in subcommands])
                embed.add_field(
                    name="Sub-commands for this command:",
                    value=f"```css\n{c_formatted}\n```",
                    inline=False,
                )
            if subgroups:
                g_formatted = "\n".join([self.get_minimal_command_signature(group) for group in subgroups])
                embed.add_field(
                    name="Sub-groups for this command:",
                    value=f"```css\n{g_formatted}\n```\n**Do `{self.context.clean_prefix}help command subcommand` for more info on a sub-command**",  # noqa: E501
                    inline=False,
                )
        # noinspection PyBroadException
        try:
            await group.can_run(self.context)
        except commands.MissingPermissions as error:
            embed.add_field(
                name="Permissions you're missing:",
                value=", ".join(error.missing_permissions).replace("_", " ").replace("guild", "server").title(),
                inline=False,
            )
        except commands.BotMissingPermissions as error:
            embed.add_field(
                name="Permissions i'm missing:",
                value=", ".join(error.missing_permissions).replace("_", " ").replace("guild", "server").title(),
                inline=False,
            )

        except commands.NotOwner:
            embed.add_field(name="Rank you are missing:", value="Bot owner", inline=False)
        except commands.PrivateMessageOnly:
            embed.add_field(
                name="Cant execute this here:",
                value="Can only be executed in DMs.",
                inline=False,
            )
        except commands.NoPrivateMessage:
            embed.add_field(
                name="Cant execute this here:",
                value="Can only be executed in a server.",
                inline=False,
            )
        except commands.DisabledCommand:
            embed.add_field(
                name="Cant execute this command:",
                value="This command is restricted to slash commands.",
                inline=False,
            )
        except Exception as exc:
            embed.add_field(name="Cant execute this command:", value="Unknown error.", inline=False)
            print(f"{group} failed to execute: {exc}")
        finally:
            await self.context.send(embed=embed)

    @override
    def command_not_found(self, string):
        return string

    @override
    def subcommand_not_found(self, command, string):
        if isinstance(command, commands.Group) and len(command.all_commands) > 0:
            return command.qualified_name + string
        return command.qualified_name

    @override
    async def send_error_message(self, error):
        if matches := difflib.get_close_matches(error, self.context.bot.cogs.keys()):
            confirm = await self.context.confirm(  # look into this
                message=f"Sorry but i couldn't recognise {error} as one of my categories!"
                f"\n{f'**did you mean... `{matches[0]}`?**' if matches else ''}",
                delete_after_confirm=True,
                delete_after_timeout=True,
                delete_after_cancel=True,
                buttons=(
                    ("\N{WHITE HEAVY CHECK MARK}", f"See {matches[0]}"[:80], discord.ButtonStyle.blurple),
                    ("🗑", None, discord.ButtonStyle.red),
                ),
                timeout=15,
            )
            if confirm is True:
                return await self.send_cog_help(self.context.bot.cogs[matches[0]])
            return
        else:
            command_names = []
            for command in list(self.context.bot.commands):
                # noinspection PyBroadException
                try:
                    if await command.can_run(self.context):
                        command_names.append([command.name] + command.aliases)
                except Exception:
                    continue
            command_names = list(itertools.chain.from_iterable(command_names))
            if matches := difflib.get_close_matches(error, command_names):
                confirm = await self.context.confirm(
                    message=f"Sorry but i couldn't recognise {error} as one of my commands!"
                    f"\n{f'**did you mean... `{matches[0]}`?**' if matches else ''}",
                    delete_after_confirm=True,
                    delete_after_timeout=True,
                    delete_after_cancel=True,
                    buttons=(
                        (
                            "\N{WHITE HEAVY CHECK MARK}",
                            f"See {matches[0]}"[:80],
                            discord.ButtonStyle.blurple,
                        ),
                        ("🗑", None, discord.ButtonStyle.red),
                    ),
                    timeout=15,
                )
                if confirm is True:
                    return await self.send_command_help(self.context.bot.get_command(matches[0]))
                return

        await self.context.send(
            f'Sorry but i couldn\'t recognise "{discord.utils.remove_markdown(error)}" as one of my commands or categories!'
            f"\nDo `{self.context.clean_prefix}help` for a list of available commands! 💞"
        )

    @override
    async def on_help_command_error(self, ctx, error):
        if isinstance(error, commands.CommandInvokeError):
            await ctx.send(
                embed=Embed(
                    title=str(error.original),
                    description="".join(traceback.format_exception(error.__class__, error, error.__traceback__)),
                )
            )


class About(commands.Cog):
    """
    😮
    Commands related to the bot itself, that have the only purpose to show information.
    """

    def __init__(self, bot: Dwello) -> None:
        self.bot: Dwello = bot
        help_command = MyHelp()
        help_command.command_attrs = {
            "help": "Shows help about a command or category, it can also display other useful information, such as "
            "examples on how to use the command, or special syntax that can be used for a command, for example, "
            "in the `welcome message` command, it shows all available special tags. So, if you have a trouble "
            "with a command you can just type it's full name when using a help command, or a name of the group, "
            "the command is bound to, to get a general idea about it's usage.",
            "name": "help",
        }
        help_command.cog = self
        bot.help_command = help_command
        self.select_emoji = "<:info:895407958035431434>"
        self.select_brief = "Bot Information commands."

        self.process = psutil.Process()
        self.repo = pygit2.Repository(".git")

    def get_uptime(self, /, complete=False) -> tuple[int, int, int, int] | str:
        """Return format: days, hours, minutes, seconds or full str."""

        uptime = datetime.datetime.now(datetime.timezone.utc) - self.bot.uptime

        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)

        if complete:
            return f"{days}d, {hours}h, {minutes}m, {seconds}s"
        return days, hours, minutes, seconds

    """def get_bot_uptime(self, *, brief: bool = False) -> str: Use Danny's code instead?
        return time.human_timedelta(self.bot.uptime, accuracy=None, brief=brief, suffix=False)"""

    def get_startup_timestamp(self, style: discord.utils.TimestampStyle = None) -> str:
        return discord.utils.format_dt(self.bot.uptime, style=style or "F")

    def get_average_latency(self, *latencies: float) -> Any | float:
        if not latencies:
            raise TypeError("Missing required argument: 'latencies'")

        pings = list(latencies)
        number = sum(pings)
        return number / len(pings)

    def format_commit(self, commit: pygit2.Commit) -> str:
        short, _, _ = commit.message.partition("\n")
        short_sha2 = commit.hex[0:6]
        commit_tz = datetime.timezone(datetime.timedelta(minutes=commit.commit_time_offset))
        commit_time = datetime.datetime.fromtimestamp(commit.commit_time).astimezone(commit_tz)

        # [`hash`](url) message (offset)
        # offset = time.format_relative(commit_time.astimezone(datetime.timezone.utc))
        ml = 35
        return (
            f"[`{short_sha2}`]({cs.GITHUB}commit/{commit.hex}) {short[:ml]}{'...' if len(short) > ml else ''} "
            f"({discord.utils.format_dt(commit_time, 'R')})"
        )

    def get_last_commits(self, count=3):
        commits = list(itertools.islice(self.repo.walk(self.repo.head.target, pygit2.GIT_SORT_TOPOLOGICAL), count))
        return "\n".join(self.format_commit(c) for c in commits)

    """@commands.command(name="test")
    async def bla(self, ctx: Context) -> discord.Message | None:
        return await ctx.send("bleh")"""

    # make uptime: add here -> trigger on mention in on_message
    @commands.hybrid_command(name="hello", aliases=cs.HELLO_ALIASES, with_app_command=True)
    async def hello(self, ctx: Context) -> discord.Message | None:
        """Hello there!"""

        return await ctx.send(
            content=random.choice(cs.HELLO_RESPONSES).format(
                name=self.bot.user.name, prefix=f"`{self.bot.DEFAULT_PREFIXES[0]}`",
            ),
        ) # display more info about bot

    @commands.hybrid_command(name="about", aliases=["botinfo", "info", "bi"], with_app_command=True)
    async def about(self, ctx: Context) -> discord.Message | None:
        """Some info about me and the creators!"""

        # information: discord.AppInfo = await self.bot.application_info()
        author: discord.User = self.bot.get_user(548846436570234880)

        main_desc: str = (
            f"Hello there. My name is {self.bot.user.name} and I was created by **{author.name}** "
            f"at {discord.utils.format_dt(self.bot.user.created_at, style='D')}.\n\n"
            "I posses a big variety of prefix/slash commands for people's entertainment. "
            "My purpose is to be fun to interact with and be helpful at times.\n\n"
            "I always wanted this to be a *community* bot, so you're free to join our contributor team anytime. "
            "Just go to source below and fork our repo using GitHub! We would greatly appreciate it.\n\n"
        )

        links: str = (
            f"> {cs.GITHUB_EMOJI} [Source]({self.bot.repo})\n" f"> {cs.EARLY_DEV_EMOJI} [Website]({cs.WEBSITE})\n" "\n"
        )

        commit_counts: dict[str, int] = {}
        commit_signatures: dict[str, pygit2.Signature] = {}
        for commit in self.repo.walk(self.repo.head.target):
            signature = commit.author
            author_ = signature.name
            if author_ not in commit_counts:
                commit_counts[author_] = 0
            commit_signatures[author_] = signature
            commit_counts[author_] += 1

        embed: Embed = Embed(
            title="About Me",
            description=main_desc + links,
            url=cs.WEBSITE,  # link to about page ?
            color=self.bot.color,
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        # embed.set_footer(text=f"ID: {self.bot.user.id}")
        embed.set_author(
            name=author.name,
            icon_url=author.display_avatar.url,
            url="https://github.com/DwellerIsTaken/",
        )

        og_commiters = sorted(commit_signatures.values(), key=lambda x: x.time)[:3]
        embed.add_field(
            name="First Contributors",
            value="\n".join(
                f"• [{author.name}](https://github.com/{author.name}): <t:{int(author.time)}:D>" for author in og_commiters
            ),  # noqa: E501
        )

        top_commiters = sorted(commit_counts.items(), key=lambda x: x[1], reverse=True)[:3]  # noqa: E501
        embed.add_field(
            name="Top Contributors",
            value="\n".join(
                f"• [{author}](https://github.com/{author}): {count}" for author, count in top_commiters
            ),  # noqa: E501
        )
        embed.timestamp = discord.utils.utcnow()
        # f"{constants.INVITE} [invite me]({self.bot.invite_url}) | "
        # f"{constants.TOP_GG} [top.gg]({self.bot.vote_top_gg}) | "
        # f"{constants.BOTS_GG} [bots.gg]({self.bot.vote_bots_gg})"

        return await ctx.send(embed=embed)

    async def _suggest_idea(self, ctx: Context, title: str, content: str) -> discord.Message | None:
        idea = await self.bot.db.suggest_idea(title, content, ctx.author)
        # also somehow check if the ideas are similair

        return await ctx.reply(
            embed=Embed(
                title="Successfully suggested", description=(f"Title: {idea.title}\n" f"Description: {idea.content}")
            ).set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
        )

    async def _ideas_show(self, ctx: Context) -> DefaultPaginator | discord.Message:
        if not (ideas := await self.bot.db.get_ideas()):
            return await ctx.reply(embed=Embed(description="No ideas yet."))
        return await IdeaPaginator.start(ctx, ideas)

    @commands.hybrid_command(
        name="ideas",
        brief="Shows the list of suggested ideas.",
        description="Shows the list of suggested ideas.",
    )
    async def ideas(self, ctx: Context) -> discord.Message | None:
        """Should show some of the newest ideas people suggested."""
        return await self._ideas_show(ctx)

    # somehow check if ideas is bullshit or not
    # maybe ai or smh
    # or a dict of 'bad' words instead
    @commands.hybrid_command(
        name="suggest",
        brief="Suggest an idea for bot improvement.",
        description="Suggest an idea for bot improvement.",
    )  # call a modal here
    async def suggest(self, ctx: Context, title: str, *, content: str) -> discord.Message | None:
        """Suggest an idea, so we can improve our bot!"""
        return await self._suggest_idea(ctx, title, content)

    @commands.hybrid_group(name="idea", invoke_without_command=True, with_app_command=True)
    async def idea(self, ctx: Context):
        """Idea command group that contains some commands for suggesting and displaying suggested ideas."""
        return await ctx.send_help(ctx.command)

    @idea.command(
        name="suggest",
        brief="Suggest an idea for bot improvement.",
        description="Suggest an idea for bot improvement.",
    )
    async def hybrid_suggest(self, ctx: Context, title: str, *, content: str) -> discord.Message | None:
        """Suggest an idea, so we can improve our bot!"""
        return await self._suggest_idea(ctx, title, content)

    @idea.command(
        name="show", aliases=["display"],
        brief="Shows the list of suggested ideas.",
        description="Shows the list of suggested ideas.",
    )
    async def hybrid_show_idea(self, ctx: Context) -> discord.Message | None:
        """Should show some of the newest ideas people suggested."""
        return await self._ideas_show(ctx)

    @commands.hybrid_command(name="uptime", help="Returns bot's uptime.", with_app_command=True)
    async def uptime(self, ctx: Context) -> discord.Message | None:
        """Returns bot's uptime."""

        timestamp = self.get_startup_timestamp()

        embed: Embed = Embed(
            title="Current Uptime",
            description=f"**{self.get_uptime(complete=True)}**",
        )

        embed.add_field(name="Startup Time", value=timestamp, inline=False)
        return await ctx.reply(embed=embed)
    
    @commands.hybrid_command(name="invite", help="Please invite me.", with_app_command=True)
    async def invite(self, ctx: Context) -> discord.Message | None:
        """Invite me PLEASE!"""
        return await ctx.reply(f"[invite me](<{cs.INVITE_LINK}>)")

    @commands.hybrid_command(name="contribute", help="Please do.", with_app_command=True)
    async def contribute(self, ctx: Context) -> discord.Message | None:
        """And contribute... begging you."""
        return await ctx.reply(f"{cs.GITHUB_EMOJI} {cs.GITHUB}\nJoin my [guild](<{cs.DISCORD}>) for more.")

    @commands.hybrid_command(
        name="ping",
        brief="Pong.",
        description="Pong.",
        aliases=["latency", "latencies"],
    )
    async def ping(self, ctx: Context) -> discord.Message | None:  # work on return design?
        """Returns some boring-ass latencies."""

        typing_start = time.monotonic()
        await ctx.typing()
        typing_end = time.monotonic()
        typing_ms = (typing_end - typing_start) * 1000

        start = time.perf_counter()
        message = await ctx.send("\N{TABLE TENNIS PADDLE AND BALL} pong!")
        end = time.perf_counter()
        message_ms = (end - start) * 1000

        latency_ms = self.bot.latency * 1000

        postgres_start = time.perf_counter()
        await self.bot.pool.fetch("SELECT 1")
        postgres_end = time.perf_counter()
        postgres_ms = (postgres_end - postgres_start) * 1000

        average = self.get_average_latency(typing_ms, message_ms, latency_ms, postgres_ms)

        await asyncio.sleep(0.7)

        return await message.edit(
            content=None,
            embed=Embed(
                description=(
                    f"**`Websocket -> {round(latency_ms, 3)}ms{' ' * (9 - len(str(round(latency_ms, 3))))}`**\n"
                    f"**`Typing    -> {round(typing_ms, 3)}ms{' ' * (9 - len(str(round(typing_ms, 3))))}`**\n"
                    f"**`Message   -> {round(message_ms, 3)}ms{' ' * (9 - len(str(round(message_ms, 3))))}`**\n"
                    f"**`Database  -> {round(postgres_ms, 3)}ms{' ' * (9 - len(str(round(postgres_ms, 3))))}`**\n"
                    f"**`Average   -> {round(average, 3)}ms{' ' * (9 - len(str(round(average, 3))))}`**\n"
                ),
            ),
        )

    @commands.hybrid_command(
        name="stats",
        brief="Returns some of the bot's stats",
        description="Returns some of the bot's stats",
    )
    async def stats(self, ctx: Context) -> discord.Message | None:
        """Some statistics depicting what I've done."""

        typing_start = time.monotonic()
        await ctx.typing()
        typing_end = time.monotonic()
        typing_ms = (typing_end - typing_start) * 1000

        latency_ms = self.bot.latency * 1000

        postgres_start = time.perf_counter()
        await self.bot.pool.fetch("SELECT 1")
        postgres_end = time.perf_counter()
        postgres_ms = (postgres_end - postgres_start) * 1000
        # maybe just return average instead, thus use some other func

        author: discord.User = self.bot.get_user(548846436570234880)

        total_members = sum(len(guild.members) for guild in self.bot.guilds if not guild.unavailable)
        links = f"-> {cs.GITHUB_EMOJI} [Source]({self.bot.repo})\n" f"-> {cs.EARLY_DEV_EMOJI} [Website]({cs.WEBSITE})\n" "\n"
        revision = self.get_last_commits()
        embed: Embed = (
            Embed(
                title=f"{self.bot.user.name} Statistics",
                description=links + "**Latest Changes:**\n" + revision,
                timestamp=discord.utils.utcnow(),
                url=cs.INVITE_LINK,
            )
            .set_thumbnail(url=self.bot.user.display_avatar.url)
            .set_footer(text=f"{self.bot.main_prefix}about for more")
            .set_author(
                name=author.name,
                icon_url=author.display_avatar.url,
                url="https://github.com/DwellerIsTaken/",
            )
            .add_field(name="Members", value=f"{total_members} total\n{len(self.bot.users)} unique")
            .add_field(name="Guilds", value=len(self.bot.guilds))
            .add_field(
                name="Process",
                value=(
                    f"{self.process.memory_full_info().uss / 1024**2:.2f} MiB"
                    f"\n{self.process.cpu_percent() / psutil.cpu_count():.2f}% CPU"
                ),
            )
            .add_field(name="Responses", value=self.bot.reply_count or 1)
            .add_field(name="Lines", value=self.bot.total_lines)
            .add_field(name="Latency", value=f"{round(self.get_average_latency(typing_ms, latency_ms, postgres_ms), 3)}ms")
            .add_field(name="Average cmd latency", value=f"{round(self.bot.average_command_execution_time, 3)}ms")
            .add_field(name="Uptime", value=self.get_uptime(complete=True))
        )
        # embed.add_field(name='Total Commands', value=len(self.bot.commands)) ?
        return await ctx.reply(embed=embed)
    
    @commands.command(name="git", brief="Returns repository.")
    async def git(self, ctx: Context) -> discord.Message | None:
        """Bot's GitHub repository."""
        return await ctx.send(cs.GITHUB)

    @commands.hybrid_command(
        name="source",
        aliases=["src"],
        brief="Returns command's source.",
        description="Returns command's source.",
    )
    async def source(self, ctx: Context, *, command_name: str | None) -> discord.Message | SourceView | None:
        """
        Provides the option to retrieve either the complete repository link or
        a targeted link directing to a specific command or cog.
        It also offers the ability to showcase code in either an embed or file format.
        """

        git = cs.GITHUB
        if not command_name:
            return await ctx.reply(git)

        bot_name: str = self.bot.user.name.lower()
        bot_guild_name: str = self.bot.user.display_name.lower()
        _bot_name: list[str] = bot_name.split()

        _base_words: list[str] = [
            "base",
            "bot",
            bot_name,
            _bot_name[0],
            f"{bot_name} base",
            f"{_bot_name[0]} base",
        ]
        _matches: list[str] = _base_words.copy()
        _command_name: str = command_name.lower()

        if bot_guild_name != bot_name:
            _matches.append(bot_guild_name)
            _bot_guild_name: list[str] = bot_guild_name.split()
            if _bot_guild_name[0] != _bot_name[0]:
                _matches.append(_bot_guild_name[0])

        _matches.extend(command.qualified_name.lower() for command in self.bot.walk_commands())
        _matches.extend(cog.qualified_name.lower() for cog in self.bot.cogs.values() if cog.qualified_name != "Jishaku")
        # ADD A CHECK FOR BOT.PY TO DISPLAY WHOLE FILE

        if _command_name == "help":
            target = type(self.bot.help_command)

        elif _command_name in {"context", "ctx"}:
            target = ctx.__class__

        elif _command_name in _base_words:
            target = self.bot.__class__.__base__

        else:
            command = self.bot.get_command(command_name)
            cog = self.bot.get_cog(command_name)

            if not command and not cog:
                matches = difflib.get_close_matches(command_name, _matches, 5)
                if not matches:
                    return await ctx.reply("That command doesn't exist!")

                description = "Perhaps you meant one of these:"
                for match in matches:
                    description += f"\n• `{match}`"

                embed: Embed = Embed(
                    title=f"Doesn't seem like command `{command_name}` exists",
                    description=f"\n{description}",
                    color=cs.WARNING_COLOR,
                )
                return await ctx.reply(embed=embed)
            if command:
                target = command.callback
            if cog:
                target = type(cog)

        # source: str = inspect.getsource(target)
        file: str = inspect.getsourcefile(target)
        lines, _ = inspect.getsourcelines(target)
        git_lines = f"#L{_}-L{len(lines)+_}"
        path = os.path.relpath(file)

        source_link = f"> [**Source**]({git}tree/main/{path}{git_lines}) {cs.GITHUB_EMOJI}\n> **{path}{git_lines}**\n"

        embed: Embed = Embed(
            title=f"Source for `{command_name}`",
            description=source_link,
        )

        return await SourceView.start(ctx, embed, lines, filename=f"{command_name}.py")


# I DONT LIKE THIS AT ALL | maybe redo
class IdeaPaginator(DefaultPaginator):
    def __init__(
        self,
        obj: Context | Interaction[Dwello],
        ideas: list[Idea],
        **kwargs,
    ) -> None:
        self.ideas = ideas
        try:
            bot = obj.bot
        except AttributeError:
            bot = obj.client
        self._embeds = self._construct_embeds(bot)  # dont override the parent class' embeds
        super().__init__(obj, self._embeds, values=self.ideas, **kwargs)

        self.voted = [(embed, self.ideas[n].voted(self.author.id)) for n, embed in enumerate(self.embeds)]

        self.upvote = UpvoteIdeaButton(row=1)
        self.add_item(self.upvote)
        self.previous.row = 0
        self.next.row = 2

    def _construct_embeds(self, bot: Dwello) -> list[Embed]:
        embeds: list[Embed] = []
        for idea in self.ideas:
            author: discord.User | None = bot.get_user(idea.author_id)
            embed = Embed(
                title=idea.title,
                description=idea.content,
                timestamp=idea.created_at,
            )
            embed.set_footer(text=f"Votes: {idea.votes}")
            if author:
                embed.set_author(name=author.name, icon_url=author.display_avatar.url)
            embeds.append(embed)
        return embeds

    def _update_buttons(self) -> None:
        styles = {True: ButtonStyle.gray, False: ButtonStyle.blurple}
        page = self.current_page
        total = len(self.embeds) - 1
        self.next.disabled = page == total
        self.previous.disabled = page == 0
        self.next.style = styles[page == total]
        self.previous.style = styles[page == 0]
        self.upvote.disabled = self.voted[page][1]
        if self.upvote.disabled is True:
            self.upvote.label = "Voted"
            self.upvote.style = ButtonStyle.red
        else:
            self.upvote.label = "Upvote"
            self.upvote.style = ButtonStyle.green

    @classmethod
    async def start(
        cls: type[IPT],
        obj: Context | Interaction[Dwello],
        ideas: list[Idea],
        **kwargs,
    ) -> IPT:
        self = cls(obj, ideas, **kwargs)
        return await self._start()


class UpvoteIdeaButton(discord.ui.Button["IdeaPaginator"]):
    def __init__(
        self,
        *,
        style: ButtonStyle | None = ButtonStyle.green,
        label: str | None = "Upvote",
        **kwargs,
    ) -> None:
        super().__init__(style=style, label=label, **kwargs)

    async def callback(self, interaction: Interaction):
        assert self.view is not None
        view: IdeaPaginator = self.view

        page = view.current_page
        embed = view.embeds[page]
        idea: Idea = view.ideas[page]

        await idea.upvote(view.author.id)

        embed.set_footer(text=f"Votes: {idea.votes}")
        view.voted[page] = (embed, True)
        self.disabled = True
        await interaction.response.edit_message(view=view)


class ShowCodeButton(discord.ui.Button["SourceView"]):
    def __init__(
        self,
        *,
        label: str | None = "Code",
        **kwargs,
    ) -> None:
        super().__init__(label=label, **kwargs)

    async def callback(self, interaction: Interaction):
        assert self.view is not None
        view: SourceView = self.view

        embed = view.embed

        if self.label.lower() == "code":
            description = embed.description + f"\n {view.code_snippet}"
            label = "Hide"
        else:
            description = embed.description
            label = "Code"

        split = description.split('```py')
        new_desc = split[0] + "```py" + discord.utils.escape_markdown(split[1][:-3])
        # after markdown the code will be incorrect if it contained the characters
        # the code will be filled with backslashes, but oh well

        embed_ = Embed(
            colour=embed.colour,
            title=embed.title,
            type=embed.type,
            url=embed.url,
            description=new_desc[:4089]+"\n...```" if len(new_desc) > 4089 else new_desc+"```",
            timestamp=embed.timestamp,
        )

        self.label = label
        await interaction.response.edit_message(embed=embed_, view=view)


class ShowFileButton(discord.ui.Button["SourceView"]):
    def __init__(
        self,
        *,
        label: str | None = "File",
        **kwargs,
    ) -> None:
        super().__init__(label=label, **kwargs)

    async def callback(self, interaction: Interaction):
        assert self.view is not None
        view: SourceView = self.view

        att: list[discord.File] = []
        if self.label.lower() == "file":
            view._update_file()
            att = [view.file]
            label = "Hide"
        else:
            label = "File"

        self.label = label
        await interaction.response.edit_message(attachments=att, view=view)


_Context: type[commands.Context] = commands.Context


class SourceView(discord.ui.View): # from our view or just default discord?
    def __init__(
        self,
        obj: Context | Interaction[Dwello],
        embed: Embed,
        source_lines: list[str],
        /,
        filename: str | None = "code.py",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        if any(
            (issubclass(obj.__class__, _Context), isinstance(obj, _Context)),
        ):
            self.bot: Dwello = obj.bot
            self.author = obj.author
        else:
            self.author = obj.user
            self.bot: Dwello = obj.client

        self.embed = embed
        self.filename = filename

        self._code_str = "".join(source_lines)
        self._fp = self._code_str.encode("utf-8")

        self.code_snippet = create_codeblock(self._code_str)
        self.file = self._create_file()

        self.add_item(ShowCodeButton())
        self.add_item(ShowFileButton())

        self.message: discord.Message = None

    def _update_file(self) -> None:
        self.file = self._create_file()

    def _create_file(self) -> discord.File:
        return discord.File(
            filename=self.filename,
            fp=io.BytesIO(self._fp),
        )

    async def interaction_check(self, interaction: Interaction[Dwello]) -> bool | None:
        if val := interaction.user == self.author:
            return val
        else:
            return await interaction.response.send_message(
                embed=(
                    Embed(
                        title="Failed to interact with the view",
                        description="Hey there! Sorry, but you can't interact with someone else's view.\n",
                        timestamp=discord.utils.utcnow(),
                    ).set_image(url="https://media.tenor.com/jTKDchcLtrcAAAAd/walter-white-walter-crying.gif")
                ),
                ephemeral=True,
            )

    async def on_timeout(self) -> None:
        self.clear_items()
        with contextlib.suppress(discord.errors.NotFound):
            await self.message.edit(view=self)

    @classmethod  # separate start method for all the views / custom view with that classmethod
    async def start(
        cls: type[SVT],
        obj: Context | Interaction[Dwello],
        embed: Embed,
        source_lines: list[str],
        /,
        filename: str | None = "code.py",
        **kwargs,
    ) -> SVT:
        new = cls(obj, embed, source_lines, filename, **kwargs)
        if any(
            (issubclass(obj.__class__, _Context), isinstance(obj, _Context)),
        ):
            new.message = await obj.reply(embed=embed, view=new)  # reply or send?
        else:
            send = obj.response.send_message
            await send(embed=embed, view=new)
            new.message = await obj.original_response()
        await new.wait()
        return new
