# WSL + usbipd troubleshooting (RealSense 8086 / librealsense)

Esta sección sirve cuando:
- En Windows `usbipd` te muestra la cámara como `Attached`,
- En WSL `lsusb` la ve (vendor `8086`),
- pero en Python con `pyrealsense2` `--list-devices` sale vacío o “no devices”.

La causa más frecuente en WSL es que, tras `usbipd attach`, los nodos USB de `/dev/bus/usb/BBB/DDD` quedan con permisos solo de `root`, y `librealsense/libusb` no puede abrirlos.

---

## Windows (usbipd-win)

1. Instala `usbipd-win` (si no lo tienes):
   `winget install --id dorssel.usbipd-win`

2. Abre PowerShell como **Administrador**.

3. Identifica el `BUSID` de tu RealSense:
   `usbipd list`

4. Comparte y adjunta a WSL:
   - `usbipd bind --busid <BUSID>`
   - `usbipd attach --wsl --busid <BUSID>`

---

## WSL (verificación base)

1. Comprueba que el kernel ve Intel USB:
   `lsusb`

2. Prueba enumeración del SDK (esto solo carga `pyrealsense2`, no hace falta matplotlib):
   - D435i:
     `python d435i_depth_color_viewer.py --list-devices`
   - T265:
     `python t265_pose_viewer.py --list-devices`

Si `lsusb` funciona pero `--list-devices` no, ve a permisos.

---

## `lsusb` ve la cámara y el script no (permisos)
<a id="wsl-usb-permissions"></a>

Tras `usbipd attach`, el kernel expone el dispositivo en:
`/dev/bus/usb/BBB/DDD`

1. De `lsusb`, toma `Bus` y `Device`:
   - ejemplo: `Bus 001 Device 003` → nodo **`/dev/bus/usb/001/003`**
   - ojo: son **tres dígitos** (por ejemplo `001`, no `1`)

2. Comprueba el nodo:
   `ls -l /dev/bus/usb/001/003`

3. **Prueba rápida (temporal):**
   `sudo chmod 666 /dev/bus/usb/001/003`

4. Ejecuta de nuevo el visor **sin** sudo:
   - D435i:
     `python d435i_depth_color_viewer.py --list-devices`
   - T265:
     `python t265_pose_viewer.py --list-devices`

5. Si quieres comprobar “root pero sin romper el venv” (evita `sudo python3`):
   Ajusta la ruta de tu `.venv`:
   - D435i (ejemplo):
     `sudo "$(readlink -f ../realsense_t265/.venv/bin/python)" d435i_depth_color_viewer.py --list-devices`
   - T265:
     `sudo "$(readlink -f .venv/bin/python)" t265_pose_viewer.py --list-devices`

6. Solución permanente (udev):
   Crea `/etc/udev/rules.d/99-realsense.rules` con:
   ```
   SUBSYSTEM=="usb", ATTR{idVendor}=="8086", MODE="0666"
   ```
   Luego:
   `sudo udevadm control --reload-rules && sudo udevadm trigger`

   Si no aplica enseguida, vuelve a adjuntar con `usbipd` (o desenchufa/reattach).

---

## Errores comunes extra

### 1) `sudo python3 ...` no usa tu entorno virtual
Si ejecutas `sudo python3`, usas el Python del sistema y puede que no tenga `pyrealsense2`/`matplotlib`.
Usa el Python del venv como en la sección de permisos (paso 5).

### 2) Estás ejecutando desde la carpeta equivocada
- Desde `realsense_t265/`: `python t265_pose_viewer.py ...`
- Desde `realsense_d435i/`: `python d435i_depth_color_viewer.py ...`

### 3) No abre ventana matplotlib / backend `Agg`
- Para headless: usa `--no-gui`.
- Para forzar Tk (si hay display): usa `--force-tk` y en WSL instala:
  `sudo apt install -y python3-tk`

