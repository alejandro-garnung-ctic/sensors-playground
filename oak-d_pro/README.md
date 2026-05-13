# oak-d_pro

Repo de prueba para la [cámara OAK-D Pro](https://shop.luxonis.com/products/oak-d-pro?srsltid=AfmBOoqdO-5N9BHOKo8Fuo6KhFZAicmeB6qTegjjcwF3PmGOrECGfJZ2) de Luxonis. Muestra imagen RGB y mapa de profundidad en tiempo real usando el SDK [DepthAI](https://docs.luxonis.com/projects/api/en/latest/).

## Requisitos

```bash
pip install -r requirements.txt
```

Opcional - Arreglar error por permisos: en Linux, dar **acceso USB al dispositivo** sin root (solo la primera vez):

```bash
[2026-05-06 10:58:12.973] [depthai] [warning] Insufficient permissions to communicate with X_LINK_UNBOOTED device with name "3.6.2". Make sure udev rules are set
[2026-05-06 10:58:14.990] [depthai] [warning] Insufficient permissions to communicate with X_LINK_UNBOOTED device having name "3.6.2". Make sure udev rules are set
```

Ejecutar: 

```bash
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/80-movidius.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## Uso

```bash
python main.py
```

Abre dos ventanas: **RGB** y **Profundidad** (coloreada, escala 0–10 m). Pulsa `q` para salir.

## Cómo funciona

Usa la API de pipeline de DepthAI 2.x. Se construye un grafo de nodos en el host y se ejecuta en el dispositivo:

| Nodo | Función |
|---|---|
| `ColorCamera` | Sensor RGB central (`CAM_A`) |
| `MonoCamera` × 2 | Par estéreo izquierda/derecha |
| `StereoDepth` | Genera mapa de profundidad alineado al RGB |
| `XLinkOut` | Envía frames al host por USB |

La profundidad sale en **uint16 milímetros**, alineada al frame RGB gracias a `setDepthAlign(CAM_A)`.
