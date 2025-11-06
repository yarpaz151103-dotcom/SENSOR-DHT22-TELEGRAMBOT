import time, network                      # time: pausas y tiempos | network: Wi-Fi
from machine import Pin, PWM              # Pin/PWM: manejo de pines y del buzzer por PWM
import dht, webserver, telegram_bot       # dht: sensor DHT22 | webserver: página | telegram_bot: bot

# ===== CONFIGURACIÓN BÁSICA =====
SSID, PASSWORD = "YRPZ", "3154901967"     # Nombre y clave del Wi-Fi
TOKEN, CHAT_ID = "8418846145:AAGI7-ENPVuAeHearVi8IOZ9HM2wFUPO4MQ", 5280862706  # Bot y chat de Telegram
PIN_DHT, PIN_BUZ, PIN_BTN = 4, 18, 15     # Pines: DHT22 (GPIO4), Buzzer (GPIO18), Botón (GPIO15)
T_UM, H_UM = 29.0, 70.0                   # Umbrales: temperatura y humedad
ANTI_SPAM, LOOP_DT = 20, 0.05             # Anti-spam (seg) para Telegram y tiempo de ciclo (seg)

# ===== FUNCIÓN Wi-Fi =====
def wifi(ssid, pwd=None, tmo=20, tries=3):         # tmo: tiempo máximo por intento | tries: reintentos
    w = network.WLAN(network.STA_IF); w.active(True)  # Modo estación (cliente) y activar Wi-Fi
    for _ in range(tries):                            # Hacer varios intentos
        try:
            w.connect(ssid, pwd) if pwd else w.connect(ssid)  # Conectar (con o sin clave)
            t0=time.time()                                   # Momento de inicio del intento
            while not w.isconnected() and time.time()-t0<tmo:  # Esperar conexión o timeout
                time.sleep(1)                                 # Dormir 1 s por vuelta
            if w.isconnected():                               # Si conectó…
                ip=w.ifconfig()[0]                            # Tomar IP asignada
                print("✅ IP:",ip); return ip                 # Mostrar y devolver IP
        except: pass                                          # Ignorar errores puntuales
        try:w.disconnect()                                    # Desconectar por si quedó colgado
        except:pass
        time.sleep(2)                                         # Esperar 2 s y reintentar
    raise SystemExit("❌ Sin Wi-Fi")                           # Si no pudo, terminar programa

# ===== HARDWARE =====
dht22 = dht.DHT22(Pin(PIN_DHT))                # Crear objeto del sensor DHT22
buz   = PWM(Pin(PIN_BUZ)); buz.duty(0)         # Buzzer por PWM; duty=0 lo apaga
btn   = Pin(PIN_BTN, Pin.IN, Pin.PULL_UP)      # Botón como entrada con resistencia pull-up

def buzz(freq=0, duty=0):                      # Función para controlar el buzzer
    if duty<=0: buz.duty(0); return            # Si duty <= 0, apagar y salir
    buz.freq(int(freq)); buz.duty(int(duty))   # Si no, poner frecuencia y potencia

# ===== ESTADO COMPARTIDO (para web y bot) =====
state = dict(
    ip="0.0.0.0",            # IP local del ESP
    temp=None, hum=None,     # Lecturas actuales (None hasta medir)
    t_umbral=T_UM, h_umbral=H_UM,     # Umbrales actuales
    alarma_temp=False, alarma_hum=False, alarma_both=False,  # Flags de alarmas
    silenciado=False, panic=False,     # Silencio (buzzer) y pánico
    ts=0                      # Timestamp de última lectura
)

# Registro para anti-spam de Telegram (última vez que se envió cada mensaje)
last = dict(temp=0, hum=0, ok=0, panic=0, both=0)

# ===== ARRANQUE =====
state["ip"]=wifi(SSID, PASSWORD)                         # Conectar Wi-Fi y guardar IP
bot = telegram_bot.TelegramBot(TOKEN, CHAT_ID, state);   # Crear bot de Telegram
bot.start()                                              # Iniciar escucha de comandos
bot.send("ESP32+conectado+IP:+{}".format(state["ip"]))   # Mensaje de bienvenida
bot.send("🤖 Bot listo. Usa /help")
webserver.start(                                         # Levantar página web (puerto 80)
    state,
    on_silence=lambda: buzz(0,0),                        # Si silencian desde la web → apagar buzzer
    on_reactivate=lambda: None                           # (reservado para futuras acciones)
)
print("Monitoreando…")                                   # Aviso por consola

# ===== BUCLE PRINCIPAL =====
prev_btn=1                                               # Guardar estado previo del botón
while True:
    try:
        # --- Botón → pánico (flanco de bajada) ---
        val=btn.value()                                  # Leer botón (1 = suelto, 0 = presionado)
        if prev_btn==1 and val==0 and not state["panic"]:  # Si se presionó y no había pánico…
            state["panic"]=True                          # Activar modo pánico
            for _ in range(2):                           # Confirmación: 2 beeps rápidos
                buzz(1800,700); time.sleep(0.12); buzz(0,0); time.sleep(0.08)
            if time.time()-last["panic"]>ANTI_SPAM:      # Anti-spam para Telegram
                bot.send("🚨 Botón+de+pánico+ACTIVADO"); last["panic"]=time.time()
        prev_btn=val                                     # Actualizar estado del botón

        # --- Sensor (leer DHT22) ---
        dht22.measure()                                  # Tomar muestra
        t,h=dht22.temperature(), dht22.humidity()        # Obtener temperatura y humedad
        state.update(temp=t, hum=h, ts=int(time.time())) # Guardar en el estado (lo usa la web/bot)

        # --- Umbrales (definir alarmas) ---
        at = (t is not None and t>state["t_umbral"])     # ¿Temp sobre umbral?
        ah = (h is not None and h>state["h_umbral"])     # ¿Hum sobre umbral?
        state["alarma_both"]= at and ah                  # Ambas altas
        state["alarma_temp"]= at and not ah              # Solo temperatura alta
        state["alarma_hum"] = ah and not at              # Solo humedad alta

        # --- Sonido (buzzer) ---
        if state["panic"]:                               # Si hay pánico: sirena que sube/baja
            if not state["silenciado"]:                  # Excepto si está silenciado
                k=(time.ticks_ms()//120)%16              # Fase (0..15) según reloj interno
                f=500+(k if k<8 else 15-k)*125           # 500→1375→500 Hz (ciclo)
                buzz(f,600)                              # Tocar sirena
            else:
                buzz(0,0)                                # Silenciado → buzzer apagado
        else:                                            # Sin pánico: tonos por tipo de alarma
            if state["silenciado"]:
                buzz(0,0)                                # Silenciado total
            elif state["alarma_both"]:
                buzz(500,600); time.sleep(1.2); buzz(0,0)  # Alerta general: tono grave sostenido
            elif state["alarma_temp"]:
                [ (buzz(900,600), time.sleep(0.2), buzz(0,0), time.sleep(0.1)) for _ in range(2) ]  # 2 beeps medios
            elif state["alarma_hum"] :
                [ (buzz(1600,600), time.sleep(0.1), buzz(0,0), time.sleep(0.05)) for _ in range(3) ] # 3 beeps agudos cortos
            else:
                buzz(0,0)                                # Todo normal → silencio

        # --- Mensajes automáticos a Telegram (con anti-spam) ---
        now=time.time()
        if not state["panic"]:                           # No enviar si hay pánico activo
            if at and ah and now-last["both"]>ANTI_SPAM: # Prioriza ALERTA GENERAL
                bot.send("🚨 ALERTA+GENERAL:+Temp+{:.1f}°C+y+Hum+{:.1f}%".format(t,h)); last["both"]=now
            elif at and now-last["temp"]>ANTI_SPAM:
                bot.send("⚠️ Temp+alta:+{:.1f}°C".format(t)); last["temp"]=now
            elif ah and now-last["hum"]>ANTI_SPAM:
                bot.send("⚠️ Humedad+alta:+{:.1f}%".format(h)); last["hum"]=now
            elif (not at and not ah) and now-last["ok"]>ANTI_SPAM:  # Mensaje de normalidad
                bot.send("✅ Normal:+{:.1f}°C,+{:.1f}%".format(t,h)); last["ok"]=now

        time.sleep(0.05)                                 # Pequeña pausa para no saturar CPU/red

    except Exception:                                    # Si algo falla (Wi-Fi, DHT, Telegram…)
        buzz(0,0); time.sleep(0.5)                       # Apagar buzzer y esperar 0.5 s para recuperarse
