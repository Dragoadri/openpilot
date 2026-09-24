# Rediseño «Órbita · Grafito» del firmware — progreso y decisiones

Plan: `2026-09-24-orbit-rediseno-ui-firmware.md` · Spec: `../specs/2026-09-24-orbit-rediseno-ui-firmware-design.md`

Rama `rediseno-orbita` desde `orbit-master@5830c90e3`. Tests `selfdrive/ui/tests/test_orbit_*.py`: 10 al empezar, 26 al terminar, todos en verde.

## Decisiones tomadas por mi cuenta (para revisar con el dueño)

- **F-R1.** Las tareas de dibujo se especificaron con requisitos y valores exactos, no con código completo. Escribir raylib a ciegas habría sido adivinar. La lógica pura está fijada por tests y el resto se revisó en capturas.
- **F-R2.** El glifo `enlace` se queda como está: tiene la misma forma «( · )» que el boceto de la app, con una diferencia de medio paso de rejilla o menos.
- **F-R3.** La tarjeta ENLACE ya no usa PULSO cuando no hay vínculo, y `draw_card` pierde el brillo, el degradado y la línea superior: queda plana, en SUP1 con borde.
- **F-R4.** El script de capturas no tuvo revisión propia. Entró en la revisión final de la rama porque no toca código de producto.
- **F-R5.** Los ~90 colores del navy antiguo marcados ORBIT dentro de `system/ui/**` (botones, listas, toggles, estilos) también pasan a tokens. Se ven en el panel ORBIT y en el diálogo del QR. El test de paleta ahora recorre también `system/ui`.
  - Coste: más diff en ficheros compartidos con sunnypilot. Solo cambian valores en líneas que ya eran de ORBIT.
- **F-R6.** El satélite del home va en la órbita interior. En la exterior estaba fuera de pantalla ~60 % de la vuelta.
- **F-R7.** El chip «FRENADA PROBABLE» vuelve a ser relleno AVISO con tinta FONDO (~12:1). Sustituye al relleno SUP1 de la tarea 5: en seguridad pesa más que se vea que la coherencia con las otras píldoras.

## Pendiente (fuera de esta rama)

- Las píldoras de mando se dibujan encima del chip de frenada cuando coinciden. Es anterior a la rama; arreglarlo es cambiar la disposición onroad.
- En el PC, con `SCALE≠1`, el texto con degradado se recorta. El dispositivo usa escala 1, así que no le afecta.
- Quedan literales CYAN/GREEN_DEEP en `system/ui` con el mismo valor que `PULSO`/`OK_PROFUNDO`. Conviene pasarlos a tokens para que no se desvíen si se retocan.
- Queda sin probar en un comma real: fps, brillo y legibilidad.

## Capturas

`BIG=1 OFFSCREEN=1 .venv/bin/python3 selfdrive/ui/tests/orbit_capturas.py <dir>` genera a 2160×1080: splash 0,5 s y 1,4 s, home conectado y sin conexión, panel ORBIT y diálogo de vinculación QR.
