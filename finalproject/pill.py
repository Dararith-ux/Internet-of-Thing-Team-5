"""
Pill Counter - YOLO ONNX Detection with Mac Camera
Usage: python pill_counter.py --model best_model.onnx
"""

import cv2
import numpy as np
import onnxruntime as ort
import argparse
import time
from collections import defaultdict

# ─── CONFIG ───────────────────────────────────────────────────────────────────
CONF_THRESHOLD = 0.4      # Minimum confidence to show a detection
NMS_THRESHOLD  = 0.45     # Non-maximum suppression overlap threshold
INPUT_SIZE     = (640, 640)  # YOLOv8 default input size

# Colors per class (BGR) — cycles if more classes than colors
PALETTE = [
    (0, 200, 100), (0, 120, 255), (220, 50, 50),
    (180, 0, 220), (255, 180, 0), (0, 220, 220),
]
# ──────────────────────────────────────────────────────────────────────────────


def load_model(model_path: str):
    """Load the ONNX model and return session + metadata."""
    sess_opts = ort.SessionOptions()
    sess_opts.log_severity_level = 3  # suppress warnings

    providers = ["CPUExecutionProvider"]
    # Use CoreML on Mac if available (faster on Apple Silicon)
    if "CoreMLExecutionProvider" in ort.get_available_providers():
        providers = ["CoreMLExecutionProvider"] + providers

    session = ort.InferenceSession(model_path, sess_options=sess_opts, providers=providers)
    input_name  = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    print(f"✅ Model loaded: {model_path}")
    print(f"   Input : {input_name} {session.get_inputs()[0].shape}")
    print(f"   Output: {output_name} {session.get_outputs()[0].shape}")
    print(f"   Provider: {session.get_providers()[0]}")

    return session, input_name, output_name


def preprocess(frame: np.ndarray):
    """Resize + normalize frame for YOLO input."""
    img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, INPUT_SIZE)
    img = img.astype(np.float32) / 255.0
    img = np.transpose(img, (2, 0, 1))          # HWC → CHW
    img = np.expand_dims(img, axis=0)            # add batch dim
    return img


def postprocess(outputs: np.ndarray, orig_shape, conf_thresh, nms_thresh):
    """
    Parse YOLO output tensor and apply NMS.
    Supports both YOLOv8 shape: [1, num_classes+4, num_anchors]
    and classic shape:          [1, num_anchors, num_classes+5]
    """
    pred = outputs[0]                            # remove batch dim → [*, *]

    # YOLOv8 transposed format: [1, 4+nc, 8400] → transpose to [8400, 4+nc]
    if pred.ndim == 2 and pred.shape[0] < pred.shape[1]:
        pred = pred.T

    oh, ow = orig_shape[:2]
    sx = ow / INPUT_SIZE[0]
    sy = oh / INPUT_SIZE[1]

    boxes, scores, class_ids = [], [], []

    for row in pred:
        if row.shape[0] == 5:
            # Single-class: [cx, cy, w, h, conf]
            cx, cy, w, h, conf = row
            if conf < conf_thresh:
                continue
            cls_id = 0
            score  = float(conf)
        else:
            # Multi-class: [cx, cy, w, h, cls1, cls2, ...]
            cx, cy, w, h = row[:4]
            cls_scores   = row[4:]

            # YOLOv8 doesn't have a separate objectness; max cls score is confidence
            cls_id = int(np.argmax(cls_scores))
            score  = float(cls_scores[cls_id])

            if score < conf_thresh:
                continue

        # Convert center-xywh (in 640-space) → xyxy (in original-image space)
        x1 = int((cx - w / 2) * sx)
        y1 = int((cy - h / 2) * sy)
        x2 = int((cx + w / 2) * sx)
        y2 = int((cy + h / 2) * sy)

        boxes.append([x1, y1, x2 - x1, y2 - y1])   # xywh for NMS
        scores.append(score)
        class_ids.append(cls_id)

    if not boxes:
        return [], [], []

    indices = cv2.dnn.NMSBoxes(boxes, scores, conf_thresh, nms_thresh)
    indices = indices.flatten() if len(indices) > 0 else []

    kept_boxes     = [[b[0], b[1], b[0]+b[2], b[1]+b[3]] for i, b in enumerate(boxes) if i in indices]
    kept_scores    = [scores[i]     for i in indices]
    kept_class_ids = [class_ids[i]  for i in indices]

    return kept_boxes, kept_scores, kept_class_ids


def draw_results(frame, boxes, scores, class_ids, class_names, pill_count):
    """Draw bounding boxes, labels, and pill counter HUD."""
    # Per-class count
    count_map = defaultdict(int)

    for box, score, cid in zip(boxes, scores, class_ids):
        x1, y1, x2, y2 = box
        color = PALETTE[cid % len(PALETTE)]
        name  = class_names[cid] if cid < len(class_names) else f"class_{cid}"
        count_map[name] += 1

        # Box
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        # Label background
        label = f"{name} {score:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 4, y1), color, -1)
        cv2.putText(frame, label, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

    # HUD — pill count overlay
    hud_lines = [f"TOTAL PILLS: {len(boxes)}"] + [f"  {k}: {v}" for k, v in count_map.items()]
    for i, line in enumerate(hud_lines):
        y = 30 + i * 26
        cv2.putText(frame, line, (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                    (0, 255, 128) if i == 0 else (200, 200, 200), 2)

    return frame


def run(model_path: str, camera_index: int, class_names: list):
    session, input_name, output_name = load_model(model_path)

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"❌ Cannot open camera index {camera_index}. Try --camera 1 or 2.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    print("\n📷 Camera started. Controls:")
    print("   Q / ESC  → quit")
    print("   S        → save snapshot\n")

    fps_timer  = time.time()
    frame_count = 0
    fps_display = 0.0
    snapshot_n  = 0
    pill_total  = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠️  Frame grab failed.")
            break

        # ── Inference ──────────────────────────────────────────────────────
        inp     = preprocess(frame)
        outputs = session.run([output_name], {input_name: inp})
        boxes, scores, class_ids = postprocess(
            outputs[0], frame.shape, CONF_THRESHOLD, NMS_THRESHOLD
        )

        pill_total = len(boxes)

        # ── Draw ───────────────────────────────────────────────────────────
        frame = draw_results(frame, boxes, scores, class_ids, class_names, pill_total)

        # FPS counter
        frame_count += 1
        if time.time() - fps_timer >= 1.0:
            fps_display = frame_count / (time.time() - fps_timer)
            frame_count = 0
            fps_timer   = time.time()

        cv2.putText(frame, f"FPS: {fps_display:.1f}", (frame.shape[1] - 120, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (100, 200, 255), 2)

        cv2.imshow("Pill Counter - YOLO", frame)

        # ── Key handling ───────────────────────────────────────────────────
        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):   # Q or ESC
            break
        elif key == ord('s'):
            snapshot_n += 1
            fname = f"snapshot_{snapshot_n:03d}.jpg"
            cv2.imwrite(fname, frame)
            print(f"📸 Saved {fname}  ({pill_total} pills detected)")

    cap.release()
    cv2.destroyAllWindows()
    print("👋 Done.")


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pill Counter — YOLO ONNX + Mac Camera")
    parser.add_argument("--model",   default="best_model.onnx",
                        help="Path to your ONNX model (default: best_model.onnx)")
    parser.add_argument("--camera",  type=int, default=0,
                        help="Camera index (default: 0 = built-in Mac camera)")
    parser.add_argument("--classes", nargs="+", default=["pill"],
                        help="Class names in training order, e.g. --classes pill tablet capsule")
    parser.add_argument("--conf",    type=float, default=CONF_THRESHOLD,
                        help=f"Confidence threshold (default: {CONF_THRESHOLD})")
    parser.add_argument("--nms",     type=float, default=NMS_THRESHOLD,
                        help=f"NMS threshold (default: {NMS_THRESHOLD})")
    args = parser.parse_args()

    CONF_THRESHOLD = args.conf
    NMS_THRESHOLD  = args.nms

    run(args.model, args.camera, args.classes)