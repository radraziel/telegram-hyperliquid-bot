import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import requests
import json

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=10)

# Token del bot (de ambiente)
TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN no configurado")

# Crear aplicación de Telegram
application = Application.builder().token(TOKEN).build()

# Función para llamar a la API de Hyperliquid
def fetch_info(type_, **kwargs):
    url = "https://api.hyperliquid.xyz/info"
    data = {"type": type_, **kwargs}
    response = requests.post(url, json=data)
    response.raise_for_status()
    return response.json()

# Handler para /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "¡Bot iniciado correctamente!\n\nComandos disponibles:\n"
        "/start - Muestra este mensaje\n"
        "/analytics - Obtiene TOTAL NOTIONAL, LONG POSITIONS, SHORT POSITIONS y GLOBAL BIAS\n"
        "/top20 - Obtiene el top 20 de posiciones principales (tamaño, long/short, crypto)"
    )

# Handler para /analytics
async def analytics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        # Obtener precios
        prices = fetch_info("allMids")
        
        # Obtener leaderboard (asumimos estructura {"leaderboard": [{"user": "0x...", ...}, ...]})
        leaderboard_data = fetch_info("leaderboard")
        users = [u["user"] for u in leaderboard_data.get("leaderboard", [])][:50]  # Top 50 para eficiencia
        
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
        await update.message.reply_text(f"Error al obtener analytics: {str(e)}")

# Handler para /top20
async def top20(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        # Obtener precios
        prices = fetch_info("allMids")
        
        # Obtener leaderboard
        leaderboard_data = fetch_info("leaderboard")
        top_users = leaderboard_data.get("leaderboard", [])[:20]
        
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
                size_m = max_ntl / 1_000_000  # En millones
                lines.append(f"{i}. {size_m:.0f}M {direction} {main_coin}")
            else:
                lines.append(f"{i}. Sin posiciones abiertas")
        
        text = f"""🏆 **Top 20 Posiciones Principales (de Top Traders)**

{chr(10).join(lines)}

*Posición principal por trader (mayor notional). Datos de Hyperliquid API.*"""
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Error al obtener top20: {str(e)}")

# Agregar handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("analytics", analytics))
application.add_handler(CommandHandler("top20", top20))

# Ruta para webhook de Telegram
@app.route('/webhook', methods=['POST'])
def webhook():
    json_data = request.get_json()
    update = Update.de_json(json_data, application.bot)
    if update:
        def process_sync():
            asyncio.run(application.process_update(update))
        executor.submit(process_sync)
    return 'OK'

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    if hostname:
        webhook_url = f"https://{hostname}/webhook"
        # Configurar webhook al iniciar
        application.bot.set_webhook(url=webhook_url)
        print(f"Webhook configurado en: {webhook_url}")
    
    app.run(host='0.0.0.0', port=port, debug=False)
