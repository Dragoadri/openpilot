# Guia de conexion Comma/Simulador - Jetson

## Arquitectura

```
[Comma/Simulador] --JPEG--> ZMQ PUB (tcp://*:5555)
                                    |
                            [Jetson Docker: jetson_1.py]
                            ZMQ SUB (tcp://comma_ip:5555)
                                    |
                              inferir(imagen) -> torque
                                    |
                            ZMQ PUSH (tcp://*:5556)
                                    |
[Comma/Simulador] <--torque-- ZMQ PULL (tcp://jetson_ip:5556)
                                    |
                        Params("JetsonTorque") = torque
```

Las ultimas 10 imagenes recibidas se guardan en la Jetson en:
`/home/sic/jetson-inference/data/zmq/ultimas_imagenes/`

---

## Archivos de configuracion

| Dispositivo | Ruta del archivo |
|---|---|
| Comma | `/data/openpilot/orbit/config_jetson.json` |
| Simulador (PC) | `orbit/config_jetson.json` (dentro del repo) |
| Jetson | `/home/sic/jetson-inference/data/zmq/config_jetson.json` |

### Formato del config (igual en ambos lados)

```json
{
    "comma_ip": "IP_DEL_COMMA",
    "jetson_enabled": true,
    "jetson_img_port": 5555,
    "jetson_ip": "IP_DE_LA_JETSON",
    "jetson_torque_port": 5556,
    "jpeg_quality": 60
}
```

### Configs guardadas por entorno

| Archivo | Red | IPs |
|---|---|---|
| `config_jetson.json` | La activa | Depende del entorno |
| `config_jetson_lab.json` | Lab UEM (10.151.65.x) | Comma: 10.151.65.207, Jetson: 10.151.65.98 |

Para cambiar de entorno en la Jetson:
```bash
# Cambiar a config del lab
cp config_jetson_lab.json config_jetson.json

# Volver a la config actual
cp config_jetson_hotspot.json config_jetson.json
```

---

## Prueba con hotspot del movil (paso a paso)

### Paso 1: Conectar ambos dispositivos al WiFi del movil

Activar hotspot en el movil y conectar tanto el Comma como la Jetson a esa red.

### Paso 2: Averiguar las IPs

En el **Comma** (por SSH):
```bash
ifconfig wlan0 | grep "inet "
```

En la **Jetson** (por SSH):
```bash
hostname -I
```

### Paso 3: Actualizar config en el COMMA

```bash
nano /data/openpilot/orbit/config_jetson.json
```

Poner:
```json
{
    "comma_ip": "IP_DEL_COMMA",
    "jetson_enabled": true,
    "jetson_img_port": 5555,
    "jetson_ip": "IP_DE_LA_JETSON",
    "jetson_torque_port": 5556,
    "jpeg_quality": 60
}
```

### Paso 4: Actualizar config en la JETSON

```bash
nano /home/sic/jetson-inference/data/zmq/config_jetson.json
```

Poner las mismas IPs (comma_ip y jetson_ip).

### Paso 5: Arrancar el Docker en la Jetson

```bash
# Entrar como root
sudo su

# Asegurar que el mount existe como fichero
touch /tmp/nv_jetson_model 2>/dev/null

# Arrancar el contenedor
docker start -i PilotNet_Zmq

# Dentro del Docker, lanzar el script
cd /jetson-inference/data/zmq && python3 jetson_1.py
```

Deberia salir:
```
============================================================
  JETSON - Receptor de imagenes Emisor de torque
============================================================
  Comma IP:    X.X.X.X
  Img port:    5555  (SUB tcp://X.X.X.X:5555)
  Torque port: 5556  (PUSH tcp://*:5556)
  Imgs dir:    /jetson-inference/data/zmq/ultimas_imagenes (ultimas 10)
  Modo:        REMOTO
============================================================
Esperando imagenes...
```

### Paso 6: Reiniciar openpilot en el Comma

```bash
cd /data/openpilot && ./launch_openpilot.sh
```

### Paso 7: Verificar que funciona

- En la Jetson se veran mensajes: `Torque enviado: XX.XXXX | Frame: WxH | img_X.jpg`
- Las imagenes se guardan en: `/home/sic/jetson-inference/data/zmq/ultimas_imagenes/`
- Para copiar imagenes a tu PC: `scp sic@IP_JETSON:~/jetson-inference/data/zmq/ultimas_imagenes/*.jpg /tmp/jetson_imgs/`

---

## Prueba con simulador (PC local)

### Paso 1: Actualizar config del simulador

Archivo: `orbit/config_jetson.json` (dentro del repo en el PC)

```json
{
    "comma_ip": "IP_DE_TU_PC",
    "jetson_enabled": true,
    "jetson_img_port": 5555,
    "jetson_ip": "IP_DE_LA_JETSON",
    "jetson_torque_port": 5556,
    "jpeg_quality": 60
}
```

Para saber tu IP: `hostname -I`

### Paso 2: Arrancar Jetson (igual que pasos 5-6 de arriba)

### Paso 3: Lanzar simulador en dos terminales

Terminal 1 (openpilot manager):
```bash
cd /ruta/al/repo/openpilot-img && ./tools/sim/launch_openpilot.sh
```

Terminal 2 (MetaDrive bridge):
```bash
cd /ruta/al/repo/openpilot-img && python tools/sim/run_bridge.py
```

---

## Resumen rapido

| Que | Donde | Comando/Archivo |
|---|---|---|
| Config Comma | SSH al Comma | `/data/openpilot/orbit/config_jetson.json` |
| Config Jetson | SSH a la Jetson | `/home/sic/jetson-inference/data/zmq/config_jetson.json` |
| Docker Jetson | SSH a la Jetson (root) | `docker start -i PilotNet_Zmq` |
| Script Jetson | Dentro del Docker | `cd /jetson-inference/data/zmq && python3 jetson_1.py` |
| Imagenes guardadas | Jetson (host) | `/home/sic/jetson-inference/data/zmq/ultimas_imagenes/` |
| Pesos modelo | Jetson (host) | `/home/sic/jetson-inference/data/zmq/pilotnet_weights.pth` |

## Troubleshooting

### Docker no arranca (error nv_jetson_model)
```bash
rm -f /tmp/nv_jetson_model && touch /tmp/nv_jetson_model
docker rm PilotNet_Zmq
docker create --name PilotNet_Zmq --runtime nvidia --network host -v /home/sic/jetson-inference/data:/jetson-inference/data -v /tmp/argus_socket:/tmp/argus_socket -v /etc/enctune.conf:/etc/enctune.conf -v /etc/nv_tegra_release:/etc/nv_tegra_release -v /tmp/nv_jetson_model:/tmp/nv_jetson_model -it jetson_zmq:v1 /bin/bash
docker start -i PilotNet_Zmq
```

### No llegan imagenes a la Jetson
1. Verificar que ambos estan en la misma red WiFi
2. Verificar que las IPs en ambos configs coinciden
3. Probar conectividad: `ping IP_DEL_COMMA` desde la Jetson
4. Verificar que el puerto 5555 no esta bloqueado por firewall

### Imagenes llegan muy lentas en el Comma real
El thumbnail de camerad se genera cada 100 frames (cada 5 segundos).
Para aumentar la frecuencia, modificar en `system/camerad/cameras/camera_qcom2.cc`:
```cpp
// Cambiar cnt % 100 por un valor menor
if (stream_type == VISION_STREAM_ROAD && cnt % 4 == 0) {  // ~5 FPS
```
Requiere recompilar openpilot.
