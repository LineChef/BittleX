#!/usr/bin/env python3
"""Turn a flat YOLO folder (images + <name>.txt, plus label-less negatives)
into the COCO-format dataset zip the SSCMA Swift-YOLO Colab notebooks expect:

    custom_data.zip
      train/ _annotations.coco.json  + images
      valid/ _annotations.coco.json  + images

    python tools/yolo_to_coco_zip.py <in_dir> <classes> [--val-frac 0.15] [--out custom_data.zip]
    e.g.  tools/yolo_to_coco_zip.py ~/Desktop/g2_vision_library/upload_3way you,dog,cat
"""
import argparse, glob, json, os, random, shutil, sys, zipfile
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_dir")
    ap.add_argument("classes", help="comma list in class-id order")
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--out", default="custom_data.zip")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    names = [c.strip() for c in a.classes.split(",") if c.strip()]
    src = os.path.expanduser(a.in_dir)
    jpgs = sorted(glob.glob(os.path.join(src, "*.jpg")))
    if not jpgs:
        sys.exit(f"no .jpg in {src}")

    random.seed(a.seed)
    random.shuffle(jpgs)
    n_val = max(1, int(len(jpgs) * a.val_frac))
    split = {"valid": jpgs[:n_val], "train": jpgs[n_val:]}

    work = os.path.join(os.path.dirname(a.out) or ".", "_coco_build")
    shutil.rmtree(work, ignore_errors=True)
    cats = [{"id": i, "name": n, "supercategory": "none"} for i, n in enumerate(names)]

    counts = {}
    for part, files in split.items():
        d = os.path.join(work, part)
        os.makedirs(d, exist_ok=True)
        images, anns = [], []
        aid = 1
        nlab = nneg = 0
        for iid, jpg in enumerate(files, 1):
            fn = os.path.basename(jpg)
            shutil.copy2(jpg, os.path.join(d, fn))
            w, h = Image.open(jpg).size
            images.append({"id": iid, "file_name": fn, "width": w, "height": h})
            txt = jpg[:-4] + ".txt"
            rows = []
            if os.path.isfile(txt):
                rows = [r.split() for r in open(txt) if r.strip()]
            if rows:
                nlab += 1
            else:
                nneg += 1
            for r in rows:
                cid = int(float(r[0])); cx, cy, bw, bh = map(float, r[1:5])
                x = (cx - bw / 2) * w; y = (cy - bh / 2) * h
                anns.append({"id": aid, "image_id": iid, "category_id": cid,
                             "bbox": [round(x, 2), round(y, 2), round(bw * w, 2), round(bh * h, 2)],
                             "area": round(bw * w * bh * h, 2), "iscrowd": 0, "segmentation": []})
                aid += 1
        json.dump({"images": images, "annotations": anns, "categories": cats},
                  open(os.path.join(d, "_annotations.coco.json"), "w"))
        counts[part] = (len(files), nlab, nneg, len(anns))

    with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, fs in os.walk(work):
            for f in fs:
                fp = os.path.join(root, f)
                z.write(fp, os.path.relpath(fp, work))
    shutil.rmtree(work, ignore_errors=True)

    print(f"wrote {a.out}")
    for part, (n, nlab, nneg, na) in counts.items():
        print(f"  {part}: {n} images ({nlab} labelled, {nneg} background), {na} boxes")
    print(f"  categories (id order): {names}")


if __name__ == "__main__":
    main()
