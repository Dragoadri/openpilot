"""Contrato CRUZADO: el catalogo de verbos del coche contra el del backend.

POR QUE EXISTE ESTE FICHERO. El firmware y el backend tenian cada uno su tabla de
verbos, cada una coherente consigo misma y con sus propios tests en verde, y los
NOMBRES de los argumentos habian divergido:

    lane_change      backend/app: 'dir'    coche: 'direction'
    cruise_delta     backend/app: 'delta'  coche: 'delta_kph'
    steering_pulse   backend/app: 'value'  coche: 'torque'

El coche RECHAZA los argumentos que no estan en su esquema (validar_args -> TYPE
"argumentos desconocidos"), asi que fallaba el 100 % de esos envios. Y como las rutas
legacy del backend publican v1 y v2 a la vez, el v2 moria con TYPE y el v1 se ejecutaba
por el puente: la app pintaba "Rechazada" mientras el coche cambiaba de carril.

Ningun test de una sola de las dos partes podia ver eso. Este si: lee el catalogo del
backend TAL CUAL ESTA EN SU FICHERO y lo compara verbo a verbo con COMMANDS.

Se lee con `ast` y no importando el modulo a proposito: `server/commands.py` importa
paho, flask y la base de datos del backend, que no estan (ni tienen por que estar) en el
entorno del firmware. El catalogo es un literal, asi que se puede leer sin ejecutar nada.

Si el repo del backend no esta en esta maquina, la prueba se SALTA -- no se aprueba: un
contrato que no se ha podido comparar no es un contrato verificado.
"""
import ast
import os
from pathlib import Path

import pytest

from openpilot.orbit.command_spec import COMMANDS, MODE_WIRE_NAMES, UNSUPPORTED, firma_args

# Donde vive el backend companero (repo orbit-iov). Se puede apuntar con la variable de
# entorno ORBIT_IOV_BACKEND al directorio `backend/` si esta en otro sitio.
_CANDIDATOS = (
  os.environ.get("ORBIT_IOV_BACKEND", ""),
  "/home/drago/Escritorio/PROYECTS/APPS/orbit-iov/backend",
  str(Path(__file__).resolve().parents[3] / "orbit-iov" / "backend"),
)


def _ruta_commands() -> Path | None:
  for base in _CANDIDATOS:
    if not base:
      continue
    ruta = Path(base) / "server" / "commands.py"
    if ruta.is_file():
      return ruta
  return None


def _literal_del_modulo(ruta: Path, nombre: str):
  """Valor de una asignacion de modulo, resolviendo las constantes que referencie.

  `VERBS` usa MODE_COPILOTO y compania, que son cadenas asignadas antes en el mismo
  fichero: se recogen primero y se sustituyen por su valor. Cualquier otra cosa que no
  sea un literal hace fallar la prueba en vez de adivinar.
  """
  arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
  constantes: dict = {}
  objetivo = None
  for nodo in arbol.body:
    if not isinstance(nodo, ast.Assign) or len(nodo.targets) != 1:
      continue
    destino = nodo.targets[0]
    if not isinstance(destino, ast.Name):
      continue
    if destino.id == nombre:
      objetivo = nodo.value
      break
    try:
      constantes[destino.id] = ast.literal_eval(nodo.value)
    except ValueError:
      continue
  assert objetivo is not None, f"{ruta} ya no define {nombre}"

  class _Resolver(ast.NodeTransformer):
    def visit_Name(self, node):   # el nombre lo fija la API de ast
      assert node.id in constantes, f"{nombre} referencia '{node.id}', que no es una constante literal"
      return ast.copy_location(ast.Constant(value=constantes[node.id]), node)

  return ast.literal_eval(_Resolver().visit(objetivo))


@pytest.fixture(scope="module")
def backend():
  ruta = _ruta_commands()
  if ruta is None:
    pytest.skip("el repo orbit-iov no esta en esta maquina (ORBIT_IOV_BACKEND para apuntarlo)")
  return {
    "ruta": ruta,
    "verbs": _literal_del_modulo(ruta, "VERBS"),
    "alias": _literal_del_modulo(ruta, "LEGACY_ARG_ALIASES"),
  }


def _firma_backend(argspec: dict) -> dict:
  """Firma comparable de UN argumento del catalogo del backend."""
  tipo = argspec["type"]
  return {
    "type": tipo,
    "required": bool(argspec.get("required", False)),
    "min": argspec.get("min"),
    "max": argspec.get("max"),
    "choices": list(argspec["values"]) if tipo == "enum" else None,
    "default": argspec.get("default"),
  }


# --------------------------------------------------------------- el mismo conjunto

def test_el_coche_no_ejecuta_ningun_verbo_que_el_backend_no_conozca(backend):
  """Un verbo con handler en el coche y ausente del catalogo del backend no se puede
  pedir desde ningun sitio: es superficie de mando muerta."""
  faltan = sorted(set(COMMANDS) - set(backend["verbs"]))
  assert not faltan, f"verbos del coche que el backend no declara: {faltan}"


def test_lo_que_el_backend_declara_de_mas_esta_declarado_como_no_soportado(backend):
  """El backend puede declarar verbos que este firmware aun no implementa (blinker,
  overtake), pero entonces NO pueden ser `base`: sin caps del coche se rechazan, y el
  coche los publica en `unsupported` con el motivo para que el rechazo lo explique."""
  for verbo in sorted(set(backend["verbs"]) - set(COMMANDS)):
    spec = backend["verbs"][verbo]
    assert not spec.get("base"), (
      f"'{verbo}' es base en el backend y este firmware no lo implementa; se aceptaria sin caps")
    assert verbo in UNSUPPORTED, (
      f"'{verbo}' no esta en COMMANDS ni en UNSUPPORTED: el coche no puede decir por que no lo hace")


# ------------------------------------------------------ nombres, tipos y rangos

@pytest.mark.parametrize("verbo", sorted(COMMANDS))
def test_los_argumentos_son_los_mismos_en_las_dos_partes(backend, verbo):
  """EL bloqueante: mismos nombres, mismos tipos, mismos rangos y mismas opciones.

  Si esto falla, lo que se rompe en produccion es el 100 % de los envios de ese verbo,
  con un ACK TYPE "argumentos desconocidos" que nadie mira hasta que el usuario dice que
  el boton no hace nada.
  """
  bspec = backend["verbs"].get(verbo)
  assert bspec is not None, f"el backend no declara '{verbo}'"
  coche = firma_args(COMMANDS[verbo])
  servidor = {n: _firma_backend(a) for n, a in bspec["args"].items()}

  assert set(coche) == set(servidor), (
    f"'{verbo}': el coche espera {sorted(coche)} y el backend manda {sorted(servidor)}")
  for arg in sorted(coche):
    assert coche[arg] == servidor[arg], f"'{verbo}.{arg}': coche {coche[arg]} != backend {servidor[arg]}"


@pytest.mark.parametrize("verbo", sorted(COMMANDS))
def test_el_modo_exigido_es_el_mismo(backend, verbo):
  esperado = MODE_WIRE_NAMES[COMMANDS[verbo].mode_min]
  declarado = backend["verbs"][verbo]["mode"]
  assert declarado == esperado, (
    f"'{verbo}': el coche exige modo '{esperado}' y el backend declara '{declarado}': el sobre saldria mal")


@pytest.mark.parametrize("verbo", sorted(COMMANDS))
def test_el_ttl_es_el_mismo(backend, verbo):
  """El coche RECORTA el ttl del sobre al de su catalogo (nunca lo amplia). Un backend
  con un TTL mas largo no es peligroso, pero le dice al usuario que su orden vale mas
  tiempo del que vale: la app calcula con el suyo cuando dar por perdida una orden."""
  coche = COMMANDS[verbo].ttl_ms
  servidor = backend["verbs"][verbo]["ttl_ms"]
  assert isinstance(servidor, int) and servidor > 0, f"'{verbo}': ttl_ms del backend invalido"
  if coche is None:
    return    # solo disarm_all: no tiene TTL en el coche (se ejecuta siempre)
  assert servidor == coche, f"'{verbo}': ttl_ms coche {coche} != backend {servidor}"


# ----------------------------------------------------------------- alias legacy

def test_los_alias_del_backend_apuntan_a_argumentos_que_existen(backend):
  """Los alias son la rampa de migracion de los nombres viejos. Uno que apunte a un
  argumento inexistente no traduce nada: vuelve el fallo original."""
  for verbo, alias in backend["alias"].items():
    bspec = backend["verbs"].get(verbo)
    assert bspec is not None, f"alias para un verbo que ya no existe: '{verbo}'"
    for viejo, canonico in alias.items():
      assert canonico in bspec["args"], f"alias '{verbo}.{viejo}' -> '{canonico}', que no es un argumento"
      assert viejo not in bspec["args"], (
        f"'{verbo}.{viejo}' es a la vez alias y argumento real: la traduccion se pisaria a si misma")


def test_ningun_alias_viaja_al_coche(backend):
  """Los nombres viejos mueren en el backend. Si alguno fuera ademas un nombre canonico
  de otro verbo, el coche lo veria y lo rechazaria con TYPE."""
  canonicos = {arg for spec in COMMANDS.values() for arg in spec.args_schema}
  viejos = {viejo for alias in backend["alias"].values() for viejo in alias}
  colision = sorted(viejos & canonicos)
  # `value` es nombre canonico de physical_control y alias viejo de steering_pulse: son
  # verbos distintos, asi que la traduccion (que es POR VERBO) no las confunde.
  assert colision == ["value"], f"alias que colisionan con nombres canonicos: {colision}"


# ------------------------------------------------------------------ modo banco

def test_el_modo_banco_no_se_puede_pedir_por_mando(backend):
  """Subir a banco es subir a la autoridad fisica y solo se hace con armado FISICO en la
  pantalla del comma (seccion 4.1). Si 'banco' apareciera entre las opciones de set_mode,
  un mensaje MQTT abriria el modo de torque_mode, steering_pulse y physical_control."""
  opciones = COMMANDS["set_mode"].args_schema["target_mode"].opciones
  assert "banco" not in opciones and "bench" not in opciones
  assert list(backend["verbs"]["set_mode"]["args"]["target_mode"]["values"]) == list(opciones)
