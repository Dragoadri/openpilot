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

Usa el instalador de software custom del dispositivo con la URL del repo:

```
https://github.com/Dragoadri/ORBITPILOT
```

El instalador clona con submódulos. Tras instalar, verifica LFS (ver abajo).

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

Desde este build, al arrancar manager se ejecuta un **chequeo automático de
instalación** (`orbit/install_check.py`). Si detecta submódulos vacíos o
modelos LFS sin descargar, muestra la alerta offroad
**"ORBIT: la instalación está incompleta"** con el problema exacto y el comando
para arreglarlo — en vez de caer en dashcam sin explicación.

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
