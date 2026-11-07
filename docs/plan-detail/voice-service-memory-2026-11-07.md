# Voice service memory on the Pi Zero 2 W (measured 2026-11-07)

The Pi has 463 MB usable. With the voice service stopped the whole OS idles at about 114 MB; the service is the rest.

## Where the memory goes (a clean process loading each part in turn, service stopped)
| Part | Cost |
|---|---|
| Python + `pi_pipeline`, numpy, onnxruntime, vosk imports | about 57 MB together |
| Vosk model (the small mobile English model, 68 MB on disk) | 118 MB; the full-vocabulary and grammar recognisers add about 3 MB |
| Piper `ryan-low` | 88 MB at load, **about 175 MB after the first sentence** (onnxruntime's memory arena keeps what it grabbed) |
| Policy session | about 0 MB |
| Camera, walker, memory database, threads | roughly 50-60 MB (the remainder of the service's total) |

The service itself read 280 MB resident plus 71 MB in swap 3 minutes after boot (about 351 MB) before the change below.

## Done (2026-11-07)
- **Arena off for Piper and the embedder** (`util/ort_memory.py`; `G2_ORT_ARENA=1` restores the old way). In isolation Piper after a sentence: 175 MB to 155 MB, same speed (2.7 s to 2.6 s for a sentence). In the service at 3.5 minutes after boot: 317 MB total with no swap, against about 351 MB.
- **Tried and dropped:** `MALLOC_ARENA_MAX=1` with a low trim threshold on the service: 316 MB against 317 MB, no gain. The test override was removed.

## Already in place
The embedder (DINOv2 session, about 100 MB) is lazy: it loads on first use and is released 90 s after the last (`LazyOnnxEmbedder`). Vosk is one shared model for the wake word and the speech-to-text. The Vosk model in use is already the small one.

## Options left, biggest first (none done)
1. **(Built 2026-11-07, `G2_RELEASE_VOICE`)** **Release Piper while no sentence is likely** (about 155 MB). Loading takes about 10 s, so the first reply after a release would lag; the speech cache already covers fixed lines. A release only during a goal session or an exploration roam (which speak little) avoids the lag in conversation.
2. **A smaller or quantised Piper voice** (the 63 MB `ryan-low` is already the low-quality one; a smaller voice would sound worse; needs a download, which needs the owner's yes).
3. **A systemd `MemoryHigh` limit** so a runaway is throttled instead of dragging the whole box into swap. Untested.
4. **Run heavy work in-process** (already the direction for goals), so no second copy of the stack is loaded.

## Smaller Piper voices (researched 2026-11-07; nothing downloaded)
The robot filter (`voice/effects.py`, `apply_style`) runs on the synthesised audio array and takes the sample rate as an argument, so it works the same on any Piper voice; the speech cache is keyed by voice file plus style, so a new voice starts with an empty cache.
- **Every English voice is the same size.** From the official voice list (rhasspy/piper-voices `voices.json`): all English "low" and "medium" voices have a 63.0-63.5 MB model file (our `ryan-low` is 63,104,526 bytes, the same as `amy-low`, `danny-low`, `kathleen-low`, `alan-low`; medium ones 62.95-63.5 MB). "Low" means a 16 kHz output, not a smaller network. Multi-speaker voices are 76-81 MB, high-quality ones 114-137 MB.
- **`x_low` voices are the small ones (21-28 MB), but none exists for English** in the list read (Spanish only: `es_MX-ald` 21 MB, `es_ES-carlfm` 28 MB). Part of the list (the last 82 KB) was not read, so a late entry could be missing.
- So within official Piper voices there is no smaller English choice than the one in use. The memory is mostly the network's working buffers rather than the 63 MB of weights, so even a half-size model would not halve the 155 MB.
- **Tried 2026-11-07 (Mac, onnxruntime 1.23 and 1.30, no download: the repo-root `.venv` already has `onnx`): int8 dynamic quantisation of `ryan-low` is not viable.** Quantising everything (the model is mostly convolutions) gives an 18 MB file that will not run: onnxruntime's CPU provider has no `ConvInteger` kernel (`NOT_IMPLEMENTED ... ConvInteger`). Quantising only MatMul/Gemm runs but saves nothing: 61.7 MB against 63.1 MB, memory after a sentence 277 MB against 285 MB in a Mac process (noise), same speed (0.17 s against 0.18 s). Played side by side with and without the `metal` filter: no audible difference. A static (calibrated) QDQ quantisation might get convolutions to run but is a larger experiment, not started.
- ~~Left to try (no download):~~ an int8 dynamic quantisation of our own `ryan-low` with onnxruntime's quantisation tool on the Mac (a local conversion; may need the `onnx` package, which would be a pip install and so needs a yes), then listen and measure memory. VITS models can lose quality or fail to quantise, so it is an experiment.
