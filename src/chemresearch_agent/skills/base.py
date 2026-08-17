from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class Skill[InputT: BaseModel, OutputT: BaseModel](ABC):
    """A versioned, validated professional operation.

    Concrete skills own domain rules and prompts. They must not own workflow state,
    HTTP concerns, or persistence.
    """

    name: str
    version: str

    @abstractmethod
    def run(self, value: InputT) -> OutputT:
        raise NotImplementedError
