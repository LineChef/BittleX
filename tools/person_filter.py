"""Find people in pictures, locally, so they can be left out of the object library (user, 2026-10-07: any picture with a person in it is excluded; people have their own model).

YOLOX-small (COCO, 80 classes; class 0 is "person") run with onnxruntime on this Mac. Nothing is sent anywhere. The model file is public and lives outside the repo (`~/g2_data/models/yolox_s.onnx`, 36 MB;
`python tools/person_filter.py --fetch` downloads it from the OpenCV model zoo). The camera's own detector only knows faces, so a person standing in the background or just their legs was missed;
this finds bodies, partial ones too. It is deliberately eager: a low score threshold, because leaving a picture out costs little and keeping a person in the library costs more.

    python tools/person_filter.py PICTURE...            print the best person score for each picture
"""
from __future__ import annotations

import os
import sys

import numpy as np

MODEL_PATH = os.path.expanduser("~/g2_data/models/yolox_s.onnx")
MODEL_URL = "https://huggingface.co/opencv/object_detection_yolox/resolve/main/object_detection_yolox_2022nov.onnx"
INPUT = 640
STRIDES = (8, 16, 32)
PERSON = 0
COCO = ("person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
        "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
        "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
        "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
        "scissors", "teddy bear", "hair drier", "toothbrush")


def _grid():
    grids, strides = [], []
    for s in STRIDES:
        n = INPUT // s
        xv, yv = np.meshgrid(np.arange(n), np.arange(n))
        grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), s))
    return np.concatenate(grids), np.concatenate(strides)


def decode_all(raw: np.ndarray, ratio: float, *, min_score: float, nms_iou: float = 0.45) -> list[tuple[str, float, tuple[float, float, float, float]]]:
    """YOLOX raw head output (8400 x 85) -> [(class name, score, (x1, y1, x2, y2) in the original picture's pixels)] for every COCO class, best first, with non-maximum suppression within each class."""
    d = raw.astype(np.float32).copy()
    grid, stride = _grid()
    d[:, :2] = (d[:, :2] + grid) * stride
    d[:, 2:4] = np.exp(d[:, 2:4]) * stride
    cls = d[:, 5:].argmax(1)
    score = d[:, 4] * d[np.arange(len(d)), 5 + cls]
    keep = np.where(score >= min_score)[0]
    out = []
    for c in sorted(set(cls[keep].tolist())):
        idx = keep[cls[keep] == c]
        cx, cy, w, h, sc = d[idx, 0], d[idx, 1], d[idx, 2], d[idx, 3], score[idx]
        boxes = np.stack([(cx - w / 2) / ratio, (cy - h / 2) / ratio, (cx + w / 2) / ratio, (cy + h / 2) / ratio], 1)
        picked: list[int] = []
        for i in np.argsort(-sc):
            if all(_iou(boxes[i], boxes[j]) < nms_iou for j in picked):
                picked.append(int(i))
        out += [(COCO[c], float(sc[i]), tuple(float(v) for v in boxes[i])) for i in picked]
    return sorted(out, key=lambda r: -r[1])


def decode(raw: np.ndarray, ratio: float, *, min_score: float, nms_iou: float = 0.45) -> list[tuple[float, tuple[float, float, float, float]]]:
    """YOLOX raw head output (8400 x 85) -> [(person score, (x1, y1, x2, y2) in the original picture's pixels)], best first, after non-maximum suppression."""
    d = raw.astype(np.float32).copy()
    grids, strides = [], []
    for s in STRIDES:
        n = INPUT // s
        xv, yv = np.meshgrid(np.arange(n), np.arange(n))
        grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), s))
    grid, stride = np.concatenate(grids), np.concatenate(strides)
    d[:, :2] = (d[:, :2] + grid) * stride
    d[:, 2:4] = np.exp(d[:, 2:4]) * stride
    score = d[:, 4] * d[:, 5 + PERSON]
    keep = score >= min_score
    if not keep.any():
        return []
    cx, cy, w, h, sc = d[keep, 0], d[keep, 1], d[keep, 2], d[keep, 3], score[keep]
    boxes = np.stack([(cx - w / 2) / ratio, (cy - h / 2) / ratio, (cx + w / 2) / ratio, (cy + h / 2) / ratio], 1)
    order = np.argsort(-sc)
    picked: list[int] = []
    for i in order:
        if all(_iou(boxes[i], boxes[j]) < nms_iou for j in picked):
            picked.append(int(i))
    return [(float(sc[i]), tuple(float(v) for v in boxes[i])) for i in picked]


def _iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


class PersonDetector:
    def __init__(self, model_path: str = MODEL_PATH, *, min_score: float = 0.25):
        import onnxruntime as ort
        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"person model not found at {model_path}; run: python tools/person_filter.py --fetch")
        self._sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._in = self._sess.get_inputs()[0].name
        self.min_score = min_score

    def _run(self, image):
        rgb = np.asarray(image.convert("RGB"))
        bgr = rgb[:, :, ::-1]
        h, w = bgr.shape[:2]
        ratio = min(INPUT / h, INPUT / w)
        nh, nw = int(h * ratio), int(w * ratio)
        from PIL import Image
        resized = np.asarray(Image.fromarray(np.ascontiguousarray(bgr)).resize((nw, nh), Image.BILINEAR), dtype=np.float32)
        canvas = np.full((INPUT, INPUT, 3), 114.0, dtype=np.float32)
        canvas[:nh, :nw] = resized
        return self._sess.run(None, {self._in: canvas.transpose(2, 0, 1)[None]})[0][0], ratio

    def detect(self, image) -> list[tuple[float, tuple[float, float, float, float]]]:
        """`image`: a PIL image. Returns the people found as (score, box in the picture's pixels), best first."""
        out, ratio = self._run(image)
        return decode(out, ratio, min_score=self.min_score)

    def objects(self, image, *, min_score: float = 0.30) -> list[tuple[str, float, tuple[float, float, float, float]]]:
        """Everyday objects the model recognises in the picture (any of its 80 classes except person): (class name, score, box in the picture's pixels), best first.
        Category hints and crop boxes only: it was trained on normal-height photos, names a kind of thing ("cup"), not your "red mug", and is far too big to run on G2."""
        out, ratio = self._run(image)
        return [r for r in decode_all(out, ratio, min_score=min_score) if r[0] != "person"]

    def best_score(self, image) -> float:
        found = self.detect(image)
        return found[0][0] if found else 0.0


def fetch(path: str = MODEL_PATH) -> str:
    import urllib.request
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    urllib.request.urlretrieve(MODEL_URL, tmp)
    os.replace(tmp, path)
    return path


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if a[:1] == ["--fetch"]:
        print("downloaded", fetch())
        return 0
    if not a:
        print(__doc__)
        return 2
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    det = PersonDetector()
    for p in a:
        print(f"{det.best_score(Image.open(p)):.2f}  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
