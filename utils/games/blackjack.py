from __future__ import annotations

import random

import discord

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core import Context

from constants import BLACK_JACK_CARDS


class BlackJack:
    def __init__(self, *, player: discord.User | discord.Member, bet: int | None = None) -> None:
        self.player = player
        self.bet = bet

        self.player_cards: list[discord.PartialEmoji] = []
        self.computer_cards: list[discord.PartialEmoji] = []
        self.__cards: dict[str, discord.PartialEmoji] = BLACK_JACK_CARDS.copy()
        self._standed = False

        for _ in range(2):
            self.player_cards.append(self.deal_card())
            self.computer_cards.append(self.deal_card())

    def _get_card_value(self, card: discord.PartialEmoji, *, A: int = 11) -> int:
        card_value = card.name[:-1]
        if card_value == "A":
            return A

        return 10 if card_value in ("J", "Q", "K", "0") else int(card.name[:1])

    def _get_card_name(self, card: discord.PartialEmoji) -> str:
        return card.name[:-1]

    def deal_card(self) -> discord.PartialEmoji:
        card_name = random.choice(list(self.__cards.keys()))
        card = self.__cards[card_name]
        self.__cards.pop(card_name)
        return card

    def calculate_score(self, cards: list[discord.PartialEmoji]) -> int:
        if sum(self._get_card_value(card) for card in cards) == 21 and len(cards) == 2:
            return 0

        is_21_or_above = sum(self._get_card_value(card) for card in cards)
        if is_21_or_above <= 21:
            return is_21_or_above
        return sum(self._get_card_value(card, A=1) for card in cards)

    def hit(self) -> None:
        self.player_cards.append(self.deal_card())
        if self.calculate_score(self.player_cards) > 21:
            self._standed = True

    def stand(self) -> None:
        self._standed = True
        self._evaluate_computer_cards()

    def _evaluate_computer_cards(self) -> None:
        while self.calculate_score(self.computer_cards) < 17:
            self.computer_cards.append(self.deal_card())

    @property
    def player_score(self) -> int:
        return self.calculate_score(self.player_cards)

    @property
    def player_display_score(self) -> int:
        return self.player_score

    @property
    def player_cards_string(self) -> str:
        return " ".join(str(card) for card in self.player_cards)

    @property
    def computer_score(self) -> int:
        return self.calculate_score(self.computer_cards)

    @property
    def computer_display_score(self) -> int:
        if not self.game_over:
            return self._get_card_value(self.computer_cards[0])
        return self.computer_score

    @property
    def computer_cards_string(self) -> str:
        if self.game_over:
            return " ".join(str(card) for card in self.computer_cards)
        BACK_CARD = discord.PartialEmoji.from_str("<:CARD_BACK:1143090855910051851>")
        return str(self.computer_cards[0]) + (f" {str(BACK_CARD)}" * (len(self.computer_cards) - 1))

    @property
    def game_over(self) -> bool:
        return self._standed or (
            self.player_score == 0 or self.computer_score == 0 or self.player_score > 21 or self.computer_score > 21
        )

    def get_game_over_description(self) -> str:
        if self.player_score == 0:
            return "You got a Blackjack! You win!"
        if self.computer_score == 0:
            return "Dealer got a Blackjack. You lose!"
        if self.player_score > 21 and self.computer_score > 21:
            return "You went over. You lose!"
        if self.player_score > 21:
            return "You went over. You lose!"
        if self.computer_score > 21:
            return "Dealer went over. You win!"
        if self.player_score > self.computer_score:
            return "You win!"
        if self.player_score < self.computer_score:
            return "You lose!"

        return ""

    @property
    def player_won(self) -> bool:
        return self.player_score > self.computer_score and self.game_over


class BlackJackView(discord.ui.View):
    message: discord.Message

    def __init__(self, *, player: discord.User | discord.Member, bet: int | None = None) -> None:
        super().__init__(timeout=60)
        self.game = BlackJack(player=player, bet=bet)

        """
        Example:
            view = BlackJackView(player=ctx.author, bet=100)
            await view.start(ctx)
        """

    @property
    def embed(self) -> discord.Embed:
        # TODO: Beautify this embed
        embed = (
            discord.Embed(
                title="BlackJack Game",
                description=f"**{self.game.player.mention} vs {self.ctx.bot.user.mention}**",
                color=discord.Color.blurple(),
            )
            .add_field(
                name=f"Your Card [{self.game.player_display_score}]",
                value=self.game.player_cards_string,
                inline=False,
            )
            .add_field(
                name=f"Dealer Card [{self.game.computer_display_score}]",
                value=self.game.computer_cards_string,
                inline=False,
            )
        )

        if self.game.game_over:
            embed.set_footer(text=f"Game Over - {self.game.get_game_over_description()}")

            if self.game.player_won:
                embed.color = discord.Color.yellow()
                self.game.bet = self.game.bet * 2 if self.game.bet else None
            else:
                embed.color = discord.Color.red()
                self.game.bet = 0

        return embed

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.green)
    async def hit_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.game.hit()
        if self.game.game_over:
            self.stop()
            self.disable_all()
        await interaction.response.edit_message(embed=self.embed, view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.red)
    async def stand_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.game.stand()
        if self.game.game_over:
            self.stop()
            self.disable_all()
        await interaction.response.edit_message(embed=self.embed, view=self)

    async def start(self, ctx: Context) -> None:
        self.ctx = ctx
        self.message = await ctx.send(embed=self.embed, view=self)

    def disable_all(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    async def on_timeout(self) -> None:
        self.disable_all()
        if hasattr(self, "message"):
            await self.message.edit(view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.game.player:
            await interaction.response.send_message(
                "You can't use this button.", ephemeral=True,
            )
            return False
        return True