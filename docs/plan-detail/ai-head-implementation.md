# The Petoi AI Head: everything we know and the plan to use it

The one home for facts about the head, the pros and cons of adopting it, what it would take, and a staged path. First hands-on session: 2026-10-11. **Status: exploration. Nothing here is committed yet: adopting the head, forking its firmware and running a backend are all open decisions** (section 8). What is deployed or running right now is in [`../STATUS.md`](../STATUS.md); the original keep-the-Pi-or-not criteria and the behavior inventory stay in [`../research/petoi-ai-head-evaluation.md`](../research/petoi-ai-head-evaluation.md); the vendor's own page is [Petoi AI conversation](https://guide.petoi.com/extensible-modules/ai-conversation).

**The owner's goal for the head (2026-10-10):** offload as much work as possible from Claude to the head, so there are as few API calls as possible. A second, related wish: one voice for G2, not two.

## 1. Where we are

| | State |
|---|---|
| Head | Brought up on the bench, activated on its own account, talking in English. Not mounted on G2. |
| Brain it uses | XiaoZhi's free cloud model ("XiaoZhi Lite", the only choice on the free plan). |
| Tools | Proven: our tool server on the Pi (`python -m pi_pipeline.head`) is called by the head's model through the agent's MCP access point. Two test tools only (`g2_about`, `g2_test_word`). It is started by hand and stops when the Pi reboots. |
| Pi voice service | Stopped by hand on 2026-10-11 (G2 is in pieces); G2's own voice does not work until it is restarted. |
| Documentation | The vendor documents were read on 2026-10-11 (as a guest, no logins) and summarized in English in [`../research/xiaozhi-vendor-docs.md`](../research/xiaozhi-vendor-docs.md); what they change for this project is in section 3a. |
| Firmware | Backed up (read-only copy of the head's whole flash, kept on the Mac outside the repo; it contains the saved Wi-Fi settings, so it is never shared). Not forked, not flashed. |

## 2. What the head is

- **Hardware:** an ESP32-C3 (single core at 160 MHz, no floating-point hardware, Wi-Fi 2.4 GHz and Bluetooth LE), 16 MB flash, mass 42 g (Petoi). By the firmware's board profile `lichuang-c3-dev` (an open-source LCKFB development board): a 320 x 240 color screen, a speaker codec (ES8311), a microphone chip (ES7210) and the button on GPIO 9. Neither Petoi's documentation nor that profile lists a camera. It has a USB-C port (native USB serial) and one Grove cable to the BiBoard.
- **Firmware:** the open-source XiaoZhi firmware (MIT), **version 2.0.4**, built 2026-05-26 with **ESP-IDF 5.4.2**, plus Petoi's additions (below). Petoi has said its head source will be published; it is not yet.
- **Flash layout:** `nvs` (settings, including the saved Wi-Fi: never read), `otadata`, `phy_init`, a 960 KB wake-word `model`, a 7 MB `storage` (assets), and two 4 MB program slots of which only `ota_0` is used. OTA is off by default.
- **Petoi's additions** (not in the upstream project): a `SecondUart` on UART1 (the link to the BiBoard; the pin numbers are constants in the code, not visible as text), a device tool `self.robot.send_command` taking Petoi tokens (`ksit`, `kwkF 3`, `knd` nod, `kwh` shake, `kck` check, `kscrh` scratch), a built-in "Bittle" role text, and an on-screen **face**: tools `self.expression.look` (center, up, down, left, right), `blink`, `set_mouth_width`, `set_mouth_style`, `set_quiet_after_speech`. The firmware also removes tool-call text from speech (`Detected code leak in TTS text`).
- **Transport:** MQTT with UDP audio to XiaoZhi's cloud (as upstream).
- **Wake word:** the on-device model is `wakenet9s` for the Mandarin phrase "你好小智". Petoi's guide says "Hi, Jason". In our tests the **side button** is what reliably wakes it; "Hi, Jason" was not reliable. On this chip the vendor's tools only offer preset wake words (section 3a).
- **Source for a fork:** upstream is [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) (MIT). Its tree has the head's board (`main/boards/lckfb/szpi-esp32c3`). A copy of v2.5.0 (commit `ac6deed3…`) and esptool 5.4.0 (hash-verified) sit in `~/g2_head_firmware` on the Mac, outside the repo. v2.5.0 needs a newer toolchain than the head's v2.0.4 base.

## 3. What we learned hands-on (2026-10-11)

**Setup**
1. Power it (USB-C or the Grove cable). With no saved Wi-Fi it opens a hotspot `Xiaozhi-xxxx`; open `http://192.168.4.1`, choose a 2.4 GHz network, enter the password. Once saved it reconnects by itself and no longer shows the hotspot (the Boot button re-enters setup).
2. At the first join it looks up its country from the public IP (a GeoIP lookup), then shows a 6-digit activation code about every 170 seconds.
3. Account at xiaozhi.me (**spelled with "zh"**; a look-alike domain exists): sign-up needs a **phone number** and an SMS code. In the console: **create an agent first, then Add Device** with the code. A new boot gives a new code.
4. The new agent listens and replies in **Mandarin** until its language is set to English in the agent's settings.

**Console settings seen:** a role page (language, voice, the role/introduction text, and at the bottom right the agent's **MCP access point**), Model & Memory (one model on the free plan), a knowledge-base feature (limits not yet checked), Extensions. Speaker Recognition is not on the free plan. The voice list changes only the voice.

**Reading the head:** its USB-C port is a serial log at 115200. **Opening the port reboots it.** The log prints each turn: `>>` what it heard, `<<` what it said, plus network, wake-word and tool messages.

**Conversation quality:** greetings, small talk, simple arithmetic and questions about itself were answered by its own model, about one second to the start of a reply, with no Claude call. The tone comes from the role text and the model (it said "la" and "eh" until prompted otherwise); it also knows the date from the server.

**The device's own robot tool did not move anything in our tests, cause not established:** every "sit down", "shake your head" and "say goodbye" produced the log line `Detected code leak in TTS text, removing: % self.robot.send_command...`, the head said it had done the action, and no command was seen reaching the BiBoard (checked on the BiBoard's USB log and the Pi's serial line, with the BiBoard in low-power mode and later with the battery on). Petoi's own Role template tells the model to filter `% self.robot.` and `% get_xxx` out of what it speaks, which suggests that text is the cloud's normal notation for a tool call, so the strip alone does not prove the call was never made; whether the call reached the head, and whether the head's serial line was connected the way we assumed, were not separated. Petoi's recommended Role template made no difference.

**MCP works, with the same free model.** A tool server of ours on the Pi (`pi_pipeline/head/mcp_tools.py`, using the `websockets` package already on the Pi) connects out to the access point. The cloud immediately sent `initialize`, `notifications/initialized`, `tools/list` and later `ping`. A made-up answer (`g2_test_word` = "marmalade") was spoken by the head and the Pi's log showed the `tools/call`. So **the head's model can reach G2's abilities through code we control**, with our rules and safety layers.

**Wiring and BiBoard facts**
- The head's serial lines run through the first Grove socket (G1 = UART2, the only UART-capable one), the same UART as the Pi's 5-pin header. G1 is free now; the camera runs over the Pi's USB.
- **The Pi cannot hear the head's commands:** the Pi's receive pin is on the BiBoard's transmit line; the head's transmit is on the BiBoard's receive line. The Pi hears only the BiBoard's own output (the IMU stream). A 2-minute Pi listener with the head plugged in only saw that. To see the head's commands, use its own USB log, the BiBoard's replies, or a USB-serial adapter on the head's transmit line.
- On USB power alone the BiBoard boots, prints `Low power: 2.27V. The robot won't move.` every 10 seconds, and still answers a query from the Pi on its Serial2 (so that path works in that state). In that state G2 cannot move.
- Powering the head from the BiBoard's Grove 5 V and from a Mac at once is two supplies on one rail: avoid. Its current draw on the Grove supply is **not measured yet**.

**What G2 spends on Claude today:** 57 billed calls, about $0.33, in 72 hours (2026-10-07 to 10-10). The saving the head can offer in dollars is small; the reason to use it is the principle of fewer calls, the face, and the placement of the mic and speaker.

**The vendor's rules for tools (their MCP access-point guide, the precautions section)**
- Name tools and parameters so the model knows what they do (no abbreviations; for a search tool the parameter is `keywords`), and put the guidance for when to use a tool in its description.
- A tool's return value is usually a string or JSON and is **limited, typically to 1024 bytes**; our server cuts results at 1000 bytes.
- The tool list text is limited too (counted in tokens), so keep the list short.
- Each access point has an upper limit on connections: run one connector only.
- The console's "MCP access point" dialog shows the connection status (online) and the **names of the registered tools**, a quick way to check that our server is connected.
- The vendor's own example tool evaluates a Python expression from the model (`eval`); we do not do that.

**Flashing without a toolchain (from the vendor's firmware flashing guide, a Feishu page, updated 2026-01-27)**
- A prebuilt upstream image exists for the head's board: board type `BOARD_TYPE_LICHUANG_C3`, firmware file `vx.x.x_lichuang-c3-dev.zip` (the S3 board is a different row), from the official firmware list.
- It is flashed as a single `merged-binary.bin` written at address 0x0 (the whole flash), either with Espressif's Flash Download Tool 3.9.7 in UART mode (Windows-oriented; the path must not contain Chinese characters) or with esptool; the guide also mentions a browser-based method (not seen).
- The guide gives three ways: Espressif's Flash Download Tool 3.9.7 (Windows, UART mode, address 0x0, no Chinese characters in any path); a third-party web flasher (needs Edge and a login; skipped); and **ESP-Launchpad**, Espressif's own browser flasher (`espressif.github.io/esp-launchpad`, Chrome or Edge: DIY page, Connect, pick `merged-binary.bin`, address 0x0, Program, then Reset Device). esptool, which we already have, does the same write.
- **Forcing download mode** if a board will not respond: hold BOOT, tap RST, release BOOT. The head's C3 has native USB, so none of the guide's serial-chip drivers (CH340/CH343) are needed.
- **Restoring the backup is the same operation:** the backup is a full 16 MB image from address 0x0, the same shape as `merged-binary.bin`, so writing it back at 0x0 restores Petoi's firmware and its saved settings. (A generic prebuilt image overwrites the settings partition too.)
- So stock upstream firmware could be tried on the head **without building anything**. It would replace Petoi's additions (face tools, the BiBoard serial link, the robot tool), and the read-only backup is the way back. Nothing has been flashed; this is not a decision to fork.

**The device protocol (the vendor's WebSocket page, modified 2025-07-26; it matches upstream `docs/websocket.md`, `docs/mqtt-udp.md` and `docs/mcp-protocol.md`)**
- WebSocket, protocol version 1. The device connects with `Authorization: Bearer <token>`, `Protocol-Version`, `Device-Id` (its MAC address) and `Client-Id` (a UUID), then sends `hello` (features `mcp: true`; audio Opus, 16 kHz, mono, 60 ms frames); the server answers `hello` (audio at 24 kHz; no session id). Our head uses **MQTT with UDP audio** instead (its log: "no protocol specified in the OTA config, using MQTT"); the message types are the same.
- Device to server: `hello`, `listen` (`start` with a mode auto, manual or realtime; `stop`; `detect` for a wake word), `abort`, `mcp`. Server to device: `hello`, `stt` (what it heard), `llm` (an `emotion`, which drives the **screen face**), `tts` (`start`, `stop`, `sentence_start` with the sentence text), `mcp` (JSON-RPC 2.0), `system` (`reboot`), `alert` (status, message, emotion and a sound), `custom` (only if built in), and **binary Opus audio frames** (dropped while the device is listening). Audio goes up as Opus after optional echo cancellation, noise reduction and gain control.
- Device states: starting, Wi-Fi configuring, activating, idle, connecting, listening, speaking, upgrading; in manual mode a button press toggles listening, in auto mode the server's voice detection ends it.
- **What this means for pushing speech:** the audio channel opens when a conversation starts (the device connects, or opens it on a wake), so a server cannot simply start speaking to an idle head over the conversation channel; that gap is what the newer `notify` message fills. A server we run could send `alert` and, with an open channel, `tts` plus audio frames; this is the stage 8 work.

**Pushing a message to the head so it speaks (researched 2026-10-11)**
- **The protocol has push messages,** but only the *server* side of the head's connection can send them: the cloud broker that the head's MQTT link goes to. Upstream documents these (`docs/notify.md` and `main/application.cc` in the xiaozhi-esp32 source): `notify` (an https/http URL to a mono Ogg Opus file, plus optional subtitles, played while the head is idle), `alert` (status, message and emotion: shows text and a face emotion and plays a sound), `tts` (the cloud's own speech: start, stop, sentence text; the audio comes over the audio channel) and `custom` (only if the firmware is built with that option).
- **In the head's firmware (v2.0.4):** `alert`, `tts`, `stt`, `llm`, `mcp`, `system` and `iot` message types are present; **`notify` is not** (no `audio_url` or `subtitles` handling; it arrived in a newer release).
- **For us:** no documented public interface on xiaozhi.me for sending these to our own head. Searches in English and Chinese turned up none; the one lead is a community pattern of a platform-run scheduled task that calls an MCP tool and speaks the result (polling, not a push, and unverified on the free plan). Upstream's `xz-mqtt` forwarding is the vendor's internal server tooling.
- **So** without firmware or a backend of our own, the Pi cannot make the head say something on its own. With **our own backend** (stage 8) we would be the server and could send `alert` now and `tts` audio; `notify` would also need a firmware newer than v2.0.4. With a **firmware change** (stage 7) a host-driven speaker is the other route.

## 3b. The opened head: what the photos show (2026-10-11)

Photos are kept locally and are gitignored (`*.jpeg`): `blueprints/images/ai-head/head-board-top.jpeg` (whole board, top side), `head-board-button-closeup.jpeg` (left edge, soft focus) and `head-shell-button-opening-ruler.jpeg` (outside of the shell, ruler in inches, low resolution).

- **The board is a custom Petoi design, not the stock LCKFB dev board.** A bare **ESP32-C3** chip (not a module), a **Winbond 25Q128JVSQ** flash (128 Mbit = 16 MB), a 40 MHz crystal, a USB-C port (top right), a **speaker** connector labeled SPKER (bottom right, twisted red and black pair), a small microphone (top right), and a 4-pin connector at the top left labeled **R, T, V, G** (UART plus power) for the cable to the body. The antenna is **external**: a thin coax from a u.FL socket at the bottom left runs up the left side. It is not a ground lead and must not be pulled or melted.
- **So the button pin (GPIO 9) from the firmware's board profile is unconfirmed for this board.** It has to be measured.
- **Two small switches on the left edge.** The lower one, with a **B** printed below it, is the likely BOOT/user button, a side-actuated surface-mount switch whose plunger points at the shell wall. The upper one has a cut-off letter (D or R) and is not to be used. Which terminal is the signal side is not known; measure with the head on USB power (signal side should read about 3.3 V against the USB-C shell), then do the jumper touch test before any soldering.
- **The round spot on the shell is a raised button** (owner, 2026-10-11), not a recessed plunger, and it sits in a small oval opening about 1/8 inch (3 to 4 mm) across by the ruler in the photo (rough: tilted, low resolution). A pusher can press it from outside with a flat tip; the alignment tolerance is looser than I first wrote. The owner estimates it stands proud by about 1/40 inch (0.025 in, about 0.6 mm; an eyeball estimate, to be measured edge-on). The shell around it is a natural depth stop for a wide flat tip, but the rest clearance is tiny, so the bracket must be rigid and adjustable. Still unmeasured: the cap's diameter, the force and travel needed to trigger the switch.
- Soldering to the switch is hard (small terminals, the antenna coax and the 8-pin flash chip next to it); the alternatives are a pusher through the opening or having someone experienced do the joint. The decision is open.

## 3a. What the vendor documents change for this project

Read 2026-10-11; the English summary with every source is [`../research/xiaozhi-vendor-docs.md`](../research/xiaozhi-vendor-docs.md). The findings that matter here, each with its effect on the plan:

1. **Stronger free models are one account step away.** "Developer certification" (console, avatar menu, bind a GitHub account) unlocks Qwen 3, the full DeepSeek and Doubao (and two preview models), where the ordinary free tier has only "XiaoZhi Lite" and a quantized DeepSeek; it also raises limits (knowledge bases 1 to 10, documents each 1 to 10, bound devices 10 to 100). *Plan effect:* the tool-reliability and chat-quality tests of stages 1 and 2 should be repeated on a stronger model; a stronger model may also change the robot-tool result. It links a GitHub account to a third party, so it is the owner's decision (section 8).
2. **A push feature exists for developers but is not public.** The activation design lists, for developers: device activation status and deregistering, device status and usage statistics, **real-time notification push (needs an active MQTT connection)**, and agent configuration read and write ("to be evaluated"). *Plan effect:* the stage 4 loss (no self-initiated speech) might be avoidable without firmware or a backend; find that interface (ask XiaoZhi or Petoi; it may only be visible after certification) before relying on it. Until seen, the earlier conclusion stands.
3. **A G2-like voice may be possible with no firmware change: voice cloning.** In the console: 99 yuan a year for 8 clones (as of March 2025), an 8 to 30 second clean clip (one speaker, no echo), selectable about 5 minutes after the clone succeeds. It is **paid with WeChat Pay**, which is likely a blocker for a US account and is something the assistant cannot do for the owner; the clone lapses when the year ends; whether a synthetic robot voice clones well is unknown; some users reported a device going silent after choosing a clone. *Plan effect:* an option for stage 4 beside a stock voice, behind a payment decision.
4. **Wake words on this chip are presets only.** C3 and C6 chips take a fixed list of four (Espressif's speech library, WakeNet9s: "Hi, 乐鑫", "Hi, ESP", "你好小智" and "Hi, Jason"); custom words are for the S3 and P4; a truly custom trained word is an Espressif commercial service (2 to 3 weeks, a corpus of over 20,000 samples or Espressif collects, a minimum fee). "Hi, Jason" is therefore a preset, but the head's firmware loads the 你好小智 model (its model partition holds one model), which is why "Hi, Jason" did not wake it; a settings-only build can select it. *Plan effect:* hands-free "G2" needs stage 7b (the Pi's own wake word on the head's audio) or an add-on recognition module (a community scheme), not the head's chip; the button stays the wake action until then.
5. **The firmware route is cheaper to try.** The console has a **cloud firmware build** (10 builds per account per day, official boards only; options: wake-word preset, echo cancellation on or off, display style, Wi-Fi setup method) and a prebuilt image exists for the head's board, flashable in a browser with ESP-Launchpad or with esptool (`merged-binary.bin` at 0x0). *Plan effect:* "see what stock upstream does on the head" needs no toolchain, but it **drops Petoi's additions** (the BiBoard serial link, the robot tool, the face tools); the backup is the way back. A local build needs ESP-IDF 5.4.2 for the head's v2.0.4 base (5.5.2 for v2.2.4; the newest source needs 6). The device's Client-Id is regenerated when its flash is erased, so a full flash may need the device re-added to the account; restoring the backup restores the old identity.
6. **Pointing the head at our own server is a menu setting.** The firmware's configuration menu has **Default OTA URL**; the server's OTA reply carries the MQTT and WebSocket settings and the activation code. Older versions (1.6.0 and earlier) set the WebSocket address directly. *Plan effect:* stage 8 is our OTA endpoint plus a protocol server plus one setting and a rebuild; no firmware code change for the address. The community server is heavy (2 to 4 GB, no Piper in its speech list, not security-tested), so our own small server stays the plan.
7. **The face is driven by emotion messages with 19 fixed names** (neutral, happy, laughing, funny, sad, angry, crying, loving, embarrassed, surprised, shocked, thinking, winking, cool, relaxed, delicious, kissy, confident, sleepy). With the cloud agent the model picks its own emotion; the role text can steer it; G2 cannot send one without our own server. *Plan effect:* stage 6 can map G2's moods (neutral, content, playful, lonely, subdued) onto these names, but only through our server or the role text.
8. **The knowledge base is a fair home for static reference material, not for live facts.** One knowledge base with one document is not the limit that matters: one large document can hold a whole G2 handbook (commands, abilities, how he talks, background). What limits it: it is static (no live state such as battery or the last exploration, which stay tools), it is stored in XiaoZhi's cloud, it is a preview feature ("limited-time free"), and the model must be told in the knowledge base's description to call it first in every conversation. Supported file types and the size limit were not read. *Plan effect:* an optional stage 1 addition with a non-personal handbook, after the tools; never household details.
9. **The vendor's tool rules are applied in the code:** results cut at 1000 bytes, one connection, clear names and "when to use" descriptions (to keep).
10. **Persona limits:** the role text is at most 2000 characters; XiaoZhi has its own memory box (about 1000 characters, regenerated each conversation) that is separate from G2's memory and should stay off or ignored. *Plan effect:* the persona tool of stage 2 carries what does not fit.
11. **Wiring and power:** Petoi's photo for the voice-module BiBoard shows the head's Grove cable on the socket at the board's left edge; on BiBoard V1 G1 is the only UART socket (G2 I²C, G3 and G4 analog), so before mounting confirm which physical socket on G2's board is G1 and that it matches the photo. The board's input is 7 to 9 V; no per-socket current is given, so the head's draw still has to be measured.
12. **Wi-Fi:** Petoi's firmware stores several networks (home and a phone hotspot) and falls back to setup mode after failures; the generic firmware remembers only the last. *Plan effect:* roaming to a hotspot is possible; the saved networks are listed and deletable on the setup page.
13. **The robot-tool silence is still open.** Petoi's role template tells the model to filter `% self.robot.` out of speech, so that text is probably the cloud's tool-call notation. *Plan effect:* the next test must separate "the cloud made the call" from "the head's serial line was connected as assumed" (a USB-serial adapter on the head's transmit line, or the head's own log at a higher level).
14. **Petoi's next product uses the same firmware on an S3 board.** Their "Quaddle" pages describe an AI core board with an ESP32-S3 flashed with a `merged` bin. An S3 supports custom wake words and is where the vendor documents echo cancellation. *Plan effect:* watch for a published source; an S3-based head would make stage 7b more realistic than the C3.
15. **Account facts:** first sign-up needs a mobile phone number; a device already bound to an account will not announce its code (unbinding is by email to support); the ordinary tier binds 10 devices. Terms, privacy and pricing sit behind the login and were not read, so the privacy gate stands.

16. **A custom backend on unmodified upstream firmware may avoid part of the fork, but not the microphone side.** The newest upstream source has the server address as a build setting (`Default OTA URL`) and a `notify` message that lets a server play an audio file on an idle device, so Piper audio from our server could speak G2's self-initiated lines in G2's voice and the conversation could use G2's voice and brain. **The realtime listening idea is ruled out on the C3 (checked 2026-10-11):** in the realtime mode the device keeps listening while it speaks and the server decides what to react to, so a server-side "G2" wake word was conceivable; but that mode is only selected when echo cancellation is on, and echo cancellation (and the audio front end it needs) is an S3, P4-class feature that needs extra memory (PSRAM): the vendor's AEC page and the upstream settings both say so. A C3 cannot enable it. Even where it works, a vendor comment says interruption worked only with the official server. Still unknown: whether `notify` runs on the C3 build, the toolchain download for a settings build, and that a stock build drops Petoi's additions (not needed if motion goes through the Pi's tools). *Plan effect:* a backend can give G2's voice and speech on his own initiative; hands-free "G2" and the Pi-mic removal still need stage 7b or an S3 head.
17. **A hardware route to a hands-free "G2" also exists:** the Pi already hears "G2" with its own wake word; it could "press" the head's side button electrically (two wires and a small transistor on the Pi's GPIO). No firmware change; more wiring on the head.

18. **Echo cancellation and custom wake words are S3 features, and the same dev-board family has an S3 variant.** The head's board profile is the C3 version of the LCKFB "Lichuang" board; the vendor lists the **S3 version of the same board** among the boards that support echo cancellation, and the S3 supports custom wake words (typed as text). Petoi's upcoming Quaddle AI core board is also an S3. *Plan effect:* if a hands-free "G2" or interruption on the head itself becomes a must, the route is an S3-based head (Petoi's, if one is offered, or a swap of the board if it fits the head), not a fork of the C3 firmware.

**Net effect on the staged plan:** stages 1 to 3 are unchanged in order, with a stronger-model retest added after the certification decision; stage 4 gains two possible ways to keep self-initiated speech or a G2-like voice (a developer push, voice cloning), both unverified or payment-blocked; stage 6 and stage 8 get concrete mechanisms (emotion messages, the OTA URL); stage 7 gets a no-toolchain trial path; the wake word on the head's chip is presets only, which makes stage 7b the route to "G2".

**What each update needs** (nothing, our own backend, a fork, or other hardware) is listed update by update in section 5a, which is the one home for that answer.

**Dependency view: what works with neither a backend of our own nor a fork, what needs a backend, what needs a fork** (written 2026-10-11).

- **Works with neither** (stock firmware, XiaoZhi's cloud agent, our tool server on the Pi): chat through the head by button; the tools (about G2, last exploration, learned notes, battery, persona); "ask the brain" escalation to Claude; an optional handbook in the knowledge base; mounting the head; one voice with a stock voice (stage 4, with its losses); motion by voice through the Pi's allowlisted skills; the face following the model's own emotions. A preset wake word ("Hi, Jason", "Hi, ESP") is a settings build, not a fork and not a backend, but it replaces Petoi's build.
- **Needs our own backend, and probably not a fork:** G2's Piper voice in conversation; self-initiated speech (narration, alarms, announcements) in G2's voice (through `notify`, unverified on the C3); face and mood driven by G2 himself; the brain being Claude with G2's memory directly in the conversation; audio staying in the house; independence from XiaoZhi's free service. A server-side "G2" wake word through the realtime mode is **not possible on the C3** (it needs echo cancellation). The backend itself needs a settings build of upstream (the address is a build setting, `Default OTA URL`), which means the toolchain, and the console's cloud build does not offer that setting.
- **Needs a fork (custom firmware source):** the head as the Pi's microphone and speaker (7b; the realtime-mode shortcut is ruled out on the C3); a host-driven speaker without a backend; keeping Petoi's BiBoard link and tools while changing the server; custom boot and Wi-Fi sounds. A custom wake word "G2" on this chip is not something a fork alone provides (it needs a trained model).
- **Lost if neither is built:** self-initiated speech in any voice (unless the developer push turns out to be usable), G2's own voice (unless voice cloning, which is paid with WeChat Pay), a hands-free "G2" (unless the button trick), audio that stays in the house, and removing the Pi's mic and speaker. So the long-term goals depend on the backend or the fork. The backend covers G2's voice and speech on his own initiative without source changes; it does not cover a hands-free "G2" or removing the Pi's mic and speaker, which need stage 7b (a fork) or an S3 head.
- **First test before choosing:** build a settings-only upstream image for the head's board, point it at a tiny test server of ours, and check that `notify` and the standard speech flow work on the C3. The echo-cancellation and realtime-mode question is already answered by the documents (not on the C3). That test needs the toolchain download (a yes from the owner) and no fork.

**Should we upgrade the head's firmware (v2.0.4)?** Not now. Upgrading means replacing Petoi's build (their BiBoard link, robot tool and face tools) with stock upstream, and nothing in the newer versions is needed by stages 1 to 6. The reasons to change it later are `notify` and a different wake-word preset, and both belong to the stage 7 and 8 decisions; wait for those or for Petoi's own update or source.

## 4. Pros and cons of adopting the head

**Pros**
- A free cloud model handles open-ended chat, small talk and simple questions with no Claude call.
- It can reach G2's abilities and facts through our own tools (proven), so it can answer "what did you do" and "what have you learned" from the Pi without Claude.
- It adds a **screen with an animated face** (look, blink, mouth) that G2 does not have.
- Microphone and speaker sit in the head, a natural place for them, and it is a vendor-supported accessory ($39) with a documented Grove connection.
- Developer certification (a GitHub account) may unlock stronger free models than "XiaoZhi Lite" (section 3a).
- The firmware base is open source (MIT) and Petoi has said theirs will be, so a custom wake word, a host-driven speaker or our own backend stay possible later.
- Everything on the Pi (gait, safety, vision, exploration, memory, reflection) is unaffected: the head complements the Pi, as Petoi says.

**Cons**
- **Voice:** through the head G2 speaks with a stock cloud voice, not his Piper robot voice. G2's own lines (narration, alarms, announcements) cannot be spoken through it without a firmware change.
- **Two voices** while the Pi voice stays; one voice means giving up Pi speech or changing firmware.
- **Wake word:** the side button only, in practice. A different wake word needs firmware, and on this chip (an ESP32-C3) the vendor's wake-word tool offers **only a fixed list of preset words** (custom words such as "G2" are supported only on the S3); the Pi-side route (stage 7b, the Pi's own wake word running on the head's audio) is the way to get "G2".
- **A G2-like voice costs money and needs WeChat Pay** (voice cloning), or needs our own backend (section 3a).
- **Privacy:** every sentence goes to XiaoZhi's cloud; the account needs a phone number; retention terms are unread; tool answers also pass through their cloud.
- **Dependence on a free service** that can change or stop; G2 is silent without Wi-Fi or the service.
- **Personality is thinner:** a small model with a fixed role text, and no mood, traits or memory unless a tool supplies them.
- **Small saving in money** (see section 3).
- **Weight:** 42 g at the front of a robot that is already about 46 percent front-heavy, and the walking policy was trained with an assumed head mass. Not yet checked in simulation.
- **Small chip** (one core, little memory), so the heavy work stays on the Pi.
- **The device's own robot tool produced no movement in our tests** (cause not established), and the head's serial lines stay connected to the BiBoard's input, so it could send motion on its own if its model does call the tool.
- **Two sources of truth to maintain:** an agent configured in a web console, plus our tool server.
- **Firmware is not published**, so any change starts from upstream plus a rebuild of Petoi's additions.

## 5. The target

The head is G2's **mouth, ears and face**. The Pi remains the body's brain (gait, safety, vision, exploration, memory, reflection). The head's free model does the everyday talking; our tools give it facts about G2; Claude answers only the turns that need G2's memory and personality, through an "ask the brain" tool. G2 speaks in one voice, and anything he must say on his own (alarms, announcements) has a route.

## 5a. What each update needs: nothing, our own backend, a fork, or other hardware

**Legend.** **None** = stock firmware, XiaoZhi's cloud agent and our tool server on the Pi (nothing to build). **Settings build** = the unmodified upstream firmware built with different options (for example the server address or the wake-word preset); not a fork and not a backend, but it needs the toolchain (or the console's cloud build for the few options it offers) and it replaces Petoi's build, dropping their BiBoard link, robot tool and face tools. **Backend** = our own server instead of XiaoZhi's cloud (it also needs a settings build so the head points at it). **Fork** = changing the firmware source. **Other hardware** = an S3 head, an add-on module, or wiring.

| # | Update | Stage | Needs | Why |
|---|---|---|---|---|
| 1 | Chat through the head, woken by the button | 1 | **None** | the cloud agent |
| 2 | Tools: about G2, last exploration, what he learned, battery | 1 | **None** | tool server on the Pi |
| 3 | Persona and mood tool | 2 | **None** | tool server |
| 4 | "Ask the brain": hard questions go to Claude with G2's memory | 2 | **None** | a tool that calls Claude through the Pi |
| 5 | A G2 handbook in the knowledge base | 1 | **None** | console feature, static and non-personal only |
| 6 | Stronger free models (developer certification) | 1 | **None** | an account step (a GitHub account) |
| 7 | Mounting the head on G2 | 3 | **None** | hardware and a weight check |
| 8 | One voice: the head's stock voice, Pi speech off | 4 | **None** | loses G2's voice, narration and alarms, hands-free wake word, offline speech |
| 9 | A G2-like voice by voice cloning | 4 | **None** (paid) | the console, WeChat Pay |
| 10 | Motion by voice through the Pi's allowlisted skills | 5 | **None** | a tool on the Pi |
| 11 | The face follows the model's own emotions | 6 | **None** | the model chooses; the role text can steer |
| 12 | A preset wake word ("Hi, Jason" or "Hi, ESP") | 7 | **Settings build** | not a fork or a backend; replaces Petoi's build |
| 13 | The face and mood driven by G2's own mood | 6 | **Backend** | the server sends the emotion messages |
| 14 | G2's Piper voice in conversation | 8 | **Backend** | our server makes the speech |
| 15 | G2 speaking on his own initiative (narration, alarms, announcements) in G2's voice | 4 and 8 | **Backend** (the newer push message, unverified on the C3); a developer push (unverified); or a **Fork** (a host-driven speaker) | the head only speaks inside a conversation unless the server pushes audio |
| 16 | Claude with G2's memory as the live brain, not through a tool | 8 | **Backend** | our server calls Claude |
| 17 | Audio stays in the house; independence from XiaoZhi's free service | 8 | **Backend** | our server replaces the cloud |
| 18 | Pointing the head at our own server | 8 | **Settings build + Backend** | the address is a build setting (`Default OTA URL`) |
| 19 | Hands-free "G2" by the Pi pressing the head's button | none yet | **Other hardware** | two wires and a transistor on a Pi pin; needs the Pi's microphone to stay |
| 20 | A custom wake word "G2" on the head itself | none yet | **Other hardware** (an S3 head, or an add-on module) | not possible on the C3 by a fork or a backend |
| 21 | Interrupting the head while it speaks | none yet | **Other hardware** (an S3 head) | echo cancellation is an S3 feature |
| 22 | The head as the Pi's microphone and speaker; removing the Pi's own mic and speaker | 7b | **Fork** (or an S3 head); **a backend cannot do it** | custom firmware streams the mic to the Pi and plays what it sends |
| 23 | A host-driven speaker without a backend | 7 | **Fork** | custom firmware |
| 24 | Keeping Petoi's BiBoard link and tools while changing the server | 7 and 8 | **Fork** (or Petoi's published source) | a settings build drops them |
| 25 | Custom boot and Wi-Fi sounds | 7 | **Settings build with new sound files** (a source build) | the sounds are compiled in |
| 26 | Removing the head's direct robot command | 3 and 7 | **None** for a role-text discouragement; a real removal needs a **settings build** (which drops Petoi's tool) or a **Fork** | |

**Reading it:** rows 1 to 11 need nothing and make stages 0 to 6. Rows 13 to 18 are the **backend** group. Rows 22 to 24 are the **fork** group. Rows 19 to 21 need other hardware, not a fork or a backend. The long-term goals split like this: G2's voice and speech on his own initiative need the backend (rows 14, 15); a hands-free "G2" needs other hardware (row 19 or 20); removing the Pi's mic and speaker needs the fork or an S3 head (row 22).

## 5b. Build order: where the backend and the fork become necessary

One ordered list, in the order we would build it. **Steps 1 to 9 need neither a backend nor a fork.** The first server code is a tiny test server at step 11; the **backend gate** is step 12; the **fork gate** is step 15. Each step says what it unlocks. The "Needs" words are defined in section 5a.

| Step | What we build | Needs | What it unlocks |
|---|---|---|---|
| 1 | Decide on developer certification (a GitHub account); if yes, compare the stronger models on chat quality and tool-call reliability | None | the head's free brain |
| 2 | Run the tool server as a service; real read-only tools: about G2, last exploration, what he learned, battery | None | the head answers questions about G2 with no Claude call (stage 1) |
| 3 | Role text (2000 characters at most), a voice, a call log; optionally a G2 handbook in the knowledge base | None | a usable talker; the measurements of the savings |
| 4 | A persona and mood tool, and "ask the brain" (hard questions go through the Pi to Claude, rate-limited and logged) | None | personality, and Claude only for the hard turns (stage 2) |
| 5 | Measure the head's current, simulate its mass, mount it (Grove cable to the UART socket, the head's transmit line left disconnected) | None (hardware) | the head on G2's body (stage 3) |
| 6 | One-voice policy: Pi speech off for conversation, sounds stay, commands become tools, the silent stop-word listener stays on the Pi | None | one voice; it **loses** G2's voice, narration and alarms, hands-free wake word and offline speech (stage 4) |
| 7 | A skills tool with an allowlist, run through the Pi's safety | None | "G2, sit" through the head (stage 5) |
| 8 | Steer the model's emotions with the role text | None | a face that follows the conversation (stage 6, partly) |
| 9 | Optional: the Pi presses the head's button when it hears "G2" (one wire from a free Pi pin through a resistor to the button's pad; ground is already shared; details in section 5c) | Other hardware | a hands-free "G2" while the Pi's microphone stays |
| | **Decision point:** if one stock voice and the button trick are enough, stop here. Everything below is what steps 1 to 9 cannot give. | | |
| 10 | Try stock upstream on the head with a preset wake word ("Hi, Jason"): the console's cloud build or the prebuilt image flashed in a browser, backup ready | Settings build | the preset wake word; shows what of Petoi's build is lost; no server needed |
| 11 | Install the toolchain (a multi-GB download, your yes first) and make a settings build whose `Default OTA URL` points at a tiny test server of ours; check the push message and the normal speech flow on the C3 | Settings build + a tiny test server | **tells us whether the backend path works on this chip** |
| **12** | **BACKEND GATE.** Build the real server: OTA endpoint, protocol server, speech-to-text (Vosk), the brain (Claude through our conversation code, with G2's memory), speech (Piper with the robot effect); pick an always-on machine | **Backend** | **G2's voice in conversation; Claude as the live brain; audio stays in the house; independence from XiaoZhi's cloud** |
| 13 | The server pushes to the head: emotion messages from G2's mood, `alert`, and audio files for the push message | Backend | **the face driven by G2's mood; speech on his own initiative (narration, alarms, announcements) in G2's voice**; this repairs the losses of step 6 |
| 14 | Move narration, alarms and announcements to the server and retire the stock-voice policy | Backend | G2 sounds like G2 everywhere on the head, except for hands-free wake and interruption |
| **15** | **FORK GATE.** Fork the firmware (or use Petoi's source if it is published): stream the head's microphone to the Pi, play audio the Pi sends, keep Petoi's BiBoard link and tools, custom boot sounds | **Fork** | **the head as the Pi's microphone and speaker; keeping Petoi's parts while changing the server; custom sounds** |
| 16 | Pass the eight-item gate (section 6), then remove the Pi's own microphone and speaker | Fork (step 15) | **removing the Pi's microphone and speaker** (stage 7b) |
| 17 | Alternative to steps 15 and 16: an S3 head (Petoi's, if offered, or the S3 version of the same board if it fits) | Other hardware, plus the backend | **a custom wake word "G2" on the head, interrupting the head while it speaks**; with these, the backend may reach the Pi-mic removal without a fork (the voice emergency stop would then travel through the server and needs its own independent path) |

**What each gate holds back.** *Before the backend (steps 12 to 14):* G2's own voice in conversation, Claude with G2's memory as the live brain, speech on his own initiative, a face driven by G2's mood, audio staying in the house. *Before the fork (steps 15 and 16):* the head as the Pi's microphone and speaker, removing the Pi's microphone and speaker, keeping Petoi's BiBoard link while changing the server, custom boot sounds. *Not held by either:* a hands-free "G2" (step 9 now, step 17 later) and interrupting the head (step 17).

## 5c. The two goals that matter most, and what is still impossible with both a backend and a fork

**The owner's two priorities (2026-10-11): hands-free talk and responses, and removing the Pi's own microphone and speaker.**

- **Hands-free talk now (step 9, neither a fork nor a backend):** no servo is needed. The head's side button is the board's BOOT button (GPIO 9 in the board profile). Pressing it electrically means connecting that button's signal line to ground for about 100 ms, and the Pi can do that from one GPIO pin through a resistor (about 330 ohms to 1 kilohm), leaving the pin high-impedance otherwise. **Ground is already shared** (the head's ground goes to the BiBoard over the Grove cable, and the BiBoard's ground goes to the Pi over the 5-pin header), so it is **one extra thin wire** from a free Pi pin to the button's signal pad, run along the Grove cable. It needs the head opened and one wire soldered to the button's pad (which pad is the signal side needs a photo of the opened head's board; the plan does not assume it). Pick a Pi pin not used by the amplifier and microphone (GPIO 16, 18, 19, 20, 21) or the BiBoard serial link; `blueprints/biboard-pi-connector.md` has the pin table. GPIO 9 is a boot-mode pin on this chip: the Pi must never hold it low at the head's power-up. The Pi's software would pulse the pin after it hears "G2" and only while the head is idle (pressing the button during a conversation stops it). **A servo is not recommended:** it needs a bracket on the head, adds noise and current, and a spare BiBoard servo port, for what one wire does.
- **This trick needs the Pi's microphone,** so it conflicts with the second priority. With the Pi's microphone gone, a hands-free "G2" needs the head's own audio to reach the Pi (stage 7b, a fork) or an S3 head with our backend (step 17).
- **Removing the Pi's microphone and speaker** needs the fork (7b) on this C3 head, or an S3 head plus the backend. **The backend alone cannot do it on the C3.**
- **The tension with the first goal (offload to the head's free model):** under 7b the head becomes the Pi's microphone and speaker and the conversation runs through the Pi's own pipeline, so XiaoZhi's free cloud model is no longer used and Claude calls come back; under our own backend the brain is ours (Claude, or a cheaper local model) for the same reason. So hands-free plus removing the Pi's mic and the head's free model do not all fit on the C3 head; the free model fits with the button trick and the Pi's mic kept.

**Even with both a backend and a fork, what is still not possible or not guaranteed:**
1. **Interrupting the head while it speaks** is not available on the C3: echo cancellation is an S3-class feature. With the fork, the Pi could do the echo cancellation itself (it plays the audio, so it knows the reference) but that is unproven and delicate; otherwise the head stays half-duplex (it cannot be talked over).
2. **The free cloud model** (XiaoZhi's) is not used once the conversation runs through our backend or the Pi; the savings from it are lost unless the backend routes small talk to a cheaper or local model, which is weaker.
3. **Chip capacity is unknown:** whether the C3 can stream the microphone, play audio, run the screen and keep Wi-Fi stable at the same time. It could fail even with a fork.
4. **Audio hardware parity is unknown:** the head's speaker and microphone against the Pi's amp and microphone (volume for the horns and "oof", microphone noise from the servos near the head, the Pi's tuned microphone gain). Software cannot fix a speaker that is too quiet or a microphone that is too noisy.
5. **The voice emergency stop becomes dependent on a Wi-Fi link** once the Pi's microphone is gone; it needs an independent path (a physical control or the existing halt command), not the head's link alone.
6. **Power and weight are physical:** the head's current on the Grove supply is unmeasured, and about 27 g more at the nose may not suit the walking policy; neither is changed by any software.
7. **Petoi's own face tools and BiBoard link** exist only in Petoi's build; a fork from upstream has to rebuild them (or wait for Petoi's source).
8. **A custom trained wake word on the C3 itself** is not possible, but it is not needed: the Pi's own "G2" wake word, running on the head's audio, replaces it.

Everything else in the plan (steps 1 to 17) becomes possible with both a backend and a fork, subject to items 3 and 4.

## 6. What it takes: the full list

| Area | Work |
|---|---|
| Account and agent | Role text (persona, brevity, English, "call tools for facts about G2"); a chosen voice; keep the MCP access point secret in the Pi's `.env` (`XIAOZHI_MCP_ENDPOINT`); read XiaoZhi's terms for data retention; decide on developer certification (a GitHub account; stronger free models) and on voice cloning (WeChat Pay); a knowledge base with one handbook document is an optional extra (static, non-personal material only). |
| Pi software | Tool server as a service (start at boot, restart on failure, log each call with a count); real tools: about G2, last-exploration recap, experience notes, persona and mood hint; an **"ask the brain"** tool to Claude with a call log and rate limit; later a skills tool with an allowlist; keep tool answers safe to leave the house. |
| Voice policy | One-voice rules (section 7, stage 4); answers to local commands (battery, floor, recap) become tools; alarms and narration need a non-speech route or a firmware change. **The emergency stop must stay on the Pi** (local stop-word listening, silent): never depend on the cloud to stop G2. |
| Hardware | Measure the head's current on the Grove 5 V; check the center of mass and the walking policy in simulation with the head's mass; mount on the head servo; Grove cable to G1; decide whether the head's transmit line stays connected to the BiBoard; check the camera mount and the head do not collide (Petoi: they do not). |
| Firmware (optional) | Trial first with the console's cloud build or the prebuilt image for the head's board (no toolchain; drops Petoi's additions); custom wake word (presets only on this chip); host-driven speaker (text or audio from the Pi, so G2's Piper voice); remove the head's direct robot command; keep Petoi's face tools; toolchain ESP-IDF 5.4.2 and the v2.0.4 source; flash with the backup in hand. |
| Backend (optional) | An OTA endpoint that returns the MQTT and WebSocket settings, set as the firmware's Default OTA URL; a server the head connects to: speech-to-text, the brain, Piper with the robot effect, tool handling; point the firmware at it; a machine that is always on. |
| Safety and privacy | Hardware rules (G2 on his feet, hands near; no moving while he is in pieces); no household names, faces or routines in the role text, tools or knowledge base; endpoint and account details never in chat, logs or the repo. |
| Measurement | Before and after: Claude calls per day (`python -m pi_pipeline.voice.api_log`, `python -m pi_pipeline.memory calls`), share of turns the head handled, tool-call success rate, delay, and quality. |

### Removing the Pi's own microphone and speaker (a long-term goal of the owner)

The first draft of the staged plan assumed they stay. What depends on them today (microphone: Vosk wake word, speech recognition and the local stop words; speaker: Piper speech and every sound):

| Behavior | Needs today | Mic and speaker removed, stock firmware (stage 4) | Mic and speaker removed, with the head as the Pi's audio peripheral (stage 7b) |
|---|---|---|---|
| Conversation | Pi mic and speaker | Works through the head (button, stock cloud voice) | Works, in G2's voice, local |
| Hands-free wake word "G2" | Pi mic (Vosk) | **Lost** (button only) | Works (Vosk on the audio the head sends) |
| Emergency stop by voice ("emergency stop", "freeze", "halt") | Pi mic, local, never the cloud | **Lost** unless another path exists | Works, plus an independent path (the head link is Wi-Fi) |
| Exploration voice control ("go ahead and look around", "that's enough", "tell me what you see", naming an object) | Pi mic | **Lost** while G2 is away from the button (some could become tools, but only after a button press) | Works |
| Spoken narration and alarms | Pi speaker | **Lost** (silent) | Works |
| Sounds (horn, "oof", chirps, ta-da) | Pi speaker | **Lost**, except the BiBoard's own buzzer beeps | Works (audio sent to the head) |
| Sleep and wake by wake word | Pi mic | Button only | Works |

**Order, decided by the owner (2026-10-11): the Pi's microphone and speaker stay installed until the head's own microphone and speaker can do their job.** Nothing in the table above is lost along the way, because they are removed only after stage 7b is proven. Until then every stage, including stage 4, runs with them in place.

**Gate before anything is unplugged (all of these, on the real G2):**
1. The wake word "G2" wakes him from across a room using the head's microphone, and false wake-ups are no worse than today.
2. The voice emergency stop works from the head's audio, and an independent stop path (not the head's Wi-Fi link alone) exists and was tested.
3. Exploration commands work by voice while he is walking away from the button.
4. Speech, narration, alarms and every sound play on the head's speaker at a usable level, with no clipping and no echo into the microphone.
5. The head's audio link survives the things that go wrong: Wi-Fi dropping and returning, the Pi restarting, the head rebooting, an hour of use.
6. The Pi's load and the delay from speech to reply are no worse than today (the Pi already runs some control ticks late during exploration).
7. Power: the head's added current on the Grove supply fits the battery budget, and the Pi's saved current is measured.
8. A way back: the removed mic and speaker (and their wiring notes in `blueprints/`) are kept so they can be reinstalled.

So with the stock firmware, if they were removed early, this would cost hands-free control, the voice emergency stop, exploration voice commands, narration and sounds. **Even stage 7 as first described (wake word plus a host-driven speaker) does not cover the microphone side.** What does is **stage 7b** below, which is also what Petoi said the head's firmware could do (stream the microphone out, accept audio to play).

## 7. Staged integration

Each stage ends in something that works on its own, so the project can stop after any of them.

**Stages at a glance: what each one gains and what it costs**

| Stage | What we gain | What we lose or risk | Needs (section 5a) |
|---|---|---|---|
| **0. Bench bring-up** (done) | The head talks in English on its own account; our tool server answers its model; the firmware is backed up. | Nothing from G2's existing setup. The test audio goes to XiaoZhi's cloud, and the account holds a phone number. | None |
| **1. Talker + read-only tools** | Free chat about G2; "what did you do" and "what have you learned" answered from the Pi with no Claude call; real measurements of the savings. | Nothing existing is removed. There are briefly two voices (the head on the button, the Pi as usual), a small service to keep running, and tool answers pass through the cloud. | None |
| **2. Personality + escalation** | The head carries G2's mood and traits through a tool; hard questions go to Claude with G2's memory, spoken by the head; Claude is called only then. | Casual chat is flatter than Claude's. A hard question takes two hops, so it is slower. A new rate limit and call log to maintain. | None |
| **3. Mount on G2** | The head on his body with the face in front; microphone and speaker in the head. | About 27 g more at the nose than the 15 g head the walking policy assumes, which may change the gait; unmeasured current on the Grove supply; a risk that the head's serial line sends commands (default: leave it disconnected). | None (hardware) |
| **4. One voice, no firmware change** | A single voice for all conversation, and answers to commands as tools. | **G2's robot voice; spoken narration and alarms** (they become sounds); the Pi's hands-free "G2" wake word (the head is button-only); local, offline speech (all speech now goes to the cloud). The silent stop-word listener stays on the Pi. | None; G2's voice and speech on his own initiative need the backend |
| **5. Motion through the head** | "G2, sit" and similar through the head, with the Pi's eased stand-up and fall guard around it. | A new way for G2 to move: it needs an allowlist, refusal rules and trust in a cloud model that may mishear. | None |
| **6. The face** | An expressive screen tied to his mood and events. | It depends on whether the cloud model can call the head's own face tools; if not, it waits for stage 7. | None for the model's emotions; the backend for G2's mood |
| **7. Firmware fork** (not decided) | A hands-free wake word; the Pi can send text or audio to the head's speaker (self-initiated speech and the robot voice for those lines return); the head's direct robot command removed. | We maintain a fork and no longer get Petoi's updates; a multi-GB toolchain download; a flash (the backup is the way back); Petoi's additions rebuilt unless their source appears. Conversation is still the cloud voice. | Settings build for a preset wake word; Fork for a host-driven speaker |
| **7b. Head as the Pi's mic and speaker** (firmware) | Everything the Pi voice does today (G2's voice, wake word, voice stop, exploration commands, narration, sounds) from hardware in the head, local; the Pi's own mic and speaker can be removed. | The free cloud brain (the Pi's Claude pipeline keeps talking); a Wi-Fi link between head and Pi that the voice stop must not depend on alone; unproven chip capacity. | Fork (or an S3 head) |
| **8. Our own backend** (optional) | G2's own voice everywhere; no audio to XiaoZhi's cloud; independence from the free plan. | The free brain: Claude calls return (or a weaker local model); a machine that must be on; more moving parts. | Backend + a settings build |

**Stage 0: bench bring-up and the tool proof. Done 2026-10-11.** Gets working: the head talks in English on its own account; our tool server answers its model; the firmware is backed up.

**Stage 1: a talker with read-only tools, beside the Pi voice (no mounting).**
- Work: run the tool server as a service (after the certification decision, repeat the tool-reliability test on a stronger model); replace the test tools with `g2_about`, a last-exploration recap and the experience notes; write the role text; choose a voice; log every tool call.
- Gets working: press the head's button and ask what G2 is, what he did, what he has learned; answers come from the Pi with no Claude call. The Pi's own voice is unchanged.
- Measure: tool-call reliability over a set of questions; the delay; how many of G2's usual Claude turns the head can take.
- Stop point: if the model calls tools unreliably, the head stays a toy and nothing else is affected.

**Stage 2: personality and escalation.**
- Work: a persona tool (current mood hint, traits); an **"ask the brain"** tool that sends a hard question through the Pi to Claude with G2's memory and personality, rate-limited and logged.
- Gets working: casual chat is free; hard questions get Claude's answer with G2's memory, spoken in the head's voice. Claude is called only then.
- Measure: Claude calls per day against the baseline; how often the model chooses to escalate.

**Stage 3: mount the head on G2.**
- Work: current measurement; center-of-mass and gait check in simulation with the head's mass; mount; Grove to G1; decide about the head's transmit line (a safe default is to leave it disconnected); standing test, then a short walk, with G2 on his feet and hands near.
- Gets working: the head on G2's body, powered by him, his face in front.
- Risk: weight at the nose; if the policy copes poorly, the mount stops here.

**Stage 4: one voice, no firmware change.**
- Work: turn off the Pi's spoken output; keep its non-voice sounds (horns, "oof", chirps); answers to local commands become tools; narration and alarms become sounds or nothing; the Pi keeps a silent local stop-word listener.
- No route found for the Pi to push speech to the head without firmware or a backend (section 3); a developer-only real-time push exists on paper and should be found before relying on it (section 3a), and voice cloning could give the head a G2-like voice behind a payment decision.
- The Pi's microphone and speaker stay installed through this stage (they come out only after stage 7b passes its gate), so the silent stop-word listener keeps working.
- Gets working: G2 has one voice (the head's, a stock voice) for all conversation. Loses: self-initiated spoken lines, his current robot voice, the hands-free "G2" wake word (the head is button-only), and offline speech.
- Decision gate: if losing the robot voice and the spoken narration is too much, stop at stage 3, or go to stage 7.

**Stage 5: motion through the head, via the Pi.**
- Work: a skills tool with an allowlist (sit, wave, nod and similar), run through the Pi's skill layer with the eased stand-up and the fall guard; refuse while halted, exploring or on low battery; log each use.
- Gets working: "G2, sit" works through the head with the Pi's safety around it.

**Stage 6: the face.**
- Work: find out whether the cloud model can call the head's own face tools; if so, tie expressions to mood and events. The face follows the model's own emotion messages (19 names, section 3a); G2 can only steer them through the role text unless we run our own server.
- Gets working: an expressive screen. If those tools are unreachable, this needs firmware (stage 7).

**Stage 7: firmware fork (decision gate; not decided).**
- Work: wake word (**a preset one only**: on the C3 the vendor's tool has no custom words; "G2" arrives with stage 7b); host-driven speaker so the Pi plays G2's Piper robot voice through the head; the head's direct robot command removed; Petoi's face tools kept.
- Gets working: a hands-free wake word and G2's own voice for his announcements. Conversation is still the cloud voice unless stage 8.
- Trial path with no toolchain: build stock upstream for the head's board in the console (10 a day) or flash the prebuilt image with ESP-Launchpad; it drops Petoi's additions and the backup restores them; a full flash may need the device re-added to the account.
- Prerequisites: Petoi's source (or a rebuild from upstream v2.0.4); the ESP-IDF 5.4.2 toolchain (a multi-GB download, needs approval); the backup in hand.

**Stage 7b: the head as the Pi's microphone and speaker (firmware change; this is the route to removing the external mic and speaker, and only after the gate above is met).**
- Work: firmware that streams the head's microphone audio to the Pi over the local network (not the cloud) and plays audio the Pi sends; the Pi's existing voice pipeline (wake word, speech recognition, stop words, exploration commands, Piper, sounds, the audio gate) runs on that audio unchanged; check echo between the head's speaker and microphone; keep an independent stop path (the head link is Wi-Fi, so it must never be the only way to stop G2); then remove the Pi's microphone and speaker.
- Gets working: everything the Pi voice does today, from hardware in the head: G2's own voice, the hands-free wake word, the voice emergency stop, exploration commands, narration, alarms and all the sounds. Local and private. One set of audio hardware, the screen face on the same unit.
- Loses: the free cloud brain for chat (the Pi's own pipeline keeps using Claude as it does now; the head's cloud model would be off), and a dependence on a reliable Wi-Fi link between the head and the Pi.
- Prerequisites: stage 7's firmware work plus microphone streaming (a prebuilt upstream image for the head's board exists, see section 3, for trying stock upstream first); whether the C3 can stream audio, play audio, run the screen and keep Wi-Fi stable at once is **not yet known**.

**Stage 8: our own backend (optional).**
- Work: a server for the head's audio protocol: speech-to-text, the brain (Claude, or a local model), Piper with the robot effect; the firmware pointed at it; an always-on machine (a Mac works only while it is on and awake; a small always-on computer is roughly $100 to $200, or a rented server a few dollars to about $20 a month; the Pi is already busy).
- Needs: an OTA endpoint (its reply carries the MQTT and WebSocket settings), the firmware's Default OTA URL pointed at it, a protocol server, and Piper as a custom speech source (the community servers do not list it).
- Gets working: G2's own voice everywhere and no audio to XiaoZhi's cloud. Costs: the Claude calls come back (the brain is Claude again), so the call savings from the free model are gone.

**Existing community servers (read about, not downloaded; for stage 8).** The firmware README lists several open-source backends that speak the same protocol; the main one is [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) (Python, Java and Vue, MIT). From its README: MQTT+UDP, WebSocket and MCP access-point support; local speech-to-text (FunASR, SherpaASR) and local text-to-speech (FishSpeech, GPT-SoVITS, Index-TTS, PaddleSpeech; **Piper is not listed**); any LLM with an OpenAI-style interface; Docker or source install. Its minimum is 2 cores and 2 to 4 GB of memory, **more than the Pi Zero 2 W has** (512 MB); it calls itself not production-ready and not security-tested. It documents **no** "send text to a device" interface (only MCP commands sent from its console). The head would need to be pointed at its OTA and WebSocket addresses, which is a firmware matter. Our own small server speaking the documented protocol (`docs/websocket.md` and `docs/mqtt-udp.md` in the firmware source) remains the alternative to adopting one of these.

**The trade-off in one line:** the free brain and the cloud voice come together; G2's own voice everywhere comes with our own backend, where we pay for the brain again.

## 8. Decisions waiting on the owner

1. Whether to adopt the head as G2's voice at all, or keep the Pi voice and use the head as a trial.
2. Whether a stock cloud voice is acceptable for G2.
3. Whether to fork the firmware (stage 7) or wait for Petoi's source. Not decided; no fork work has started.
4. Whether a backend is worth running (stage 8), and on what machine.
5. What the head's model may do beyond talking (stage 5), and what may leave the house through tools.
6. Decided 2026-10-11: the long-term goal is to remove the Pi's own microphone and speaker, but only once the head's microphone and speaker can do their job. The route is stage 7b (a firmware change), with the gate in section 6 first.
7. Whether to certify as a developer (bind a GitHub account) for stronger free models and higher limits.
8. Whether to buy voice cloning (WeChat Pay, 99 yuan a year as of March 2025), or stay with a stock voice, or wait for stage 8.
9. Whether to ask XiaoZhi or Petoi about the developer push interface and about publishing the head's firmware.

## 9. Still to verify (none of it blocks writing this or stage 1)

- How reliably the free model calls tools (rate over many tries) and how long a tool round trip takes.
- Whether the cloud model can call the head's own face and volume tools.
- Behavior over long sessions and Wi-Fi drops; whether the tool server reconnects cleanly overnight (it reconnects with a growing pause; not yet exercised for hours).
- Whether the console has an interface to update the role text from code (for a live persona).
- XiaoZhi's data-retention terms (they sit behind the login). The knowledge base's limits are now known (1 and 1 on the free tier).
- The head's power draw; the exact serial pins; how the head's serial output looks on the wire (needs its transmit line, see section 3).
- The effect of the head's mass on the walking policy (simulation first).
- Whether the developer real-time push has an interface we can use, and where it is documented.
- Whether the cloud made the robot-tool call in our tests (section 3a, item 13).
- Whether a cloned voice of the robot voice sounds good (needs the paid feature).

**Documents:** everything read is summarized, with every address, in [`../research/xiaozhi-vendor-docs.md`](../research/xiaozhi-vendor-docs.md) (its section 13 is the page index and section 14 lists what was not read). Not read: the breadboard wiring and parts pages, the third-party MCP pages, the serial tool page, the supported-boards list, the rest of the echo-cancellation page, the knowledge base's images; and, behind the login, the console, plans, terms and privacy. Petoi's three wiring photos and the full Role template were read in the browser.

## 10. How-to reference

- **Read the head's log (Mac):** plug the head's USB-C into the Mac, find the new `usbmodem` port, open it at 115200 (this reboots the head). Do not do this while the Grove cable also powers it.
- **Run the tool server (Pi):** `cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.head` (reads `XIAOZHI_MCP_ENDPOINT` from `.env`; logs request names, never the address). Stop with Ctrl-C or `pkill`.
- **Set the access point:** copy it from the console's role page; add it to the Pi's `.env` with a hidden-input command so it never appears on screen or in chat; verify only with a count and the first characters of the line.
- **Backups:** the head's firmware is read with esptool's read-only `read-flash`; the copy and its checksum are on the Mac, outside the repo. Restoring is a write and needs the owner's go.
- **Safety:** G2 does not move while he is in pieces (battery off, or USB power alone so the BiBoard reports low power); never flash anything without a checked backup; never put the access point, account details or the Wi-Fi settings in the repo or in chat.

## 11. Related

[`../research/petoi-ai-head-evaluation.md`](../research/petoi-ai-head-evaluation.md) (the original questions, vendor answers, behavior inventory, scorecard) · [`../research/xiaozhi-vendor-docs.md`](../research/xiaozhi-vendor-docs.md) (our summary and translation of the vendors' documents, with the list of pages still to collect) · [`../research/xiaozhi-esp32-review.md`](../research/xiaozhi-esp32-review.md) · [`../research/firmware-fork-case.md`](../research/firmware-fork-case.md) · [`../guides/swappable-llm.md`](../guides/swappable-llm.md) · [`../guides/settings-switches.md`](../guides/settings-switches.md) · [`reflection-plan.md`](reflection-plan.md)
