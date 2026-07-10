# SICUEM — Sacar logs del comma por SSH (commIssue / locationd)

Herramienta para capturar del comma **por qué OP se desactiva** al activarse:
`Communication Issue Between Processes` (evento `commIssue`) y
`locationd - Temporary Error` (evento `locationdTemporaryError`).

El dato decisivo es el evento `commIssue` que escribe `selfdrived` en swaglog: incluye
los arrays `not_alive` / `not_freq_ok` / `invalid`, es decir **qué servicio llegó tarde**
en el instante de la desactivación → eso señala el proceso culpable.

## ⭐ Flujo recomendado: conducir una ruta y analizarla después

1. **El conductor hace una ruta** e **intenta enganchar OP** (que se reproduzca el fallo:
   TAKE CONTROL / locationd). No hace falta nada más; queda grabado en el log de la ruta.
2. **Más tarde, tú** accedes al comma por SSH y sacas los logs:
   ```bash
   KEY=~/.ssh/tu_clave_github tools/orbit/grab_orbit_logs.sh pull
   ```
   Esto baja swaglog + `rlog`/`qlog` de la última ruta y, en tu PC, produce un **VEREDICTO**
   automático en `orbit_logs/<fecha>/veredicto.txt` diciendo la causa exacta:
   - desfase de reloj sensord↔cámara (causa #1, el bug de locationd),
   - o caída de frecuencia de modelV2/cameraOdometry (causa #2),
   - o el servicio concreto que aparece en el `commIssue`.
3. Pégame `veredicto.txt` (y `commissue_resumen.txt`) y confirmo causa + fix.

Si ya tienes los segmentos descargados, puedes correr el analizador a mano:
```bash
PYTHONPATH=. python3 tools/orbit/analyze_route_logs.py orbit_logs/<fecha>/route/*/
```

## 1) Conectarte por SSH al comma

Requisito: tener tu clave SSH (GitHub) registrada en el comma → `Settings ▸ Device ▸ SSH`
(pegas tu usuario de GitHub; el comma descarga tus claves públicas).

- **Por cable / tethering USB** (lo más fácil): el comma es `192.168.43.1`
  ```bash
  ssh comma@192.168.43.1 -i ~/.ssh/tu_clave_github
  ```
- **Misma WiFi**: usa la IP del comma en tu red (la ves en `Settings ▸ Network`).
- **comma prime** (proxy ssh.comma.ai): `ssh comma-<dongleid>` (ver `docs/how-to/connect-to-comma.md`).

El openpilot vive en `/data/openpilot`. La sesión corre en tmux:
```bash
tmux a -t comma            # ver la consola en vivo (procesos, excepciones)
sudo systemctl restart comma   # reiniciar openpilot limpio para reproducir
```

## 2) Capturar los logs (desde tu PC, en este repo)

### Modo OFFLINE — después de reproducir el fallo
```bash
# (HOST/KEY opcionales; por defecto comma@192.168.43.1)
KEY=~/.ssh/tu_clave_github tools/orbit/grab_orbit_logs.sh pull
```
Genera en `./orbit_logs/<fecha>/`:
- `commissue_resumen.txt` → cada `commIssue` con sus arrays `not_alive/not_freq_ok/invalid`.
- `onroad_events.txt` → conteo de `locationdTemporaryError`, `commIssue`, etc. (de qlog).
- `eventos_swaglog.txt` → líneas crudas (incluye errores `[Bemposta]` del hilo MQTT).

### Modo EN VIVO — mientras reproduces (activa OP durante la captura)
```bash
SECS=40 KEY=~/.ssh/tu_clave_github tools/orbit/grab_orbit_logs.sh live
```
Genera: `live_errors.txt` (commIssue con fichero:línea), `live_freq.txt` (Hz reales por
servicio: el que esté por debajo es el que cae), `live_cpu.txt` (CPU por proceso),
`live_onroad.txt` (onroadEvents/selfdriveState).

## 3) Cómo leer el resultado

| Servicio en `not_alive` / `not_freq_ok` | Proceso culpable |
|---|---|
| `carControl`, `controlsState` | controlsd |
| `carState`, `carOutput` | card |
| `modelV2`, `cameraOdometry` | modeld |
| `livePose` | locationd |
| `*sensor*`, `accelerometer`, `gyroscope` | sensord |

- Si ves `livePose` en `not_alive` **o** cuenta de `locationdTemporaryError` > 0 → stall del
  pipeline de localización (cámara/IMU tarde).
- Si ves `carControl`/`controlsState` → el loop de control (core 4) se retrasó.

Ambos apuntan a la **misma** causa raíz (contención de I/O de Params por las escrituras
MQTT/Jetson) que los fixes de `zmq_client.py` y `controlsd.py` atacan. Estos logs sirven
para **confirmar** que el fix funcionó y, si quedara algo, decir exactamente qué servicio.

## 4) Comandos manuales útiles (directos por SSH)
```bash
# Errores en vivo con fichero:línea exactos
ssh comma@192.168.43.1 'cd /data/openpilot && PYTHONPATH=. python3 selfdrive/debug/filter_log_message.py --level ERROR'
# Frecuencias reales por servicio
ssh comma@192.168.43.1 'cd /data/openpilot && PYTHONPATH=. python3 selfdrive/debug/check_freq.py'
# CPU/temperatura por proceso
ssh comma@192.168.43.1 'cd /data/openpilot && PYTHONPATH=. python3 selfdrive/debug/cpu_usage_stat.py'
# Prueba I/O (confirma la tormenta de fsync): ¿se dispara la latencia de /data?
ssh comma@192.168.43.1 'iostat -x 1 5'
```
