# XiaoZhi (`78/xiaozhi-esp32`) — what is in it that helps us

Review of the upstream project the Petoi AI Head's firmware is built on ([github.com/78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32), MIT),
2026-10-03. Context: [`petoi-ai-head-evaluation.md`](petoi-ai-head-evaluation.md) and [`firmware-fork-case.md`](firmware-fork-case.md). Read from the repo's
README and `docs/` through a fetch tool, not built or run; items marked *unverified* need checking against the source or the unit.

## Is the head's firmware its own repo?

- **Upstream is a separate project** from Petoi's BiBoard firmware (OpenCatEsp32): different chip target (the head is an ESP32-C3 built with ESP-IDF; the
  BiBoard firmware is an Arduino-style ESP32 project). They can't sensibly be one codebase.
- **Petoi's head build is not in upstream.** `main/boards` holds ~138 board directories and none is named for Petoi, Bittle or the AI Head. So Petoi's version is
  either a private fork, an unmerged board definition, or not yet pushed.
- **Not confirmed:** where Petoi will publish it. Petoi says it will open-source it; its own guide says the module is "built upon the open-source XiaoZhi project".
  A separate repo (probably a fork of upstream) is the likely shape, but a folder or branch in an existing Petoi repo is possible.
- **Upstream moves fast and breaks things:** the README now requires ESP-IDF v6.0.1+ (v6.1 recommended) and no longer supports 5.x. Any head patches must pin an
  exact upstream tag or Petoi's tag, and expect rebases.

## What is useful to us

| Finding | Why it matters |
|---|---|
| **Documented WebSocket protocol** (device `hello`, then `listen`/`stt`/`tts`/`llm`/`mcp` JSON messages; mono Opus, 16 kHz up, 60 ms frames, up to 24 kHz down) | We can write the backend ourselves. The device sends microphone audio to a server and plays back audio the server returns, so a backend on the Pi (or a laptop) can put Claude, our memory and personality, and our vision behind the head |
| **Four community self-hosted servers** (Python `xinnan-tech/xiaozhi-esp32-server`, Java, and two Go ones) | Existing servers to adapt rather than write from scratch; swapping their LLM step for Claude is the likely change. *Unverified: quality, how they handle memory and tools* |
| **MCP on the device**: `McpServer::AddTool` registers a tool with a name, description and JSON input schema; the backend calls it with `tools/call` | Petoi's `self.robot.send_command` is one such tool. We can add tools such as stop, get status, or perform-skill. Tools can also live on the backend side, so "what do you see?" can be a backend function that reads the Pi's camera feed |
| **`otto-robot` board** (a servo walker): exposes `self.otto.action` with parameters, plus `stop`, `get_status` and trims as tools | A worked example of a motion-tool set to copy for a Petoi tool set, including a stop tool |
| **Custom-board guide**: three files per board (`config.h` pins, `config.json`, a board class), builds with `scripts/build.py`; ESP32-C3 is covered | Shows what we would need from Petoi's release (pin map, codec) and confirms the build path is conventional ESP-IDF |
| **Vision hook**: MCP `initialize` can carry a vision server URL and token, and boards with cameras can send a photo for the LLM to describe | The pattern for "what do you see?" exists, but it assumes a camera on the head. For us the equivalent is a backend tool that returns the Vision Module's detections as text |
| **Offline, customizable wake word** (ESP-SR; WakeNet9s on C3) | The stock phrase is "Hi, Jason"; a custom one such as G2's name may be possible. *Unverified on the head* |
| **Speaker recognition** (3D Speaker) | Could tell who is talking, which maps to our bonds and enrollment ideas. Petoi's console lists it as not on the free plan; *unverified whether a self-hosted setup gets it* |
| **MIT licence** | Free to patch and redistribute our changes |

## What does not help

- No Petoi board, so the pin map and codec for the head are still unknown.
- The camera/vision features target boards with a camera on the device; the head has none.
- Nothing in the project replaces our local reflexes or the learned gait; this is a voice front end.

## How this changes the picture (corrections to earlier answers)

- **Memory and personality are ours if we host the backend.** The default xiaozhi.me backend keeps its own memory ("Model & Memory"). A self-hosted server can call
  Claude and use our SQLite memory. The server has to run somewhere: the Pi, a laptop, or a cloud machine. With no Pi on G2 it would be one of the latter two.
- **The Pi can use the head's microphone and speaker, but only through a modified or redirected head.** Petoi's founder said the mic audio "could be modified to
  stream out" and the speaker can take host playback commands, both by modifying the firmware. With stock firmware the head talks to its configured server over
  Wi-Fi, not to the Pi over the UART. So I overstated it earlier by saying the Pi cannot use them: the accurate statement is **not without changing the head's
  server address or firmware.** The practical route is the Wi-Fi voice-peripheral design already in the evaluation doc: point the head at a backend on the Pi. The
  UART is then unused (motion stays on the Pi), so there is no UART conflict. *Unverified: whether the server address can be changed without rebuilding.*
- **Voice-peripheral cost-benefit:** versus the ordered I2S microphone and amplifier, the head saves wiring and looks integrated, but needs a backend and a firmware
  or settings change first, and adds a Wi-Fi hop. Keep the I2S parts regardless.
