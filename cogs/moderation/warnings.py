from __future__ import annotations

import contextlib
import functools
from typing import Any, Literal

import discord
from discord.app_commands import Choice
from discord.ext import commands
from discord.ui import Button, button

import constants as cs
from core import BaseCog, Context, Dwello, Embed, View
from utils import Warning, apostrophize
from .standard import member_check

from .timeout import tempmute


class TimeoutSuggestion(View):
    def __init__(
        self,
        ctx: Context,
        member: discord.Member,
        reason: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self.ctx = ctx
        self.member = member
        self.reason = reason

    @button(label="Yes", style=discord.ButtonStyle.green)
    async def _yes(self, interaction: discord.Interaction, button: Button) -> None:
        await tempmute(self.ctx, self.member, 12, None, self.reason)
        self.finish()
        await interaction.message.delete()

    @button(label="No", style=discord.ButtonStyle.red)
    async def _no(self, interaction: discord.Interaction, button: Button) -> None:
        self.finish()
        await interaction.message.delete()


class Warnings(BaseCog):
    def __init__(self, bot: Dwello, *args: Any, **kwargs: Any) -> None:
        super().__init__(bot, *args, **kwargs)

    async def cog_check(self, ctx: Context) -> bool:
        return ctx.guild is not None

    async def _warn(
        self,
        ctx: Context,
        member: discord.Member,
        reason: str | None = "Not specified",
    ) -> discord.Message | None:
        db = self.bot.db

        if not await member_check(ctx, member):
            return

        await db.warn(member.id, ctx.guild, ctx.author, reason=reason)
        warns: int = len(await db.get_warnings(member.id, ctx.guild))
        with contextlib.suppress(discord.HTTPException):
            await member.send(
                embed=Embed(
                    title="Warned",
                    description=(
                        "Goede morgen!\n"
                        "You have been warned. Try to avoid being warned next time or it might get bad...\n\n"
                        f"Reason: **{reason}**\n\nYour amount of warnings: `{warns}`"
                    ),
                    color=cs.WARNING_COLOR,
                    timestamp=discord.utils.utcnow(),
                )
                .set_footer(text=cs.FOOTER)
                .set_image(url="https://c.tenor.com/GDm0wZykMA4AAAAd/thanos-vs-vision-thanos.gif"),
            )

        return await ctx.send(
            embed=Embed(
                title="User is warned!",
                description=(
                    f"*Warned by:* {ctx.author.mention}\n"
                    f"\n**{member.name}** has been successfully warned! \nReason: `{reason}`"
                ),
                color=cs.WARNING_COLOR,
                timestamp=discord.utils.utcnow(),
            ).set_footer(text=f"Amount of warnings: {warns}"),
        )

    async def _unwarn(
        self,
        ctx: Context,
        member: discord.Member,
        warn_id: str | Literal["all"],
    ) -> discord.Message | None:
        
        if not await member_check(ctx, member):
            return

        db = self.bot.db

        if not (all := warn_id == "all"):
            warn_id = int(warn_id)
            if not await db.get_warning_by_id(warn_id, member.id, ctx.guild):
                return await ctx.reply(
                    f"Warning already removed! Use `{self.bot.main_prefix}warnings [member]` for more.",
                    user_mistake=True,
                )

        warnings = len(await self.bot.db.unwarn(warn_id if not all else 0, member.id, ctx.guild, all=all))
        return await ctx.reply(
            embed=Embed(
                timestamp=discord.utils.utcnow(),
                title="Removed",
                description=(
                    f"*Removed by:* {ctx.author.mention}\n\n" f"Successfully removed *{warnings}* warning(s) from {member}."
                ),
            ),
            permission_cmd=True,
        )

    async def _warnings(self, ctx: Context, member: discord.Member = commands.Author) -> discord.Message | None:
        db = self.bot.db

        warnings: list[Warning] = await db.get_warnings(member.id, ctx.guild)

        embed: Embed = Embed(timestamp=discord.utils.utcnow())
        embed.set_thumbnail(url=f"{member.display_avatar}")
        embed.set_footer(text=cs.FOOTER)
        embed.set_author(
            name=f"{apostrophize(member.name)} warnings",
            icon_url=str(member.display_avatar),
        )

        warns = 0
        for warning in warnings:
            if reason := warning.reason:
                embed.add_field(
                    name=f"Warning #{warns+1}",
                    value=(
                        f"Reason: *{reason}*\n"
                        f"Date: {discord.utils.format_dt(warning.created_at)}\n"
                        f"ID: `{warning.id}`"
                    ),
                    inline=False,
                )
                warns += 1

        if not warns:
            embed = Embed(description=f"{'You have' if member == ctx.author else 'This user has'} no warnings yet.")

        await ctx.defer()  # because view can be called (?)
        await ctx.reply(embed=embed, mention_author=False)

        if member != ctx.author and warns > 3 and ctx.author.guild_permissions.moderate_members:
            return await ctx.send(
                embed=Embed(
                    title="A lot of warnings",
                    description=f"Would you like to time **{member}** out for 12 hours?",
                    color=cs.WARNING_COLOR,
                ),
                view=TimeoutSuggestion(self.bot, ctx, member, "Too many warnings!"),
            )

    @commands.command(name="warn", brief="Warns member.")
    @commands.has_guild_permissions(moderate_members=True)
    async def warn(self, ctx: Context, member: discord.Member, *, reason: str | None) -> discord.Message | None:
        """Gives member a warning."""

        async with ctx.typing(ephemeral=True):
            return await self._warn(ctx, member, reason)

    @commands.command(name="unwarn", brief="Removes selected warning.")
    @commands.has_guild_permissions(moderate_members=True)
    async def unwarn(self, ctx: Context, member: discord.Member, warning: str) -> discord.Message | None:
        """Removes the warning by its ID."""

        async with ctx.typing(ephemeral=True):
            if not warning.isdigit() and warning != "all":
                return await ctx.reply("Please provide a valid ID.", user_mistake=True)
            return await self._unwarn(ctx, member, warning)

    @commands.command(name="warnings", brief="Shows member's warnings.")
    @commands.has_guild_permissions(moderate_members=True)
    async def warnings(self, ctx: Context, member: discord.Member = commands.Author) -> discord.Message | None:
        """Shows all member's warnings."""

        async with ctx.typing(ephemeral=True): # if too many warnings activate a paginator
            return await self._warnings(ctx, member) # also maybe a func for the top 5 most warned and then also somehow include that into economy system   # noqa: E501

    @commands.hybrid_group(name="warning", invoke_without_command=True)
    async def warning(self, ctx: Context):
        """A command group for managing warnings."""

        return await ctx.send_help(ctx.command)

    @warning.command(name="warn", brief="Gives member a warning.", description="Gives member a warning.")
    @commands.has_permissions(moderate_members=True)
    async def hybrid_warn(self, ctx: Context, member: discord.Member, *, reason: str | None) -> discord.Message | None:
        """Gives member a warning."""

        async with ctx.typing(ephemeral=True):
            return await self._warn(ctx, member, reason)

    @warning.command(
        name="warnings",
        aliases=["show", "display"],
        brief="Shows member's warnings.",
        description="Shows member's warnings.",
    )
    async def hybrid_warnings(self, ctx: Context, member: discord.Member = commands.Author) -> discord.Message | None:
        """Shows all member's warnings."""

        async with ctx.typing(ephemeral=True):
            return await self._warnings(ctx, member)

    @warning.command(
        name="remove",
        aliases=["delete"],
        brief="Removes selected warning.",
        description="Removes selected warning.",
    )
    @commands.has_permissions(moderate_members=True)
    async def hybrid_unwarn(self, ctx: Context, member: discord.Member, warning: str) -> discord.Message | None:
        """Removes the warning by its ID."""
        
        async with ctx.typing(ephemeral=True):
            if not warning.isdigit() and warning != "all":
                return await ctx.reply("Please provide a valid ID.", user_mistake=True)
            return await self._unwarn(ctx, member, warning)

    @functools.lru_cache(maxsize=1)
    @hybrid_unwarn.autocomplete("warning")
    async def autocomplete_callback(self, interaction: discord.Interaction, current: str) -> list[Choice]:
        item = len(current)
        warnings: list[Warning] = await self.bot.db.get_warnings(interaction.namespace["member"].id, interaction.guild)
        choices: list[Choice[str]] = [Choice(name="all", value="all")] + [
            Choice(
                name=f"ID {warning.id}: {str(warning.reason)[:20]} | {str(warning.created_at)[:-7]}", value=str(warning.id)
            )
            for warning in warnings
            if (
                current.startswith(str(warning.reason).lower()[:item])
                or current.startswith(str(warning.created_at)[:item])
                or current.startswith(str(warning.id)[:item])
            )
        ]
        return choices[:25]
