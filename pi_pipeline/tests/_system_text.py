"""The text of a captured request's `system` argument: a plain string, or the list of blocks the prompt cache needs."""


def system_text(system) -> str:
    if isinstance(system, str):
        return system
    return "\n\n".join(b["text"] for b in system)
