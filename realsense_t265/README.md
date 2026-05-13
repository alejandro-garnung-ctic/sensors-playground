# RealSense T265 - minimal playground

Script minimo para arrancar la **Intel RealSense T265** (cámara **2D** de **tracking**), leer su stream de pose y abrir un visor simple de trayectoria en XY.

Se ve, al conectar por USB (esta cámara tiene conector Micro-B, como los de los discos duros), el VPU (Vision Processing Unit) **Movidius MA2x5x** (una **Myriad 2 de Intel**) de que cuenta la cámara.

También hay versiones del Viewer oficial del SDK de RealSense (RealSense.SDK-WIN10-2.57.7.10378.exe ), y el visor [RealSense.Viewer_2.57.7.exe](https://github.com/realsenseai/librealsense/releases); cuidado que T265 está obsoleta y solo la soporta versiones antiguas de la librería. 

## Requisitos

- Intel RealSense T265 conectada por USB
- Linux con acceso al dispositivo USB
- Python 3.9+ (recomendado)

Dependencias Python para este playground:

```bash
pip install pyrealsense2 matplotlib
```

> Nota: `pyrealsense2` no esta en `requirements.txt` principal del repo, por eso se instala aparte aqui.

Otras cámaras con las que funciona esta librería:

- Serie D (profundidad estéreo):
    - Intel RealSense D415
    - Intel RealSense D435
    - Intel RealSense D455
- Serie L (LiDAR):
    - Intel RealSense L515
- Cámaras de seguimiento:
    - Intel RealSense T265

## Uso

Desde esta carpeta:

```bash
python t265_pose_viewer.py
```

Modo solo terminal (sin ventana, util para WSL/headless):

```bash
python t265_pose_viewer.py --no-gui
```

Forzar backend grafico Tk en WSL (si detecta Agg):

```bash
python t265_pose_viewer.py --force-tk
```

Listar dispositivos detectados por librealsense (solo `pyrealsense2`; no requiere matplotlib):

```bash
python t265_pose_viewer.py --list-devices
```

## Que muestra

- En terminal: posicion y velocidad en tiempo real.
- En ventana matplotlib: trayectoria XY acumulada y pose actual.

Salir con `Ctrl+C`.

## Troubleshooting rapido (WSL + usbipd / permisos / BUSID)

Si `usbipd` dice `Attached` pero en WSL `pyrealsense2 --list-devices` no detecta la cámara, mira la guía única (con `BUSID`, `/dev/bus/usb/BBB/DDD`, `chmod`, udev y el tema de `sudo` vs `.venv`):

[WSL + usbipd troubleshooting](README_wsl_usbipd.md#wsl-usb-permissions)

