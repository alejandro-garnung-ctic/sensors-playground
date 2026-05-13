#!/usr/bin/env python3
"""
Minimal Intel RealSense T265 pose viewer.

What it does:
- Opens a T265 pipeline (pose stream).
- Prints position and velocity in terminal.
- Shows a live 2D XY trajectory plot (matplotlib).

Press Ctrl+C to exit.
"""

from __future__ import annotations

import argparse
import os
import time
from collections import deque

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal RealSense T265 pose viewer")
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run terminal-only mode (no matplotlib window).",
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
    return parser.parse_args()


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

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.pose)

    # Keep last N points for a lightweight "playground" trajectory.
    max_points = 2000
    xs: deque[float] = deque(maxlen=max_points)
    ys: deque[float] = deque(maxlen=max_points)

    use_gui = not args.no_gui
    if use_gui:
        backend = plt.get_backend().lower()
        if "agg" in backend:
            print(
                "Matplotlib backend is non-interactive (Agg). "
                "Switching to terminal-only mode."
            )
            use_gui = False

    if use_gui:
        fig, ax = plt.subplots(figsize=(7, 7))
        fig.canvas.manager.set_window_title("T265 Pose Viewer (XY trajectory)")
        line, = ax.plot([], [], lw=1.5, label="Trajectory")
        current = ax.scatter([], [], s=30, label="Current pose")
        ax.set_xlabel("X (m)")
        ax.set_ylabel("Y (m)")
        ax.set_title("Intel RealSense T265 - Live Pose")
        ax.grid(True, alpha=0.3)
        ax.axis("equal")
        ax.legend(loc="upper right")
        plt.ion()
        plt.show(block=False)

    try:
        pipeline.start(config)
        print("T265 started. Waiting for pose frames...")
        last_print = 0.0

        while True:
            frames = pipeline.wait_for_frames()
            pose_frame = frames.get_pose_frame()
            if not pose_frame:
                continue

            pose_data = pose_frame.get_pose_data()
            x = float(pose_data.translation.x)
            y = float(pose_data.translation.y)
            z = float(pose_data.translation.z)
            vx = float(pose_data.velocity.x)
            vy = float(pose_data.velocity.y)
            vz = float(pose_data.velocity.z)

            xs.append(x)
            ys.append(y)

            # Terminal status at ~5 Hz
            now = time.time()
            if now - last_print >= 0.2:
                last_print = now
                print(
                    f"\rpos=({x:+.3f}, {y:+.3f}, {z:+.3f}) m | "
                    f"vel=({vx:+.3f}, {vy:+.3f}, {vz:+.3f}) m/s",
                    end="",
                    flush=True,
                )

            if use_gui:
                line.set_data(xs, ys)
                current.set_offsets([[x, y]])

                if len(xs) > 1:
                    xmin, xmax = min(xs), max(xs)
                    ymin, ymax = min(ys), max(ys)
                    pad = 0.2
                    # Keep visible area non-degenerate
                    if abs(xmax - xmin) < 0.1:
                        xmin -= 0.05
                        xmax += 0.05
                    if abs(ymax - ymin) < 0.1:
                        ymin -= 0.05
                        ymax += 0.05
                    ax.set_xlim(xmin - pad, xmax + pad)
                    ax.set_ylim(ymin - pad, ymax + pad)

                fig.canvas.draw_idle()
                fig.canvas.flush_events()
                plt.pause(0.001)

    except KeyboardInterrupt:
        print("\nStopping T265 viewer...")
    except RuntimeError as exc:
        print(f"\nRuntimeError: {exc}")
        print("Check USB connection and that the T265 is detected.")
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

