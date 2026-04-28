"""
Pill Counter — Flask MJPEG Streaming Server (ESP32-CAM edition)
Run: python3 pill_server.py --model best_model.onnx
Then open: http://localhost:5000
"""

import cv2
import numpy as np
import onnxruntime as ort
import argparse
import time
import threading
import base64
import requests
from collections import defaultdict
from flask import Flask, Response, jsonify

# ─── CONFIG ────────────────────────────────────────────────────────────────────
CONF_THRESHOLD = 0.4
NMS_THRESHOLD  = 0.45
INPUT_SIZE     = (640, 640)

ESP32_URL      = "..."          # ← your ESP32-CAM IP
ESP32_STREAM   = f"{ESP32_URL}:81/stream"
ESP32_CAPTURE  = f"{ESP32_URL}/capture"

PALETTE = [
    (0, 220, 110), (0, 140, 255), (220, 60, 60),
    (180, 0, 230), (255, 190, 0), (0, 230, 230),
]
# ───────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)

# Global session — shared between streaming thread and capture route
g_session     = None
g_input_name  = None
g_output_name = None
g_batch_size  = 1
g_class_names = ["pill"]
session_lock  = threading.Lock()

# Shared streaming state
state = {
    "frame_jpg":        None,
    "pill_count":       0,
    "fps":              0.0,
    "counts_per_class": {},
    "conf_threshold":   CONF_THRESHOLD,
    "target_count":     0,       # 0 = no target set
    "capture_id":       0,       # increments on every capture
    "capture_status":   {},      # stores last capture's count_status
}
state_lock = threading.Lock()


# ─── MODEL ─────────────────────────────────────────────────────────────────────

def load_model(model_path):
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    providers = ["CPUExecutionProvider"]
    if "CoreMLExecutionProvider" in ort.get_available_providers():
        providers = ["CoreMLExecutionProvider"] + providers
    session     = ort.InferenceSession(model_path, sess_options=opts, providers=providers)
    input_name  = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    batch_size  = session.get_inputs()[0].shape[0]
    batch_size  = batch_size if isinstance(batch_size, int) and batch_size > 1 else 1
    print(f"✅ Model: {model_path}  |  batch={batch_size}  |  {session.get_providers()[0]}")
    return session, input_name, output_name, batch_size


def preprocess(frame, batch_size):
    img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
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
        scores.append(score); class_ids.append(cls_id)
    if not boxes:
        return [], [], []
    idxs = cv2.dnn.NMSBoxes(boxes, scores, conf_thresh, nms_thresh)
    idxs = idxs.flatten() if len(idxs) else []
    kept_boxes = [[b[0],b[1],b[0]+b[2],b[1]+b[3]] for i,b in enumerate(boxes) if i in idxs]
    return kept_boxes, [scores[i] for i in idxs], [class_ids[i] for i in idxs]


def draw(frame, boxes, scores, class_ids, class_names):
    count_map = defaultdict(int)
    for idx, (box, score, cid) in enumerate(zip(boxes, scores, class_ids)):
        x1, y1, x2, y2 = box
        color = PALETTE[cid % len(PALETTE)]
        name  = class_names[cid] if cid < len(class_names) else f"pill{cid}"
        count_map[name] += 1

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        # Index number in center
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        num_label = str(idx + 1)
        (nw, nh), _ = cv2.getTextSize(num_label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.circle(frame, (cx, cy), max(nw, nh) // 2 + 8, color, -1)
        cv2.putText(frame, num_label, (cx - nw//2, cy + nh//2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # Label tag
        label = f"{name} {score:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(frame, (x1, y1-th-8), (x1+tw+4, y1), color, -1)
        cv2.putText(frame, label, (x1+2, y1-4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

    return frame, dict(count_map)


def run_inference(image, conf_thresh):
    """Shared inference helper — used by both stream thread and capture route."""
    with session_lock:
        inp = preprocess(image, g_batch_size)
        raw = g_session.run([g_output_name], {g_input_name: inp})[0]
    boxes, scores, class_ids = postprocess(raw, image.shape, conf_thresh, NMS_THRESHOLD)
    annotated, count_map = draw(image.copy(), boxes, scores, class_ids, g_class_names)
    return annotated, boxes, count_map


def get_count_status(detected, target):
    """
    Compare detected pill count against the target.
    Returns a dict with status, message, and difference.
    status: 'correct' | 'add_more' | 'remove' | 'no_target'
    """
    if target == 0:
        return {"status": "no_target", "message": "", "diff": 0}
    diff = detected - target
    if diff == 0:
        return {
            "status":  "correct",
            "message": f"Correct! Exactly {target} pill{'s' if target != 1 else ''} detected.",
            "diff":    0
        }
    elif diff < 0:
        missing = abs(diff)
        return {
            "status":  "add_more",
            "message": f"Add {missing} more pill{'s' if missing != 1 else ''}. ({detected} of {target} detected)",
            "diff":    diff
        }
    else:
        return {
            "status":  "remove",
            "message": f"Remove {diff} excess pill{'s' if diff != 1 else ''}. ({detected} detected, need {target})",
            "diff":    diff
        }


# ─── CAPTURE THREAD ────────────────────────────────────────────────────────────

def capture_loop():
    """Reads MJPEG stream from ESP32-CAM and runs inference continuously."""
    print(f"📡 Connecting to ESP32 stream: {ESP32_STREAM}")
    cap = cv2.VideoCapture(ESP32_STREAM)

    if not cap.isOpened():
        print("❌ Could not open ESP32 stream. Check IP and that :81/stream is reachable.")
        return

    print("✅ ESP32 stream connected")

    fps_t, fps_count, fps_val = time.time(), 0, 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠️  Frame dropped, retrying...")
            time.sleep(0.05)
            continue

        with state_lock:
            conf_thresh = state["conf_threshold"]

        annotated, boxes, count_map = run_inference(frame, conf_thresh)

        # FPS counter
        fps_count += 1
        elapsed = time.time() - fps_t
        if elapsed >= 1.0:
            fps_val   = fps_count / elapsed
            fps_count = 0
            fps_t     = time.time()

        _, jpg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])

        with state_lock:
            state["frame_jpg"]        = jpg.tobytes()
            state["pill_count"]       = len(boxes)
            state["fps"]              = round(fps_val, 1)
            state["counts_per_class"] = count_map

    cap.release()


# ─── FLASK ROUTES ───────────────────────────────────────────────────────────────

def gen_frames():
    while True:
        with state_lock:
            jpg = state["frame_jpg"]
        if jpg is None:
            time.sleep(0.03)
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")
        time.sleep(0.01)


@app.route("/video_feed")
def video_feed():
    return Response(gen_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/stats")
def stats():
    with state_lock:
        detected = state["pill_count"]
        target   = state["target_count"]
        return jsonify({
            "pill_count":   detected,
            "fps":          state["fps"],
            "classes":      state["counts_per_class"],
            "target_count": target,
            "count_status": get_count_status(detected, target),
        })


@app.route("/capture_result")
def capture_result():
    """Polled by the ESP32 buzzer — only changes when a new capture happens."""
    with state_lock:
        return jsonify({
            "capture_id":     state["capture_id"],
            "capture_status": state["capture_status"],
        })


@app.route("/set_conf/<float:val>")
def set_conf(val):
    val = max(0.1, min(0.95, val))
    with state_lock:
        state["conf_threshold"] = val
    return jsonify({"conf_threshold": val})


@app.route("/set_target/<int:val>")
def set_target(val):
    val = max(0, val)
    with state_lock:
        state["target_count"] = val
    return jsonify({"target_count": val})


@app.route("/capture_and_detect")
def capture_and_detect():
    """
    Grab a fresh still from the ESP32-CAM, run inference,
    return annotated image (base64) + counts + target status as JSON.
    Also increments capture_id so the ESP32 buzzer knows a new capture occurred.
    """
    try:
        r = requests.get(ESP32_CAPTURE, timeout=5)
        r.raise_for_status()
    except Exception as e:
        return jsonify({"error": f"Could not reach ESP32: {e}"}), 502

    arr   = np.frombuffer(r.content, np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        return jsonify({"error": "Failed to decode image from ESP32"}), 500

    with state_lock:
        conf_thresh  = state["conf_threshold"]
        target_count = state["target_count"]

    annotated, boxes, count_map = run_inference(image, conf_thresh)
    detected     = len(boxes)
    count_status = get_count_status(detected, target_count)

    # Increment capture_id and store status so ESP32 buzzer can react
    with state_lock:
        state["capture_id"]    += 1
        state["capture_status"] = count_status

    _, jpg_annotated = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 90])
    _, jpg_raw       = cv2.imencode(".jpg", image,     [cv2.IMWRITE_JPEG_QUALITY, 90])

    return jsonify({
        "image":        base64.b64encode(jpg_annotated).decode("utf-8"),
        "raw_image":    base64.b64encode(jpg_raw).decode("utf-8"),
        "count":        detected,
        "classes":      count_map,
        "target_count": target_count,
        "count_status": count_status,
    })


@app.route("/")
def index():
    return open("pill_ui2.html").read()


# ─── MAIN ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",   default="best_model.onnx")
    parser.add_argument("--classes", nargs="+", default=["pill"])
    parser.add_argument("--port",    type=int,  default=5000)
    args = parser.parse_args()

    g_session, g_input_name, g_output_name, g_batch_size = load_model(args.model)
    g_class_names = args.classes

    t = threading.Thread(target=capture_loop, daemon=True)
    t.start()

    print(f"\n🌐 Open http://localhost:{args.port}\n")
    app.run(host="0.0.0.0", port=args.port, threaded=True)