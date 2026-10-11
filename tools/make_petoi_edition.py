#!/usr/bin/env python3
"""Make the clean edition of the English XiaoZhi / Petoi head documentation for sending to Petoi.

    python tools/make_petoi_edition.py [OUT_DIR]          default OUT_DIR: ~/g2_head_firmware/vendor-docs/for-petoi

Reads docs/research/xiaozhi-vendor-docs.md (the source of truth) and writes `xiaozhi-docs-english.md` and `.html` into OUT_DIR, outside the repo:
  * adds a note to Petoi at the top (what this is, what is asked, and which pages have named community authors);
  * leaves out the section of hands-on test observations (those are this project's own notes and unverified);
  * changes nothing else. Rerun it whenever the source document changes.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "research" / "xiaozhi-vendor-docs.md"

NOTE = """## Note to Petoi

The XiaoZhi firmware that powers the AI head is documented almost entirely in Chinese, and as far as we could find there is no English version. This is an unofficial English summary and translation of the parts that matter for the AI head: setup and activation, accounts and models, voices and wake words, flashing and building the firmware, the device protocol, MCP tools, and your own head guide. It was prepared by a Bittle X owner with machine assistance, and **it has not been reviewed by a native Mandarin speaker or by the XiaoZhi team**.

**What would help:** (1) a review by Petoi's Mandarin-speaking staff, since errors are likely; (2) your view on whether Petoi would like to publish or link an English edition. Publishing a fuller translation would need permission from the XiaoZhi team (Tenclass, the maintainers of the open-source project) and, for the pages listed below, from the community authors; this summary is written in its own words, with no copied text or images, and links to every original; (3) corrections and the answers to the open questions in section 14, in particular whether the head's firmware source will be published and whether the developer-only push interface mentioned in section 3 has public documentation.

[Sender: add the terms on which you offer this summary text for reuse, and your contact details.]

**Pages with a named community author** (the author's name appears on the page; treat every other page as third-party until its author is confirmed):

| Page | Author named on the page | Used in |
|---|---|---|
| 小智AI终端ASR自定义唤醒词简单方案 (custom wake-word add-on module) | 粽子DIY | section 5 |
| 修改提示音P3文件 (changing the prompt sounds) | 酷世DIY | section 6 |
| Windows搭建 ESP IDF开发环境&编译小智 (Windows ESP-IDF build) | 酷世DIY | sections 5 and 6 |
| xiaozhi-esp32-server (a community backend, MIT) | the xinnan-tech project | section 11 |

"""


def make(out_dir: Path) -> None:
    text = SRC.read_text(encoding="utf-8")
    a = text.index("**Observations from one hands-on session**")
    b = text.index("## 13. Page index with addresses")
    text = text[:a].rstrip() + "\n\n" + text[b:]
    text = text.replace("## Contents\n\n", "## Contents\n\n- [Note to Petoi](#note-to-petoi)\n", 1)
    text = text.replace("## About this document", NOTE + "## About this document", 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "xiaozhi-docs-english.md"
    md.write_text(text, encoding="utf-8")
    subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "md_to_html.py"), str(md), str(out_dir / "xiaozhi-docs-english.html"), "docs/research"], check=True)
    print(f"wrote {md} and the .html ({len(text.splitlines())} lines)")


if __name__ == "__main__":
    make(Path(os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/g2_head_firmware/vendor-docs/for-petoi")))
