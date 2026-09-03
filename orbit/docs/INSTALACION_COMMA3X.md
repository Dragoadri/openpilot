# Guía de instalación en comma 3X

Esta guía deja un comma 3X funcionando con ORBITPILOT igual que con sunnypilot
u openpilot stock (conducción automática incluida), y explica cómo diagnosticar
los dos fallos de despliegue más comunes: **submódulos vacíos** y **modelos
LFS sin descargar**.

---

## Requisitos

- comma 3X con AGNOS y conexión a internet (Wi-Fi) para el primer arranque.
- El coche debe estar soportado por el opendbc incluido (misma lista que
  sunnypilot). Si el coche no se reconoce, el sistema entra en dashcam mode
  igual que haría sunnypilot stock.

## Instalación

### Opción A — instalador (recomendada)

Usa el instalador de software custom del dispositivo (URL de instalador de
fork, p. ej. `installer.comma.ai/Dragoadri/orbit-master`, que clona
`https://github.com/Dragoadri/openpilot.git` rama `orbit-master`).

El instalador clona con submódulos y, como AGNOS trae git-lfs configurado para
el usuario `comma`, descarga también los objetos LFS desde el GitLab de
sunnypilot que indica `.lfsconfig` (si alguna descarga LFS fallase, el propio
clon fallaría y el instalador no llegaría a "Finishing install").

### Opción B — manual por SSH

```bash
cd /data
git clone --recurse-submodules https://github.com/Dragoadri/ORBITPILOT.git openpilot
cd openpilot
git lfs install
git lfs pull        # descarga los modelos .onnx/.pkl (OBLIGATORIO)
```

Los dos errores típicos:

| Error | Síntoma | Arreglo |
|---|---|---|
| Clon sin `--recurse-submodules` | build falla o procesos no arrancan | `git submodule update --init --recursive` |
| Olvidar `git lfs pull` | modeld caído ("openpilot unavailable") | `git lfs pull` |

## Primer arranque

En el primer arranque el dispositivo **compila todo con scons** (puede tardar
entre 20 y 60 minutos; la pantalla muestra progreso). No apagues el coche ni
el dispositivo durante el build.

Antes de compilar, `launch_chffrplus.sh` ejecuta la **auto-reparación de la
instalación** (`orbit/install_repair.py`): si el árbol tiene punteros LFS sin
descargar o submódulos vacíos, hace `git lfs pull` (excluyendo los modelos
`big_*` de USB-GPU, que el comma no usa) y `git submodule update`, mostrando el
progreso en el spinner y con todo lo de red acotado por timeout. En un árbol
sano no ejecuta nada. Su registro queda en `/tmp/orbit_install_repair.log` y en
la salida de tmux (`/tmp/launch_log`).

Después, al arrancar manager, el **chequeo de instalación**
(`orbit/install_check.py`) muestra la alerta offroad **"ORBIT: la instalación
está incompleta"** si algo sigue roto, con el problema exacto y el comando para
arreglarlo — en vez de caer en dashcam sin explicación.

Si la pantalla se queda en el logo de arranque, por SSH (`ssh comma@<ip>`):

```bash
cat /tmp/orbit_install_repair.log      # que hizo la auto-reparacion (si hubo algo que reparar)
cat /tmp/launch_log                    # salida del arranque hasta el build
tmux a                                 # sesion viva del arranque (Ctrl-b d para salir)
```

## Verificación post-instalación

Por SSH (`ssh comma@<ip>`):

```bash
cd /data/openpilot
git submodule status                 # ninguna línea debe empezar por '-'
cat /data/params/d/OpenpilotEnabledToggle   # debe ser 1
cat /data/params/d/SteerTorqueMode          # debe ser 0 (Comma) salvo que uses Jetson
```

Comprobaciones en pantalla:

- No debe aparecer la alerta "instalación incompleta".
- Con el coche encendido, el aviso de arranque debe ser el normal de
  sunnypilot, **no** "dashcam mode" ni "car unrecognized".

## Si aparece dashcam mode

El modo dashcam significa que el coche se reconoció pero el control está
desactivado. Revisa en este orden:

1. `OpenpilotEnabledToggle` = 1 (toggle "Enable ORBIT" en Ajustes → Toggles).
2. Que el coche no sea una variante `dashcamOnly` de opendbc (p.ej. Hyundai/Kia
   non-SCC, PSA, Ford SecOC sin key): con sunnypilot stock pasaría lo mismo.
3. `CarParams` cacheado de otra instalación: borra
   `/data/params/d/CarParams` y `/data/params/d/CarParamsCache` y reinicia.

Si el aviso es **"car unrecognized"**, el coche no está en la base de datos de
firmware de opendbc: habría que añadir sus FW versions (ver `docs/CARS.md` y
`opendbc_repo/opendbc/car/`).

## Params de seguridad (automáticos)

- `SteerTorqueMode=2` (TEST MAX, solo banco) **se resetea a 0 en cada
  arranque**. Los modos Jetson (1/3) sí persisten.
- `ForceLaneChangeLeft/Right` y `silenciar_alertas_comm` se limpian en cada
  arranque (no sobreviven a reinicios ni viajan en backups).
- Desde el panel ORBIT de Ajustes, el botón **"Restablecer valores seguros"**
  devuelve todos los params ORBIT a su estado seguro sin reiniciar.
