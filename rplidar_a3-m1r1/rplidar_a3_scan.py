#!/usr/bin/env python3
"""
Minimal RPLIDAR A3 (M1R1) scanner.

Connects to the lidar via serial USB, reads 360° scans and shows them
as a live polar plot (matplotlib) or prints stats to the terminal.

The core logic lives in ``LidarScanner`` so it can be imported and
reused from other scripts:

    from rplidar_a3_scan import LidarScanner

    with LidarScanner("/dev/ttyUSB0") as s:
        for scan in s.iter_scans():
            ...                          # [(quality, angle, dist_mm), ...]
        s.run_terminal(n_scans=10)
        s.run_gui(max_dist=5000)

Press Ctrl+C to stop and disconnect cleanly.

Usage:
    # Live polar plot (default port /dev/ttyUSB0)
    python rplidar_a3_scan.py

    # Specify a different port
    python rplidar_a3_scan.py --port /dev/ttyUSB1

    # Terminal only — scan stats without GUI
    python rplidar_a3_scan.py --no-gui

    # Stop after 20 complete 360° scans
    python rplidar_a3_scan.py --n-scans 20

    # Clip polar plot at 4 m instead of the default 8 m
    python rplidar_a3_scan.py --max-dist 4000

    # Force TkAgg backend (WSL / remote display)
    python rplidar_a3_scan.py --force-tk

    # List available serial ports and exit
    python rplidar_a3_scan.py --list-ports

    # RPLIDAR A1 / A2 (different baud rate)
    python rplidar_a3_scan.py --baudrate 115200
"""

from __future__ import annotations

import argparse
import glob
import sys
import time

# Background turns red when the nearest point is closer than this distance.
PROXIMITY_ALERT_MM = 1000


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal RPLIDAR A3 scanner")
    parser.add_argument(
        "--port",
        default="/dev/ttyUSB0",
        help="Serial port of the lidar (default: /dev/ttyUSB0).",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=256000,
        help="Baud rate — 256000 for A3/A2M8, 115200 for A1/A2 (default: 256000).",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Terminal only: print scan stats, no matplotlib window.",
    )
    parser.add_argument(
        "--force-tk",
        action="store_true",
        help="Force TkAgg backend (useful on WSL with GUI forwarding).",
    )
    parser.add_argument(
        "--n-scans",
        type=int,
        default=0,
        metavar="N",
        help="Stop after N complete 360° scans (0 = run until Ctrl+C, default: 0).",
    )
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="List available ttyUSB* / ttyAMA* ports and exit.",
    )
    parser.add_argument(
        "--max-dist",
        type=float,
        default=8000.0,
        metavar="MM",
        help="Maximum distance in mm to display in the polar plot (default: 8000).",
    )
    return parser.parse_args()


def list_serial_ports() -> int:
    candidates = sorted(
        glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyAMA*") + glob.glob("/dev/serial/by-id/*")
    )
    if not candidates:
        print("No ttyUSB*/ttyAMA* devices found.")
        print("Check USB connection and/or run: sudo dmesg | tail -20")
        return 1
    print("Available serial ports:")
    for p in candidates:
        print(f"  {p}")
    return 0


def _try_enable_interactive_backend(force_tk: bool = False) -> None:
    import matplotlib

    if force_tk:
        try:
            matplotlib.use("TkAgg", force=True)
            return
        except Exception:
            pass

    import os

    backend = matplotlib.get_backend().lower()
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if "agg" in backend and has_display:
        try:
            matplotlib.use("TkAgg", force=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# LidarScanner
# ---------------------------------------------------------------------------

class LidarScanner:
    """Wrapper around RPLidar with resilient scanning and reusable views.

    Can be used as a context manager::

        with LidarScanner("/dev/ttyUSB0") as scanner:
            for scan in scanner.iter_scans():
                ...

    Or manually::

        scanner = LidarScanner()
        scanner.connect()
        try:
            scanner.run_terminal()
        finally:
            scanner.disconnect()
    """

    MAX_SCAN_RETRIES = 5

    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 256000) -> None:
        self.port = port
        self.baudrate = baudrate
        self._lidar = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the serial port, print device info, and start the motor."""
        from rplidar import RPLidar

        print(f"Connecting to RPLIDAR A3 on {self.port} at {self.baudrate} baud...")
        try:
            self._lidar = RPLidar(self.port, baudrate=self.baudrate)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to open port: {exc}\n"
                "Tips:\n"
                "  • Check USB cable and connection.\n"
                "  • Grant serial access: sudo usermod -aG dialout $USER  (re-login after)\n"
                "  • Or temporarily: sudo chmod 666 /dev/ttyUSB0\n"
                "  • List available ports: python rplidar_a3_scan.py --list-ports"
            ) from exc

        info = self._lidar.get_info()
        print(f"  Model:    {info['model']}")
        print(f"  Firmware: {info['firmware']}")
        print(f"  Hardware: {info['hardware']}")

        health = self._lidar.get_health()
        print(f"  Health:   {health[0]}  (error_code={health[1]})")
        if health[0] == "Error":
            print("  Error state — resetting chip...")
            self._lidar.reset()

        # Start motor once here so iter_measures() skips its 2 s spin-up
        # delay on every subsequent call (motor_running stays True).
        print("  Starting motor...")
        self._lidar.start_motor()

    def disconnect(self) -> None:
        """Stop motor and close the serial port."""
        if self._lidar is not None:
            print("Stopping motor and disconnecting...")
            try:
                self._lidar.stop()
                self._lidar.stop_motor()
                self._lidar.disconnect()
            except Exception:
                pass
            self._lidar = None
            print("Done.")

    def __enter__(self) -> "LidarScanner":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prepare_buffer(self) -> None:
        """Stop scan data output and flush stale bytes from the RX buffer.

        Calls stop() (not stop_motor()) so the lidar stops emitting measurement
        frames while the motor keeps spinning. Because motor_running is already
        True from connect(), iter_measures() will skip its own 2 s spin-up and
        go straight to the scan command — reading a clean descriptor.
        """
        self._lidar.stop()
        time.sleep(0.2)  # let any in-flight bytes arrive
        self._lidar._serial.flushInput()

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def iter_scans(self):
        """Resilient scan iterator.

        Yields complete 360° scans as lists of ``(quality, angle_deg, dist_mm)``.
        Automatically recovers from descriptor / buffer errors up to
        ``MAX_SCAN_RETRIES`` times before re-raising.
        """
        from rplidar import RPLidarException

        for attempt in range(1, self.MAX_SCAN_RETRIES + 1):
            try:
                self._prepare_buffer()
                for scan in self._lidar.iter_scans():
                    yield scan
                return
            except RPLidarException as exc:
                if attempt >= self.MAX_SCAN_RETRIES:
                    raise
                print(f"  Scan error ({exc}), retrying ({attempt}/{self.MAX_SCAN_RETRIES})...")
                time.sleep(0.5)

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    def run_terminal(self, n_scans: int = 0) -> None:
        """Print per-scan stats to the terminal.

        Args:
            n_scans: Stop after this many scans (0 = run until Ctrl+C).
        """
        print("\nReading scans (Ctrl+C to stop)...")
        scan_count = 0
        for scan in self.iter_scans():
            scan_count += 1
            valid = [(q, a, d) for q, a, d in scan if q > 0 and d > 0]
            if not valid:
                continue
            distances = [d for _, _, d in valid]
            nearest = min(valid, key=lambda x: x[2])
            print(
                f"  Scan {scan_count:4d} | points={len(valid):4d} | "
                f"min={min(distances):6.0f} mm  avg={sum(distances)/len(distances):6.0f} mm"
                f"  max={max(distances):6.0f} mm | "
                f"nearest → {nearest[2]:.0f} mm @ {nearest[1]:.1f}°"
            )
            if n_scans and scan_count >= n_scans:
                break

    def run_gui(self, max_dist: float = 8000.0, n_scans: int = 0) -> None:
        """Live polar plot with proximity alert.

        The background turns red when the nearest detected point is closer
        than ``PROXIMITY_ALERT_MM``.

        Args:
            max_dist: Radial axis limit in mm (default: 8000).
            n_scans:  Stop after this many scans (0 = run until Ctrl+C).
        """
        import matplotlib.pyplot as plt
        import numpy as np

        fig = plt.figure(figsize=(7, 7))
        ax = fig.add_subplot(111, polar=True)
        ax.set_theta_zero_location("N")   # 0° at top (forward)
        ax.set_theta_direction(-1)        # clockwise (matching physical rotation)
        ax.set_ylim(0, max_dist)
        ax.set_title("RPLIDAR A3 — live scan", va="bottom", pad=20)
        ax.set_xlabel("distance (mm)")

        scatter = ax.scatter([], [], s=2, c="dodgerblue", alpha=0.7)
        nearest_dot = ax.scatter([], [], s=60, c="red", zorder=5, label="nearest")
        ax.legend(loc="upper right", bbox_to_anchor=(1.15, 1.1))
        status_text = ax.text(
            0.5, -0.08, "", transform=ax.transAxes, ha="center", fontsize=9, color="gray"
        )

        plt.ion()
        plt.show()

        scan_count = 0
        for scan in self.iter_scans():
            scan_count += 1
            valid = [(q, a, d) for q, a, d in scan if q > 0 and d > 0 and d <= max_dist]
            if not valid:
                continue

            angles = np.radians([a for _, a, _ in valid])
            dists = np.array([d for _, _, d in valid])
            scatter.set_offsets(np.c_[angles, dists])

            nearest = min(valid, key=lambda x: x[2])
            nearest_dot.set_offsets([[np.radians(nearest[1]), nearest[2]]])

            alert = nearest[2] < PROXIMITY_ALERT_MM
            bg = "#ff4444" if alert else "white"
            fig.patch.set_facecolor(bg)
            ax.set_facecolor(bg)

            status_text.set_text(
                f"Scan {scan_count} | {len(valid)} pts | "
                f"nearest: {nearest[2]:.0f} mm @ {nearest[1]:.1f}°"
                + (f"  ⚠ < {PROXIMITY_ALERT_MM} mm" if alert else "")
            )

            fig.canvas.draw_idle()
            fig.canvas.flush_events()

            if n_scans and scan_count >= n_scans:
                break

        plt.ioff()
        plt.show()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    if args.list_ports:
        return list_serial_ports()

    try:
        import rplidar  # noqa: F401
    except ImportError:
        print("rplidar not installed. Run: pip install rplidar-roboticia")
        return 1

    scanner = LidarScanner(port=args.port, baudrate=args.baudrate)
    try:
        scanner.connect()
        if args.no_gui:
            scanner.run_terminal(n_scans=args.n_scans)
        else:
            _try_enable_interactive_backend(force_tk=args.force_tk)
            scanner.run_gui(max_dist=args.max_dist, n_scans=args.n_scans)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as exc:
        print(f"Error: {exc}")
        return 1
    finally:
        scanner.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
