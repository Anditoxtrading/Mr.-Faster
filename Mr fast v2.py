import config
import time
from pybit.unified_trading import HTTP
from decimal import Decimal, ROUND_DOWN, ROUND_FLOOR
import threading
import telebot

session = HTTP(
    testnet=False,
    api_key=config.api_key,
    api_secret=config.api_secret,
)

# DEFINIR PARAMETROS PARA OPERAR
amount_usdt = Decimal(20) # Monto en USDT 
distancia_porcentaje_sl = Decimal( 1/ 100) # Stop loss a un 2%, puedes modificarlo segun tu gestion.
Numero_de_posiciones= 1  # Numero de posiciones que quieres permitir abrir de forma simultanea
posiciones_con_stop = {}
monedas_protegidas = set()  # guardar monedas operadas


bot_token = config.token_telegram
bot = telebot.TeleBot(bot_token)
chat_id = config.chat_id

def enviar_mensaje_telegram(chat_id, mensaje):
    try:
        bot.send_message(chat_id, mensaje, parse_mode='HTML')
    except Exception as e:
        print(f"No se pudo enviar el mensaje a Telegram: {e}")

def reiniciar_monedas_protegidas():
    global monedas_protegidas
    while True:
        time.sleep(43200)  # 12 horas = 43200 segundos
        monedas_protegidas.clear()
        mensaje=("🧹 Lista de monedas protegidas reiniciada")
        enviar_mensaje_telegram(chat_id=chat_id, mensaje=mensaje)
        print(mensaje)

def get_current_position(symbol):
    try:
        response_positions = session.get_positions(category="linear", symbol=symbol)
        if response_positions['retCode'] == 0:
            return response_positions['result']['list']
        else:
            print(f"Error al obtener la posición: {response_positions}")
            return None
    except Exception as e:
        print(f"Error al obtener la posición: {e}")
        return None


def get_open_positions_count():
    try:
        response_positions = session.get_positions(category="linear", settleCoin="USDT")
        if response_positions['retCode'] == 0:
            positions = response_positions['result']['list']
            open_positions = [position for position in positions if Decimal(position['size']) != 0]
            return len(open_positions)
        else:
            print(f"Error al obtener el conteo de posiciones abiertas: {response_positions}")
            return 0
    except Exception as e:
        print(f"Error al obtener el conteo de posiciones abiertas: {e}")
        return 0


def abrir_posicion_corto(symbol, base_asset_qty_final, distancia_porcentaje_sl):
    try:
        if get_open_positions_count() >= Numero_de_posiciones: 
            mensaje_count =("Se alcanzó el máximo posiciones abiertas. No se abrirá una nueva posición.")
            enviar_mensaje_telegram(chat_id=chat_id, mensaje=mensaje_count)
            print (mensaje_count)
            return

        positions_list = get_current_position(symbol)
        if positions_list and any(Decimal(position['size']) != 0 for position in positions_list):
            print("Ya hay una posición abierta. No se abrirá otra posición.")
            return

        response_market_order = session.place_order(
            category="linear",
            symbol=symbol,
            side="Sell",
            orderType="Market",
            qty=base_asset_qty_final,
        )
        time.sleep(1.5)
        # Añadir el símbolo a la lista protegida
        monedas_protegidas.add(symbol)
        if response_market_order['retCode'] != 0:
            print("Error al abrir la posición: La orden de mercado no se completó correctamente.")
            return

        positions_list = get_current_position(symbol)
        current_price = Decimal(positions_list[0]['avgPrice'])

        price_sl = adjust_price(symbol, current_price * Decimal(1 + distancia_porcentaje_sl))
        stop_loss_order = session.set_trading_stop(
            category="linear",
            symbol=symbol,
            stopLoss=price_sl,
            slTriggerBy="LastPrice",
            tpslMode="Full",
            slOrderType="Market",
        )
        Mensaje_market = (
            f"<b>🔴 ¡ORDEN SHORT ABIERTA!</b>\n"
            f"🔹 Ticker: <b>{symbol}</b>\n"
            f"Stop Loss colocado con éxito: {stop_loss_order}\n"
            f"✅ Estado: <i>Abierta con éxito</i>"
        )

        enviar_mensaje_telegram(chat_id=chat_id, mensaje=Mensaje_market)
        print(Mensaje_market)
    except Exception as e:
        print(f"Error al abrir la posición: {e}")

def qty_step(symbol, amount_usdt):
    try:
        tickers = session.get_tickers(symbol=symbol, category="linear")
        for ticker_data in tickers["result"]["list"]:
            last_price = float(ticker_data["lastPrice"])

        last_price_decimal = Decimal(last_price)

        step_info = session.get_instruments_info(category="linear", symbol=symbol)
        qty_step = Decimal(step_info['result']['list'][0]['lotSizeFilter']['qtyStep'])

        base_asset_qty = amount_usdt / last_price_decimal

        qty_step_str = str(qty_step)
        if '.' in qty_step_str:
            decimals = len(qty_step_str.split('.')[1])
            base_asset_qty_final = round(base_asset_qty, decimals)
        else:
            base_asset_qty_final = int(base_asset_qty)

        return base_asset_qty_final
    except Exception as e:
        print(f"Error al calcular la cantidad del activo base: {e}")
        return None

def adjust_price(symbol, price):
    try:
        instrument_info = session.get_instruments_info(category="linear", symbol=symbol)
        tick_size = float(instrument_info['result']['list'][0]['priceFilter']['tickSize'])
        price_scale = int(instrument_info['result']['list'][0]['priceScale'])

        tick_dec = Decimal(f"{tick_size}")
        precision = Decimal(f"{10**price_scale}")
        price_decimal = Decimal(f"{price}")
        adjusted_price = (price_decimal * precision) / precision
        adjusted_price = (adjusted_price / tick_dec).quantize(Decimal('1'), rounding=ROUND_FLOOR) * tick_dec

        return float(adjusted_price)
    except Exception as e:
        print(f"Error al ajustar el precio: {e}")
        return None


def monitorear_posiciones():
    # Niveles de avance en % y stops a proteger (todos como Decimal)
    niveles_avance = [Decimal("0.02"), Decimal("0.04"), Decimal("0.06"), Decimal("0.08"), Decimal("0.10"), Decimal("0.12"), Decimal("0.14"), Decimal("0.16"), Decimal("0.18"), Decimal("0.20")]
    stops_a_proteger = [Decimal("0.01"), Decimal("0.02"), Decimal("0.03"), Decimal("0.05"), Decimal("0.08"), Decimal("0.10"), Decimal("0.12"), Decimal("0.14"), Decimal("0.16"), Decimal("0.18")]

    while True:
        try:
            posiciones = session.get_positions(category="linear", settleCoin="USDT")
            for posicion in posiciones["result"]["list"]:
                size = Decimal(posicion["size"])
                if size == 0:
                    continue

                symbol = posicion["symbol"]
                side = posicion["side"]
                entry_price = Decimal(posicion["avgPrice"])

                # Obtener el precio actual
                tickers = session.get_tickers(symbol=symbol, category="linear")
                last_price = None
                for ticker_data in tickers["result"]["list"]:
                    if ticker_data["symbol"] == symbol:
                        last_price = Decimal(ticker_data["lastPrice"])
                        break
                if last_price is None:
                    continue

                # Calcular avance en porcentaje
                if side == "Buy":
                    avance_pct = (last_price - entry_price) / entry_price
                else:  # Short
                    avance_pct = (entry_price - last_price) / entry_price

                # Determinar stop a proteger
                stop_pct = Decimal("0")
                for idx, nivel in enumerate(niveles_avance):
                    if avance_pct < nivel:
                        stop_pct = stops_a_proteger[idx - 1] if idx > 0 else Decimal("0")
                        break
                else:
                    stop_pct = stops_a_proteger[-1]

                if stop_pct == Decimal("0"):
                    continue  # aún no se alcanza ningún nivel de protección

                # Evitar recolocar el mismo stop
                if symbol in posiciones_con_stop and posiciones_con_stop[symbol] >= stop_pct:
                    continue

                # Calcular precio del stop
                if side == "Buy":
                    stop_price = entry_price * (Decimal("1") + stop_pct)
                else:
                    stop_price = entry_price * (Decimal("1") - stop_pct)

                stop_price_ajustado = adjust_price(symbol, stop_price)

                # Cancelar stop anterior si existe
                try:
                    orders = session.get_open_orders(symbol=symbol, category="linear")
                    for order in orders["result"]["list"]:
                        if order["type"] == "STOP_MARKET":
                            session.cancel_order(symbol=symbol, orderId=order["orderId"], category="linear")
                except Exception as e:
                    print(f"Error al cancelar stop anterior para {symbol}: {e}")

                # Colocar nuevo stop
                stop_loss_order = session.set_trading_stop(
                    category="linear",
                    symbol=symbol,
                    stopLoss=str(stop_price_ajustado),
                    slTriggerBy="LastPrice",
                    tpslMode="Full",
                    slOrderType="Market",
                )

                mensaje = (
                    f"🛡️ Stop escalado en {symbol}: Avance {avance_pct*100:.2f}% → protegiendo {stop_pct*100:.2f}%\n"
                    f"Stop colocado en: {stop_price_ajustado}\n"
                    f"Resultado: {stop_loss_order}"
                )
                enviar_mensaje_telegram(chat_id=chat_id, mensaje=mensaje)
                print(mensaje)

                posiciones_con_stop[symbol] = stop_pct

        except Exception as e:
            print(f"Error al monitorear posiciones: {e}")

        time.sleep(5)

def notificar_pnl_cerrado():
    ultimo_order_id_reportado = None

    while True:
        try:
            response = session.get_closed_pnl(category="linear", limit=1)
            if response["retCode"] == 0 and response["result"]["list"]:
                ultimo_pnl = response["result"]["list"][0]
                order_id = ultimo_pnl["orderId"]

                if ultimo_order_id_reportado is None:
                    # Inicializamos la variable sin enviar mensaje,
                    # para ignorar el último PNL viejo al iniciar el bot
                    ultimo_order_id_reportado = order_id
                elif order_id != ultimo_order_id_reportado:
                    symbol = ultimo_pnl["symbol"]
                    closed_pnl = Decimal(ultimo_pnl["closedPnl"]).quantize(Decimal("0.01"))
                    side = ultimo_pnl["side"]
                    if closed_pnl >= 0:
                        posiciones_con_stop.clear()
                        mensaje = (
                            f"<b>✅ ¡Operación cerrada en ganancia!</b> 🎉💰\n"
                            f"Símbolo: <b>{symbol}</b>\n"
                            f"Lado: <b>{side}</b>\n"
                            f"PNL: <b>+{closed_pnl} USDT</b>"
                        )
                    else:
                        posiciones_con_stop.clear()
                        mensaje = (
                            f"<b>😢 Operación cerrada en pérdida</b> 😢💸\n"
                            f"Símbolo: <b>{symbol}</b>\n"
                            f"Lado: <b>{side}</b>\n"
                            f"PNL: <b>{closed_pnl} USDT</b>"
                        )

                    enviar_mensaje_telegram(chat_id=chat_id, mensaje=mensaje)
                    print(f"PNL notificado: {mensaje}")

                    ultimo_order_id_reportado = order_id

        except Exception as e:
            print(f"Error al obtener PNL cerrado: {e}")

        time.sleep(10)
def obtener_simbolos_volumen_minimo(volumen_minimo=100_000_000, precio_maximo=20):
    response = session.get_tickers(category="linear")
    simbolos_filtrados = []

    if response["retCode"] != 0:
        print("Error al obtener tickers:", response["retMsg"])
        return simbolos_filtrados

    for ticker in response["result"]["list"]:
        turnover_24h = float(ticker.get("turnover24h", "0"))
        last_price = float(ticker.get("lastPrice", "0"))
        simbolo = ticker["symbol"]

        if turnover_24h >= volumen_minimo and last_price <= precio_maximo:
            simbolos_filtrados.append(simbolo)

    return simbolos_filtrados


def obtener_precio_actual(symbol):
    response = session.get_tickers(category="linear", symbol=symbol)
    if response["retCode"] != 0 or not response["result"]["list"]:
        print(f"Error al obtener precio actual para {symbol}: {response['retMsg']}")
        return None

    return float(response["result"]["list"][0]["lastPrice"])
def calcular_porcentaje_subida(precio_antiguo, precio_actual):

    if precio_antiguo == 0:
        return 0
    return ((precio_actual - precio_antiguo) / precio_antiguo) * 100

precios_historicos = {}

def main():
    print("Bot iniciado. Monitoreando movimientos en futuros lineales con volumen > 100M USDT y precio <= 20 USDT...")

    while True:
        try:
            simbolos = obtener_simbolos_volumen_minimo()

            for symbol in simbolos:
                # 👇 Saltar monedas que ya están protegidas
                if symbol in monedas_protegidas:
                    continue

                precio_actual = obtener_precio_actual(symbol)
                if precio_actual is None:
                    continue

                if symbol in precios_historicos:
                    precio_anterior = precios_historicos[symbol]
                    pct_subida = calcular_porcentaje_subida(precio_anterior, precio_actual)

                    if pct_subida >= 2:
                        mensaje = (
                            f"🚨 ALERTA: {symbol} subió {pct_subida:.2f}% | "
                            f"Precio anterior: {precio_anterior} | Precio actual: {precio_actual}"
                        )
                        print(mensaje)

                        base_asset_qty_final = qty_step(symbol, amount_usdt)
                        if base_asset_qty_final is None:
                            print(f"No se pudo calcular la cantidad para {symbol}.")
                            continue

                        abrir_posicion_corto(symbol, base_asset_qty_final, distancia_porcentaje_sl)

                # Guardar/actualizar precio actual para la próxima vuelta
                precios_historicos[symbol] = precio_actual

            time.sleep(60)

        except Exception as e:
            print("⚠️ Error inesperado:", e)
            time.sleep(60)

if __name__ == "__main__":

    # Hilo para notificar PNL cuando se cierre una posición
    pnl_thread = threading.Thread(target=notificar_pnl_cerrado)
    pnl_thread.start()

    # Hilo para la función 'monitorear_posiciones' con el argumento necesario
    monitor_position_thread = threading.Thread(target=monitorear_posiciones)
    monitor_position_thread.start()

    # Lanzar la función de reinicio en otro hilo separado
    threading.Thread(target=reiniciar_monedas_protegidas, daemon=True).start()

    # Ejecutar el main loop
    main()
