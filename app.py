import asyncio
import os
import logging
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import requests
import json

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

# Función para llamar a la API de Hyperliquid
def fetch_info(type_, **kwargs):
    url = "https://api.hyperliquid.xyz/info"
    data = {"type": type_, **kwargs}
    if type_ == "leaderboard":
        data["timeframe"] = "1d"  # Agregar timeframe para leaderboard
    logger.info(f"Llamando API con type={type_}, kwargs={data}")
    response = requests.post(url, json=data)
    response.raise_for_status()
    logger.info(f"Respuesta API: {response.json()}")
    return response.json()

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
        prices = fetch_info("allMids")
        leaderboard_data = fetch_info("leaderboard")
        users = [u["user"] for u in leaderboard_data.get("leaderboard", [])][:50]
        
        long_total = 0.0
        short_total = 0.0
        total_ntl = 0.0
        
        for user in users:
            state = fetch_info("userState", user=user)
            for pos in state.get("assetPositions", []):
                coin = pos["coin"]
                szi_str = pos["szi"]
                szi = float(szi_str) if szi_str else 0.0
                px = float(prices.get(coin, 0))
                if px == 0:
                    continue
                ntl = abs(szi) * px
                if szi > 0:
                    long_total += ntl
                else:
                    short_total += ntl
                total_ntl += ntl
        
        if total_ntl == 0:
            bias = 0.0
        else:
            bias = ((long_total - short_total) / total_ntl) * 100
        
        text = f"""📊 **Analytics de Hyperliquid (Top Traders)**

**TOTAL NOTIONAL:** ${long_total + short_total:,.0f}
**LONG POSITIONS:** ${long_total:,.0f}
**SHORT POSITIONS:** ${short_total:,.0f}
**GLOBAL BIAS:** {bias:.1f}% (Long Bias)

*Datos agregados de los top traders en leaderboard.*"""
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Error en /analytics: {str(e)}")
        await update.message.reply_text(f"Error al obtener analytics: {str(e)}")

# Handler para /top20
async def top20(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Procesando comando /top20")
    try:
        prices = fetch_info("allMids")
        leaderboard_data = fetch_info("leaderboard")
        top_users = leaderboard_data.get("leaderboard", [])[:10]  # Reducido a 10 para evitar rate limits
        
        lines = []
        for i, u in enumerate(top_users, 1):
            state = fetch_info("userState", user=u["user"])
            max_ntl = 0.0
            main_coin = ""
            direction = ""
            for pos in state.get("assetPositions", []):
                coin = pos["coin"]
                szi_str = pos["szi"]
                szi = float(szi_str) if szi_str else 0.0
                px = float(prices.get(coin, 0))
                if px == 0:
                    continue
                ntl = abs(szi) * px
                if ntl > max_ntl:
                    max_ntl = ntl
                    main_coin = coin
                    direction = "Long" if szi > 0 else "Short"
            if max_ntl > 0:
                size_m = max_ntl / 1_000_000
                lines.append(f"{i}. {size_m:.0f}M {direction} {main_coin}")
            else:
                lines.append(f"{i}. Sin posiciones abiertas")
        
        text = f"""🏆 **Top 10 Posiciones Principales (de Top Traders)**

{chr(10).join(lines)}

*Posición principal por trader (mayor notional). Datos de Hyperliquid API.*"""
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
