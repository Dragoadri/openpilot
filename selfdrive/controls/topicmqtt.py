#!/usr/bin/env python3
import datetime
import time

import paho.mqtt.client as mqtt
import cereal.messaging as messaging

class TopicMqtt:

  def __init__(self):
    self.ultimo = time.time()
    try:
      broker_address = "195.235.211.197"
      #broker_address="mqtt.eclipseprojects.io"
      self.mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
      self.mqttc.connect(broker_address, 1883, 60)
    except Exception as e:
      print("Error en la conexion con el broker mqtt")
      print(e)

  def ping(self):
    f = open("./mqtt.txt", "a")
    f.write("Ping....\n")
    f.close()

  def setCanalControlsd(self, sn):
    self.sm = sn

  def loop(self):
    ahora=time.time()
    if ahora-self.ultimo > 1:
      infot = self.mqttc.publish("telemetry_mqtt/driver", str(self.sm['driverMonitoringState']), qos=0)
      self.mqttc.publish("telemetry_mqtt/deviceState", str(self.sm['deviceState']), qos=0)
      self.mqttc.publish("telemetry_mqtt/liveCalibration", str(self.sm['liveCalibration']), qos=0)
      self.mqttc.publish("telemetry_mqtt/longitudinalPlan", str(self.sm['longitudinalPlan']), qos=0)
      self.mqttc.publish("telemetry_mqtt/liveLocationKalman", str(self.sm['liveLocationKalman']), qos=0)
      self.mqttc.publish("telemetry_mqtt/liveParameters", str(self.sm['liveParameters']), qos=0)
      self.mqttc.publish("telemetry_mqtt/liveTorqueParameters", str(self.sm['liveTorqueParameters']), qos=0)
      self.mqttc.publish("telemetry_mqtt/longitudinalPlanSP", str(self.sm['longitudinalPlanSP']), qos=0)

      #infot = self.mqttc.publish("sicuem/gps", time.time(), qos=0)
      self.ultimo=time.time()

    self.mqttc.loop(0)
