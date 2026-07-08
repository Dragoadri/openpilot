#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de prueba para verificar que no hay errores de importación
"""
import sys
import os

# Agregar el directorio actual al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    print("🧪 Probando importaciones...")

    # Probar importación de mqtt_comandos
    from mqtt_comandos import MQTTComandos
    print("✅ MQTTComandos importado correctamente")

    # Probar importación de mqtt_envio_general
    from mqtt_envio_general import MQTTEnvioGeneral
    print("✅ MQTTEnvioGeneral importado correctamente")

    # Probar inicialización
    print("🧪 Probando inicialización...")
    comandos = MQTTComandos()
    print("✅ MQTTComandos inicializado correctamente")

    print("🎯 ¡Todas las importaciones funcionan correctamente!")

except ImportError as e:
    print(f"❌ Error de importación: {e}")
except Exception as e:
    print(f"❌ Error general: {e}")














