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

# Crear aplicación de Telegram
application = None

# Headers comunes para Hyperdash API
HEADERS = {
    'accept': '*/*',
    'accept-language': 'es-MX,es;q=0.9,en;q=0.8',
    'content-type': 'application/json',
    'referer': 'https://hyperdash.info/',
    'sec-ch-ua': '"Google Chrome";v="129", "Not?A_Brand";v="24", "Chromium";v="129"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
    'x-api-key': 'hyperdash_public_7vN3mK8pQ4wX2cL9hF5tR1bY6gS0jD'
}

# Función para llamar a la API de Hyperdash
def fetch_hyperdash(endpoint):
    url = f"https://hyperdash.info/api/hyperdash/{endpoint}"
    logger.info(f"Llamando Hyperdash API: {url}")
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    data = response.json()
    logger.info(f"Respuesta Hyperdash: {data}")
    return data

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
        summary_data = fetch_hyperdash("summary")
        
        # Asumiendo estructura del JSON; ajusta si es diferente
        total_notional = summary_data.get('totalNotional', 'N/A')
        long_positions = summary_data.get('longPositions', 'N/A')
        short_positions = summary_data.get('shortPositions', 'N/A')
        global_bias = summary_data.get('globalBias', 'N/A')
        
        text = f"""📊 **Analytics de Hyperliquid**

**TOTAL NOTIONAL:** {total_notional}
**LONG POSITIONS:** {long_positions}
**SHORT POSITIONS:** {short_positions}
**GLOBAL BIAS:** {global_bias}

*Datos de Hyperdash API.*"""
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Error en /analytics: {str(e)}")
        await update.message.reply_text(f"Error al obtener analytics: {str(e)}")

# Handler para /top20
async def top20(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Procesando comando /top20")
    try:
        top_traders_data = fetch_hyperdash("top-traders-cached")
        
        top_users = top_traders_data.get('traders', [])[:20]  # Asumiendo array 'traders'; ajusta si es diferente
        
        lines = []
        for i, trader in enumerate(top_users, 1):
            # Asumiendo estructura; ajusta según respuesta real
            main_position = trader.get('mainPosition', 'N/A')
            direction = trader.get('direction', '').upper()
            coin = trader.get('coin', 'N/A')
            lines.append(f"{i}. {main_position} {direction} {coin}")
        
        text = f"""🏆 **Top 20 Posiciones Principales (de Top Traders)**

{chr(10).join(lines)}

*Datos de Hyperdash API.*"""
        logger.info("Enviando respuesta de /top20")
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Error en /top20: {str(e)}")
        await update.message.reply_text(f"Error al obtener top20: {str(e)}")

# Agregar handlers
async def setup_application():
    global application
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("analytics", analytics))
    application.add_handler(CommandHandler("top20", top20))
    await application.initialize()

# Ruta para webhook de Telegram
@app.route('/webhook', methods=['POST'])
def webhook():
    logger.info("Recibida solicitud en /webhook")
    json_data = request.get_json()
    update = Update.de_json(json_data, application.bot)
    if update:
        logger.info(f"Procesando update: {update.update_id}")
        def process_sync():
            try:
                asyncio.run(application.process_update(update))
            except Exception as e:
                logger.error(f"Error procesando update: {str(e)}")
        executor.submit(process_sync)
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
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    asyncio.run(main())
