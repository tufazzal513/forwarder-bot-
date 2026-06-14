import os
import json
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pyrogram import Client, filters
from pyrogram.types import Message
from google.cloud import firestore
from google.oauth2 import service_account

# ━━━━ Render Free Tier Port Binding Workaround ━━━━
# Render-এর ফ্রি টিয়ারে বট সচল রাখতে পোর্ট বাইন্ড করা অত্যন্ত জরুরি।
class HealthCheckHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Mirror Bot is Alive and Running!")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f"Health Check Server running on port {port}")
    server.serve_forever()

# ব্যাকগ্রাউন্ড থ্রেডে সার্ভারটি চালু করা হচ্ছে
threading.Thread(target=run_health_check_server, daemon=True).start()
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ১. টেলিগ্রাম এপিআই ও চ্যানেল কনফিগারেশন
API_ID = int(os.environ.get("API_ID", 1234567)) 
API_HASH = os.environ.get("API_HASH", "your_api_hash")

SESSION_STRING = os.environ.get("USER_SESSION", "") 
BOT_TOKEN = os.environ.get("BOT_TOKEN", "") 

SOURCE_CHANNEL = -1003962440092 # আপনার মূল মেইন লগ চ্যানেল আইডি
BACKUP_CHANNELS = [-1003984468691, -1003980607861] # আপনার ব্যাকআপ চ্যানেলগুলোর আইডি

# ২. ফায়ারবেস ক্লাউড ফায়ারস্টোর ইনিশিয়ালাইজেশন
db = None
creds_json = os.environ.get("FIREBASE_CREDENTIALS")
if creds_json:
    try:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(creds_dict)
        db = firestore.Client(credentials=creds)
        print("Successfully connected to Firebase Firestore from Python!")
    except Exception as e:
        print(f"Failed to initialize Firestore in Python: {e}")
else:
    print("Warning: FIREBASE_CREDENTIALS environment variable is empty. DB mapping is disabled.")

# ৩. ক্লায়েন্ট সেটআপ
if SESSION_STRING:
    app = Client("mirror_userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
else:
    app = Client("mirror_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ৪. নতুন মেসেজ মনিটরিং এবং ফায়ারবেস ম্যাপিং হ্যান্ডলার
@app.on_message(filters.chat(SOURCE_CHANNEL))
async def mirror_messages(client, message: Message):
    backup_mappings = {}

    # প্রথমে ব্যাকআপ চ্যানেলগুলোতে ফরোয়ার্ড ট্যাগ ছাড়া হুবহু ফাইল ও বাটন কপি করা হচ্ছে
    for target in BACKUP_CHANNELS:
        try:
            copied_msg = await message.copy(target)
            backup_mappings[str(target)] = copied_msg.id
            print(f"Copied message {message.id} to backup channel {target} (New Msg ID: {copied_msg.id})")
        except Exception as e:
            print(f"Failed to copy message {message.id} to backup channel {target}: {e}")

    # কপি সফল হলে ফায়ারবেসে ব্যাকআপ ম্যাপিং আপডেট করা হচ্ছে
    if db and len(backup_mappings) > 0:
        try:
            # মেইন মেসেজ আইডি কুয়েরি করে ওই ডকুমেন্টের ফেইলওভার ম্যাপ আপডেট করা হচ্ছে
            docs = db.collection("files").where("main_msg_id", "==", message.id).limit(1).stream()
            updated = False
            for doc in docs:
                doc.reference.update({
                    "backup_mappings": backup_mappings
                })
                print(f"Successfully mapped backup IDs in Firestore for main_msg_id {message.id}!")
                updated = True
            
            if not updated:
                print(f"Firestore warning: No document found with main_msg_id {message.id}")
        except Exception as e:
            print(f"Error updating Firestore backup mappings: {e}")

print("Dynamic Channel Mirroring CDN Bot is fully active!")
app.run()
