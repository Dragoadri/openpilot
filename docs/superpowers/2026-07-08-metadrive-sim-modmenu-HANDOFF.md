# MetaDrive Sim Mod-Menu — Handoff / qué verificar tú

Rama: **orbit-master**. Todo el código está implementado, revisado y commiteado.

## Qué se construyó

Un **mod-menu dentro del simulador MetaDrive**, accionado por teclas en la terminal de `run_bridge`, con un HUD on-screen (`--render`). Permite, en caliente: cambiar de mapa (incl. rotonda), activar/ajustar tráfico, y **soltar coches y obstáculos a voluntad** para probar si openpilot los esquiva / frena. Todo por defecto reproduce el comportamiento actual (sin flags = mundo de siempre).

Spec: `docs/superpowers/specs/2026-07-08-metadrive-sim-modmenu-design.md`
Plan: `docs/superpowers/plans/2026-07-08-metadrive-sim-modmenu.md`

## Cómo usarlo

```bash
cd tools/sim
./run_bridge.py --map roundabout --render          # rotonda + HUD
./run_bridge.py --map intersection_x --traffic 0.1 # cruce con tráfico
./preview_map.py --map roundabout                  # ver un mapa sin openpilot
```

Hotkeys (en la terminal de run_bridge): `l` coche parado · `k` cut-in (IDM) · `o` obstáculo · `p` obstáculo lateral · `t` tráfico on/off · `+`/`-` densidad · `m`/`n` mapa sig/ant · `c` limpiar · `h` HUD. (Las de siempre siguen: `1/2/3` cruise, `wasd`, `r`, `i`, `q`.)

## Estado de verificación

- ✅ **Tests de lógica pura, ejecutados y en verde**: mapas (5/5), comandos (3/3), hotkeys (4/4), ModMenu dispatch (7/7). Corridos con el venv de SICUEM (metadrive) + `--confcutdir` (el conftest raíz de ORBITPILOT rompe pytest porque el repo no está compilado).
- ✅ **Todo el código compila** (`py_compile`) y `run_bridge.py --help` muestra las flags nuevas.
- ✅ **Revisión de rama completa** (subagente independiente contra el código real de MetaDrive): encontró 2 crashes Críticos (C1/C2) en el ciclo spawn→reset, **ya corregidos** (commit `c087ae58d`) y re-revisados. Ver más abajo.
- ⏸️ **NO verificado aquí (necesita TU entorno compilado + GUI):** los tests que importan `openpilot.common.params`/cereal (crashean por capnp en este checkout sin compilar), y todo lo visual.

### Cómo correr los tests en tu entorno compilado

```bash
# desde un checkout de openpilot COMPILADO (scons) con el extra tools:
pytest tools/sim/tests/test_metadrive_maps.py tools/sim/tests/test_metadrive_command.py \
       tools/sim/tests/test_keyboard_ctrl.py tools/sim/tests/test_metadrive_modmenu.py \
       tools/sim/tests/test_metadrive_bridge.py -v
```

(Los 4 primeros ya pasaron aquí; el de bridge no pudo correr por el entorno.)

## ⚠️ Lo que TIENES que verificar tú (GUI)

Un subagente no puede pulsar teclas en la ventana 3D. Lanza y observa:

1. **Núcleo de spawn (Tarea 7, sin render):**
   `./run_bridge.py` → pulsa `l`, `k`, `o`, `c`. No debe crashear el proceso metadrive; `c` limpia sin error. **Tras los fixes, pulsar `r`/`t`/`m` después de spawnear ya NO debe crashear** (era el bug C1/C2).

2. **Render + HUD (Tarea 9 / spike):**
   `./run_bridge.py --render` → debe abrir la ventana de MetaDrive con el HUD arriba-izquierda (map/traffic/spawned + leyenda). Spawnea con `l/k/o/p`, cuenta sube; `c` limpia; `h` oculta/muestra HUD. **Verifica que la cámara de openpilot NO se ve en negro** (que conviven ventana + cámara offscreen). Si hay frames negros o errores CUDA/GL: en `metadrive_bridge.py build_config`, añade `image_on_cuda=_cuda_enable and not self.should_render` cuando renderices (ya está `multi_thread_render=False`).

3. **Cambio de mapa en caliente (Tarea 10 / spike, la única incógnita real):**
   `./run_bridge.py --render` → pulsa `m` varias veces. El HUD debe ciclar mapas y, tras una pausa de regeneración, aparecer la geometría nueva con el ego re-spawneado. Engancha openpilot y comprueba que conduce la rotonda. **Fallback si falla:** elegir mapa al lanzar (`--map roundabout`) ya funciona; si el cambio en vivo crashea, se puede desactivar `m`/`n` (ver Tarea 10 del plan).

4. **Previewer (Tarea 11):**
   `./preview_map.py --map roundabout` (y `intersection_x`, `highway`) → ventana con la geometría, sin openpilot.

## Caveats (fork minimal)

- Coches/NPC y conos/barreras se ven como **cajas** (mallas 3D quitadas). El obstáculo por defecto es la **señal de warning** (única con malla). Físicamente colisionan e IDM conduce — vale para probar esquivar/reacción a líder, no para fidelidad visual.
- Mapas reales (Waymo/nuScenes/OSM) **no soportados** en este fork (falta `scenarionet` + datos + mallas). No cablear `ScenarioEnv`.

## Desviaciones del plan (menores, intencionales)

- `keyboard_ctrl.py`: import de `common` hecho **lazy** (testabilidad; sin cambio de comportamiento).
- `metadrive_bridge.py`: `multi_thread_render=False` solo al renderizar → el config por defecto queda **byte-idéntico** al original.

## Commits del feature (en orbit-master)

`8e05ed0a7` maps · `c99458531` comandos · `c9dcef369` hotkeys · `d9383b9d9` dispatch · `1769454f2` ModMenu · `7b6f11f2b` world pipe · `784bd7d89` process · `f6cc3dd1c` bridge+CLI · `f88c72468` previewer+docs · `c087ae58d` fixes de revisión (C1/C2).
