# sensors-playground

Un espacio de experimentación y prueba con distintos tipos de sensores 2D y 3D (estéreo, RGB-D, LiDAR...).

La idea es encapsular en diferentes directorios scripts de prueba y uso de cada sensor, así como explicaciones y documentación sobre su uso.

---

## Sensores

### Intel RealSense T265

| Campo | Valor |
|-------|-------|
| Tipo | Cámara de **tracking** (V-SLAM) |
| Salida principal | Pose 6-DoF (posición + orientación) a 200 Hz |
| Sensores | 2× ojo de pez (fisheye) 163° + IMU (acelerómetro + giroscopio) |
| Procesador on-board | Intel Movidius Myriad 2 (MA2x5x) |
| Conexión | USB 2.0/3.0 (conector Micro-B) |
| SDK | librealsense (`pyrealsense2`) |
| Estado | **Descatalogada** — solo soportada por versiones antiguas de librealsense |

Diseñada para odometría visual-inercial en tiempo real sin carga al host. Útil para robótica móvil, AR/VR y navegación autónoma.

→ [`realsense_t265/`](realsense_t265/)

---

### Intel RealSense D435i

| Campo | Valor |
|-------|-------|
| Tipo | Cámara **RGB-D** (estéreo activa + color) |
| Salida principal | Mapa de profundidad alineado al color + imagen RGB |
| Sensores | Par estéreo IR global shutter + proyector IR + sensor RGB rolling shutter + IMU (acelerómetro + giroscopio) |
| Rango de profundidad | ~0.1 m – 10 m |
| Resolución máx. | 1280×720 @ 30 fps (profundidad), 1920×1080 @ 30 fps (color) |
| Conexión | USB-C (requiere USB 3.x para rendimiento completo) |
| SDK | librealsense (`pyrealsense2`) |
| Estado | **En producción** — serie D400 sigue activa |

Pensada para SLAM, reconstrucción 3D densa, detección de obstáculos y odometría visual-inercial. Funciona en USB 2.0 pero con resolución y FPS muy limitados.

→ [`realsense_d435i/`](realsense_d435i/)

---

### Luxonis OAK-D Pro

| Campo | Valor |
|-------|-------|
| Tipo | Cámara **RGB + estéreo** con aceleración de IA on-device |
| Salida principal | RGB, mapa de profundidad estéreo, inferencia de redes neuronales |
| Sensores | Sensor RGB central (IMX378, 12 MP) + 2× mono global shutter (OV9282) + proyector IR dot + flood IR |
| Procesador on-board | Intel Movidius Myriad X (VPU) — inferencia NN a ~4 TOPS |
| Rango de profundidad | ~0.2 m – 35 m (según baseline y configuración) |
| Conexión | USB-C (USB 3.x) o PoE (variante Pro-PoE) |
| SDK | DepthAI (`depthai`) |
| Estado | **En producción** |

Destaca por ejecutar redes neuronales (detección, segmentación, tracking) directamente en el VPU sin necesidad de GPU en el host. El SDK usa una API de pipeline/grafos de nodos que se compila y ejecuta en el dispositivo.

→ [`oak-d_pro/`](oak-d_pro/)
