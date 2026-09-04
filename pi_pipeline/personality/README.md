# personality

G2's personality is a set of **traits**. Each trait is a small, self-contained
bias that can touch three channels — you implement only the ones it needs:

| channel | method | effect |
|---|---|---|
| how G2 talks / decides | `prompt_fragment()` | a sentence appended to Claude's system prompt |
| how G2 behaves on its own | `bias(params)` | nudges `BehaviorParams` (explore timing, novelty pull, cue frequency, caution) |
| expressive reactions | `cues(event)` | skill / cue tokens for a named event ("novelty", "explore_start", …) |

Every trait has a `level` in `[0, 1]` and should scale all three channels by it,
so `0.2` reads as "a little" and `0.9` as "a lot".

## Configuring

`G2_TRAITS` — comma-separated `name=level`:

```
G2_TRAITS="curiosity=0.85, playfulness=0.4"
```

A bare name means level `1.0`. Unknown names are warned about and skipped (a
config from a newer build still loads on an older one). Empty ⇒ the neutral
personality: base prompt unchanged, neutral behaviour params.

```
python -m pi_pipeline.personality                 # show what G2_TRAITS resolves to
python -m pi_pipeline.personality "curiosity=0.9" # …with an override
```

## Using it

```python
from pi_pipeline.personality import Personality

p = Personality.from_settings(settings)         # or .from_spec("curiosity=0.9")
system = p.system_prompt(settings.system_prompt)
params = p.behavior_params()                    # -> BehaviorParams for behavior/
cues   = p.cues("novelty")                      # -> ["head_tilt", "chirp_rising", ...]
```

`voice/conversation.py` already calls `system_prompt()` at construction.

## Adding a trait

1. New file, subclass `Trait`, set `name`, implement the channels it affects
   (see `curiosity.py`).
2. Add it to `REGISTRY` in `traits.py`.
3. Set its level in `G2_TRAITS`.

Nothing else changes. Candidate next traits: `playfulness`, `caution`,
`affection`, `independence` — each mostly a `bias()` + a `prompt_fragment()`.
The behaviour-idea backlog items **B4** (expressive body language), **B5**
(chirp vocabulary), and **B6** (mood from memory) all plug in through the `cues`
channel and `BehaviorParams`.
