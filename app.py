import asyncio
import os
import logging
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import requests
import json
import time

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=10)

# Token del bot (de ambiente)
TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN no configurado")

# Crear aplicación de Telegram y loop global
application = None
loop = None  # Loop global para manejar coroutines

# Headers para Hyperliquid API
HEADERS = {
    'accept': '*/*',
    'content-type': 'application/json',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
}

# Función para llamar a la API de Hyperliquid
def fetch_hyperliquid(type_, **kwargs):
    url = "https://api.hyperliquid.xyz/info"
    data = {"type": type_, **kwargs}
    if type_ == "leaderboard":
        data["sortBy"] = "pnl"  # Para top traders
    logger.info(f"Llamando Hyperliquid API con payload: {data}")
    response = requests.post(url, headers=HEADERS, json=data)
    logger.info(f"Status Code: {response.status_code}")
    logger.info(f"Response Headers: {dict(response.headers)}")
    response.raise_for_status()
    data = response.json()
    logger.info(f"Respuesta Hyperliquid: {data}")
    time.sleep(0.5)  # Evitar rate limits
    return data

# Error handler para Telegram
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Error en bot: {context.error}")
    if update and hasattr(update, 'effective_message') and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Ocurrió un error interno. Intenta de nuevo."
            )
        except Exception as e:
            logger.error(f"No se pudo enviar mensaje de error: {e}")

# Handler para /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Procesando comando /start")
    await update.message.reply_text(
        "¡Bot iniciado correctamente!\n\nComandos disponibles:\n"
        "/start - Muestra este mensaje\n"
        "/analytics - Obtiene TOTAL NOTIONAL, LONG POSITIONS, SHORT POSITIONS y GLOBAL BIAS\n"
        "/top20 - Obtiene el top 20 de posiciones principales (tamaño, long/short, crypto)"
    )

# Handler para /analytics
async def analytics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Procesando comando /analytics")
    try:
        # Usamos openInterest para obtener datos agregados
        summary_data = fetch_hyperliquid("openInterest")
        
        # Procesar datos (ajusta según estructura real del JSON)
        total_notional = summary_data.get('totalNotional', 'N/A')
        long_positions = summary_data.get('longNotional', 'N/A')
        short_positions = summary_data.get('shortNotional', 'N/A')
        global_bias = summary_data.get('bias', 'N/A')  # O calcula: long/(long+short)
        
        text = f"""📊 **Analytics de Hyperliquid**

**TOTAL NOTIONAL:** {total_notional}
**LONG POSITIONS:** {long_positions}
**SHORT POSITIONS:** {short_positions}
**GLOBAL BIAS:** {global_bias}

*Datos de Hyperliquid API.*"""
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Error en /analytics: {str(e)}")
        await update.message.reply_text(f"Error al obtener analytics: {str(e)}")

# Handler para /top20
async def top20(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Procesando comando /top20")
    try:
        leaderboard_data = fetch_hyperliquid("leaderboard")
        
        top_users = leaderboard_data[:20]  # Primeros 20 traders
        lines = []
        for i, trader in enumerate(top_users, 1):
            # Ajusta según estructura real (ejemplo basado en docs)
            size = trader.get('size', 'N/A')
            is_long = trader.get('isLong', True)  # True = Long, False = Short
            direction = "LONG" if is_long else "SHORT"
            coin = trader.get('coin', 'N/A')
            lines.append(f"{i}. {size} {direction} {coin}")
        
        text = f"""🏆 **Top 20 Posiciones Principales**

{chr(10).join(lines)}

*Datos de Hyperliquid API.*"""
        logger.info("Enviando respuesta de /top20")
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Error en /top20: {str(e)}")
        await update.message.reply_text(f"Error al obtener top20: {str(e)}")

# Agregar handlers
async def setup_application():
    global application, loop
    loop = asyncio.new_event_loop()  # Crear loop global
    asyncio.set_event_loop(loop)
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("analytics", analytics))
    application.add_handler(CommandHandler("top20", top20))
    application.add_error_handler(error_handler)
    await application.initialize()

# Ruta para webhook de Telegram
@app.route('/webhook', methods=['POST'])
def webhook():
    logger.info("Recibida solicitud en /webhook")
    json_data = request.get_json()
    update = Update.de_json(json_data, application.bot)
    if update:
        logger.info(f"Procesando update: {update.update_id}")
        # Ejecutar coroutine en el loop global
        future = asyncio.run_coroutine_threadsafe(
            application.process_update(update), loop
        )
        try:
            future.result(timeout=10)  # Esperar hasta 10 segundos
        except Exception as e:
            logger.error(f"Error procesando update: {str(e)}")
    else:
        logger.warning("No se pudo parsear el update")
    return 'OK'

# Configurar aplicación y webhook
async def main():
    await setup_application()
    port = int(os.environ.get('PORT', 5000))
    hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    if hostname:
        webhook_url = f"https://{hostname}/webhook"
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook configurado en: {webhook_url}")
    # Ejecutar Flask en el loop global
    loop.run_in_executor(None, lambda: app.run(host='0.0.0.0', port=port, debug=False))
    loop.run_forever()  # Mantener el loop activo

if __name__ == '__main__':
    asyncio.run(main())
