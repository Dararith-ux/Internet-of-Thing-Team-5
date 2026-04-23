"""
Pill Counter — Flask MJPEG Streaming Server
Run: python3 pill_server.py --model best_model.onnx
Then open: http://localhost:5000
"""

import cv2
import numpy as np
import onnxruntime as ort
import argparse
import time
import threading
from collections import defaultdict
from flask import Flask, Response, jsonify

# ─── CONFIG ────────────────────────────────────────────────────────────────────
CONF_THRESHOLD = 0.4
NMS_THRESHOLD  = 0.45
INPUT_SIZE     = (640, 640)

PALETTE = [
    (0, 220, 110), (0, 140, 255), (220, 60, 60),
    (180, 0, 230), (255, 190, 0), (0, 230, 230),
]
# ───────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)

# Shared state (thread-safe via lock)
state = {
    "frame_jpg": None,
    "pill_count": 0,
    "fps": 0.0,
    "counts_per_class": {},
    "conf_threshold": CONF_THRESHOLD,
}
state_lock = threading.Lock()


# ─── MODEL ─────────────────────────────────────────────────────────────────────

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
    for box, score, cid in zip(boxes, scores, class_ids):
        x1, y1, x2, y2 = box
        color = PALETTE[cid % len(PALETTE)]
        name  = class_names[cid] if cid < len(class_names) else f"cls{cid}"
        count_map[name] += 1
        cv2.rectangle(frame, (x1,y1), (x2,y2), color, 2)
        label = f"{name} {score:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(frame, (x1, y1-th-8), (x1+tw+4, y1), color, -1)
        cv2.putText(frame, label, (x1+2, y1-4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,255), 1)
    return frame, dict(count_map)


# ─── CAPTURE THREAD ────────────────────────────────────────────────────────────

def capture_loop(model_path, camera_index, class_names):
    session, input_name, output_name, batch_size = load_model(model_path)

    cap = cv2.VideoCapture(camera_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    if not cap.isOpened():
        print("❌ Camera failed to open.")
        return

    fps_t = time.time()
    fps_count = 0
    fps_val = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        with state_lock:
            conf_thresh = state["conf_threshold"]

        inp = preprocess(frame, batch_size)
        raw = session.run([output_name], {input_name: inp})[0]
        boxes, scores, class_ids = postprocess(raw, frame.shape, conf_thresh, NMS_THRESHOLD)
        frame, count_map = draw(frame, boxes, scores, class_ids, class_names)

        # FPS
        fps_count += 1
        elapsed = time.time() - fps_t
        if elapsed >= 1.0:
            fps_val   = fps_count / elapsed
            fps_count = 0
            fps_t     = time.time()

        # Encode to JPEG
        _, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])

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
        return jsonify({
            "pill_count": state["pill_count"],
            "fps":        state["fps"],
            "classes":    state["counts_per_class"],
        })


@app.route("/set_conf/<float:val>")
def set_conf(val):
    val = max(0.1, min(0.95, val))
    with state_lock:
        state["conf_threshold"] = val
    return jsonify({"conf_threshold": val})


@app.route("/")
def index():
    return open("pill_ui.html").read()


# ─── MAIN ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",   default="best_model.onnx")
    parser.add_argument("--camera",  type=int, default=0)
    parser.add_argument("--classes", nargs="+", default=["pill"])
    parser.add_argument("--port",    type=int, default=5000)
    args = parser.parse_args()

    t = threading.Thread(target=capture_loop,
                         args=(args.model, args.camera, args.classes),
                         daemon=True)
    t.start()

    print(f"\n🌐 Open http://localhost:{args.port}\n")
    app.run(host="0.0.0.0", port=args.port, threaded=True)