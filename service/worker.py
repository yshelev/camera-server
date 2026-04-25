import argparse
import json
from collections import deque
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
from scipy.signal import butter, detrend, sosfiltfilt, welch
from dotenv import load_dotenv
import os
import requests

load_dotenv()
WORKER_ID = os.getenv("WORKER_ID")
SERVER_URL = "http://127.0.0.1:8080/update_data"

FLOW_SCALE = 0.5
MOTION_THRESHOLD = 0.01
MOTION_WINDOW_SEC = 2.0
FLOW_MAG_CLIP = 5.0
GLOBAL_FLOW_MEDIAN = False

GRID_ROWS = 12
GRID_COLS = 12
PASSIVE_CELL_COVERAGE_THRESHOLD = 0.20
PASSIVE_PERCENTILE = 95.0

BREATHING_HISTORY_SEC = 10.0
BREATHING_MIN_BPM = 25.0
BREATHING_MAX_BPM = 150.0
BREATHING_BANDPASS_ORDER = 2
BREATHING_MIN_VALID_SEC = 4.0
BREATHING_MIN_ZONE_WHITE_AREA = 25
EXPORT_INTERVAL_SEC = 1.0

MASK_KERNEL_SIZE = 1
WHITE_LOW = (0, 0, 145)
WHITE_HIGH = (180, 85, 255)
MIN_WHITE_AREA = 90
WHITE_V_TARGET_MEAN = 145.0
WHITE_MASK_EMA_ALPHA = 0.2
WHITE_MASK_EMA_THRESHOLD = 0.5
CLAHE_CLIP_LIMIT = 2.5
CLAHE_TILE_GRID = (6, 6)

CAMERA_MOTION_METHOD = "lk_ransac"
DIS_VARIATIONAL_REFINEMENT_ITERS = 2
DIS_FINEST_SCALE = 1

GFTT_MAX_CORNERS = 800
GFTT_QUALITY_LEVEL = 0.005
GFTT_MIN_DISTANCE = 5
GFTT_BLOCK_SIZE = 7
LK_WIN_SIZE = (31, 31)
LK_MAX_LEVEL = 4
LK_TERM_COUNT = 30
LK_TERM_EPS = 0.01
MIN_TRACKED_POINTS = 12
RANSAC_REPROJ_THRESHOLD = 1
RANSAC_MAX_ITERS = 4000
RANSAC_CONFIDENCE = 0.99
RANSAC_REFINE_ITERS = 20

ECC_MOTION_TYPE = cv2.MOTION_EUCLIDEAN
ECC_MAX_ITERS = 50
ECC_EPSILON = 1e-4
ECC_GAUSS_FILT_SIZE = 5
ECC_MIN_BACKGROUND_RATIO = 0.05
WINDOW_NAME = "Passive Breathing Debug"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export breathing-style debug metrics for all passive 5%% zones to JSON."
    )
    parser.add_argument("--video", required=True, help="Path to input video.")
    parser.add_argument(
        "--out",
        default="outputs/breathing_passive_debug",
        help="Output base path without extension.",
    )
    parser.add_argument("--flow-scale", type=float, default=FLOW_SCALE)
    parser.add_argument("--passive-percentile", type=float, default=PASSIVE_PERCENTILE)
    parser.add_argument("--export-interval-sec", type=float, default=EXPORT_INTERVAL_SEC)
    parser.add_argument("--show", dest="show", action="store_true", help="Show debug window.")
    parser.add_argument("--no-show", dest="show", action="store_false", help="Do not show GUI window.")
    parser.set_defaults(show=True)
    parser.add_argument("--max-frames", type=int, default=None)
    return parser.parse_args()


def resize_frame(frame, scale):
    if scale == 1:
        return frame
    return cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def safe_json(value):
    if isinstance(value, dict):
        return {key: safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(item) for item in value]
    if isinstance(value, np.ndarray):
        return safe_json(value.tolist())
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    return value


def normalize_value_channel(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    value = hsv[..., 2]
    current_mean = float(np.mean(value))
    if current_mean > 1e-6:
        value *= WHITE_V_TARGET_MEAN / current_mean
    hsv[..., 2] = np.clip(value, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def remove_small_white_components(mask):
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    clean_mask = np.zeros_like(mask)
    for label_idx in range(1, num_labels):
        area = int(stats[label_idx, cv2.CC_STAT_AREA])
        if area >= MIN_WHITE_AREA:
            clean_mask[labels == label_idx] = 255
    return clean_mask


def get_white_mask(bgr):
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (MASK_KERNEL_SIZE, MASK_KERNEL_SIZE))
    normalized_bgr = normalize_value_channel(bgr)
    hsv = cv2.cvtColor(normalized_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, WHITE_LOW, WHITE_HIGH)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return remove_small_white_components(mask)


def compute_grid_scores(activity_map):
    row_edges = np.linspace(0, activity_map.shape[0], GRID_ROWS + 1, dtype=np.int32)
    col_edges = np.linspace(0, activity_map.shape[1], GRID_COLS + 1, dtype=np.int32)
    grid_scores = np.zeros((GRID_ROWS, GRID_COLS), dtype=np.float32)
    for row_idx in range(GRID_ROWS):
        for col_idx in range(GRID_COLS):
            y0, y1 = row_edges[row_idx], row_edges[row_idx + 1]
            x0, x1 = col_edges[col_idx], col_edges[col_idx + 1]
            cell = activity_map[y0:y1, x0:x1]
            if cell.size:
                grid_scores[row_idx, col_idx] = float(cell.mean())
    return grid_scores, row_edges, col_edges


def compute_grid_masked_scores(activity_map, binary_mask):
    row_edges = np.linspace(0, activity_map.shape[0], GRID_ROWS + 1, dtype=np.int32)
    col_edges = np.linspace(0, activity_map.shape[1], GRID_COLS + 1, dtype=np.int32)
    grid_scores = np.full((GRID_ROWS, GRID_COLS), np.nan, dtype=np.float32)
    for row_idx in range(GRID_ROWS):
        for col_idx in range(GRID_COLS):
            y0, y1 = row_edges[row_idx], row_edges[row_idx + 1]
            x0, x1 = col_edges[col_idx], col_edges[col_idx + 1]
            activity_cell = activity_map[y0:y1, x0:x1]
            mask_cell = binary_mask[y0:y1, x0:x1] > 0
            if activity_cell.size and np.any(mask_cell):
                grid_scores[row_idx, col_idx] = float(activity_cell[mask_cell].mean())
    return grid_scores, row_edges, col_edges


def compute_grid_coverage(binary_mask, row_edges, col_edges):
    grid_coverage = np.zeros((GRID_ROWS, GRID_COLS), dtype=np.float32)
    for row_idx in range(GRID_ROWS):
        for col_idx in range(GRID_COLS):
            y0, y1 = row_edges[row_idx], row_edges[row_idx + 1]
            x0, x1 = col_edges[col_idx], col_edges[col_idx + 1]
            cell = binary_mask[y0:y1, x0:x1]
            if cell.size:
                grid_coverage[row_idx, col_idx] = float(np.count_nonzero(cell) / cell.size)
    return grid_coverage


def select_local_breathing_roi(binary_mask, row_idx, col_idx, row_edges, col_edges):
    y0, y1 = row_edges[row_idx], row_edges[row_idx + 1]
    x0, x1 = col_edges[col_idx], col_edges[col_idx + 1]
    cell_mask = binary_mask[y0:y1, x0:x1]
    roi_mask = np.zeros_like(binary_mask, dtype=np.uint8)
    white_area = int(np.count_nonzero(cell_mask))
    zone_coverage = float(white_area / cell_mask.size) if cell_mask.size else 0.0
    if white_area > 0:
        roi_mask[y0:y1, x0:x1] = cell_mask
    return roi_mask, (int(x0), int(y0), int(x1), int(y1)), white_area, zone_coverage


def compute_local_breathing_signals(flow_x, flow_y, roi_mask):
    roi_pixels = roi_mask > 0
    if not np.any(roi_pixels):
        return float("nan"), float("nan"), float("nan"), float("nan")
    roi_y, roi_x = np.nonzero(roi_pixels)
    mean_abs_flow_x = float(np.abs(flow_x[roi_pixels]).mean())
    centroid_x = float(roi_x.mean())
    mean_abs_flow_y = float(np.abs(flow_y[roi_pixels]).mean())
    centroid_y = float(roi_y.mean())
    return mean_abs_flow_x, centroid_x, mean_abs_flow_y, centroid_y


def append_breathing_history_sample(
    history_map,
    zone_key,
    time_sec,
    mean_abs_flow_x_raw,
    centroid_x_raw,
    mean_abs_flow_y_raw,
    centroid_y_raw,
    history_len,
):
    if zone_key not in history_map:
        history_map[zone_key] = {
            "time_sec": deque(maxlen=history_len),
            "mean_abs_flow_x_raw": deque(maxlen=history_len),
            "centroid_x_raw": deque(maxlen=history_len),
            "mean_abs_flow_y_raw": deque(maxlen=history_len),
            "centroid_y_raw": deque(maxlen=history_len),
        }
    zone_history = history_map[zone_key]
    zone_history["time_sec"].append(float(time_sec))
    zone_history["mean_abs_flow_x_raw"].append(float(mean_abs_flow_x_raw))
    zone_history["centroid_x_raw"].append(float(centroid_x_raw))
    zone_history["mean_abs_flow_y_raw"].append(float(mean_abs_flow_y_raw))
    zone_history["centroid_y_raw"].append(float(centroid_y_raw))
    return zone_history


def estimate_breathing_rate(signal_values, fps):
    values = np.asarray(signal_values, dtype=np.float32)
    min_samples = max(8, int(round(BREATHING_MIN_VALID_SEC * fps)))
    if values.size < min_samples:
        return {
            "available": False,
            "reason": "history_too_short",
            "bpm": None,
            "peak_power": None,
            "raw": values,
            "filtered": None,
        }
    finite = np.isfinite(values)
    if finite.sum() < min_samples:
        return {
            "available": False,
            "reason": "not_enough_valid_points",
            "bpm": None,
            "peak_power": None,
            "raw": values,
            "filtered": None,
        }
    indices = np.arange(values.size, dtype=np.float32)
    if not np.all(finite):
        values = np.interp(indices, indices[finite], values[finite]).astype(np.float32)
    values = detrend(values, type="linear").astype(np.float32)
    nyquist = 0.5 * fps
    low = (BREATHING_MIN_BPM / 60.0) / nyquist
    high = min((BREATHING_MAX_BPM / 60.0) / nyquist, 0.99)
    if high <= low:
        return {
            "available": False,
            "reason": "invalid_band",
            "bpm": None,
            "peak_power": None,
            "raw": values,
            "filtered": None,
        }
    if values.size < 18:
        return {
            "available": False,
            "reason": "filter_padding",
            "bpm": None,
            "peak_power": None,
            "raw": values,
            "filtered": None,
        }
    sos = butter(BREATHING_BANDPASS_ORDER, [low, high], btype="bandpass", output="sos")
    try:
        filtered = sosfiltfilt(sos, values).astype(np.float32)
    except ValueError:
        return {
            "available": False,
            "reason": "filter_failed",
            "bpm": None,
            "peak_power": None,
            "raw": values,
            "filtered": None,
        }
    nperseg = min(filtered.size, max(16, int(round(fps * 4))))
    freqs, psd = welch(filtered, fs=fps, nperseg=nperseg)
    valid_band = (freqs >= BREATHING_MIN_BPM / 60.0) & (freqs <= BREATHING_MAX_BPM / 60.0)
    if not np.any(valid_band):
        return {
            "available": False,
            "reason": "no_band_power",
            "bpm": None,
            "peak_power": None,
            "raw": values,
            "filtered": filtered,
        }
    band_freqs = freqs[valid_band]
    band_psd = psd[valid_band]
    peak_idx = int(np.argmax(band_psd))
    peak_freq = float(band_freqs[peak_idx])
    peak_power = float(band_psd[peak_idx])
    return {
        "available": True,
        "reason": "ok",
        "bpm": peak_freq * 60.0,
        "peak_power": peak_power,
        "raw": values,
        "filtered": filtered,
    }


def serialize_estimate(estimate, fps):
    tail_len = max(1, int(round(BREATHING_MIN_VALID_SEC * fps)))
    filtered = estimate.get("filtered")
    filtered_tail = []
    centroid_shift = 100
    if filtered is not None:
        filtered_tail = np.asarray(filtered, dtype=np.float32)[-tail_len:].tolist()
        centroid_shift = np.abs(np.asarray(filtered, dtype=np.float32)[-tail_len:]).sum()
    return {
        "available": bool(estimate["available"]),
        "reason": estimate["reason"],
        "bpm": estimate["bpm"],
        "peak_power": estimate["peak_power"],
        "filtered_last_4sec": filtered_tail,
        "filtered_last_4sec_sample_count": len(filtered_tail),
        "filtered_centroid_shift": centroid_shift
    }


def warp_triplet(gray_frame, color_frame, mask_frame, affine):
    size = (gray_frame.shape[1], gray_frame.shape[0])
    gray_aligned = cv2.warpAffine(
        gray_frame,
        affine,
        size,
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REPLICATE,
    )
    color_aligned = cv2.warpAffine(
        color_frame,
        affine,
        size,
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REPLICATE,
    )
    mask_aligned = cv2.warpAffine(
        mask_frame,
        affine,
        size,
        flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return gray_aligned, color_aligned, mask_aligned


def align_with_ecc(prev_gray, curr_gray, curr_small, curr_white_mask, prev_background_mask):
    background_ratio = float(np.count_nonzero(prev_background_mask)) / prev_background_mask.size
    if background_ratio < ECC_MIN_BACKGROUND_RATIO:
        return curr_gray, curr_small, curr_white_mask

    warp_matrix = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, ECC_MAX_ITERS, ECC_EPSILON)
    try:
        cv2.findTransformECC(
            prev_gray,
            curr_gray,
            warp_matrix,
            ECC_MOTION_TYPE,
            criteria,
            prev_background_mask,
            ECC_GAUSS_FILT_SIZE,
        )
    except cv2.error:
        return curr_gray, curr_small, curr_white_mask
    return warp_triplet(curr_gray, curr_small, curr_white_mask, warp_matrix)


def align_with_lk_ransac(prev_gray, curr_gray, curr_small, curr_white_mask, prev_background_mask):
    prev_points = cv2.goodFeaturesToTrack(
        prev_gray,
        maxCorners=GFTT_MAX_CORNERS,
        qualityLevel=GFTT_QUALITY_LEVEL,
        minDistance=GFTT_MIN_DISTANCE,
        mask=prev_background_mask,
        blockSize=GFTT_BLOCK_SIZE,
    )
    if prev_points is None or len(prev_points) < MIN_TRACKED_POINTS:
        return curr_gray, curr_small, curr_white_mask

    next_points, status, _ = cv2.calcOpticalFlowPyrLK(
        prev_gray,
        curr_gray,
        prev_points,
        None,
        winSize=LK_WIN_SIZE,
        maxLevel=LK_MAX_LEVEL,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, LK_TERM_COUNT, LK_TERM_EPS),
    )
    if next_points is None or status is None:
        return curr_gray, curr_small, curr_white_mask

    status = status.reshape(-1).astype(bool)
    prev_good = prev_points.reshape(-1, 2)[status]
    next_good = next_points.reshape(-1, 2)[status]
    finite = np.isfinite(prev_good).all(axis=1) & np.isfinite(next_good).all(axis=1)
    prev_good = prev_good[finite]
    next_good = next_good[finite]
    if len(prev_good) < MIN_TRACKED_POINTS:
        return curr_gray, curr_small, curr_white_mask

    affine, _ = cv2.estimateAffinePartial2D(
        prev_good,
        next_good,
        method=cv2.RANSAC,
        ransacReprojThreshold=RANSAC_REPROJ_THRESHOLD,
        maxIters=RANSAC_MAX_ITERS,
        confidence=RANSAC_CONFIDENCE,
        refineIters=RANSAC_REFINE_ITERS,
    )
    if affine is None:
        return curr_gray, curr_small, curr_white_mask
    return warp_triplet(curr_gray, curr_small, curr_white_mask, affine)


def align_with_global_motion(prev_gray, curr_gray, curr_small, curr_white_mask, prev_background_mask):
    if CAMERA_MOTION_METHOD == "none":
        return curr_gray, curr_small, curr_white_mask
    if CAMERA_MOTION_METHOD == "ecc":
        return align_with_ecc(prev_gray, curr_gray, curr_small, curr_white_mask, prev_background_mask)
    return align_with_lk_ransac(prev_gray, curr_gray, curr_small, curr_white_mask, prev_background_mask)


def build_debug_display(base_small, motion_ema, passive_zone_records, scale_x, scale_y, fps, time_sec):
    motion_vis = np.clip(motion_ema * 500.0, 0, 255).astype(np.uint8)
    heatmap_small = cv2.applyColorMap(motion_vis, cv2.COLORMAP_JET)
    display = cv2.addWeighted(base_small, 0.6, heatmap_small, 0.4, 0)

    for zone_idx, zone_record in enumerate(passive_zone_records):
        x0, y0, x1, y1 = zone_record["roi_bbox_scaled"]
        color = (120, 255, 120) if zone_record["has_min_white_area"] else (120, 120, 255)
        cv2.rectangle(display, (x0, y0), (x1, y1), color, 2)
        mean_y = zone_record["metrics"]["mean_abs_flow_y"]
        cent_y = zone_record["metrics"]["centroid_y"]
        mean_label = f"{mean_y['bpm']:.0f}" if mean_y["available"] and mean_y["bpm"] is not None else "--"
        cent_label = f"{cent_y['bpm']:.0f}" if cent_y["available"] and cent_y["bpm"] is not None else "--"
        label = f"z{zone_idx + 1}: {mean_label}/{cent_label}"
        cv2.putText(
            display,
            label,
            (x0 + 4, max(18, y0 + 18)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )

    cv2.putText(display, f"FPS: {fps:.1f}", (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    cv2.putText(display, f"time: {time_sec:.1f}s", (20, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(
        display,
        f"passive zones: {len(passive_zone_records)}",
        (20, 100),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (120, 220, 255),
        2,
    )

    if scale_x != 1.0 or scale_y != 1.0:
        display = cv2.resize(
            display,
            (int(round(display.shape[1] * scale_x)), int(round(display.shape[0] * scale_y))),
            interpolation=cv2.INTER_LINEAR,
        )
    return display


def build_zone_record(
    zone_key,
    zone_history,
    roi_bbox_scaled,
    roi_area,
    roi_coverage,
    activity_score,
    cell_coverage,
    scale_x,
    scale_y,
    fps,
):
    x0, y0, x1, y1 = roi_bbox_scaled
    mean_abs_x_estimate = estimate_breathing_rate(zone_history["mean_abs_flow_x_raw"], fps)
    centroid_x_estimate = estimate_breathing_rate(zone_history["centroid_x_raw"], fps)
    mean_abs_y_estimate = estimate_breathing_rate(zone_history["mean_abs_flow_y_raw"], fps)
    centroid_y_estimate = estimate_breathing_rate(zone_history["centroid_y_raw"], fps)
    return {
        "zone_key": [int(zone_key[0]), int(zone_key[1])],
        "roi_bbox_scaled": [int(x0), int(y0), int(x1), int(y1)],
        "roi_bbox_original": [
            float(x0 * scale_x),
            float(y0 * scale_y),
            float(x1 * scale_x),
            float(y1 * scale_y),
        ],
        "roi_area": int(roi_area),
        "roi_coverage": float(roi_coverage),
        "cell_activity_score": float(activity_score),
        "cell_coverage": float(cell_coverage),
        "history_sec": float(
            zone_history["time_sec"][-1] - zone_history["time_sec"][0]
        ) if len(zone_history["time_sec"]) >= 2 else 0.0,
        "has_min_white_area": bool(roi_area >= BREATHING_MIN_ZONE_WHITE_AREA),
        "metrics": {
            "mean_abs_flow_x": serialize_estimate(mean_abs_x_estimate, fps),
            "centroid_x": serialize_estimate(centroid_x_estimate, fps),
            "mean_abs_flow_y": serialize_estimate(mean_abs_y_estimate, fps),
            "centroid_y": serialize_estimate(centroid_y_estimate, fps),
        },
    }


def export_passive_breathing(args):
    out_base = Path(args.out)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    json_path = out_base.with_suffix(".json")

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {args.video}")

    ok, prev_frame = cap.read()
    if not ok:
        raise RuntimeError(f"Could not read first frame: {args.video}")

    prev_small = resize_frame(prev_frame, args.flow_scale)
    scale_x = prev_frame.shape[1] / prev_small.shape[1]
    scale_y = prev_frame.shape[0] / prev_small.shape[0]

    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=CLAHE_TILE_GRID)
    prev_gray = cv2.cvtColor(prev_small, cv2.COLOR_BGR2GRAY)
    prev_gray_enhanced = clahe.apply(prev_gray)

    initial_white_mask = get_white_mask(prev_small)
    prev_stable_white_mask = initial_white_mask.copy()
    white_mask_ema = initial_white_mask.astype(np.float32) / 255.0

    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
    dis.setVariationalRefinementIterations(DIS_VARIATIONAL_REFINEMENT_ITERS)
    dis.setFinestScale(DIS_FINEST_SCALE)

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not np.isfinite(fps) or fps <= 0:
        fps = 30.0

    breathing_history_len = max(8, int(round(fps * BREATHING_HISTORY_SEC)))
    alpha = 1.0 / max(1, int(round(fps * MOTION_WINDOW_SEC)))
    motion_ema = np.zeros_like(prev_gray, dtype=np.float32)

    breathing_histories = {}
    export_samples = []
    next_export_time = float(max(1e-6, args.export_interval_sec))
    frame_count = 0
    total_runtime_sec = 0.0

    while True:
        t_start = perf_counter()
        ok, frame = cap.read()
        if not ok:
            break
        if args.max_frames is not None and frame_count >= args.max_frames:
            break

        small = resize_frame(frame, args.flow_scale)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray_enhanced = clahe.apply(gray)
        raw_white_mask = get_white_mask(small)
        prev_background_mask = cv2.bitwise_not(prev_stable_white_mask)

        gray_aligned, small_aligned, white_mask_aligned = align_with_global_motion(
            prev_gray_enhanced,
            gray_enhanced,
            small,
            raw_white_mask,
            prev_background_mask,
        )

        cv2.accumulateWeighted(
            white_mask_aligned.astype(np.float32) / 255.0,
            white_mask_ema,
            WHITE_MASK_EMA_ALPHA,
        )
        stable_white_mask = (white_mask_ema >= WHITE_MASK_EMA_THRESHOLD).astype(np.uint8) * 255

        flow = dis.calc(prev_gray_enhanced, gray_aligned, None)
        flow_x = flow[..., 0]
        flow_y = flow[..., 1]

        gate_pixels = stable_white_mask > 0
        if GLOBAL_FLOW_MEDIAN and np.any(gate_pixels):
            flow_x = flow_x.copy()
            flow_y = flow_y.copy()
            flow_x -= float(np.median(flow_x[gate_pixels]))
            flow_y -= float(np.median(flow_y[gate_pixels]))

        mag, _ = cv2.cartToPolar(flow_x, flow_y)
        mag = mag.astype(np.float32)
        mag[~gate_pixels] = 0.0
        mag = np.maximum(mag - MOTION_THRESHOLD, 0.0)
        np.clip(mag, 0.0, FLOW_MAG_CLIP, out=mag)
        cv2.accumulateWeighted(mag, motion_ema, alpha)

        last_grid_scores, row_edges, col_edges = compute_grid_scores(motion_ema)
        passive_grid_scores, _, _ = compute_grid_masked_scores(motion_ema, stable_white_mask)
        grid_coverage = compute_grid_coverage(stable_white_mask, row_edges, col_edges)

        passive_candidates = (grid_coverage >= PASSIVE_CELL_COVERAGE_THRESHOLD) & np.isfinite(passive_grid_scores)
        finite_passive_scores = np.isfinite(passive_grid_scores)
        if np.any(passive_candidates):
            valid_passive_scores = passive_grid_scores[passive_candidates]
            passive_selection_mask = passive_candidates
        elif np.any(finite_passive_scores):
            valid_passive_scores = passive_grid_scores[finite_passive_scores]
            passive_selection_mask = finite_passive_scores
        else:
            valid_passive_scores = last_grid_scores.reshape(-1)
            passive_selection_mask = np.ones_like(last_grid_scores, dtype=bool)

        percentile_threshold = max(0.0, 100.0 - float(args.passive_percentile))
        passive_score_threshold = float(np.percentile(valid_passive_scores, percentile_threshold))

        if np.any(np.isfinite(passive_grid_scores)):
            passive_cells_mask = passive_selection_mask & (
                np.where(np.isfinite(passive_grid_scores), passive_grid_scores, np.inf) <= passive_score_threshold
            )
        else:
            passive_cells_mask = passive_selection_mask & (last_grid_scores <= passive_score_threshold)

        passive_indices = np.argwhere(passive_cells_mask)
        if passive_indices.size == 0:
            passive_flat_idx = int(np.argmin(last_grid_scores))
            passive_cells_mask.flat[passive_flat_idx] = True
            passive_indices = np.argwhere(passive_cells_mask)

        zone_records = []
        time_sec = float((frame_count + 1) / fps)
        zone_keys = []
        for zone_rc in passive_indices:
            zone_key = (int(zone_rc[0]), int(zone_rc[1]))
            zone_keys.append(zone_key)

        zone_keys.sort(
            key=lambda key: float(passive_grid_scores[key]) if np.isfinite(passive_grid_scores[key]) else float(last_grid_scores[key])
        )

        for zone_key in zone_keys:
            zone_row, zone_col = zone_key
            roi_mask, roi_bbox_scaled, roi_area, roi_coverage = select_local_breathing_roi(
                white_mask_aligned,
                zone_row,
                zone_col,
                row_edges,
                col_edges,
            )
            mean_abs_flow_x_raw, centroid_x_raw, mean_abs_flow_y_raw, centroid_y_raw = compute_local_breathing_signals(
                flow_x,
                flow_y,
                roi_mask,
            )
            zone_history = append_breathing_history_sample(
                breathing_histories,
                zone_key,
                time_sec,
                mean_abs_flow_x_raw,
                centroid_x_raw,
                mean_abs_flow_y_raw,
                centroid_y_raw,
                breathing_history_len,
            )
            activity_score = (
                float(passive_grid_scores[zone_key])
                if np.isfinite(passive_grid_scores[zone_key])
                else float(last_grid_scores[zone_key])
            )
            cell_coverage = float(grid_coverage[zone_key])
            zone_records.append(
                build_zone_record(
                    zone_key,
                    zone_history,
                    roi_bbox_scaled,
                    roi_area,
                    roi_coverage,
                    activity_score,
                    cell_coverage,
                    scale_x,
                    scale_y,
                    fps,
                )
            )

        total_runtime_sec += perf_counter() - t_start
        current_fps = (frame_count + 1) / max(total_runtime_sec, 1e-6)

        if time_sec + 1e-9 >= next_export_time:
            # export_samples.append(
            #     {
            #         "sample_idx": int(len(export_samples) + 1),
            #         "frame_idx": int(frame_count + 1),
            #         "time_sec": time_sec,
            #         "passive_percentile": float(args.passive_percentile),
            #         "passive_score_threshold": passive_score_threshold,
            #         "passive_zone_count": int(len(zone_records)),
            #         "zones": zone_records,
            #     }
            # )
            json_val = safe_json({
                "service_id": WORKER_ID, 
                "sample_idx": int(len(export_samples) + 1),
                "frame_idx": int(frame_count + 1),
                "time_sec": time_sec,
                "passive_percentile": float(args.passive_percentile),
                "passive_score_threshold": passive_score_threshold,
                "passive_zone_count": int(len(zone_records)),
                "zones": zone_records,
            })
            try: 
                response = requests.post(
                    SERVER_URL, 
                    json=json_val
                )
            except Exception as e: 
                print(e)
            
            next_export_time += float(max(1e-6, args.export_interval_sec))

        if args.show:
            debug_display = build_debug_display(
                small_aligned,
                motion_ema,
                zone_records,
                scale_x,
                scale_y,
                current_fps,
                time_sec,
            )
            # cv2.imshow(WINDOW_NAME, debug_display)
            # if cv2.waitKey(1) & 0xFF == ord("q"):
            #     frame_count += 1
            #     break

        prev_gray_enhanced = gray_aligned
        prev_stable_white_mask = stable_white_mask
        frame_count += 1

    payload = {
        "schema_version": "passive_breathing_debug.v1",
        "video_source": args.video,
        "fps": float(fps),
        "frame_size_original": [int(prev_frame.shape[1]), int(prev_frame.shape[0])],
        "frame_size_scaled": [int(prev_small.shape[1]), int(prev_small.shape[0])],
        "config": {
            "flow_scale": float(args.flow_scale),
            "passive_percentile": float(args.passive_percentile),
            "export_interval_sec": float(args.export_interval_sec),
            "grid_rows": GRID_ROWS,
            "grid_cols": GRID_COLS,
            "passive_cell_coverage_threshold": PASSIVE_CELL_COVERAGE_THRESHOLD,
            "breathing_min_valid_sec": BREATHING_MIN_VALID_SEC,
            "breathing_history_sec": BREATHING_HISTORY_SEC,
            "breathing_min_zone_white_area": BREATHING_MIN_ZONE_WHITE_AREA,
            "camera_motion_method": CAMERA_MOTION_METHOD,
        },
        "samples": export_samples,
        "summary": {
            "frames_processed": int(frame_count),
            "samples_written": int(len(export_samples)),
            "json_path": str(json_path),
        },
    }

    with open(json_path, "w", encoding="utf-8") as json_file:
        json.dump(safe_json(payload), json_file, ensure_ascii=False, allow_nan=False, indent=2)
        json_file.write("\n")

    cap.release()
    if args.show:
        cv2.destroyAllWindows()
    print(json.dumps(safe_json(payload["summary"]), ensure_ascii=False))


def main():
    args = parse_args()
    export_passive_breathing(args)


if __name__ == "__main__":
    main()
