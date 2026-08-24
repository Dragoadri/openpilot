#!/usr/bin/env python3
"""Genera el descriptor de telemetria que consume ORBIT-IoV, desde el del firmware.

POR QUE ESTE FICHERO EXISTE
---------------------------
La telemetria v2 se entrego con TRES vocabularios independientes: el coche publicaba
`speed_kph`, el backend esperaba `v_ego` y la app estaba alineada a un descriptor que el
backend se habia inventado a partir de la prosa del diseno. 86 de los 102 campos se
descartaban EN SILENCIO (el backend devolvia True e insertaba la fila igual), asi que los
tres repos daban verde con sus propios tests y no llegaba un solo dato util.

Es el mismo fallo que ya rompio el 100 % de tres verbos de mando por los nombres de sus
argumentos. La leccion no es "revisar mejor": es que un contrato copiado a mano diverge
siempre. El firmware es la fuente -- es quien conoce el capnp y las unidades reales -- y
este script CONVIERTE su descriptor a la forma que parsea backend/server/telemetry_descriptor.py:

    firmware:  "campos": [ {"nombre": "speed_kph", "tipo": "float", "dec": 1, ...}, ... ]
    backend:   "campos": { "speed_kph": {"tipo": "float", "redondeo": 1, ...}, ... }

Uso:
    uv run python3 orbit/gen_descriptor_backend.py > .../backend/schema/telemetry_v2.json

El test de contrato cruzado vuelve a generar esto y compara: si alguien edita el JSON del
backend a mano, o cambia un campo en el firmware sin regenerar, el test cae.
"""
import json
import sys

from openpilot.orbit.telemetria_v1 import (CONTRACT_VERSION, SCHEMA_TELEMETRIA, TOPIC_TEL,
                                           descriptor_backend, firma_telemetria)

_CABECERA = [
  "FICHERO GENERADO. No lo edites a mano.",
  "",
  "Lo produce orbit/gen_descriptor_backend.py desde orbit/telemetria_v1.py, que es la",
  "UNICA fuente de verdad del contrato de telemetria: es quien conoce el esquema capnp",
  "y las unidades reales de cada senal.",
  "",
  "Para regenerarlo:",
  "  cd <ORBITPILOT> && uv run python3 orbit/gen_descriptor_backend.py \\",
  "      > <orbit-iov>/backend/schema/telemetry_v2.json",
  "",
  "'tipo' es el tipo del CABLE y decide la columna SQL (float->REAL, int/bool->INTEGER,",
  "str->TEXT). 'redondeo' son decimales, se aplica al guardar. 'col' solo aparece cuando",
  "la columna no se llama como el campo.",
]


# El firmware distingue `enum` (cadena de un conjunto cerrado: gear, personality,
# lane_change...) porque necesita validar el valor contra el capnp. En el CABLE un enum es
# una cadena y nada mas, y el backend solo conoce cuatro tipos porque son los que sabe
# convertir a columna SQL. Sin esta traduccion se ignoraban 19 campos con un WARN que
# nadie mira, y el canal parecia vivo yendo vacio -- justo el fallo que este generador
# existe para cerrar.
#
# `list[str]` (health.procs_caidos: los procesos caidos) se guarda como TEXTO con el JSON
# dentro. Es una lista corta y de consulta ocasional; darle tabla propia seria mas coste
# que valor.
#
# `list[obj]` (event.ev) NO se traduce a propósito: es la carga entera del canal de
# eventos, y su sitio no es una columna de muestras sino la tabla device_events. El
# backend tiene que ingerirlo por su propio camino; si algun dia aparece aqui como
# columna, sera que alguien lo esta guardando en el sitio equivocado.
_TIPO_CABLE = {"enum": "str", "list[str]": "str"}


def convertir() -> dict:
  """Descriptor del firmware -> forma que parsea telemetry_descriptor.Descriptor."""
  fw = descriptor_backend()
  canales = {}
  for nombre, cuerpo in fw["canales"].items():
    campos = {}
    for campo in cuerpo.get("campos", []):
      tipo = campo["tipo"]
      spec = {"tipo": _TIPO_CABLE.get(tipo, tipo)}
      if campo.get("unidad"):
        spec["unidad"] = campo["unidad"]
      if campo.get("dec") is not None:
        spec["redondeo"] = campo["dec"]
      campos[campo["nombre"]] = spec
    # `hz` es informativo para el backend; el firmware declara el periodo POR PERFIL, asi
    # que se publica el del perfil normal, que es el que describe el caso corriente.
    periodo = (cuerpo.get("periodo_s") or {}).get("normal")
    canales[nombre] = {
      "descripcion": cuerpo.get("desc", ""),
      "hz": round(1.0 / periodo, 4) if periodo else None,
      "disparo": cuerpo.get("disparo"),
      "campos": campos,
    }
  return {
    "_comentario": _CABECERA,
    "descriptor_version": SCHEMA_TELEMETRIA,
    "contrato": CONTRACT_VERSION,
    # La huella viaja DENTRO del fichero para que el backend pueda decir en un log con que
    # version del contrato esta hablando, y para que el test cruzado la compare sin
    # recalcular nada.
    "firma": firma_telemetria(),
    "topic": TOPIC_TEL.format("{dongle}", "{canal}"),
    "canales": canales,
    "eventos": fw.get("eventos", {}),
    "severidades": fw.get("severidades", {}),
  }


if __name__ == "__main__":
  json.dump(convertir(), sys.stdout, ensure_ascii=False, indent=2, sort_keys=False)
  sys.stdout.write("\n")
