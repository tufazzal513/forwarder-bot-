import os
import logging
import asyncio
from aiohttp import web
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO)

# Environment Variables
BOT_TOKEN = os.getenv("BACKUP_BOT_TOKEN")
MAIN_CHANNEL_ID = int(os.getenv("MAIN_CHANNEL_ID"))
BACKUP_CHANNEL_ID = int(os.getenv("BACKUP_CHANNEL_ID"))
PORT = int(os.getenv("PORT", 10000))

async def auto_copy_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.chat_id == MAIN_CHANNEL_ID:
        try:
            msg = update.channel_post
            msg_id = msg.message_id
            
            # অরিজিনাল ফাইল নেম বের করা
            raw_filename = None
            if msg.video and msg.video.file_name:
                raw_filename = msg.video.file_name
            elif msg.document and msg.document.file_name:
                raw_filename = msg.document.file_name
            elif msg.audio and msg.audio.file_name:
                raw_filename = msg.audio.file_name

            original_caption = msg.caption or ""
            
            if raw_filename:
                if original_caption:
                    new_caption = f"{original_caption}\n\n📁 File Name: {raw_filename}"
                else:
                    new_caption = f"📁 File Name: {raw_filename}"
            else:
                new_caption = original_caption

            await context.bot.copy_message(
                chat_id=BACKUP_CHANNEL_ID,
                from_chat_id=MAIN_CHANNEL_ID,
                message_id=msg_id,
                caption=new_caption if new_caption else None
            )
            logging.info(f"Successfully copied message {msg_id} with file name: {raw_filename}")
        except Exception as e:
            logging.error(f"Error copying message: {e}")

# 🚀 ব্যান্ডউইথ-ফ্রি ৩0২ রিডাইরেক্ট রুট (Render-এর ১ কেবি ব্যান্ডউইথও নষ্ট হবে না!)
async def stream_redirect(request):
    try:
        msg_id = request.match_info['msg_id']
        query = request.query_string
        target_url = f"https://onutilizir507-mp4video1.hf.space/stream/{msg_id}"
        if query:
            target_url += f"?{query}"
            
        # ইনস্ট্যান্ট রিডাইরেক্ট করে প্লে করার কমান্ড
        return web.HTTPFound(location=target_url)
    except Exception as e:
        logging.error(f"Redirect error: {e}")
        return web.Response(status=500, text="Redirect Connection Failed")

async def health_check(request):
    return web.Response(text="Auto Backup Bot & Bandwidth-Free Redirect are Active 24/7 on Render!")

async def main():
    ptb_app = ApplicationBuilder().token(BOT_TOKEN).build()
    ptb_app.add_handler(MessageHandler(filters.ALL, auto_copy_post))
    
    await ptb_app.initialize()
    await ptb_app.start()
    await ptb_app.updater.start_polling(drop_pending_updates=True)
    logging.info("Auto Copy Bot Started Successfully!")

    web_app = web.Application()
    web_app.router.add_get("/", health_check)
    # ৩0২ রিডাইরেক্ট রুট
    web_app.router.add_get("/stream/{msg_id}", stream_redirect)
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"Web Server Started on Port {PORT}!")

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
