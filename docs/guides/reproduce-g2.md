---
audience: builder
kind: guide
---

# Reproducing G2: the build path from parts to a walking, talking robot

This page is the single ordered path for building G2 and bringing up its software. Each stage names its inputs, the steps or the page that holds the detail, and a check that shows the stage worked. Do the stages in order, and do not start a stage until the check of the previous one passes.

1\. Parts
--------

- Inputs: The parts list in [As built](../hardware/as-built.md): a Petoi Bittle X V2 with its BiBoard, a Raspberry Pi Zero 2 W with a PiSugar S battery, a Grove Vision AI V2 camera, an I2S microphone and amplifier with a speaker, the Pi add-on pod, and optionally the claw arm.
- Check: Every part in the "Parts" list is on hand, and the Pi, the camera and the BiBoard each power up on their own.

2\. Hardware assembly
--------------------

- Inputs: The parts from stage 1 and Petoi's assembly guide.
- Steps: Follow the [assembly sequence](../../blueprints/assembly-sequence.md) top to bottom. The detail pages are the [wiring guide](../../blueprints/wiring.md), [mounting](../../blueprints/mounting.md) and [calibration](../../blueprints/calibration.md).
- Check: After calibration, `kbalance` stands G2 level on a flat floor, and the Pi stack sits in the pod without touching the legs.

3\. Firmware
-----------

- Inputs: The assembled G2 and the current official OpenCat firmware for the BiBoard.
- Steps: Erase and reflash the BiBoard, then enable Serial-2 (`XS`). The firmware tokens and the module behaviour are in the [Petoi firmware reference](../hardware/petoi-firmware-reference.md).
- Check: The BiBoard answers its `?` banner over the Pi link, and the IMU prints frames.

4\. Pi provisioning
------------------

- Inputs: A Pi Zero 2 W and an SD card.
- Steps: Flash and boot the card, turn off Wi-Fi power-save, set up swap and zram, and enable the UART for the BiBoard link, as in [Pi bring-up](pi-bring-up.md). Then run `bash pi_pipeline/setup_pi.sh` over SSH. The script is idempotent.
- Models: `bash pi_pipeline/fetch_models.sh` downloads the speech models into `models/`. It fetches files from the internet, so it is run only with explicit approval, and the models are never committed ([Models](models.md)).
- Secrets: The Claude API key goes in the Pi's `.env` (copy `.env.example`). The file is gitignored and never printed.
- Check: `python -m pi_pipeline.doctor` reports every item ready.

5\. Deploying the software
-------------------------

- Steps: Commit the change, then run `tools/g2_deploy_when_online.sh --once` with G2 idle. The deploy is an `rsync` of `pi_pipeline/` and the one exported policy named by `DEFAULT_POLICY`, with its `.onnx.json` sidecar. It is never a `git clone`.
- Check: The deploy script prints "imports ok" and restarts `g2-voice`.

6\. Link and first movement
--------------------------

- Steps: With G2 standing on the floor and a hand near, run `python -m pi_pipeline.link.check_serial` for the port and ping checks, then `firstmove` (one joint at a time) and `allmoves` (the full sweep, which logs voltage and latency). `python -m pi_pipeline.bringup` runs the same sequence step by step, one prompt per step.
- Check: Every skill plays, the voltage log stays above the low-battery line, and no command is refused except the deliberately disabled moves ([Disabled moves](../hardware/disabled-moves.md)).

7\. The first walk
-----------------

- Inputs: G2 standing on a known floor, a charged pack, and a deployed policy.
- Steps: Set the floor label with `g2floor <label>`, read the pack percent, then run `python pi_pipeline/gait/run_gait.py --cmd 0.10 --seconds 12.5 --log ~/g2_runs/first.csv` with a hand near. See [Gait deployment](gait-deployment.md).
- Check: On hardwood, G2 covers about 4 ft in 12 s and drifts a few inches to one side, and the log's end reason is `complete`.

8\. Voice, memory and the camera
-------------------------------

- Steps: Install the service with `bash pi_pipeline/install_voice_service.sh`, and read its log with `journalctl -u g2-voice -f`. The camera attaches to the Pi's USB port, as in [Vision](../vision/README.md).
- Check: G2 says "G2 online", answers to "gee two", and replies to a spoken question. `python -m pi_pipeline.memory` shows the exchange afterwards.

9\. Training a walking policy
----------------------------

- Inputs: The Mac with the repository's `.venv`.
- Steps: Set up the environment as in `rl_training/opencat-gym` (pybullet builds from source with `CPPFLAGS="-Dfdopen=fdopen"`), then train with `../../.venv/bin/python train.py`. `../../.venv/bin/python preflight.py` must print ALL PASS before a 20-million-step run. Promote the result with `tools/g2_promote_policy.sh TAG NAME`. The training design and the benchmarks are in [Gait training](../rl/README.md).
- Check: The exported policy loads on the Pi, passes `validate_deploy.py --onnx`, and walks as in stage 7.

10\. Verifying the whole system
------------------------------

- Software: `pi_pipeline/.venv/bin/pytest` passes, `pi_pipeline/.venv/bin/ruff check` is clean, and `python tools/check_docs.py` reports no errors.
- Robot: The checks of stages 3 to 8 still pass after the last change, and G2 ends every session in the rest position.
