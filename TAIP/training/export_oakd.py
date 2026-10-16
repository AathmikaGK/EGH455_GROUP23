"""Export best.pt to an OAK-D blob in the layout DepthAI YoloDetectionNetwork expects.

Same approach as tools.luxonis.com: replace YOLOv5's Detect forward so the
ONNX has three raw heads (sigmoid applied, no grid/anchor decode), shapes
(1, 24, 80, 80), (1, 24, 40, 40), (1, 24, 20, 20) for 3 classes at 640.
The VPU does the decode with the ANCHORS / ANCHOR_MASKS in detect_oakd.py.

Run from a yolov5 v7.0 checkout (needs its models/ package to unpickle):
    cd yolov5 && python /path/to/export_oakd.py /path/to/best.pt OUT_DIR
"""
import pathlib
import sys

import torch

sys.path.insert(0, ".")
sys.modules.setdefault("pathlib._local", pathlib)  # best.pt was pickled on Python 3.13

IMG = 640


def heads_forward(self, x):
    return [self.m[i](x[i]).sigmoid() for i in range(self.nl)]


def main(weights, out_dir):
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model = torch.load(weights, map_location="cpu", weights_only=False)["model"].float().fuse().eval()
    det = model.model[-1]
    im = torch.rand(1, 3, IMG, IMG)

    # Self-check: our heads must equal sigmoid of the raw per-scale outputs
    # YOLOv5's own Detect returns, so only the decode step moves to the VPU.
    with torch.no_grad():
        _, raw = model(im)  # raw[i]: (1, na, ny, nx, 5+nc)
        det.forward = heads_forward.__get__(det)
        heads = model(im)
    for r, h in zip(raw, heads):
        assert torch.allclose(r.sigmoid().permute(0, 1, 4, 2, 3).reshape(h.shape), h, atol=1e-5)
    print("heads:", [tuple(h.shape) for h in heads])

    onnx_path = out_dir / "best_oakd.onnx"
    names = ["output1_yolov5", "output2_yolov5", "output3_yolov5"]
    torch.onnx.export(model, im, onnx_path, opset_version=12, input_names=["images"],
                      output_names=names, dynamo=False)
    try:
        import onnx
        import onnxsim
        simp, ok = onnxsim.simplify(onnx.load(onnx_path))
        assert ok
        onnx.save(simp, onnx_path)
    except ImportError:
        print("onnxsim not installed, skipping simplify")

    import blobconverter
    blob = blobconverter.from_onnx(
        model=str(onnx_path), data_type="FP16", shaves=6, version="2022.1",
        optimizer_params=["--scale=255", "--reverse_input_channel"],
        output_dir=str(out_dir),
    )
    print("anchors:", (det.anchors * det.stride.view(-1, 1, 1)).flatten().round().int().tolist())
    print(blob)


if __name__ == "__main__":
    main(*sys.argv[1:3])
