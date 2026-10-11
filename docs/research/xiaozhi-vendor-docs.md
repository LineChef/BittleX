# XiaoZhi AI and the Petoi AI head: the documentation in English

An unofficial English summary and translation of the vendor documentation for the **XiaoZhi AI firmware and cloud service** and for the **Petoi AI head**, which runs XiaoZhi firmware.

## Contents

- [About this document](#about-this-document)
- [Key facts at a glance](#key-facts-at-a-glance)
- [1. Concepts and vocabulary](#1-concepts-and-vocabulary)
- [2. Getting started](#2-getting-started)
- [3. Accounts, models and the developer program](#3-accounts-models-and-the-developer-program)
- [4. Voices and voice cloning](#4-voices-and-voice-cloning)
- [5. Wake words](#5-wake-words)
- [6. Firmware: versions, flashing and building](#6-firmware-versions-flashing-and-building)
- [7. The device protocol](#7-the-device-protocol)
- [8. MCP tools](#8-mcp-tools)
- [9. Knowledge base](#9-knowledge-base)
- [10. Hardware notes](#10-hardware-notes)
- [11. Community and upstream material](#11-community-and-upstream-material)
- [12. The Petoi AI head](#12-the-petoi-ai-head)
- [13. Page index with addresses](#13-page-index-with-addresses)
- [14. Not yet read and open questions](#14-not-yet-read-and-open-questions)
- [15. Glossary](#15-glossary)

## About this document

- **Status:** unofficial and community-made. It was prepared with machine assistance (a language model read the Chinese pages and wrote this summary). It has **not been reviewed by a native Mandarin speaker or by the vendors**, so details may be wrong. Corrections are welcome.
- **Sources:** the XiaoZhi documentation hub on Feishu ("小智 AI 聊天机器人百科全书", the XiaoZhi AI Chatbot Encyclopedia) and the pages linked from it, written by the XiaoZhi project team (the open-source licence names Shenzhen Xinzhi Future Technology Co., Ltd.; the service's own addresses use the name Tenclass) and by community authors; the open-source firmware repository ([xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)); Petoi's guide pages ([guide.petoi.com](https://guide.petoi.com)); and two community projects. Section 13 lists every page with its address and says which were read.
- **Rights:** this text is a summary in its own words and a short quotation of titles and field names; it is not a copy of the originals and it does not include their images. **All rights in the original documents remain with their authors**; please follow the links for the full text. Permission from the original authors would be needed before publishing a fuller translation.
- **How it was read:** as a guest in a web browser. No account was created and no login was used. Pages that need a login (the console itself, the plans, terms and privacy pages) were not read.
- **Dates:** the dates given are each page's own "modified" date. Most XiaoZhi pages date from 2025, some from 2026. Prices, model lists and limits change; treat them as of the page's date.
- **Conventions:** every Chinese title is followed by its English meaning. Names like `/xiaozhi/ota/` are quoted as they appear.

## Key facts at a glance

1. **A cloud MCP access point lets you attach your own tool server to an agent.** The console shows it on the agent's role page (bottom right) with the connection status, the registered tools and a secret address (section 8).
2. **Tool rules:** clear tool and parameter names, results up to about **1024 bytes**, a limited tool list (counted in tokens), and a limited number of connections per access point (section 8).
3. **Push messages:** the protocol has server-to-device messages (`alert`, `tts`, `custom`, and in newer firmware `notify`); a developer-only "real-time notification push over MQTT" is listed in the activation design. No public description of that push interface was found (section 7).
4. **Developer status** is gained in the console by binding a GitHub account. It unlocks stronger models (Qwen 3, full DeepSeek, Doubao and previews) and higher limits (section 3).
5. **Voice cloning** (public beta) costs 99 yuan a year for 8 clones, paid with WeChat Pay, from an 8 to 30 second clean recording (section 4).
6. **Wake words:** chips of the C3 and C6 families can only use a fixed list of preset words; custom words are for the S3 and P4; a truly custom word is a commercial service of the chip maker (section 5).
7. **A device finds its server through an OTA address**; the reply supplies the activation code, the MQTT and WebSocket settings and the firmware. The OTA address is a build setting (section 7).
8. **A prebuilt firmware exists for the Petoi head's board** (`BOARD_TYPE_LICHUANG_C3`), flashed as one `merged-binary.bin` at address 0x0; the console also offers a **cloud firmware build** (10 builds per account per day, official boards only) (section 6).
9. **Petoi's head connects with one Grove cable**, to a different socket depending on whether the BiBoard V1 has the voice module (section 12).
10. **Forcing download mode:** hold BOOT, tap RST, release BOOT.

## 1. Concepts and vocabulary

- **Agent:** the virtual half of a XiaoZhi device (the physical half is the device terminal and its firmware). It holds a role, a voice, a language model and a memory. One agent can serve several devices, which then share the role, configuration and memory. You create the agent first, then add a device to it.
- **Console:** the XiaoZhi web control panel at xiaozhi.me, opened with the Console button after signing in. Its navigation has the agents, voice cloning and the knowledge base (test version).
- **Role:** template buttons, an agent name, an assistant nickname, a role voice (with a play button), the role introduction (up to 2000 characters, the system prompt), the language model, and Save. A device restart is needed for a new configuration to take effect.
- **Memory:** a box of about 1000 characters, regenerated at each conversation, with a "clear memory" button. The FAQ advises clearing it after changing the model. Long-term memory is "coming soon".
- **Voiceprint (speaker recognition):** console, agent, "声纹识别": add a speaker from a clean sample of two seconds or more so the agent can tell who is speaking. Petoi notes this tab is not available on the free plan.
- **Role name versus wake word:** the role name is only the agent's name for the model; it is unrelated to the offline wake word.
- **Emotion:** each reply carries a mood (one emoji token) that drives the on-screen face (section 7).

## 2. Getting started

**First boot and Wi-Fi.** With no saved network the device opens a hotspot named `Xiaozhi-XXXX` (for example `Xiaozhi-E7C1`) and announces it ("Alert: Wi-Fi configuration mode: connect the hotspot, browse to http://192.168.4.1"). Connect a phone or computer to it; the setup page opens by itself, or open `http://192.168.4.1` while staying on that network. Choose your network from the list of **2.4 GHz** networks (the name fills in; an iPhone hotspot needs "maximum compatibility" on), type the password, press Connect. The scan takes about 5 seconds; do not close the page. On success it shows a green tick and "device will restart in 3 seconds", then joins the network.

**Several networks or one.** The generic vendor page says the device remembers only the last network, re-enters setup after three failed connections, and that holding BOOT while the blue light blinks during connection also enters setup. Petoi's page for its head describes newer behavior: it stores several networks, tries the most recent one five times, then the others, then enters setup (about 10 seconds later it says "Please configure the network"); briefly pressing BOOT after a restart enters setup, and the setup page lists the saved networks with an X to delete one.

**Activation.** After the device is online and restarted, it plays a prompt with a **6-digit code** (wake it again to hear it repeated; on boards without an offline wake word use the button). On xiaozhi.me: sign in (the first time you register with a mobile phone number and an SMS code), open the Console, **create an agent**, choose Add Device, type the code, confirm. A new boot gives a new code. If the device does not announce a code it is probably already bound to an account: unbind it there, or follow the page in section 3.

**Unbinding and lost accounts** (page "无法接收手机验证码、忘记密码或解绑设备", May 2025): the page covers not receiving the SMS code, a forgotten password, forgotten username and password, finding a device's ID and MAC address, and a device already bound by someone you cannot reach. For several devices fill in a spreadsheet template with each device ID and MAC address and email it with the subject 【解绑设备】 (unbind devices). The MAC address is the value on the log line `wifi:mode : sta (…)` that appears about 550 ms after boot on the serial port (use any serial tool, 115200 baud).

**Common problems from the FAQ and the Wi-Fi page:** the hotspot is invisible (the board's antenna is weak on some S3 boards; holding a finger on the antenna helps; or the wrong firmware for the board); the status RGB light can stay dark without harm; no sound or crackling (check the speaker amplifier wiring and its gain pin ground; a 3 W speaker on weak USB power stutters, use a 5 V 2.1 A source); the wake word does nothing (it must be exactly "你好小智", check the microphone wiring and the microphone orientation).

## 3. Accounts, models and the developer program

**Models.** The FAQ (March 2025) lists the models the console offered then: Qwen 2.5 (real-time, the default and the fastest), DeepSeek V3, Doubao 1.5 Pro and Qwen Max 2.5; **models other than the real-time one add about one second of delay**. The developer page (July 2025, below) lists the current free and developer tiers: the ordinary free tier has "XiaoZhi Lite" and a quantized DeepSeek.

**Developer certification** (page "小智AI 开发者认证", July 2025). In the console, open the avatar menu, choose "认证为开发者" (certify as developer), then **bind a GitHub account**; all models and features unlock. Some commenters could not complete it (the certification screen stalled, or GitHub was unreachable from China).

| Feature | Ordinary user | Developer |
|---|---|---|
| Language models | XiaoZhi Lite, quantized DeepSeek | those, plus Qwen 3, full DeepSeek, Doubao, and (preview, time-limited free) GLM 4.7 and Kimi K2 |
| Vision model | time-limited free | time-limited free |
| Memory | none, short-term; long-term "coming soon" (time-limited free) | same |
| Role voices | Mandarin, other languages | plus preview Mandarin voices (time-limited free) |
| MCP services | weather, jokes, music, news; knowledge base (preview, time-limited free) | plus internal-preview MCP services (time-limited free) |
| Knowledge base | simple document parsing; 1 knowledge base; 1 document each | AI-optimized parsing (time-limited free); 10 knowledge bases; 10 documents each |
| Bound open-source devices | 10 | 100 |

**Developer capabilities in the activation design.** The activation design page (section 7) lists, for developers: view a serial number's activation and deregister it, read device status and usage statistics, **real-time notification push (needs an active MQTT connection)**, and read and write an agent's configuration (marked "to be evaluated").

## 4. Voices and voice cloning

- **Choosing a voice:** console, the agent's role configuration, "role voice": a list with a play button and language tags (Mandarin voices, some Cantonese or Taiwanese-accent ones, and a few for other languages such as Japanese or English). Save, then restart the device.
- **Voice cloning** (page "小智AI声音复刻（公测）控制台操作指引", public beta, March 2025): in the console open **声音复刻** (voice cloning). **Price (as of March 2025): 99 yuan per year** (list 150, discounted 51) with **8 clones**, paid with **WeChat Pay** (scan a QR code in the WeChat app). **Recording:** 8 to 30 seconds of one person's clear speech without noise or echo, made in the browser with a microphone or uploaded as a WAV or MP3 file. After a successful clone, wait **about 5 minutes** before it can be chosen as the role voice; then save and restart the device.
- **Notes the page makes:** meant for personal assistants and language learning; users must obey the law (cloning can be abused for fake speech). The mobile-browser steps are marked "to be added".
- **User reports in the page comments (anonymous, unverified):** some devices went silent after a clone was selected; some read "8 clones" as only the latest being kept; a clone stops working when the yearly subscription ends; no Cantonese, Japanese or Vietnamese option at the time; unclear whether an uploaded recording may be any text.

## 5. Wake words

- **Default:** "你好小智" ("nǐ hǎo xiǎo zhì", hello XiaoZhi), not "小智你好" or the role's name. The vendor's pages say C3-series boards have no offline wake word and use the **button** to wake. Petoi's page for its head says to wake with "Hi, Jason" or the Boot button.
- **Changing it is a build-time setting** (page "关于唤醒词更改及配置操作步骤", March 2025): in the firmware's configuration menu (`idf.py menuconfig`, or the VS Code ESP-IDF extension), ESP Speech Recognition, "use wakenet", then a list of wake words. About 25 words are offered **for the S3**; for other chips the list is short (a commenter confirmed: set the target to ESP32-S3 and many appear). Rebuild and flash; if the firmware was erased, set up Wi-Fi again. The serial log may still print "小智" after a change; this is harmless.
- **Online compile** (section 6) also offers the wake word as a dropdown of presets, and allows none.
- **Fully custom word (S3 only)** (Windows build page, section 6): in `idf.py menuconfig`, "Xiaozhi Assistant", set **"Wake Word Implementation Type"** to **"Multinet model (Custom Wake Word)"** (the three choices are Disabled, Wakenet model with AFE, Multinet model); the page shows a log where a custom word was recognized.
- **Presets only on C3 and C6:** the assets generator tool (section 11) lists WakeNet9s presets (examples "Hi, 乐鑫" and "你好小智") for C3 and C6, and custom command words only for the S3 and P4.
- **A truly custom trained word** is a commercial service of the chip maker, Espressif: the customer supplies wake-word audio (the page cites a corpus of over 20,000 samples) or Espressif collects it; training and tuning take **2 to 3 weeks**; there is a minimum customization fee; time and cost depend on the number of words and the production volume. The FAQ says the open-source project itself cannot create custom words.
- **Add-on module scheme** (page "小智AI终端ASR自定义唤醒词简单方案", September 2025): a separate offline speech-recognition module (an "ASR PRO" core board with an auto-downloader and a microphone, plus jumper wires) listens for your own wake word and triggers the XiaoZhi board; it needs wiring and board-specific settings (the page's detail sections were collapsed and were not read).

## 6. Firmware: versions, flashing and building

**Versions and downloads.**
- **v2.2.4** (latest listed; page modified March 2026): a list of small changes (more boards, fixes). From v2.0.x the flash partition table changed (to allow online custom fonts, emoji and backgrounds), so **a device cannot be upgraded automatically from v1.9.x or earlier**; flash v2.0.x or newer by hand. **The v2.2.4 source needs ESP-IDF 5.5.2 to build.** A screenshot of the repository shows v2.4.0 "Migrate to IDF 6.0" as the latest release at that time, so the newest source needs ESP-IDF 6.
- **v2.0.5** (test version, February): source as a zip (4.37 MB) and tar.gz (3.76 MB) and a table of prebuilt firmware; among the rows are **`BOARD_TYPE_LICHUANG_C3` → `v2.0.5_lichuang-c3-dev.zip` (2.16 MB)** and the S3 board's `v2.0.5_lichuang-dev.zip`. Names starting `bread` are breadboard versions, `ml307` or `NT26` endings are 4G versions, `128x64` and similar are screen resolutions.

**Flashing without a development environment** (page "Flash工具/Web端烧录固件（无IDF开发环境）", modified January 2026).
- **Method 1, Espressif's Flash Download Tool 3.9.7** (a 20.63 MB zip; Windows recommended; no Chinese characters in the tool's or the file's folder path). Connect by USB (a data cable, not charge-only), ChipType ESP32-S3 (choose ESP32-C3 for C3 boards), WorkMode Develop, LoadMode UART; tick the file's box, set the address to 0x0, choose the COM port, leave SPI speed and mode at their defaults (a higher baud rate is faster); press START; FINISH means done (a few minutes); then press RST to restart into Wi-Fi setup mode. The UART port on the S3 dev boards appears as a CH340 or CH343 serial device (driver links are on the page).
- **The firmware zip** holds `merged-binary.bin`, written at 0x0. A table of 33 boards maps board type to file name; **row 10, "立创·实战派ESP32-C3开发板", `BOARD_TYPE_LICHUANG_C3`, `vx.x.x_lichuang-c3-dev.zip` is the Petoi head's board**; row 9 (S3) is a different board.
- **Method 2, a third-party web flasher** (鹿戴马物联, `16302.com`): detects the chip and picks the firmware; needs Edge and a WeChat or account login.
- **Method 3, ESP-Launchpad** (`espressif.github.io/esp-launchpad`, Chrome or Edge): the DIY page, Connect and pick the port ("Connected to device: ESP32-xx"), load `merged-binary.bin`, address 0x0, Program; progress shows in the Console; press Reset Device and Confirm; the board then logs the Wi-Fi setup prompt. Troubleshooting: if the port is not listed, check the cable, the port and other programs using it; if Program stays grey, reconnect, reload the page (F5 or Ctrl-R) and reselect the file; if the board will not run after flashing, the firmware is not for that board.
- **Boot mode:** hold BOOT, tap RST (about half a second), release BOOT. The page also gives the DTR and RTS levels for "auto program".

**Online firmware compile** (page "小智AI 固件在线编译功能操作教程文档", August 2025). In the console, the top-right menu **固件编译** (firmware compile). Only boards already merged into the official GitHub repository are supported; the board list is fixed. Options: target chip, board type, board ID, firmware language, **wake word (a dropdown of presets; may be left off)**, display style (default, WeChat-like, emoji animation), multi-line chat (default style only), camera mirror and flip, **echo cancellation (AEC) on or off**, **Wi-Fi setup method (hotspot or ESP-BluFi)**. **Limit: 10 builds per account per day.** After a build you can see progress, cancel, view the build history (board, version, parameters, status, time), then flash it in the browser or download the `.bin` for the Flash Download Tool or to give to others.

**Building from source** (pages "Windows搭建 ESP IDF开发环境&编译小智", August 2025, and "小智AI终端开源项目配置修改等操作指引（一）", April 2025; both are mostly screenshots).
- Install ESP-IDF (the Windows page covers ESP-IDF 6 through Espressif's Installation Manager and ESP-IDF 5.5 through an offline installer; Linux and macOS are mentioned), test it, download the source, set the chip type (the default is plain ESP32, so set it to the right one), choose the board type, build. The source's version decides the IDF version: v2.2.4 needs 5.5.2; older sources used 5.3 or 5.4; the newest needs 6.
- **Configuration menu** (`idf.py menuconfig`, "Xiaozhi Assistant"): **Default OTA URL** (the shipped value is `https://api.tenclass.net/xiaozhi/ota/`), Flash Assets, Default Language, Board Type, LCD type, display style, **Wake Word Implementation Type**, Enable Audio Noise Reduction, **Enable Device-Side AEC**, **Enable Server-Side AEC (Unstable)**, Enable Audio Debugger, Enable Acoustic Wi-Fi Provisioning, **Enable Custom Message Reception**.
- **Server address:** the page says the newest source (1.6.2 at the time) removed the menu entry for the WebSocket address; the WebSocket address now comes from the OTA reply. Check out v1.6.0 or older to set the WebSocket address directly (the connection type is also a setting there: MQTT plus UDP, or WebSocket). With newer firmware you point the device at another server by changing the **Default OTA URL** and having that server return the connection settings (section 7).
- **Board pins and screen:** each board has `main/boards/<board>/config.h` (microphone, amplifier, screen pins, screen size), and editing it needs a rebuild and flash. The flash size and the partition table (`partitions.csv`, or a menu entry in new versions) are also configurable. The page has a section for an I2C driver conflict error and one for installing the serial driver.
- **AEC** (page "小智AI终端开源项目SDK配置AEC支持操作指引", April 2025, only the start was loaded): for developers; ESP-IDF 5.0 or newer (5.3.2 recommended); the procedure shown sets the target chip to **ESP32-S3** and enables the real-time conversation mode with voice interruption (AEC) in the SDK settings. Whether other chips support it is not stated in the part read.

**Prompt sounds** (page "修改提示音P3文件（例如开机播报和配网播报）", February 2025). The built-in announcements (boot, Wi-Fi setup, upgrade, welcome) are **P3** audio files in the firmware's language folder (`main/assets/zh-CN`). Convert a WAV to the required sample rate, run the project's `convert_audio_to_p3.py` (or the batch tool `batch_convert_gui.py` in `scripts/p3_tools`), put the `.p3` in that folder and rebuild; the new sound then appears in the generated `lang_config.h` and is referenced from the code (for example `P3_WIFICONFIG`). Commenters: the converter needs the `opuslib` library and a built Opus library, and the build file's dependency list must include the language and common sound sets.

**Firmware repair page** ("固件修复", June 2025): upgrade steps for an old 4G firmware version's communication problem, per product family. Not otherwise relevant.

## 7. The device protocol

**How a device finds its server: the OTA interface** (page "OTA 接口文档", April 2025). The device sends `POST /xiaozhi/ota/` (the example host is `api.tenclass.net`) with headers `Device-Id` (the MAC address), `Client-Id` (a UUID that is **regenerated when the flash is erased or the firmware reinstalled**), `User-Agent` (name and version, for example `esp-box-3/1.5.6`) and optionally `Accept-Language`, and a JSON body: `application` (name, version, compile time, IDF version, `elf_sha256`), `mac_address`, `uuid`, `chip_model_name`, `flash_size`, `psram_size`, `partition_table`, and `board` (type, name, ssid, rssi). **The reply** carries: `activation` (a `code` and a `message` for the screen), `mqtt` (server settings), `websocket` (server settings), `server_time` (timestamp, timezone, offset) and `firmware` (latest version and download address). Errors: 400 for a missing or invalid field, 500 for a server error. This reply is how the device learns which server to use.

**Activation flow v2** (page "激活设备流程 v2", April 2025). (1) The manufacturer keeps a board id, a firmware list and a license list (serial number, an HMAC key, generated and activation dates, status). (2) On an ESP32 the serial number and HMAC key are burned into the chip's eFuse. (3) The device calls the OTA address with its current version, MAC address and client id. (4) If the firmware is current and the reply has an `activation` field, the device speaks the code and the user adds the device at xiaozhi.me, while the device polls `/xiaozhi/ota/activate` with its serial number, a challenge and HMAC(challenge) (the call waits on the server: 200 means success, 202 means timed out, retry). (5) It then logs in over MQTT or WebSocket. Devices without a serial number follow the older flow (no challenge). For an already activated device the server may issue a challenge at any time without a spoken code. The "developer can" list is in section 3.

**WebSocket protocol** (page "通信协议：Websocket 连接", July 2025; it matches the firmware repository's `docs/websocket.md`). Version 1. Headers `Authorization: Bearer <token>`, `Protocol-Version`, `Device-Id` (the MAC address), `Client-Id` (a UUID). The device sends `hello` (`features.mcp: true`; audio Opus, 16 kHz, mono, 60 ms frames); the server answers `hello` (audio at 24 kHz; no session id on WebSocket).
- **Device to server:** `hello`; `listen` (`start` with mode **auto**, **manual** or **realtime** (continuous, needs echo cancellation); `stop`; `detect` for a wake word); `abort` (optional reason such as `wake_word_detected`); `mcp`.
- **Server to device:** `hello`; `stt` (the speech-to-text result); `llm` (an emotion, for the face); `tts` (`start`, `stop`, `sentence_start` with the sentence text); `mcp` (JSON-RPC 2.0); `system` (`reboot`); `alert` (status, message, emotion, plus a sound); `custom` (only if built in); and **binary Opus frames** (dropped while the device is listening).
- **Device states:** unknown, starting, Wi-Fi configuring, activating, upgrading, idle, connecting, listening, speaking. Errors close the connection and the device must reconnect. Petoi's head uses **MQTT with UDP audio**; the message types are the same.

**Emotions** (page "通信协议：Emoji 心情显示", February 2025). The model spends one token on an emoji for its mood; it is not spoken and arrives as its own message `{"type":"llm","text":"😊","emotion":"smile"}`. The 19 emotion names the face understands: neutral (😶), happy (🙂), laughing (😆), funny (😂), sad (😔), angry (😠), crying (😭), loving (😍), embarrassed (😳), surprised (😲), shocked (😱), thinking (🤔), winking (😉), cool (😎), relaxed (😌), delicious (🤤), kissy (😘), confident (😏), sleepy (😴).

**Push messages.** The conversation audio channel opens when a conversation starts, so a server cannot simply start speaking to an idle device. The firmware repository documents a newer `notify` message: the server sends an `audio_url` (a mono Ogg Opus file at an http or https address) and optional `subtitles`; it plays only while the device is idle, and delivery is best effort with no acknowledgement. **`notify` is in upstream v2.5.0; it is not in the Petoi head's v2.0.4 firmware.** `alert` shows text and an emotion with a sound and is present in v2.0.4. A developer-only real-time push over MQTT is listed in the activation design with no public description found; the firmware's `Enable Custom Message Reception` option enables the `custom` message.

## 8. MCP tools

**The MCP access point** (page "小智AI配置MCP接入点使用说明（官方）", September 2025).
- **What it is:** MCP (Model Context Protocol) lets a server expose callable tools (database queries, API calls, calculations) to a language model, each with a unique name and a schema. The access point connects a **local MCP service** to the XiaoZhi model for voice devices; it is pitched for remote control, calculation, email operations and knowledge search.
- **Where:** sign in at xiaozhi.me, open the agent's role configuration page; the agent's own access point is at the bottom right. The dialog shows the connection status, the available tools and the address (a secret address with a token; treat it like a password).
- **Example:** [78/mcp-calculator](https://github.com/78/mcp-calculator) (MIT): a `FastMCP` server over stdio with a `calculator` tool that **evaluates a Python expression sent by the model** (a security risk: do not copy it); run with the environment variable `MCP_ENDPOINT` set to the address and `mcp_pipe.py`. The log shows `Connecting to WebSocket server`, a `ListToolsRequest` and a `CallToolRequest`. The repository's bridge connects many tool servers from a config file (stdio, SSE or HTTP) and reconnects with exponential backoff; it does not mention pushing messages.
- **Precautions (six):** (1) give tools and parameters clear names and a description (a search tool's parameter should be `keywords`, a calculator's `python_expression`); (2) the docstring tells the model when to use the tool and what is available inside it; (3) with stdio transport do not `print`, use logging; (4) results are a string or JSON and length-limited, about **1024 bytes** (like the device's own IoT commands); (5) the tool list text is limited, counted in tokens; (6) each access point has a **limit on connections**.
- **Device-side tools** are different: a device offers its own tools to the cloud over the same protocol (for example volume, screen brightness and theme; the Petoi head adds a robot command tool and screen-face tools). Upstream documents them in `docs/mcp-protocol.md` and `docs/mcp-usage.md`.
- **Other pages** listed in the hub (not read): connecting web lookup or search through MCP, simple computer control (a community scheme), "mcphub" (a management platform for MCP tools), and third-party tool examples.

## 9. Knowledge base

Page "小智知识库使用说明" (October 2025). Console navigation: agent, voice cloning, **knowledge base (test version)**. Steps: (1) create a knowledge base with a name and a **description**; the description matters: it must tell the model that the knowledge base holds specific content and that it **cannot answer from memory but must call this tool in every conversation first** and then answer from the result (the page gives a template with the content summary below that instruction); (2) open the knowledge base and add a document (it parses automatically; the status becomes "parsing finished"; there is a **recall test** button); (3) associate the knowledge base with the agent; (4) use it by talking. The supported file types and size limits were in screenshots and were not read. The tier limits are in section 3.

## 10. Hardware notes

From the FAQ (modified March 2025; 30 questions, the answers to most were read):
- **Power (Q24):** the S3 board needs a stable 5 V; a 3.8 V lithium cell is not enough, add a 5 V boost or charge-and-discharge board; either USB-C port can supply power; a 3 W speaker wants a 5 V 2.1 A source (weak USB power causes stutter or silence, Q6).
- **Volume (Q8):** firmware 0.9.7 or newer accepts a spoken volume command; older firmware needs two physical buttons.
- **Bigger speaker, earphones, screens (Q16 to Q18):** possible with I2S audio modules (a PCM5102 board is verified for 3.5 mm output) and SSD1306, ST7789, ILI9341 or ST7735 screens, with board-configuration edits and a rebuild.
- **Motors and servos by voice (Q25) and other devices (Q26):** **not supported by default**: add a servo or motor driver module and use the IoT framework (from firmware 0.9.7 you can define pins to switch things); the vendor lists a small tank robot as an adapted example.
- **Supported boards (Q27):** ESP32-S3-DevKitC-1, ESP-BOX-3, the Lichuang S3 board, Kevin boxes; others need code changes (a fuller list is in the release notes). The answers to Q28 and Q29 (which model the project uses, whether the server is open source, GPT support) were not loaded; section 11 answers the open-source part.
- **Provisioning and flashing tips (Q4, Q9, Q10, Q11):** see sections 2 and 6.

## 11. Community and upstream material

- **Upstream firmware** ([xiaozhi-esp32](https://github.com/78/xiaozhi-esp32), MIT): the documents `docs/notify.md`, `docs/websocket.md`, `docs/mqtt-udp.md` (the transport the Petoi head uses), `docs/mcp-protocol.md`, `docs/mcp-usage.md` and `docs/custom-board.md`. The board profile for the Petoi head's board is `main/boards/lckfb/szpi-esp32c3`; it enables the wake-word code and the USB serial console. The latest source needs a newer ESP-IDF than the head's firmware (v2.0.4, ESP-IDF 5.4.2).
- **Community server** [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) (MIT): a Python, Java and Vue backend that speaks the XiaoZhi protocol (MQTT with UDP, and WebSocket) with MCP access points. Local speech recognition (FunASR, SherpaASR), local speech output (FishSpeech, GPT-SoVITS, Index-TTS, PaddleSpeech; **Piper is not listed**), any model with an OpenAI-style interface; Docker or source install, a minimal mode and a full mode (2 to 4 GB of memory at least, more with local recognition). **Its warnings:** it has no commercial tie to the third-party services it calls (read their terms; it holds no accounts or funds); its features are not complete and it **has not passed security testing, so it is not for production or the public internet without your own protection**. It documents no interface for sending text to a device. A device already bound to the official cloud will not announce its code to a local server (unbind it first). Other servers (Java, Go), a Python and an Android client and a Linux client are linked from the firmware README.
- **Assets generator** ([78/xiaozhi-assets-generator](https://github.com/78/xiaozhi-assets-generator)): a browser tool that builds an `assets.bin` (wake word, emoji set, font, chat background); it runs locally in the browser. **C3 and C6 chips can only use a fixed list of preset WakeNet9s models; custom command words (MultiNet, Chinese or English) are only for the S3 and P4.** It does not say which firmware versions it supports.

## 12. The Petoi AI head

From Petoi's guide ([AI conversation](https://guide.petoi.com/extensible-modules/ai-conversation), checked 2026-10-11; also available as Markdown).

**What it is.** A head unit for Bittle built on the open-source XiaoZhi chatbot project: connected to the XiaoZhi backend it holds LLM conversations while the robot performs skill-based movements tied to the dialogue.

**Hardware.** Replace the original head unit on the head servo and connect the head's Grove cable to the board. The guide has three photos: **BiBoard V1 without the voice module** (the cable goes to a connector at the top right of the board), **BiBoard V1 with the voice module** (the cable goes to a Grove socket at the **left edge** of the board, circled in red; the voice module is the small board at the top middle) and **NyBoard V1** (a Grove socket on the board's left side). On BiBoard V1 the Grove sockets are **G1 = UART2, G2 = I2C, G3 and G4 = analog input**; the Raspberry Pi port needs a 5-pin socket installed and supports a Pi 3A+, 4 or 5; the board takes 7 to 9 V on its battery input. (Source: Petoi's BiBoard V1 guide.)

**Setup.** As in section 2: connect to the `Xiaozhi-` hotspot, `http://192.168.4.1`, a 2.4 GHz network, restart in 3 seconds; Petoi's firmware stores several networks (section 2); activate at xiaozhi.me with the 6-digit code. In the console the guide says to select the language and press Console, register with a mobile phone number the first time, press Add Device, enter the code.

**Configuration.** Petoi's recommended role introduction (summarized, not copied): the agent is "Bittle", a lively quadruped robot dog made by Petoi with a witty, friendly personality; replies are at most two short plain-text sentences suited to speech synthesis (no Markdown, asterisks, backticks, emoji or decorative punctuation; company and product names as plain text); with several requested actions, run them one by one and give a short summary at the end; for a single action, perform it first and then reply in natural language, without command code in the text. **Action rules:** tool parameters must be command codes only (`ksit`, `kwkF 3`), never descriptions like "sit down(ksit)"; when the user names an action do that; otherwise use a default: nod (`knd`) for agreement, shake head (`kwh`) for disagreement or confusion, check (`kck`) for thinking, scratch (`kscrh`) for relaxation; **at goodbye, standby or rest, first call the tool `self.robot.send_command` with the command `d` (rest)**; call the tool once per task; the tool's documentation lists the actions (basic, emotional, skills such as jumping and rolling, and gaits). **Voice rule:** before speech output, filter out tool-calling syntax such as `% self.robot.` and `% get_xxx`; do not read it aloud. Model and memory are set in the Model and Memory tab; Speaker Recognition is not available on the free plan; services are set in the Extensions tab.

**Using it.** Wake the device with "Hi, Jason." to talk or command the robot, or press the Boot button, which also stops a conversation.

**Other Petoi pages.** Petoi's index (guide.petoi.com/llms.txt) also lists: the BiBoard V1 guide, joint pins, the voice command module, a Raspberry Pi serial port page, the serial protocol and feedback servos, and a **"Quaddle" (under construction) section with a Xiaozhi AI page** for a product whose **AI core board uses an ESP32-S3** (flashed with the `tyutool` tool at 921600 baud, choosing the `merged` bin file). The S3 supports custom wake words (section 5).

**Observations from one hands-on session** (a head connected to a Bittle X; unofficial and not verified by Petoi):
- The firmware is the XiaoZhi project, version 2.0.4 (built with ESP-IDF 5.4.2), on the board profile `lichuang-c3-dev` (an ESP32-C3 with 16 MB flash). The boot log reports the Wi-Fi setup hotspot and the IP address, and each turn is logged (`>>` what it heard, `<<` what it said) on its USB-C serial port at 115200 baud (opening the port reboots it).
- A new agent defaulted to Mandarin until its language was set to English in the agent's settings. "Hi, Jason." did not reliably wake it; the side button did.
- Spoken requests for movement ("sit down", "shake your head") produced the log line `Detected code leak in TTS text, removing: % self.robot.send_command...` and the head said it had done the action, but no command was seen on the BiBoard's serial output or its USB log (with the BiBoard first in low-power mode, then with its battery on). The cause was not established; Petoi's role template names that `% self.robot.` syntax as something to filter out of speech.
- Tools added through the agent's **MCP access point** (a small tool server connecting out to the address) were called by the head's free model: a made-up answer was spoken and the tool server logged the call.
- With the head connected, a listener on the Pi's receive pin heard only the BiBoard's own output; the head's transmit line goes to the BiBoard's receive pin, which the Pi cannot hear.

## 13. Page index with addresses

All addresses are Feishu pages (open in a browser; no login was needed) unless noted; short forms drop the `https://` and the second-level host prefix is the part before `.feishu.cn`. **Read** pages are summarized above. The hub: "小智 AI 聊天机器人百科全书" (XiaoZhi AI Chatbot Encyclopedia), `ccnphfhqs21z.feishu.cn/wiki/F5krwD16viZoF0kKkvDcrZNYnhb` (also `xiaozhi.me/docs`).

| Chinese title | Meaning | Address | Status |
|---|---|---|---|
| 小智AI 开发者认证 | Developer certification | `smvsudqc87.feishu.cn/docx/AjtQdM0KpoVQ3YxJfaLco4KsnSe` | **read** |
| v2.2.4 小智AI终端最新版本固件及源码下载 | v2.2.4 latest firmware and source | `ccnphfhqs21z.feishu.cn/wiki/W14Kw1s1uieoKjkP8N0c1VVvn8d` | **read** |
| v2.0.5 小智AI终端固件及源码下载 | v2.0.5 firmware and source | `my.feishu.cn/wiki/EuL7wqMOui2Mhgkw6ujcgre0ngg` | **read** |
| v1.9.4 小智AI终端固件下载 | v1.9.4 firmware | `rcnv1t9vps13.feishu.cn/wiki/WJlMwqOkLigfWhk6YRjc028annf` | not read |
| 小智AI聊天机器人面包板DIY硬件清单与接线教程 | Breadboard DIY parts list and wiring | `ccnphfhqs21z.feishu.cn/wiki/EH6wwrgvNiU7aykr7HgclP09nCh` | not read |
| 小智AI终端DIY面包板WIFI-LCD彩屏接线教程 | Breadboard Wi-Fi color LCD wiring | `rcnv1t9vps13.feishu.cn/wiki/Zq62wST38iuNxZkwg9JcjkSSnSd` | not read |
| 【最新】小智AI面包板带摄像头互动功能接线教程 | Breadboard with camera interaction wiring | `my.feishu.cn/wiki/HDWdwcVGUi3b3dk0IoycXR6pnOc` | not read |
| Flash工具/Web端烧录固件（无IDF开发环境） | Flash tool and web flashing, no IDF | `ccnphfhqs21z.feishu.cn/wiki/Zpz4wXBtdimBrLk25WdcXzxcnNS` | **read** |
| 配置设备 Wi-Fi 和添加设备及信号问题 | Set up Wi-Fi, add a device, signal problems | `ccnphfhqs21z.feishu.cn/wiki/KGvIwjTQxiTxPCkRbbjcPnsLnMb` | **read** |
| 小智AI ESP32S3开发板+面包板DIY模块购买说明 | Buying notes for the S3 board and modules | `rcnv1t9vps13.feishu.cn/wiki/TdBIw5e0GiORQSkVuvmc74jandh` | not read |
| AI类产品乐鑫设计参考以及要求 | Espressif design reference for AI products | `icnynnzcwou8.feishu.cn/wiki/IgzPwOoSFifXqZku0UkcQCBWn3f` | not read |
| ESP32-C3小智AI终端面包板DIY硬件接线教程 | C3 breadboard wiring | `rcnv1t9vps13.feishu.cn/wiki/PovjwxG8tiEDrVkybstcqOz0nzf` | not read |
| ESP32面包板-小智AI 制作说明 | Plain ESP32 breadboard build | `hcngjtwigghb.feishu.cn/wiki/CmZxwV17miwpYHk46ZpcXutOnJ8` | not read |
| 小智AI声音复刻（公测）控制台操作指引 | Voice cloning console guide | `rcnv1t9vps13.feishu.cn/wiki/Kxw3wBk0EiepeQkOHpncWTOrn4r` | **read** |
| 小智AI聊天机器人常见问题Q&A【先看】 | FAQ, read first | `rcnv1t9vps13.feishu.cn/wiki/JiQowaSe1itt07kyVvZcHFcQnee` | **read** |
| 无法接收手机验证码、忘记密码或解绑设备 | No SMS code, forgotten password, unbinding | `ccnphfhqs21z.feishu.cn/wiki/IJmWwu841isfAWkz1dEcrJjznof` | **read** |
| 小智知识库使用说明 | Knowledge base usage | `pipic77kjb4.feishu.cn/wiki/QS5ewZHh0iOEI0kdbjncmtY1nFg` | **read** |
| 小智AI 固件在线编译功能操作教程文档 | Online firmware compile | `my.feishu.cn/wiki/MUIdwr3IUiMkngkmhPUcRnThndb` | **read** |
| Windows搭建 ESP IDF开发环境&编译小智 | Windows ESP-IDF setup and building XiaoZhi | `icnynnzcwou8.feishu.cn/wiki/JEYDwTTALi5s2zkGlFGcDiRknXf` | **read, outline and menu sections** |
| 小智AI终端开源项目配置修改等操作指引（一） | Open-source project configuration changes, part 1 | `rcnv1t9vps13.feishu.cn/wiki/UwaJwcJQwiuZVtk5QCfcrkS2nmf` | **read, outline only** |
| 小智AI终端开源项目SDK配置AEC支持操作指引 | SDK configuration for echo cancellation | `rcnv1t9vps13.feishu.cn/wiki/JZ0vw5zcViWJaTkpa7Vccgr7nXb` | **read, start only** |
| 关于唤醒词更改及配置操作步骤 | Changing the wake word and its configuration | `rcnv1t9vps13.feishu.cn/wiki/H4dywK6ucigEtykKmm3cmZ7Dnog` | **read** |
| 关于独立串口工具的使用操作指引 | Standalone serial tool guide | `rcnv1t9vps13.feishu.cn/wiki/R3Gmwk9IuiEtnvkXjgxcdRwonhf` | not read |
| 修改提示音P3文件（例如开机播报和配网播报） | Changing the P3 prompt sounds | `icnynnzcwou8.feishu.cn/wiki/I5Mfw6USWivlRYk5yzzc3nC0nCg` | **read** |
| 小智AI配置MCP接入点使用说明（官方） | MCP access-point guide (official) | `ccnphfhqs21z.feishu.cn/wiki/HiPEwZ37XiitnwktX13cEM5KnSb` | **read** |
| 小智接入联网查询教程mcp | Web lookup through MCP | `x0ntkzs0zde.feishu.cn/docx/JKFXd8bLYo6YZtxz9ORcbnA8nbe` | not read |
| 小智AI 简单操控电脑 超简方案 | Simple computer control (community) | `kcn80f4hacgs.feishu.cn/wiki/RTaHwEOp8iu6ACkXbrNcJ4GMnVg` | not read |
| xiaozhi-mcphub-小智生态新一代mcp管理平台 | mcphub, an MCP management platform | `rhzmskwk8b.feishu.cn/wiki/VrHAwQRRdiWS8ykHk44cbdpynGe` | not read |
| 简单赋予小智 MCP 能力（第三方工具接入与玩法示例） | Giving XiaoZhi MCP abilities, third-party examples | `lcn17bfbw6fr.feishu.cn/wiki/OzyBwcRD1i5nONkHmMQcJPQOnwc` | not read |
| 小智接入联网搜索MCP（闪猫科技） | Web search MCP (a third party) | `pipic77kjb4.feishu.cn/wiki/EprvwfRSSiGtvOk7nQUcJh64nuh` | not read |
| 小智AI终端固件支持开发板/产品及购买链接 | Supported boards and products with shops | `rcnv1t9vps13.feishu.cn/wiki/LdCrw9neaiGgzrkrFyjclllynYd` | not read |
| 小智AI终端ASR自定义唤醒词简单方案 | Custom wake-word scheme with an add-on module | `kcn80f4hacgs.feishu.cn/wiki/OxsZwab8iiGYjvkH9SBcFK2anmh` | **read** |
| 小智AI终端控制GPIO[简单教程] | Controlling GPIO pins | `kcn80f4hacgs.feishu.cn/docx/J2MrdqW27oybcCxu7Sfc4gBcn4g` | not read |
| 小智ai面包板接电池简单教程 and 面包板小智接音响或者耳机简单教程 | Battery power, and speaker or earphones, on a breadboard | `x0ntkzs0zde.feishu.cn/docx/InARdPRGbo9gUfxYquWceFucnec` and `…/docx/KxASdc423oXIzlx8FLIcRJb5nAh` | not read |
| 小智AI聊天机器人硬件开源项目汇集（一） | Open hardware projects, part 1 | `rcnv1t9vps13.feishu.cn/wiki/DdgIw4BUgivWDPkhMj1cGIYCnRf` | not read |
| 通信协议：Websocket 连接 | Protocol: WebSocket connection | `ccnphfhqs21z.feishu.cn/wiki/M0XiwldO9iJwHikpXD5cEx71nKh` | **read** |
| 通信协议：Emoji 心情显示 | Protocol: emoji mood display | `ccnphfhqs21z.feishu.cn/wiki/LDN2wbdRyi6evQk6xgXcTe6ened` | **read** |
| OTA 接口文档 | OTA interface document | `ccnphfhqs21z.feishu.cn/wiki/FjW6wZmisimNBBkov6OcmfvknVd` | **read** |
| 激活设备流程 v2 | Device activation flow v2 | `my.feishu.cn/wiki/LB6iwNFXwixyuwkm2jJcJPUxn3c` | **read** |
| 固件修复 | Firmware repair, an old 4G version | `my.feishu.cn/wiki/YLpIwacbTim2jXkqz99caQyZnrr` | **read** |
| Petoi: AI conversation | The Petoi head's guide | `guide.petoi.com/extensible-modules/ai-conversation` | **read** |
| Petoi: BiBoard V1 guide; Xiaozhi AI (Quaddle) | Board sockets; the Quaddle S3 core board | `guide.petoi.com/biboard/biboard-v1-guide`; `guide.petoi.com/product/quaddle-under-construction/control-and-program/ai-conversation/xiaozhi-ai` | **read** |

## 14. Not yet read and open questions

- **Not read:** the breadboard wiring and parts pages, the third-party MCP pages (web lookup, computer control, mcphub), the serial tool page, the supported-boards list, the open hardware projects page, the GPIO, battery and speaker pages, v1.9.4, the rest of the AEC page, and the images inside the knowledge-base page (file types and size limits).
- **Behind a login (not read):** the console itself, plans and pricing, the terms and privacy policy. The public xiaozhi.me page shows only buttons for the DIY tutorial, GitHub and the Console.
- **Open questions:** whether the real-time developer push over MQTT has a public interface; whether the Petoi head's firmware (v2.0.4) will be published; which models support tool calls on the free tier; what the free plan keeps and for how long.

## 15. Glossary

- **AEC:** acoustic echo cancellation, which stops the device hearing its own speaker; needed for interrupting the device while it speaks.
- **Agent:** the cloud half of a device: role, voice, model and memory (section 1).
- **BiBoard, NyBoard:** Petoi's controller boards; the Petoi head connects to them over a Grove cable.
- **eFuse:** one-time-programmable memory in an ESP32 chip, used for a device's serial number and key.
- **ESP-IDF:** Espressif's development framework for building ESP32 firmware.
- **Grove:** a 4-wire connector standard (power, ground and two signal lines).
- **MCP:** Model Context Protocol; a standard for giving a language model callable tools.
- **MQTT, UDP, WebSocket:** network protocols; the XiaoZhi device talks control messages over MQTT or WebSocket and audio over UDP or WebSocket.
- **Opus:** an audio codec; all XiaoZhi audio is Opus.
- **OTA:** over-the-air update; also the address a device asks for its server settings.
- **P3:** the firmware's packed audio format for built-in sounds.
- **TTS, STT:** text-to-speech and speech-to-text.
- **WakeNet, MultiNet:** Espressif's wake-word model families; WakeNet has fixed preset words, MultiNet takes custom command words on supported chips.
