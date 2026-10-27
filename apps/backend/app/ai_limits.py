"""Size limits for AI input."""

MAX_JOB_CHARACTERS = 100_000
MAX_PROMPT_CHARACTERS = 512_000


class PromptSizeError(ValueError):
    """A prompt is too large to send to the provider."""


def validate_prompt_size(value: str) -> None:
    if len(value) > MAX_PROMPT_CHARACTERS:
        raise PromptSizeError(f"AI prompt exceeds the {MAX_PROMPT_CHARACTERS}-character limit")
