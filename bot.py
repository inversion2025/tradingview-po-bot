# bot.py
from flask import Flask, request, jsonify
import requests
import json
import time

app = Flask(__name__)

# --- CONFIGURACIÓN DE POCKET OPTION ---
# ¡MUY IMPORTANTE! Necesitas tu ID de sesión de Pocket Option (SSID).
# Este es un dato SENSIBLE. NO lo compartas con nadie.
# Debes obtenerlo de tu navegador (F12, pestaña Application/Almacenamiento, Cookies, buscar 'ssid').
# Reemplaza 'TU_PO_SSID_AQUI' con tu ID de sesión real y actual.
PO_SSID = "d93a33d0b4f1c69104066f79302678ae"

# Configuración de la cuenta (DEMO o REAL)
# Para pruebas, siempre usa "PRACTICE". Para real, usa "REAL".
PO_ACCOUNT_TYPE = "PRACTICE" 

# URL base para las operaciones de Pocket Option (puede variar si la API de PO cambia)
# Esta URL y los payloads son basados en observaciones de la API interna de PO y podrían necesitar ajustes futuros.
PO_API_BASE_URL = "https://po.trade/api"

# --- CONFIGURACIÓN DE LA ESTRATEGIA (Martingala) ---
# Estos deben coincidir con los valores de tu Pine Script
LEVELS = {
    "1.0": 1.0,  # Nivel 1
    "3.0": 3.0,  # Nivel 2
    "7.0": 7.0,  # Nivel 3
    "16.0": 16.0, # Nivel 4
    "35.0": 35.0  # Nivel 5
}

# --- FUNCIÓN PARA ENVIAR OPERACIONES A POCKET OPTION ---
def send_po_trade(asset_id, amount, trade_type, duration):
    """
    Envía una operación de trading a Pocket Option.
    :param asset_id: ID del activo (ej. "EURUSD").
    :param amount: Monto de la operación en USD.
    :param trade_type: "call" (compra/sube) o "put" (venta/baja).
    :param duration: Duración de la operación en segundos (ej. 60 para 1 minuto).
    """
    if not PO_SSID or PO_SSID == "TU_PO_SSID_AQUI":
        print("ERROR: SSID de Pocket Option no configurado. ¡Operación cancelada!")
        return {"status": "error", "message": "SSID no configurado"}

    # Encabezados de la solicitud, incluyendo el SSID
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Cookie": f"ssid={PO_SSID}" # El SSID se envía como una cookie
    }

    # Cargar los IDs de los activos (esto DEBERÍA hacerse una vez y guardarse)
    # Por simplicidad, aquí haremos una solicitud para obtener los IDs de activos activos.
    # En un bot real, esto se cargaría al inicio y se actualizaría ocasionalmente.
    try:
        assets_response = requests.get(f"{PO_API_BASE_URL}/spot/instruments", headers=headers, timeout=10)
        assets_response.raise_for_status() # Lanza un error para códigos de estado HTTP malos (4xx o 5xx)
        assets_data = assets_response.json()
        
        instrument_id = None
        for asset in assets_data.get('instruments', []):
            if asset.get('name') == asset_id:
                instrument_id = asset.get('id')
                break
        
        if instrument_id is None:
            print(f"ERROR: Activo '{asset_id}' no encontrado o no activo en Pocket Option.")
            return {"status": "error", "message": f"Activo '{asset_id}' no disponible"}

    except requests.exceptions.RequestException as e:
        print(f"ERROR al obtener lista de activos: {e}")
        return {"status": "error", "message": f"Error al obtener activos: {e}"}
    except Exception as e:
        print(f"ERROR inesperado al procesar activos: {e}")
        return {"status": "error", "message": f"Error inesperado al procesar activos: {e}"}

    # Payload para la operación
    # La API de Pocket Option usa 'up' para 'call' (sube) y 'down' para 'put' (baja).
    direction = "up" if trade_type == "BUY" else "down"

    payload = {
        "instrument_id": instrument_id,
        "period": duration, # Duración en segundos
        "amount": amount,
        "type": "binary", # Tipo de operación (binary, turbo, etc.)
        "direction": direction,
        "balance_type": 1 if PO_ACCOUNT_TYPE == "PRACTICE" else 2 # 1 para demo, 2 para real
    }

    print(f"Payload a enviar: {payload}")

    try:
        response = requests.post(f"{PO_API_BASE_URL}/trading/open-trade", headers=headers, json=payload, timeout=10)
        response.raise_for_status() # Lanza un error para códigos de estado HTTP malos (4xx o 5xx)
        response_data = response.json()
        print(f"Respuesta de Pocket Option: {response_data}")

        if response_data.get("status") == "success":
            print(f"Operación {trade_type} de ${amount} enviada exitosamente para {asset_id}!")
            return {"status": "success", "message": "Operación enviada", "response": response_data}
        else:
            error_message = response_data.get("message", "Error desconocido al abrir operación")
            print(f"ERROR en respuesta de PO: {error_message}")
            return {"status": "error", "message": error_message, "response": response_data}

    except requests.exceptions.RequestException as e:
        print(f"ERROR de red/API al enviar operación: {e}")
        return {"status": "error", "message": f"Error de red/API: {e}"}
    except Exception as e:
        print(f"ERROR inesperado al enviar operación: {e}")
        return {"status": "error", "message": f"Error inesperado: {e}"}

# --- RUTA PARA RECIBIR WEBHOOKS DE TRADINGVIEW ---
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        try:
            data = request.json
            if not data:
                print("Webhook recibido, pero sin datos JSON.")
                return jsonify({"status": "error", "message": "No se recibieron datos JSON"}), 400

            print(f"Webhook recibido de TradingView: {data}")

            alert_message = data.get('alert_message')
            if not alert_message:
                print("Error: Mensaje de alerta 'alert_message' no encontrado en el webhook.")
                return jsonify({"status": "error", "message": "Mensaje de alerta no encontrado"}), 400

            parts = alert_message.split(',')
            trade_type = None
            trade_amount = None
            asset_symbol = "EURUSD" # Por defecto, puedes hacer esto configurable desde TradingView

            for part in parts:
                if part.startswith("TYPE:"):
                    trade_type = part.split(':')[1].strip().upper() # Asegurar mayúsculas
                elif part.startswith("AMOUNT:"):
                    trade_amount = float(part.split(':')[1].strip())
                elif part.startswith("ASSET:"): # Opcional: si quieres pasar el activo desde TradingView
                    asset_symbol = part.split(':')[1].strip().upper()

            if not trade_type or trade_amount is None:
                print(f"Error: Formato de mensaje de alerta inválido: {alert_message}")
                return jsonify({"status": "error", "message": "Formato de mensaje de alerta inválido"}), 400

            print(f"Señal detectada: Tipo={trade_type}, Monto={trade_amount}, Activo={asset_symbol}")

            # Aquí se envía la operación a Pocket Option
            # Duración de 60 segundos (1 minuto)
            trade_result = send_po_trade(asset_symbol, trade_amount, trade_type, 60) 
            
            if trade_result["status"] == "success":
                return jsonify({"status": "success", "message": trade_result["message"]}), 200
            else:
                return jsonify({"status": "error", "message": trade_result["message"]}), 500

        except Exception as e:
            print(f"Error procesando webhook: {e}")
            return jsonify({"status": "error", "message": f"Error interno del servidor: {e}"}), 500
    return jsonify({"status": "error", "message": "Método no permitido"}), 405

if __name__ == '__main__':
    print("Iniciando servidor Flask para recibir señales de TradingView...")
    print(f"Escuchando en http://127.0.0.1:5000/webhook (usar ngrok para exponer)")
    # app.run(debug=True, host='0.0.0.0', port=5000) # Usar debug=True para desarrollo, apagar en producción
    app.run(host='0.0.0.0', port=5000)