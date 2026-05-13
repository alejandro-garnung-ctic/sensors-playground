#!/usr/bin/env python3
"""
Minimal Intel RealSense D435i depth + RGB viewer.

The D435i is a stereo RGB-D camera with an integrated IMU (accelerometer + gyroscope).
This script enables depth and color streams, aligns depth to color, and shows both
in a matplotlib window (or terminal-only stats with --no-gui).

Press Ctrl+C to exit.
"""

from __future__ import annotations

import argparse
import os
import time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal RealSense D435i depth+color viewer")
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Terminal only: print depth stats / IMU, no matplotlib window.",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List RealSense devices and exit.",
    )
    parser.add_argument(
        "--force-tk",
        action="store_true",
        help="Force TkAgg backend (useful on WSL with GUI).",
    )
    parser.add_argument(
        "--imu",
        action="store_true",
        help="Also enable accelerometer + gyroscope streams (D435i).",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=640,
        help="Stream width (default 640).",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=480,
        help="Stream height (default 480).",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="FPS for depth and color (default 30).",
    )
    return parser.parse_args()


def _frame_by_stream_type(frames, stream_type: rs.stream):
    """Get first frame of a given stream type from a frameset (portable across pyrealsense2 versions)."""
    try:
        for f in frames:
            if f.get_profile().stream_type() == stream_type:
                return f
    except TypeError:
        pass
    return None


def _try_enable_interactive_backend(force_tk: bool = False) -> None:
    import matplotlib

    if force_tk:
        try:
            matplotlib.use("TkAgg", force=True)
            return
        except Exception:
            pass

    backend = matplotlib.get_backend().lower()
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if "agg" in backend and has_display:
        try:
            matplotlib.use("TkAgg", force=True)
        except Exception:
            pass


def main() -> int:
    args = parse_args()

    # --list-devices only needs pyrealsense2 (works with `sudo python3` if system has the wheel).
    import pyrealsense2 as rs

    devices = list(rs.context().query_devices())
    if args.list_devices:
        if not devices:
            print("No RealSense devices detected by librealsense.")
            print("WSL: usbipd attach + permisos USB (ver README).")
            return 1
        print("Detected RealSense devices:")
        for idx, dev in enumerate(devices, start=1):
            name = dev.get_info(rs.camera_info.name)
            sn = dev.get_info(rs.camera_info.serial_number)
            print(f"  {idx}. {name} (S/N: {sn})")
        return 0

    if not devices:
        print("No RealSense devices detected by librealsense.")
        print("WSL: usbipd attach + permisos USB (ver README).")
        return 1

    _try_enable_interactive_backend(force_tk=args.force_tk)
    import matplotlib.pyplot as plt
    import numpy as np

    w, h, fps = args.width, args.height, args.fps
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.depth, w, h, rs.format.z16, fps)
    config.enable_stream(rs.stream.color, w, h, rs.format.bgr8, fps)
    if args.imu:
        config.enable_stream(rs.stream.accel, rs.format.motion_xyz32f, 250)
        config.enable_stream(rs.stream.gyro, rs.format.motion_xyz32f, 200)

    use_gui = not args.no_gui
    if use_gui:
        backend = plt.get_backend().lower()
        if "agg" in backend:
            print(
                "Matplotlib backend is non-interactive (Agg). "
                "Switching to terminal-only mode."
            )
            use_gui = False

    align = rs.align(rs.stream.color)
    im_color = None
    im_depth = None
    fig = ax_rgb = ax_depth = None

    if use_gui:
        fig, (ax_rgb, ax_depth) = plt.subplots(1, 2, figsize=(12, 5))
        fig.canvas.manager.set_window_title("D435i — RGB + aligned depth")
        ax_rgb.set_title("Color (RGB)")
        ax_depth.set_title("Depth (m, aligned to color)")
        ax_rgb.axis("off")
        ax_depth.axis("off")
        plt.ion()
        plt.show(block=False)

    try:
        profile = pipeline.start(config)
        depth_sensor = profile.get_device().first_depth_sensor()
        depth_scale = float(depth_sensor.get_depth_scale())
        print(
            f"D435i started: {w}x{h} @ {fps} fps, depth_scale={depth_scale:.6f} m/unit"
        )
        if args.imu:
            print("IMU streams enabled (accel 250 Hz, gyro 200 Hz).")
        last_print = 0.0
        frame_count = 0
        t0 = time.time()

        while True:
            frames = pipeline.wait_for_frames()
            aligned = align.process(frames)

            depth_frame = aligned.get_depth_frame()
            color_frame = aligned.get_color_frame()
            if not depth_frame or not color_frame:
                continue

            depth_image = np.asanyarray(depth_frame.get_data()).astype(np.float32)
            depth_m = depth_image * depth_scale
            color_bgr = np.asanyarray(color_frame.get_data())
            color_rgb = color_bgr[:, :, ::-1]

            frame_count += 1
            now = time.time()
            if now - last_print >= 0.25:
                last_print = now
                cy, cx = h // 2, w // 2
                center_d = depth_m[cy, cx]
                valid = depth_m[depth_m > 0]
                d_mean = float(np.mean(valid)) if valid.size else float("nan")
                dt = now - t0
                fps_est = frame_count / dt if dt > 0 else 0.0
                msg = (
                    f"fps~{fps_est:.1f} | center_depth={center_d:.3f} m | "
                    f"mean_valid={d_mean:.3f} m"
                )
                if args.imu:
                    af = _frame_by_stream_type(frames, rs.stream.accel)
                    gf = _frame_by_stream_type(frames, rs.stream.gyro)
                    if af and gf:
                        a = af.as_motion_frame().get_motion_data()
                        g = gf.as_motion_frame().get_motion_data()
                        msg += (
                            f" | accel=({a.x:+.2f},{a.y:+.2f},{a.z:+.2f}) "
                            f"gyro=({g.x:+.3f},{g.y:+.3f},{g.z:+.3f})"
                        )
                print(f"\r{msg}", end="", flush=True)

            if use_gui:
                if im_color is None:
                    im_color = ax_rgb.imshow(color_rgb)
                else:
                    im_color.set_data(color_rgb)

                d_show = np.clip(depth_m, 0.1, 8.0)
                d_show = np.where(depth_m > 0, d_show, np.nan)
                if im_depth is None:
                    im_depth = ax_depth.imshow(d_show, cmap="viridis", vmin=0.1, vmax=4.0)
                    plt.colorbar(im_depth, ax=ax_depth, fraction=0.046, pad=0.04)
                else:
                    im_depth.set_data(d_show)

                fig.canvas.draw_idle()
                fig.canvas.flush_events()
                plt.pause(0.001)

    except KeyboardInterrupt:
        print("\nStopping D435i viewer...")
    except RuntimeError as exc:
        print(f"\nRuntimeError: {exc}")
        print("Check USB, that a D400 device is attached, and stream profile is supported.")
        return 1
    finally:
        try:
            pipeline.stop()
        except Exception:
            pass
        if use_gui:
            plt.close("all")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
