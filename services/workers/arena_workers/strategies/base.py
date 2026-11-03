from collections.abc import Sequence
from typing import Protocol

from ..common.models import Bar, Position, Signal


class Strategy(Protocol):
    slug: str

    def on_bar(
        self, symbol: str, bars: Sequence[Bar], position: Position | None
    ) -> Signal | None: ...
