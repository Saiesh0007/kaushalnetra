"""Convert SCUT-HEAD PartA (Pascal VOC) to YOLO format. Splits: train/val for training, test held out (Rules.md §2.2)."""
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path("data/scut/SCUT_HEAD_Part_A")
DST = Path("data/scut_yolo")
names = set()
for split in ("train", "val", "test"):
    (DST / split / "images").mkdir(parents=True, exist_ok=True)
    (DST / split / "labels").mkdir(parents=True, exist_ok=True)
    for i in (SRC / f"ImageSets/Main/{split}.txt").read_text().split():
        root = ET.parse(SRC / f"Annotations/{i}.xml").getroot()
        w, h = float(root.find("size/width").text), float(root.find("size/height").text)
        lines = []
        for o in root.findall("object"):
            names.add(o.find("name").text)
            b = o.find("bndbox")
            x1, y1, x2, y2 = (float(b.find(k).text) for k in ("xmin", "ymin", "xmax", "ymax"))
            if x2 <= x1 or y2 <= y1:
                continue
            lines.append(f"0 {(x1+x2)/2/w:.6f} {(y1+y2)/2/h:.6f} {(x2-x1)/w:.6f} {(y2-y1)/h:.6f}")
        (DST / split / "labels" / f"{i}.txt").write_text("\n".join(lines))
        img = DST / split / "images" / f"{i}.jpg"
        if not img.exists():
            img.write_bytes((SRC / f"JPEGImages/{i}.jpg").read_bytes())
(DST / "data.yaml").write_text(f"path: {DST.resolve().as_posix()}\ntrain: train/images\nval: val/images\ntest: test/images\nnames: ['head']\n")
print("classes seen:", names, {s: len(list((DST / s / 'images').glob('*.jpg'))) for s in ('train', 'val', 'test')})
