# Models: what G2 runs and where it comes from

Every model G2 uses, where it lives, where it came from and under what terms. Models are never committed to the repository. Downloads follow the project's security protocol: an official source over HTTPS, a pinned version, ONNX or plain weight formats only (no pickle files), its own folder outside the repo, a recorded SHA-256, and the user's yes before anything is fetched.

| Kind | Lives in | Fetched by |
|---|---|---|
| Speech recognition and wake word (Vosk), text-to-speech voices (Piper) | `models/` in the repo checkout (gitignored), on the Mac and on the Pi | `bash pi_pipeline/fetch_models.sh` |
| Vision models used on the Mac (embedder, person detector) | `~/g2_data/models/` | by hand, with approval: [`../vision/downloaded-models.md`](../vision/downloaded-models.md) |
| The detector on the camera | the camera module's flash | trained in this project: [`../vision/custom-model-recipe.md`](../vision/custom-model-recipe.md) |
| The walking policy | `rl_training/opencat-gym/trained/` (exported `.onnx` plus sidecar), deployed to the Pi | [`gait-deployment.md`](gait-deployment.md) |

## Voice models (`models/`)

| File | Role | Source | Size (bytes) | SHA-256 | Verified against | License |
|---|---|---|---|---|---|---|
| `vosk/` (`vosk-model-small-en-us-0.15`) | Speech recognition and the wake-word grammar; one model shared by both | [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models) | about 40 MB zip | `am/final.mdl`: `75370a0137f9daf8f469dedd7daa4513ae7a621f03240c6e512e2b50b656a7b6` | the host lists no checksum, so this is a local record only | Apache 2.0, per the host's model list |
| `piper/en_US-ryan-low.onnx` (+ `.onnx.json`) | G2's default voice; 16 kHz, light enough for the Pi Zero 2 W. The robot effect is applied on top | [`rhasspy/piper-voices`](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ryan/low) | 63,104,526 | `8d21a085cc4c0010f1f3e91d5008c8691277ccfa744eb0d747becd33a3444baf` | the Git LFS pointer on the host (oid and size), checked 2026-10-17 | CC BY-NC-SA 4.0 (dataset: RyanSpeech) |
| `piper/en_US-ryan-medium.onnx` (+ `.onnx.json`) | The documented upgrade: same voice, 22 kHz, cleaner; only if the Pi synthesises in real time with memory to spare | [`rhasspy/piper-voices`](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ryan/medium) | 63,201,294 | `abf4c274862564ed647ba0d2c47f8ee7c9b717d27bdad9219100eb310db4047a` | the Git LFS pointer on the host, checked 2026-10-17 | CC BY-NC-SA 4.0 (dataset: RyanSpeech) |

What the checks show: the hash proves the file is the one the host serves for that name, and an ONNX graph runs only mathematical operations in `onnxruntime`, so it cannot execute code the way a pickle file can. They do not prove the publisher's account is trustworthy. The Vosk acoustic model is a Kaldi model directory (plain data files); its README says it is from Alpha Cephei Inc.

**License note:** the RyanSpeech voice data is licensed CC BY-NC-SA 4.0: attribution, non-commercial use only, share-alike for derivatives. That is fine for a personal project. It would matter if G2's voice were ever shipped in a commercial product, or if the model files were redistributed from this repository (they are not: the repo carries only the fetch script).

The Pi's models are fetched on the Pi by the same script ([`../../pi_pipeline/voice/README.md`](../../pi_pipeline/voice/README.md) "Models for voice mode"); the deploy script copies only `pi_pipeline/` and the policy files, never `models/`.

## Choosing and switching the voice

`PIPER_MODEL_PATH` in the Pi's `.env` selects the voice (`models/piper/en_US-ryan-low.onnx` by default); `G2_VOICE_STYLE` picks the robot effect. Other voices are plain downloads of `<name>.onnx` and `<name>.onnx.json` from the repo above into `models/piper/`; try one with `python -m pi_pipeline.voice.check_audio tts "text" --model models/piper/<name>.onnx`. Notes on the voices tried (alan, amy, hfc_male, since removed): [`../../pi_pipeline/voice/README.md`](../../pi_pipeline/voice/README.md). Benchmark a voice on the Pi first: `python -m pi_pipeline.benchmark_pi --all-voices`.

## If a model is missing

| Symptom | Fix |
|---|---|
| Voice mode fails to start, "model not found" | `bash pi_pipeline/fetch_models.sh` (idempotent: skips what exists) |
| `models/` looks empty after a fresh clone | Expected: it is gitignored. Run the script |
| A new voice sounds wrong or runs slower than real time | Switch back to `en_US-ryan-low` and run the benchmark |

A model that is not in the fetch script, or any new download, needs the user's approval first and an entry in the table above (or in [`../vision/downloaded-models.md`](../vision/downloaded-models.md) for vision models).
