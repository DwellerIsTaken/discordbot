from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import dateparser
import discord
from discord import Interaction, app_commands
from discord.ext import commands
from discord.ui import Button, Modal, TextInput
from typing_extensions import Self
from core import BaseCog

if TYPE_CHECKING:
    from asyncpg import Record

    from core import Dwello, DwelloContext


class EditDueDateButton(Button):
    def __init__(self, todo: TodoItem, cog: Todo, *, label: str = "Add Due Date"):
        super().__init__()
        self.todo: TodoItem = todo
        self.cog: Todo = cog
        self.label: str = label
        self.style: discord.ButtonStyle = discord.ButtonStyle.green

    async def callback(self, interaction: Interaction[Dwello]):
        if interaction.user.id != self.todo.user_id:
            return await interaction.response.send_message("This button is not for you.", ephemeral=True)

        modal = EditDueDateModal(self.todo, self.cog)
        await interaction.response.send_modal(modal)


class EditDueDateModal(Modal, title="Edit Due Date"):
    due_date: TextInput = TextInput(
        label="Due at",
        required=True,
        min_length=1,
        max_length=50,
        placeholder="10m, 6 hours, tomorrow, next week, etc.",
    )

    def __init__(self, todo: TodoItem, cog: Todo) -> None:
        super().__init__()
        self.todo: TodoItem = todo
        self.cog: Todo = cog

    async def on_submit(self, interaction: Interaction[Dwello]):
        date = dateparser.parse(self.due_date.value, settings={"PREFER_DATES_FROM": "future"})
        if date is None:
            return await interaction.response.send_message(
                "Something went wrong when trying to parse the time.", ephemeral=True
            )

        async with self.cog.bot.pool.acquire() as conn:
            query = """
                UPDATE todo
                SET due_at = $1
                WHERE id = $2
            """
            await conn.execute(query, date, self.todo.id)

        timestamp = discord.utils.format_dt(date, style="R")
        await interaction.response.send_message(f"Done, The new due date is {timestamp}.", ephemeral=True)


class TodoAddModal(Modal, title="Add A Todo!"):
    """This modal is only called when using the context manager to add a todo item."""

    content: TextInput = TextInput(
        label="Content (optional)",
        required=False,
        min_length=1,
        max_length=1000,
        style=discord.TextStyle.long,
    )

    due_date: TextInput = TextInput(
        label="Due at (optional)",
        required=False,
        min_length=1,
        max_length=50,
        placeholder="10m, 6 hours, tomorrow, next week, etc.",
    )

    def __init__(self, cog: Todo, message: discord.Message) -> None:
        super().__init__()

        self.cog: Todo = cog
        self.message: discord.Message = message

    async def on_submit(self, interaction: Interaction[Dwello]) -> None:
        date: Optional[datetime] = None
        if value := self.due_date.value:
            date = dateparser.parse(value, settings={"PREFER_DATES_FROM": "future"})

        todo = TodoItem(
            user_id=interaction.user.id,
            channel_id=interaction.channel.id,
            message_id=self.message.id,
            guild_id=interaction.guild_id,
            content=self.content.value or None,
            due_at=date,
        )
        await self.cog.add_todo(todo)
        await interaction.response.send_message("Successfully added todo!", ephemeral=True)


@dataclass
class TodoItem:
    """Represents a todo item inserted and fetched from the database."""

    user_id: int
    id: int = 0
    channel_id: Optional[int] = None
    message_id: Optional[int] = None
    guild_id: Optional[int] = None
    content: Optional[str] = None
    due_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record: Record) -> Self:
        """Converts a `Record` to a `TodoItem`"""
        return cls(
            record["user_id"],
            record["id"],
            record["channel_id"],
            record["message_id"],
            record["guild_id"],
            record["content"],
            record["due_at"],
            record["completed_at"],
        )


class Todo(BaseCog):
    def __init__(self, bot: Dwello) -> None:
        self.bot = bot

    def cog_load(self) -> None:
        self.ctx_menu = app_commands.ContextMenu(name="Add Todo", callback=self.context_menu)
        self.bot.tree.add_command(self.ctx_menu)

    async def add_todo(self, todo: TodoItem) -> TodoItem:
        """Adds a todo item to the database and returns it."""
        query = """
            INSERT INTO todo (
                user_id,
                channel_id,
                message_id,
                guild_id,
                content,
                due_at,
                completed_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7
            ) RETURNING id
        """
        async with self.bot.pool.acquire() as conn:
            record: Record = await conn.fetchrow(
                query,
                todo.user_id,
                todo.channel_id,
                todo.message_id,
                todo.guild_id,
                todo.content,
                todo.due_at,
                todo.completed_at,
            )
        todo.id = record["id"]
        return todo

    async def get_todo(self, id: int) -> TodoItem:
        """Gets a todo item from the database"""
        query = """
            SELECT * FROM todo WHERE id = $1
        """
        async with self.bot.pool.acquire() as conn:
            result = await conn.fetchrow(query, id)
            todo = TodoItem.from_record(result)
            return todo

    async def context_menu(self, interaction: Interaction[Dwello], message: discord.Message):
        modal = TodoAddModal(self, message)
        await interaction.response.send_modal(modal)

    @commands.group()
    async def todo(self, ctx: DwelloContext):
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @todo.command()
    async def add(self, ctx: DwelloContext, *, content: str):
        todo = TodoItem(
            user_id=ctx.author.id,
            channel_id=ctx.channel.id,
            guild_id=ctx.guild.id,
            content=content,
        )
        todo = await self.add_todo(todo)
        embed = discord.Embed(
            title="Added todo!",
            description=content,
        )
        embed.set_footer(text=f"ID: {todo.id}")
        view = discord.ui.View()
        view.add_item(EditDueDateButton(todo, self, label="Edit Due Date"))
        await ctx.send(embed=embed, view=view)