# MetaDrive Sim Mod-Menu — Handoff / qué verificar tú

Rama: **orbit-master**. Todo el código está implementado y revisado; el fix del bug P0 `render_vehicle` está en el working tree (pendiente de commit).

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

- ✅ **Entorno de esta máquina ya compilado**: el repo tiene su propio venv (`.venv`, con metadrive 0.4.2.3 + capnp); todos los tests corren aquí con `.venv/bin/python -m pytest`.
- ✅ **Suite completa de tests en verde** (mapas, comandos, hotkeys, dispatch, bridge): 21 passed, 1 skipped.
- ✅ **Bug P0 `render_vehicle` encontrado, arreglado y verificado headless** (ver sección siguiente): spawns `l`/`k` y cualquier `traffic_density > 0` crasheaban; ahora reset con tráfico, los 4 spawns, clear y 2 cambios de mapa en vivo pasan un smoke sin render.
- ✅ **Revisión de rama completa** (subagente independiente contra el código real de MetaDrive): encontró 2 crashes Críticos (C1/C2) en el ciclo spawn→reset, **ya corregidos** (commit `c087ae58d`) y re-revisados.

### Bug P0: KeyError('render_vehicle') — arreglado

El fork comma-minimal de metadrive (0.4.2.3) lee `vehicle_config['render_vehicle']` del dict **crudo** (`base_vehicle.py:142`), así que cualquier `vehicle_config` parcial sin esa clave crashea al spawnear:

- `spawn_lead` / `spawn_cutin` (`metadrive_modmenu.py`) crasheaban al pulsar `l`/`k` → fix: `render_vehicle=False` dentro de sus dicts `vehicle_config`.
- Cualquier `traffic_density > 0` crasheaba `env.reset()` vía `traffic_manager.py:268` (el `traffic_vehicle_config` por defecto tampoco trae la clave) → fix en `metadrive_process.py`, tras crear el env: `env.config["traffic_vehicle_config"].update(dict(render_vehicle=False), allow_add_new_key=True)`. Pasarla en el dict del constructor NO funciona (`Config` rechaza claves nuevas).

Verificado por ejecución con un smoke headless (MetaDriveEnv sin render): reset con `traffic_density=0.1` (28 NPCs), lead + cut-in + obstáculo + obstáculo lateral vía `ModMenu.apply()`, clear, y cambio de mapa en vivo a roundabout y highway (con tráfico re-spawneado en cada uno).

### Cómo correr los tests

```bash
# desde la raíz del repo:
.venv/bin/python -m pytest --confcutdir=tools/sim/tests \
       tools/sim/tests/test_metadrive_maps.py tools/sim/tests/test_metadrive_command.py \
       tools/sim/tests/test_metadrive_modmenu.py tools/sim/tests/test_keyboard_ctrl.py \
       tools/sim/tests/test_metadrive_bridge.py -m 'not slow' -p no:cacheprovider
# → 21 passed, 1 skipped
```

## ⚠️ Checklist restante: SOLO GUI

Todo lo headless ya está verificado por ejecución. Queda únicamente lo visual (nadie puede pulsar teclas en la ventana 3D por ti):

1. **Render + HUD:**
   `./run_bridge.py --render` → debe abrir la ventana de MetaDrive con el HUD arriba-izquierda (map/traffic/spawned + leyenda). Spawnea con `l/k/o/p`, cuenta sube; `c` limpia; `h` oculta/muestra HUD.

2. **Cámara openpilot no-negra:**
   con `--render`, **verifica que la cámara de openpilot NO se ve en negro** (que conviven ventana + cámara offscreen). Si hay frames negros o errores CUDA/GL: en `metadrive_bridge.py build_config`, añade `image_on_cuda=_cuda_enable and not self.should_render` cuando renderices (ya está `multi_thread_render=False`).

3. **Conducir la rotonda enganchado:**
   `./run_bridge.py --render` → pulsa `m` hasta roundabout (el cambio en vivo ya no crashea headless), engancha openpilot y comprueba que conduce la rotonda.

4. **Previewer (opcional, también GUI):**
   `./preview_map.py --map roundabout` (y `intersection_x`, `highway`) → ventana con la geometría, sin openpilot.

## Caveats (fork minimal)

- Coches/NPC y conos/barreras se ven como **cajas** (mallas 3D quitadas). El obstáculo por defecto es la **señal de warning** (única con malla). Físicamente colisionan e IDM conduce — vale para probar esquivar/reacción a líder, no para fidelidad visual.
- Mapas reales (Waymo/nuScenes/OSM) **no soportados** en este fork (falta `scenarionet` + datos + mallas). No cablear `ScenarioEnv`.

## Desviaciones del plan (menores, intencionales)

- `keyboard_ctrl.py`: import de `common` hecho **lazy** (testabilidad; sin cambio de comportamiento).
- `metadrive_bridge.py`: `multi_thread_render=False` solo al renderizar → el config por defecto queda **byte-idéntico** al original.

## Commits del feature (en orbit-master)

`8e05ed0a7` maps · `c99458531` comandos · `c9dcef369` hotkeys · `d9383b9d9` dispatch · `1769454f2` ModMenu · `7b6f11f2b` world pipe · `784bd7d89` process · `f6cc3dd1c` bridge+CLI · `f88c72468` previewer+docs · `c087ae58d` fixes de revisión (C1/C2).
