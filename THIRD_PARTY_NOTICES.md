# Third-party notices

The code of this repository is released under the MIT License (see `LICENSE`). The notices below are for the third-party work it contains or builds on.

This repository contains or builds on the following third-party work. Each is used under its own license; this file keeps the notices those licenses require.

## Petoi OpenCat and OpenCatEsp32 (MIT)

`rl_training/opencat-gym/reference_gait/InstinctBittleESP.h` and `rl_training/opencat-gym/reference_gait/skill.h` are taken from Petoi's OpenCat firmware
(<https://github.com/PetoiCamp/OpenCat>, <https://github.com/PetoiCamp/OpenCatEsp32>) and are used to read the Bittle's built-in skills. The serial command tokens in
`pi_pipeline/link/opencat.py` follow the same firmware. Both repositories are released under the MIT License:

- OpenCat: Copyright (c) 2022 Rongzhong Li
- OpenCatEsp32: Copyright (c) 2021 Rongzhong Li

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## opencat-gym (MIT)

`rl_training/opencat-gym/` is a curated copy of <https://github.com/ger01d/opencat-gym> (commit 12b39ff), Copyright (c) 2021 ger01d, under the MIT License; its license
text is kept in `rl_training/opencat-gym/LICENSE`.

## Not included in this repository

Vendor artwork (Petoi, PiSugar, Raspberry Pi) used to illustrate the build is linked to, not copied; downloaded models (Vosk, Piper voices, DINOv2, MobileNet) are fetched
separately onto the robot and are not committed; their sources and licenses are recorded in `docs/vision/downloaded-models.md`.
