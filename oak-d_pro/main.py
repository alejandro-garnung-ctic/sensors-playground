#!/usr/bin/env python3
"""
OAK-D Pro — RGB + Depth con GUI de parámetros en tiempo real.
Uso: python main.py  |  'q' en la ventana de vídeo para salir.
"""

import cv2
import numpy as np
import depthai as dai
import time
import threading
import queue as pyqueue
import tkinter as tk
from tkinter import ttk
from datetime import timedelta

FPS = 25.0

MEDIAN_OPTIONS = {
    "Desactivado": dai.node.ImageFilters.MedianFilterParams.MEDIAN_OFF,
    "3×3":         dai.node.ImageFilters.MedianFilterParams.KERNEL_3x3,
    "5×5":         dai.node.ImageFilters.MedianFilterParams.KERNEL_5x5,
}
# Orden fijo de filtros en el nodo ImageFilters
FIDX = {"median": 0, "spatial": 1, "temporal": 2, "speckle": 3}

# ── Estado compartido ────────────────────────────────────────────────────────
_lock  = threading.Lock()
params = {
    # visualización (en vivo)
    "rgb_pct":       40,
    "mode":          "rel",   # "rel" | "abs"
    "depth_min_m":   0.3,
    "depth_max_m":   6.0,
    # filtros (en vivo, vía inputConfig)
    "median":        "5×5",
    "spatial":       True,
    "temporal":      True,
    "t_alpha":       0.4,
    "speckle":       False,
    # estéreo (estáticos — requieren reinicio del pipeline)
    "subpixel":      True,
    "lr_check":      True,
    "extended":      False,
    # señales internas
    "filters_dirty": False,
    "quit":          False,
}

frame_q      = pyqueue.Queue(maxsize=2)
pipeline_ref = [None]   # hilo activo del pipeline


# ── Colorización ─────────────────────────────────────────────────────────────
def colorize_relative(depth):
    invalid = depth == 0
    try:
        valid = depth[~invalid]
        lo, hi = np.percentile(valid, 3), np.percentile(valid, 95)
        log = np.zeros_like(depth, dtype=np.float32)
        np.log(depth, where=~invalid, out=log)
        log = np.clip(log, np.log(lo), np.log(hi))
        vis = np.interp(log, (np.log(lo), np.log(hi)), (0, 255)).astype(np.uint8)
        out = cv2.applyColorMap(vis, cv2.COLORMAP_JET)
        out[invalid] = 0
        return out
    except Exception:
        return np.zeros((*depth.shape, 3), dtype=np.uint8)


def colorize_absolute(depth, min_mm, max_mm):
    invalid = depth == 0
    vis = np.clip(depth.astype(np.float32), min_mm, max_mm)
    vis = ((vis - min_mm) / max(max_mm - min_mm, 1) * 255).astype(np.uint8)
    out = cv2.applyColorMap(vis, cv2.COLORMAP_JET)
    out[invalid] = 0
    return out


# ── Helpers de filtros ───────────────────────────────────────────────────────
def _make_spatial(p):
    s = dai.node.ImageFilters.SpatialFilterParams()
    s.enable = p["spatial"]
    return s

def _make_temporal(p):
    t = dai.node.ImageFilters.TemporalFilterParams()
    t.enable = p["temporal"]
    t.alpha  = p["t_alpha"]
    t.persistencyMode = dai.filters.params.TemporalFilter.PersistencyMode.VALID_2_IN_LAST_4
    return t

def _make_speckle(p):
    s = dai.node.ImageFilters.SpeckleFilterParams()
    s.enable = p["speckle"]
    return s

def apply_all_filters(cfg_q, p):
    cfg_q.send(dai.ImageFiltersConfig().updateFilterAtIndex(FIDX["median"],   MEDIAN_OPTIONS[p["median"]]))
    cfg_q.send(dai.ImageFiltersConfig().updateFilterAtIndex(FIDX["spatial"],  _make_spatial(p)))
    cfg_q.send(dai.ImageFiltersConfig().updateFilterAtIndex(FIDX["temporal"], _make_temporal(p)))
    cfg_q.send(dai.ImageFiltersConfig().updateFilterAtIndex(FIDX["speckle"],  _make_speckle(p)))


# ── Pipeline (hilo secundario) ───────────────────────────────────────────────
def run_pipeline(p0):
    try:
        with dai.Pipeline() as pipeline:
            platform = pipeline.getDefaultDevice().getPlatform()

            camRgb = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
            left   = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_B)
            right  = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_C)

            rgbOut   = camRgb.requestOutput(size=(1280, 960), fps=FPS, enableUndistortion=True)
            leftOut  = left.requestOutput(size=(640, 400), fps=FPS)
            rightOut = right.requestOutput(size=(640, 400), fps=FPS)

            stereo = pipeline.create(dai.node.StereoDepth)
            stereo.setLeftRightCheck(p0["lr_check"])
            stereo.setSubpixel(p0["subpixel"])
            stereo.setExtendedDisparity(p0["extended"])
            leftOut.link(stereo.left)
            rightOut.link(stereo.right)

            filt = pipeline.create(dai.node.ImageFilters)
            filt.setRunOnHost(True)
            filt.build(stereo.depth)
            filt.initialConfig.filterIndices = []
            filt.initialConfig.filterParams  = [
                MEDIAN_OPTIONS[p0["median"]],
                _make_spatial(p0),
                _make_temporal(p0),
                _make_speckle(p0),
            ]
            cfg_q = filt.inputConfig.createInputQueue()

            sync = pipeline.create(dai.node.Sync)
            sync.setSyncThreshold(timedelta(seconds=1 / (2 * FPS)))
            rgbOut.link(sync.inputs["rgb"])

            if platform == dai.Platform.RVC4:
                align = pipeline.create(dai.node.ImageAlign)
                filt.output.link(align.input)
                rgbOut.link(align.inputAlignTo)
                align.outputAligned.link(sync.inputs["depth"])
            else:
                filt.output.link(sync.inputs["depth"])
                rgbOut.link(stereo.inputAlignTo)

            out_q = sync.out.createOutputQueue()
            pipeline.start()
            t_list = []

            while True:
                with _lock:
                    p = dict(params)

                if p["quit"]:
                    break

                if p["filters_dirty"]:
                    apply_all_filters(cfg_q, p)
                    with _lock:
                        params["filters_dirty"] = False

                msg = out_q.get()
                if not isinstance(msg, dai.MessageGroup):
                    continue

                rgb   = msg["rgb"].getCvFrame()
                depth = msg["depth"].getFrame()

                if p["mode"] == "rel":
                    dc = colorize_relative(depth)
                else:
                    dc = colorize_absolute(depth, p["depth_min_m"] * 1000, p["depth_max_m"] * 1000)

                rw = p["rgb_pct"] / 100.0
                blended = cv2.addWeighted(rgb, rw, dc, 1.0 - rw, 0)

                t_list.append(time.time())
                t_list = t_list[-10:]
                fps = (len(t_list) - 1) / (t_list[-1] - t_list[0]) if len(t_list) > 1 else 0
                cv2.putText(blended, f"FPS: {fps:.1f}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

                try:
                    frame_q.put_nowait((blended, dc))
                except pyqueue.Full:
                    pass

    except Exception as e:
        print(f"[pipeline] error: {e}")


# ── GUI tkinter (hilo principal) ─────────────────────────────────────────────
def build_and_run_gui():
    root = tk.Tk()
    root.title("OAK-D Pro — Parámetros")
    root.resizable(False, False)

    def _set(key, val):
        with _lock:
            params[key] = val

    def _set_dirty(key, val):
        with _lock:
            params[key] = val
            params["filters_dirty"] = True

    # ── Visualización ──────────────────────────────────────────────────────
    fv = ttk.LabelFrame(root, text="Visualización", padding=8)
    fv.grid(row=0, column=0, padx=10, pady=6, sticky="ew")
    fv.columnconfigure(1, weight=1)

    ttk.Label(fv, text="Mezcla RGB %").grid(row=0, column=0, sticky="w")
    rgb_lbl = tk.StringVar(value=str(params["rgb_pct"]))
    ttk.Label(fv, textvariable=rgb_lbl, width=4).grid(row=0, column=2, padx=4)
    def on_rgb(v):
        val = int(float(v))
        _set("rgb_pct", val)
        rgb_lbl.set(str(val))
    ttk.Scale(fv, from_=0, to=100, orient="h", length=220,
              command=on_rgb).grid(row=0, column=1, sticky="ew")

    ttk.Separator(fv, orient="h").grid(row=1, column=0, columnspan=3, sticky="ew", pady=4)

    ttk.Label(fv, text="Colorización").grid(row=2, column=0, sticky="w")
    mode_var = tk.StringVar(value=params["mode"])
    ttk.Radiobutton(fv, text="Relativa (auto, escala logarítmica)", variable=mode_var,
                    value="rel", command=lambda: _set("mode", "rel")).grid(row=2, column=1, columnspan=2, sticky="w")
    ttk.Radiobutton(fv, text="Absoluta (rango fijo)", variable=mode_var,
                    value="abs", command=lambda: _set("mode", "abs")).grid(row=3, column=1, columnspan=2, sticky="w")

    ttk.Label(fv, text="Mín (m)").grid(row=4, column=0, sticky="w")
    min_lbl = tk.StringVar(value=f"{params['depth_min_m']:.1f}")
    ttk.Label(fv, textvariable=min_lbl, width=4).grid(row=4, column=2, padx=4)
    def on_min(v):
        val = round(float(v), 1)
        _set("depth_min_m", val)
        min_lbl.set(f"{val:.1f}")
    min_sc = ttk.Scale(fv, from_=0.1, to=5.0, orient="h", length=220, command=on_min)
    min_sc.set(params["depth_min_m"])
    min_sc.grid(row=4, column=1, sticky="ew")

    ttk.Label(fv, text="Máx (m)").grid(row=5, column=0, sticky="w")
    max_lbl = tk.StringVar(value=f"{params['depth_max_m']:.1f}")
    ttk.Label(fv, textvariable=max_lbl, width=4).grid(row=5, column=2, padx=4)
    def on_max(v):
        val = round(float(v), 1)
        _set("depth_max_m", val)
        max_lbl.set(f"{val:.1f}")
    max_sc = ttk.Scale(fv, from_=1.0, to=15.0, orient="h", length=220, command=on_max)
    max_sc.set(params["depth_max_m"])
    max_sc.grid(row=5, column=1, sticky="ew")

    # ── Filtros (en vivo) ──────────────────────────────────────────────────
    ff = ttk.LabelFrame(root, text="Filtros de profundidad  (en vivo)", padding=8)
    ff.grid(row=1, column=0, padx=10, pady=6, sticky="ew")
    ff.columnconfigure(1, weight=1)

    ttk.Label(ff, text="Mediana").grid(row=0, column=0, sticky="w")
    med_var = tk.StringVar(value=params["median"])
    med_cb  = ttk.Combobox(ff, textvariable=med_var, values=list(MEDIAN_OPTIONS.keys()),
                            state="readonly", width=16)
    med_cb.grid(row=0, column=1, sticky="w", pady=2)
    med_cb.bind("<<ComboboxSelected>>", lambda _: _set_dirty("median", med_var.get()))

    sp_var = tk.BooleanVar(value=params["spatial"])
    ttk.Checkbutton(ff, text="Filtro espacial  (rellena agujeros)", variable=sp_var,
                    command=lambda: _set_dirty("spatial", sp_var.get())).grid(row=1, column=0, columnspan=2, sticky="w")

    sk_var = tk.BooleanVar(value=params["speckle"])
    ttk.Checkbutton(ff, text="Filtro speckle  (elimina píxeles sueltos)", variable=sk_var,
                    command=lambda: _set_dirty("speckle", sk_var.get())).grid(row=2, column=0, columnspan=2, sticky="w")

    tp_var = tk.BooleanVar(value=params["temporal"])
    ttk.Checkbutton(ff, text="Filtro temporal  (estabiliza entre frames)", variable=tp_var,
                    command=lambda: _set_dirty("temporal", tp_var.get())).grid(row=3, column=0, columnspan=2, sticky="w")

    ttk.Label(ff, text="Alpha temporal").grid(row=4, column=0, sticky="w")
    alpha_lbl = tk.StringVar(value=f"{params['t_alpha']:.2f}")
    ttk.Label(ff, textvariable=alpha_lbl, width=4).grid(row=4, column=2, padx=4)
    def on_alpha(v):
        val = round(float(v), 2)
        _set_dirty("t_alpha", val)
        alpha_lbl.set(f"{val:.2f}")
    alpha_sc = ttk.Scale(ff, from_=0.1, to=0.9, orient="h", length=220, command=on_alpha)
    alpha_sc.set(params["t_alpha"])
    alpha_sc.grid(row=4, column=1, sticky="ew")

    # ── Estéreo (estático) ─────────────────────────────────────────────────
    fs = ttk.LabelFrame(root, text="Estéreo  (requiere reinicio del pipeline)", padding=8)
    fs.grid(row=2, column=0, padx=10, pady=6, sticky="ew")

    sub_var = tk.BooleanVar(value=params["subpixel"])
    ttk.Checkbutton(fs, text="Subpíxel  (bordes más suaves, más CPU)", variable=sub_var,
                    command=lambda: _set("subpixel", sub_var.get())).grid(row=0, column=0, sticky="w")

    lr_var = tk.BooleanVar(value=params["lr_check"])
    ttk.Checkbutton(fs, text="Left-Right check  (reduce artefactos de borde)", variable=lr_var,
                    command=lambda: _set("lr_check", lr_var.get())).grid(row=1, column=0, sticky="w")

    ext_var = tk.BooleanVar(value=params["extended"])
    ttk.Checkbutton(fs, text="Extended disparity  (rango hasta ~20 cm)", variable=ext_var,
                    command=lambda: _set("extended", ext_var.get())).grid(row=2, column=0, sticky="w")

    def do_restart():
        with _lock:
            params["quit"] = True

        def _restart():
            if pipeline_ref[0]:
                pipeline_ref[0].join(timeout=5)
            with _lock:
                params["quit"] = False
                p0 = dict(params)
            t = threading.Thread(target=run_pipeline, args=(p0,), daemon=True)
            t.start()
            pipeline_ref[0] = t

        threading.Thread(target=_restart, daemon=True).start()

    ttk.Button(fs, text="↺  Reiniciar pipeline", command=do_restart).grid(
        row=3, column=0, pady=(10, 2), sticky="w")

    # ── Poll de frames ─────────────────────────────────────────────────────
    def poll():
        try:
            blended, dc = frame_q.get_nowait()
            cv2.imshow("Profundidad", dc)
            cv2.imshow("RGB + Depth", blended)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                on_close()
                return
        except pyqueue.Empty:
            pass
        root.after(16, poll)

    def on_close():
        with _lock:
            params["quit"] = True
        root.after(600, lambda: (cv2.destroyAllWindows(), root.destroy()))

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(16, poll)
    root.mainloop()


# ── Entrada ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    with _lock:
        p0 = dict(params)

    t = threading.Thread(target=run_pipeline, args=(p0,), daemon=True)
    t.start()
    pipeline_ref[0] = t

    build_and_run_gui()
