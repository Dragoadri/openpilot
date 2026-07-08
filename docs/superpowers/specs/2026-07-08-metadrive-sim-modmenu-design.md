# MetaDrive Sim Mod-Menu — Diseño

Fecha: 2026-07-08
Rama: sicuem-mig
Estado: aprobado para plan de implementación

## 1. Objetivo

Hacer el simulador MetaDrive de este fork mucho más fácil de usar para **probar cosas en caliente**: cambiar de mapa, activar/ajustar tráfico, y sobre todo **soltar coches y obstáculos a voluntad** para ver cómo reacciona openpilot (esquivar, frenar ante un líder, cut-in). El vehículo de interacción es un **mod-menu dentro del simulador**: un HUD on-screen en la ventana de MetaDrive con hotkeys accionadas desde la terminal.

Todas las capacidades pedidas ya están soportadas por el motor; el trabajo es de integración (*fontanería*) en `tools/sim/`, no de tocar MetaDrive.

## 2. Estado actual (confirmado leyendo el código)

Flujo real, **3 procesos** y sus canales IPC:

```
 [teclado, proc. principal]      [proceso "bridge"]              [proceso "metadrive"]
 keyboard_poll_thread  ──Queue──▶ SimulatorBridge._run  ──Pipe──▶ metadrive_process
  (getch, run_bridge)             (parsea CONTROL_COMMAND)         (ejecuta sobre env)
```

- `tools/sim/lib/keyboard_ctrl.py` — `keyboard_poll_thread(q)` lee teclas con `getch()` y encola `QueueMessage(CONTROL_COMMAND, "reset")`, etc. Teclas usadas hoy: `1/2/3` (cruise), `w/a/s/d` (conducir), `z/x` (intermitentes), `i` (ignición), `r` (reset), `q` (salir).
- `tools/sim/bridge/common.py` — `SimulatorBridge._run(q)` consume la Queue (línea ~132), hace `message.info.split('_')` y despacha; `reset` → `self.world.reset()`, `quit` → break.
- `tools/sim/bridge/metadrive/metadrive_world.py` — `MetaDriveWorld`; `reset()` marca `should_reset=True` y ese flag viaja por el Pipe `controls_send` al proceso metadrive dentro de la tupla `[steer, gas, should_reset]`.
- `tools/sim/bridge/metadrive/metadrive_process.py` — `metadrive_process`; crea `env = MetaDriveEnv(config)` una vez; en cada frame lee `controls_recv`, y si `should_reset` llama a `reset()` (que hace `env.reset()`).
- `tools/sim/bridge/metadrive/metadrive_bridge.py` — `create_map()` (líneas 30-47) genera **un único** mapa fijo (bucle cerrado: 4 rectas + 4 curvas de 90°, `track_size=60`); `spawn_world()` fija `traffic_density=0.0` y `should_render=False`. No hay flags para nada de esto.
- `tools/sim/run_bridge.py` — solo expone `--joystick`, `--high_quality`, `--dual_camera`.

## 3. Capacidades confirmadas del fork `minimal`

commaai/metadrive @ `minimal` (rev `2716f55a`) **no recorta código**, solo dependencias y assets 3D. Confirmado sobre el paquete instalado:

- **Mapas por bloques (letras)**: `I`=inicio, `S`=recta, `C`=curva, `O`=**rotonda**, `X`=cruce 4 vías, `T`=intersección en T, `r`/`R`=rampas, etc. Tres formas de especificar: `map=<int>` (N bloques aleatorios), `map="SOS"` (secuencia exacta), o `map_config=dict(type=PG_MAP_FILE, config=[None, <block dict>, ...])` (paramétrico — el que ya usa el bridge).
- **Rotondas**: bloque `O` (`roundabout.py`), pura geometría de carriles, funciona sin assets.
- **Tráfico**: `traffic_density` (default upstream 0.1; el bridge lo pone a 0.0), `traffic_mode` ∈ {trigger, respawn, hybrid}; NPCs conducidos por `IDMPolicy`. Con `abs(density) < 1e-2` no se spawnea tráfico.
- **Spawn de objetos**: `env.engine.spawn_object(cls, vehicle_config={...})`. Colocación absoluta con `spawn_position_heading=([x,y], heading_rad)` (máxima prioridad) o relativa a carril con `spawn_lane_index`/`spawn_longitude`/`spawn_lateral`. Para que un NPC conduzca: `engine.add_policy(v.id, IDMPolicy, v, seed)`. Obstáculos estáticos: `TrafficCone`/`TrafficBarrier`/`TrafficWarning` (`metadrive.component.static_object.traffic_object`).

**Caveat de assets**: el `minimal` quita las mallas 3D de vehículos → coches/NPC se renderizan como **cajas** (físicamente colisionan e IDM funciona). `warning.gltf` sí está incluido (la señal de warning se ve bien). Para probar *esquivar* y *reacción a líder* sirve; la fidelidad visual del coche, no.

**Fuera de alcance (dead-end en este fork)**: mapas reales Waymo/nuScenes/OSM vía `ScenarioEnv` — requieren el paquete `scenarionet` (no instalado), datos convertidos (no incluidos) y mallas 3D (quitadas). No se intenta.

## 4. Diseño

### 4.1 Idea central

El mod-menu **reutiliza el canal de input existente**. Se añade un vocabulario de comandos que viaja: tecla → Queue (`CONTROL_COMMAND "mod_..."`) → bridge → **Pipe dedicado nuevo** → proceso metadrive → objeto `ModMenu` que ejecuta sobre `env.engine`. **Una sola fuente de input (la terminal)** ⇒ sin conflictos de foco de teclado. El HUD es **solo-display** en la ventana `--render`.

### 4.2 Componentes (cada uno una responsabilidad)

| Archivo | Nuevo/Edit | Responsabilidad |
|---|---|---|
| `tools/sim/bridge/metadrive/metadrive_maps.py` | nuevo | Librería `MAPS: dict[str, callable→config]` de presets. Solo geometría; sin dependencias del bridge; testeable aislado. Incluye `create_map(track_size)` movido aquí. |
| `tools/sim/bridge/metadrive/metadrive_command.py` | nuevo | Vocabulario de comandos (constantes/enum) compartido entre bridge y proceso. Evita imports cruzados. |
| `tools/sim/bridge/metadrive/metadrive_modmenu.py` | nuevo | Clase `ModMenu` (corre en el proceso metadrive). Estado (mapa actual, densidad, ids spawneados) + acciones + `draw_hud()`. Encapsula toda la lógica de spawn/HUD. |
| `tools/sim/bridge/metadrive/metadrive_process.py` | edit | Instancia `ModMenu`; cada frame sondea el pipe de comandos y despacha; dibuja HUD; gestiona recreación de `env` en cambio de mapa. |
| `tools/sim/bridge/metadrive/metadrive_world.py` | edit | Pipe `mod_cmd_send/recv`; método `send_command(cmd)`; pasa el extremo receptor al proceso. |
| `tools/sim/bridge/metadrive/metadrive_bridge.py` | edit | Usa `MAPS`; acepta kwargs `map`, `traffic_density`, `render`, `track_size` (con defaults = comportamiento actual idéntico); fija `use_render`. |
| `tools/sim/bridge/common.py` | edit | Añade rama `elif m[0] == "mod": self.world.send_command(...)`. Mínimo. |
| `tools/sim/lib/keyboard_ctrl.py` | edit | Hotkeys nuevas del mod-menu (sin tocar las actuales); ayuda actualizada. |
| `tools/sim/run_bridge.py` | edit | Flags `--map`, `--traffic`, `--render`, `--track-size`; los propaga a `MetaDriveBridge`. |
| `tools/sim/preview_map.py` | nuevo | Previsualizador standalone: `MetaDriveEnv(use_render=True, map_config=MAPS[name])`, reset y loop con acción cero. Sin openpilot. |
| `tools/sim/README.md` | edit | Sección de mapas (tabla de letras), hotkeys del mod-menu, previsualizador y caveats (cajas / mapas reales fuera de alcance). |
| `tools/sim/tests/...` | edit/nuevo | Tests de presets, parsing de comandos y compatibilidad de kwargs. |

### 4.3 Protocolo de comandos

Los comandos viajan como string por la Queue existente con la categoría `mod` (para no chocar con el `split('_')` actual):

```
mod_spawn_lead      # coche parado delante (sin policy → estático)
mod_spawn_cutin     # NPC en carril adyacente + IDMPolicy (se cruza/circula)
mod_obstacle_cone   # cono delante (obstáculo a esquivar)
mod_obstacle_side   # obstáculo desplazado al carril (deja hueco para esquivar)
mod_traffic_toggle  # tráfico on/off
mod_traffic_up / mod_traffic_down   # ± densidad
mod_map_next / mod_map_prev         # cicla presets (recrea env)
mod_clear           # elimina todo lo spawneado
mod_hud             # muestra/oculta HUD
```

En `common.py`: `elif m[0] == "mod": self.world.send_command(message.info)`. En `MetaDriveWorld.send_command(cmd)`: `self.mod_cmd_send.send(cmd)`. En `metadrive_process`: cada frame, `while mod_cmd_recv.poll(0): modmenu.apply(mod_cmd_recv.recv())`.

### 4.4 API de `ModMenu`

```python
class ModMenu:
    def __init__(self, env, map_names: list[str], render: bool): ...
    def apply(self, cmd: str) -> None      # despacha el vocabulario 4.3
    def on_reset(self) -> None             # limpia ids trackeados tras env.reset()
    def draw_hud(self) -> None             # OnscreenText; no-op si not render
    def pop_pending_map(self) -> str|None  # el proceso consulta si hay cambio de mapa pendiente
```

- **Colocación**: se calcula desde el ego. `long, lat = env.vehicle.lane.local_coordinates(env.vehicle.position)`; se spawnea con `spawn_position_heading` absoluto derivado de `lane.position(long + d, lat + offset)` para máxima fiabilidad.
- **Lead parado**: `spawn_object(DefaultVehicle, ...)` a `d≈40m`, sin policy.
- **Cut-in**: carril adyacente a `d≈25m` + `add_policy(v.id, IDMPolicy, v, seed)`.
- **Obstáculo**: `TrafficCone`/`TrafficBarrier` a `d≈30m`, `lateral` según variante.
- **Tracking**: `ModMenu` guarda los ids spawneados; `mod_clear` y `on_reset` los eliminan (`engine.clear_objects([...])`).

### 4.5 HUD

`OnscreenText`/`DirectGUI` (Panda3D) anclado a `aspect2d`, actualizado cada frame por `draw_hud()`. Muestra: mapa actual, tráfico on/off + densidad, nº NPCs, y la leyenda de hotkeys. Requiere ventana ⇒ solo con `--render` (degrada a no-op si no hay render).

### 4.6 Presets de mapa (`MAPS`)

`loop` (actual), `roundabout` (rectas → `O` → rectas), `intersection_x` (`X`), `intersection_t` (`T`), `highway` (rectas largas, 3 carriles), `ramps` (`r`/`R`). El bloque de rotonda se **flanquea con rectas de entrada/salida** para que la navegación del ego entre y salga.

### 4.7 Hotkeys

Se respetan las actuales. Se añaden: `l` lead parado · `k` cut-in · `o` obstáculo delante · `p` obstáculo desplazado · `t` toggle tráfico · `+`/`-` densidad · `m`/`n` mapa sig./ant. · `c` limpiar · `h` HUD/ayuda.

## 5. Niveles de robustez, incógnitas y fallbacks

- 🟢 **Sólido** (`spawn_object` directo, sin reset): lead, cut-in, obstáculos, clear, HUD. Núcleo de "spawnear a voluntad"; sin incógnitas.
- 🟡 **Sólido** (set densidad + `env.reset()`): toggle/ajuste de tráfico. Reutiliza el path de reset existente.
- 🟠 **Stretch (única incógnita real)**: cambio de mapa **en caliente** → recrear `MetaDriveEnv` en el proceso (`env.close()` + `MetaDriveEnv(new_config)` + re-aplicar patches/cámaras). Fallback si resulta frágil: elegir mapa **al lanzar** (`--map roundabout`) y cambiar = relanzar.

**Spikes a verificar en implementación** (no se asumen): (a) `use_render=True` conviviendo con las cámaras offscreen de openpilot; (b) recreación de `env` para cambio de mapa. Cada uno con su fallback.

## 6. Compatibilidad hacia atrás

- Los nuevos kwargs de `MetaDriveBridge.__init__` van **después** de los posicionales y con default que reproduce el comportamiento actual, de modo que `MetaDriveBridge(False, False, test_duration, True)` (usado en `test_metadrive_bridge.py`) sigue funcionando.
- Sin flags, `run_bridge.py` produce exactamente el mundo actual (mapa `loop`, tráfico 0.0, sin render).

## 7. Tests (TDD)

- `metadrive_maps`: cada preset construye una config PG válida (estructura, primer elemento `None`, ids de bloque conocidos).
- `common.py`: una `CONTROL_COMMAND "mod_*"` invoca `world.send_command(...)` con el string esperado (con un `World` mock).
- Compatibilidad: `MetaDriveBridge` con la firma posicional existente construye la misma config base (mapa loop, traffic 0.0).
- Los tests existentes de `test_metadrive_bridge.py`/`test_sim_bridge.py` siguen pasando.

## 8. Fuera de alcance (YAGNI)

- Mapas reales Waymo/nuScenes/OSM (`ScenarioEnv`) — dead-end en el fork minimal.
- Restaurar mallas 3D de coches (los NPC seguirán siendo cajas).
- Menú navegable con ratón/DirectGUI interactivo (se eligió HUD + hotkeys).
- Escenarios definidos por archivo JSON/YAML (posible iteración futura; el vocabulario de comandos deja la puerta abierta).
