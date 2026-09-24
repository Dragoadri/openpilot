# ORBITPILOT — Rediseño «Órbita · Grafito» de la UI del firmware

**Fecha:** 2026-09-24
**Autor:** dragoadri
**Estado:** aprobado por el dueño («ya tienes las elecciones, adelante, a implementar»): hereda todas las decisiones del rediseño de la app.
**Referencia (identidad común):** spec de la app `ORBIT-IoV/docs/superpowers/specs/2026-09-23-orbit-rediseno-orbita-design.md` (rama `rediseno-orbita` del repo ORBIT-IoV).
**Ámbito:** solo presentación de la UI Python/raylib del árbol «big» (tici/tizi, 2160×1080): `selfdrive/ui/**` partes ORBIT. Sin cambios en lógica de mando, MQTT, Params, controles ni upstream no-ORBIT. Sin dependencias nuevas.
**Rama:** `rediseno-orbita` en el checkout del firmware (no worktree: un worktree nuevo no tendría submódulos ni artefactos compilados y no se podría ejecutar la UI ni los tests).

## 1. Objetivo

Que el firmware y la app sean la misma marca: paleta Grafito, colores de sección, anillo Dúplex (bajada = órdenes, subida = telemetría, núcleo = coche), campo orbital, iconos propios y la regla de movimiento «nada decorativo se mueve en marcha».

## 2. Decisiones heredadas de la app

| Tema | Valor |
|---|---|
| Dirección | D1 Órbita — el logo Dúplex es la gramática |
| Paleta | Grafito (tabla §3) |
| Iconos | Glifos propios con órbita y satélite; el satélite orbita (una vuelta / 6 s) solo offroad |
| Color en pantallas interiores | Heredado de la sección |
| Arranque | «La órbita se cierra» ≤ 1,4 s |

## 3. Tokens (módulo único `selfdrive/ui/orbit_theme.py`)

Fondo `#0A0E14` · superficie 1 `#131A24` · superficie 2 `#19222F` · superficie 3 `#212C3C` · borde fino `#263243` · borde fuerte `#6E7F97` · texto 1 `#E8EEF6` · texto 2 `#A2B1C6` · texto 3 `#93A2B8` · pulso `#22D3EE` · acción `#86B9F7` (tinta encima `#05141E`) · OK `#4ADE80` (y `#16A34A` solo en el degradado del logo) · aviso `#F5C842` · peligro tinta `#FF8A8A` · freno/relleno rojo `#B91C1C` con blanco · azul profundo `#2563EB` solo en el degradado de la subida del logo.

Secciones: vehículo `#86B9F7`, mapa `#86DCCB`, viajes `#F2BE9E`, cabina = pulso, mando `#B3A7F2`, registro `#E9A3CF`, ajustes `#B5C0CE`, cuenta `#D9B6F2`, ayuda `#F4CDDF`, desarrollo `#CDD5DF`. Orientan; nunca son relleno de botón, texto de estado ni borde con significado.

Correspondencia desde la paleta navy antigua: VOID→fondo, NAVY→superficie 1, PANEL→superficie 2, HAIRLINE→borde fino, INK→texto 1, MUTED→texto 2, MUTED_DIM→texto 3, BLUE `#2563EB` (relleno de botón)→acción `#86B9F7` **con tinta `#05141E` encima**, BLUE_HI→acción, CYAN→pulso, GREEN→OK, AMBER→aviso.

Contraste: todo texto ≥ 4,5:1 y bordes de control ≥ 3:1 sobre fondo y superficies (test).

## 4. Pantallas

- **Splash** (`orbit_splash.py`): «La órbita se cierra» dibujado con primitivas raylib — anillo tenue (300 ms) → bajada verde y subida azul a la vez (400 ms) → núcleo → pulso ECG hacia los lados (300 ms) → wordmark ORBIT con subrayado que se alarga → lema. Cierre automático ~2,2 s o al tocar. Sustituye al anillo giratorio continuo y a los 5,5 s actuales.
- **Home offroad** (`layouts/home.py`): campo orbital (3 elipses inclinadas −14° en color vehículo, estrellas quietas, un satélite = el enlace ORBIT de este coche, que orbita si `OrbitConnected` y es anillo hueco quieto si no) centrado en el anillo Dúplex del bloque de marca (sustituye al PNG del logo; subida encendida si conectado). Tarjetas en Grafito; se mantiene la onda de telemetría (recoloreada) y la entrada en cascada.
- **Panel ORBIT y subpaneles, diálogo de vinculación QR, «acerca de», avisos offroad, onboarding, sidebar, botón experimental**: retokenizados; cabeceras de sección con icono propio y filete en el color de su sección.
- **Onroad** (`orbit_command_overlay`, `orbit_hardbrake_overlay`, `orbit_follow_coach`, alerta «ORBIT Unavailable»): solo colores Grafito. **Ningún movimiento nuevo**; el banner de frenada remota sigue siendo relleno rojo `#B91C1C` con blanco. Test que prohíbe importar módulos de animación ORBIT en estos ficheros.

## 5. Movimiento

El firmware ya no anima nada onroad (los overlays son latches). Se mantiene y se blinda con un test. Offroad (aparcado) pueden moverse: splash (una vez), satélite del home y satélites de iconos de sección.

## 6. Verificación

Script de capturas offscreen (`BIG=1 OFFSCREEN=1`) que guarda PNG del splash (dos instantes), home, panel ORBIT y diálogo QR; tests puros (tokens, contraste, geometría Dúplex) y tests AST (paleta única, onroad sin animación). Los tests existentes `test_orbit_*.py` siguen en verde.
