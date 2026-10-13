"""Turn the 4-class Roboflow YOLOv5 export into the 3-class training set.

Run in Colab after downloading the Roboflow version, before train.py:
    python strip_classes.py /content/<dataset_dir>

Drops Fire-extinguisher boxes and remaps the rest to the order detect_oakd.py
expects (LABELS = ["valve_open", "valve_closed", "gauge"]). Class mapping is by
name from data.yaml, so it doesn't depend on Roboflow's index order.
Images that end up with no boxes stay as negatives (empty label file).
"""
import sys
from pathlib import Path

RENAME = {"Valve Open": "valve_open", "Valve Close": "valve_closed", "Gauge": "gauge"}
TARGET = ["valve_open", "valve_closed", "gauge"]


def remap_lines(lines, old_names):
    out = []
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        new = RENAME.get(old_names[int(parts[0])])
        if new is not None:
            out.append(" ".join([str(TARGET.index(new))] + parts[1:]))
    return out


def main(root):
    import yaml  # installed with YOLOv5's requirements in Colab

    root = Path(root)
    cfg = yaml.safe_load((root / "data.yaml").read_text())
    old_names = cfg["names"]
    unknown = set(old_names) - set(RENAME) - {"Fire-extinguisher"}
    if unknown:
        sys.exit(f"Unexpected classes in data.yaml: {unknown}")

    files = list(root.glob("*/labels/*.txt"))
    for f in files:
        f.write_text("\n".join(remap_lines(f.read_text().splitlines(), old_names)))

    cfg["names"], cfg["nc"] = TARGET, len(TARGET)
    (root / "data.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    print(f"Remapped {len(files)} label files -> {TARGET}")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        main(sys.argv[1])
    else:  # self-check
        names = ["Fire-extinguisher", "Gauge", "Valve Close", "Valve Open"]
        got = remap_lines(["0 .5 .5 .1 .1", "1 .2 .2 .1 .1", "2 .3 .3 .1 .1", "3 .4 .4 .1 .1"], names)
        assert got == ["2 .2 .2 .1 .1", "1 .3 .3 .1 .1", "0 .4 .4 .1 .1"], got
        print("self-check ok")
