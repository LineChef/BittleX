# Petoi Bittle AI Head — questions for Petoi, and how to read the answers

Product: <https://www.petoi.com/products/bittle-ai-head-upgrade-kit> ($39, SKU PTAXZC, 42 g; in stock when checked —
the store data reads `"available": true`). **Ordered 2026-10-02, arriving around 2026-10-10.** The evaluation plan and
hands-on tests are in [`petoi-ai-head-evaluation.md`](petoi-ai-head-evaluation.md).

**Known** (Petoi's page and product data, the
[AI Conversation guide](https://guide.petoi.com/extensible-modules/ai-conversation), and the owner's own research): a
drop-in head with its own microphone, speaker and camera (the camera can be trained with new recognition models). It talks
to the XiaoZhi cloud backend over Wi-Fi (2.4 GHz); wake with "Hi, Jason" or the Boot button; needs internet and a free
xiaozhi.me account; the backend LLM replies with skill codes (`ksit`, `kwkF 3`) that the head sends to the BiBoard;
connects through Grove; documented for BiBoard V1 and NyBoard V1. **Not documented:** processor, flash/RAM, mic/speaker/
display/camera specs, the serial protocol and pins, power draw, any host-facing API, whether the server can be changed,
and any firmware source.

**The real questions:** can the head be *extended* (do we get its audio, camera results, text and tool calls), and could
it **replace the Raspberry Pi** on the robot or does it only add canned behavior?

## Sent to Petoi's founder (2026-10-02), with a paragraph describing our setup

1. Does the head expose its microphone audio to an outside host in any form (UART, USB, I2S, WebSocket, UDP)?
2. Can a host play audio or text through the head's speaker?
3. Camera: how are new recognition models trained and deployed, and can a host receive the detections or frames (format,
   protocol, rate)?
4. Can the head be pointed at a server I control, so my own backend answers instead of the XiaoZhi cloud?
5. Can it run talk-only, with motion output disabled or redirected to a host?
6. What exactly does it send to and receive from the BiBoard (port, baud, framing, full message list)? Can it send arbitrary
   tokens, including joint-level `i`/`m` moves, and at what rate?
7. Which Grove port and UART does it use, and can it coexist with a Pi on the 5-pin Serial-2 header and the voice module?
8. Is the firmware open, and can I run my own code on its processor?
9. Does it receive the BiBoard's IMU, battery or servo feedback?
10. How does a developer get logs and a debug console?
11. Can the AI head run a custom 80 Hz loop?
12. What happens if Wi-Fi or the backend goes down (keep working offline, go idle, keep executing the last command, reboot)?
    Is there an e-stop or watchdog that doesn't depend on the cloud?
13. Is the camera's recognition done on the device or in the cloud, and does it work offline? Model types, class count, input
    size and frame rate?
14. Can we customize what the AI does: edit its system prompt, add my own tools, skills or HTTP/MCP calls, get transcripts
    out, read or write its memory?
15. Power: what does it draw (idle, speaking, peak), and from where? Can the BiBoard's Grove 5 V supply it without sagging the
    servos' pack?
16. Can OTA updates be pinned or disabled, so a remote change can't break the robot? What is the recovery path if firmware
    goes bad?
17. How much CPU, RAM and flash is free for user code, which toolchain, and do the audio, Wi-Fi, display and LLM tasks share
    cores with it?
18. Can the head send joint-level `i`/`m` moves at 27–80 Hz to the BiBoard, and does the BiBoard need a special mode for that?
19. Where does conversation memory live, and can it be exported, imported and deleted?
20. What is retained from its memory, and for how long?

## Not (yet) asked — find out first-hand or ask later

21. What data leaves the device (audio, transcripts, camera images/frames), where is it processed and stored, for how long, and
    can it be deleted?
22. Free-tier limits and later pricing; do the terms restrict custom use; does the head keep working if the service changes or
    shuts down or the account is closed?
23. Within their backend, can I choose my own LLM or use my own API key?
24. Does the microphone work while the robot is walking (servo noise)? Echo cancellation while it speaks? Changeable wake word,
    languages, latency, interruptibility?
25. Does the kit drive the head servo? Does the camera stay fixed or nod with the head? How is it mounted (42 g vs the ~15 g the
    sim assumes for the camera)?
26. Which BiBoard firmware version and module flags does it require, and does installing it change stored settings such as
    Serial-2 (`XS`) mode?
27. Can the camera recognize individual people and give a host the identity label?
28. Lead time, warranty, a developer support contact, and whether it is related to the "AI core" board announced for Quaddle (so
    it may be superseded).

## How to read the answers

| If Petoi says | Then |
|---|---|
| Raw mic and speaker access, or a configurable server | **Extendable.** The head can be the audio front end, or a self-hosted server can put Claude behind it |
| Talk-only or motion redirected to a host, plus transcripts or an MCP/HTTP tool hook | **Partly extendable.** Voice front end while the Pi keeps control of motion |
| Camera detections or frames reach a host | The head's camera could replace the Grove Vision camera (one part fewer) |
| Open firmware, free compute for user code, real-time loop and IMU access | **It could replace the Pi.** A large rewrite from Python to embedded code, but possible |
| Only fixed skill codes to the BiBoard, closed firmware | **Canned behavior.** It would compete with the Pi, bypass Claude, memory and personality, and give up the learned gait and safety layers |
| Shares UART2/Serial-2 with the Pi header and can't coexist | Don't connect it without a port plan |
| Cloud-only with no offline or safety fallback | Not acceptable as the only controller of a walking robot |
