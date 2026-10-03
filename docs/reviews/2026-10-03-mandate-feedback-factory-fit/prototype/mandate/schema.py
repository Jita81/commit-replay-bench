"""The slot schema types (content is human-authored, see the question bank)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Slot:
    id: str
    group: str
    priority: int  # 1 = most important
    required: bool = False
