"""
Pill Counter — Static Image Detection
Usage: python3 pic.py --image pill_tray.jpg --model best_model.onnx
"""

import cv2
import numpy as np
import onnxruntime as ort
import argparse
import os
from collections import defaultdict

# ─── CONFIG ────────────────────────────────────────────────────────────────────
CONF_THRESHOLD = 0.5
NMS_THRESHOLD  = 0.45
INPUT_SIZE     = (640, 640)

PILL_COLOR = (0, 220, 110)  # single green color for all pills
# ───────────────────────────────────────────────────────────────────────────────


def load_model(model_path):
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    providers = ["CPUExecutionProvider"]
    if "CoreMLExecutionProvider" in ort.get_available_providers():
        providers = ["CoreMLExecutionProvider"] + providers
    session = ort.InferenceSession(model_path, sess_options=opts, providers=providers)
    input_name  = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    batch_size  = session.get_inputs()[0].shape[0]
    batch_size  = batch_size if isinstance(batch_size, int) and batch_size > 1 else 1
    print(f"✅ Model loaded | batch={batch_size} | {session.get_providers()[0]}")
    return session, input_name, output_name, batch_size


def preprocess(image, batch_size):
    img = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, INPUT_SIZE)
    img = img.astype(np.float32) / 255.0
    img = np.transpose(img, (2, 0, 1))[np.newaxis]
    if batch_size > 1:
        img = np.repeat(img, batch_size, axis=0)
    return img


def postprocess(raw, orig_shape, conf_thresh, nms_thresh):
    pred = raw[0]
    if pred.ndim == 2 and pred.shape[0] < pred.shape[1]:
        pred = pred.T
    oh, ow = orig_shape[:2]
    sx, sy = ow / INPUT_SIZE[0], oh / INPUT_SIZE[1]
    boxes, scores, class_ids = [], [], []
    for row in pred:
        if row.shape[0] == 5:
            cx, cy, w, h, conf = row
            if conf < conf_thresh: continue
            cls_id, score = 0, float(conf)
        else:
            cx, cy, w, h = row[:4]
            cls_scores = row[4:]
            cls_id = int(np.argmax(cls_scores))
            score  = float(cls_scores[cls_id])
            if score < conf_thresh: continue
        x1 = int((cx - w/2) * sx); y1 = int((cy - h/2) * sy)
        x2 = int((cx + w/2) * sx); y2 = int((cy + h/2) * sy)
        boxes.append([x1, y1, x2-x1, y2-y1])
        scores.append(score)
        class_ids.append(cls_id)
    if not boxes:
        return [], [], []
    idxs = cv2.dnn.NMSBoxes(boxes, scores, conf_thresh, nms_thresh)
    idxs = idxs.flatten() if len(idxs) else []
    kept_boxes = [[b[0],b[1],b[0]+b[2],b[1]+b[3]] for i,b in enumerate(boxes) if i in idxs]
    return kept_boxes, [scores[i] for i in idxs], [class_ids[i] for i in idxs]


def draw_results(image, boxes, scores, class_ids):
    out = image.copy()
    count_map = defaultdict(int)

    for idx, (box, score, cid) in enumerate(zip(boxes, scores, class_ids)):
        x1, y1, x2, y2 = box
        color = PILL_COLOR
        name  = "pill"
        count_map[name] += 1

        # Bounding box
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)

        # Small index number in center of box
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        num_label = str(idx + 1)
        (nw, nh), _ = cv2.getTextSize(num_label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.circle(out, (cx, cy), max(nw, nh) // 2 + 8, color, -1)
        cv2.putText(out, num_label, (cx - nw//2, cy + nh//2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # Label tag on top-left of box
        label = f"{name} {score:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        tag_y = max(y1 - th - 10, 0)
        cv2.rectangle(out, (x1, tag_y), (x1 + tw + 8, tag_y + th + 8), color, -1)
        cv2.putText(out, label, (x1 + 4, tag_y + th + 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

    # ── Summary banner at bottom ──────────────────────────────────────────────
    ih, iw = out.shape[:2]
    banner_h = 48
    banner = np.zeros((banner_h, iw, 3), dtype=np.uint8)

    total_text = f"TOTAL: {len(boxes)} pills"
    breakdown  = "  |  ".join([f"{k}: {v}" for k, v in count_map.items()])
    full_text  = f"  {total_text}    {breakdown}" if breakdown else f"  {total_text}"

    cv2.putText(banner, full_text, (10, 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 220, 110), 2)

    # Green top border on banner
    cv2.rectangle(banner, (0, 0), (iw, 2), (0, 220, 110), -1)

    out = np.vstack([out, banner])
    return out, dict(count_map)


def run(image_path, model_path, class_names, conf, nms, output_path, show):
    # ── Load image ─────────────────────────────────────────────────────────────
    if not os.path.exists(image_path):
        print(f"❌ Image not found: {image_path}")
        return

    image = cv2.imread(image_path)
    if image is None:
        print(f"❌ Could not read image: {image_path}")
        return

    print(f"📷 Image: {image_path}  ({image.shape[1]}×{image.shape[0]})")

    # ── Load model & run inference ─────────────────────────────────────────────
    session, input_name, output_name, batch_size = load_model(model_path)

    inp = preprocess(image, batch_size)
    raw = session.run([output_name], {input_name: inp})[0]
    boxes, scores, class_ids = postprocess(raw, image.shape, conf, nms)

    print(f"💊 Detected: {len(boxes)} pill(s)")

    # ── Draw & save ────────────────────────────────────────────────────────────
    result, count_map = draw_results(image, boxes, scores, class_ids)

    # Print breakdown
    for cls_name, cnt in count_map.items():
        print(f"   {cls_name}: {cnt}")

    # Save output
    if not output_path:
        base, ext = os.path.splitext(image_path)
        output_path = base + "_detected" + (ext if ext else ".jpg")

    cv2.imwrite(output_path, result)
    print(f"✅ Saved: {output_path}")

    # Show window
    if show:
        # Fit to screen (max 1400px wide)
        max_w = 1400
        h, w = result.shape[:2]
        if w > max_w:
            scale  = max_w / w
            result = cv2.resize(result, (int(w*scale), int(h*scale)))

        cv2.imshow("Pill Detection Result", result)
        print("   Press any key to close...")
        cv2.waitKey(0)
        cv2.destroyAllWindows()


# ─── ENTRY POINT ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pill Detection — Static Image")
    parser.add_argument("--image",   required=True,            help="Path to input image")
    parser.add_argument("--model",   default="best_model.onnx",help="ONNX model path")
    parser.add_argument("--classes", nargs="+", default=["pill"], help="Class names in training order")
    parser.add_argument("--conf",    type=float, default=CONF_THRESHOLD, help="Confidence threshold")
    parser.add_argument("--nms",     type=float, default=NMS_THRESHOLD,  help="NMS threshold")
    parser.add_argument("--output",  default="",               help="Output image path (optional)")
    parser.add_argument("--no-show", action="store_true",      help="Skip displaying the result window")
    args = parser.parse_args()

    run(args.image, args.model, args.classes,
        args.conf, args.nms, args.output, not args.no_show)