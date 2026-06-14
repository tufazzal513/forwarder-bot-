import os
import json
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pyrogram import Client, filters
from pyrogram.types import Message
from google.cloud import firestore
from google.oauth2 import service_account

# ━━━━ Render Free Tier Port Binding Workaround ━━━━
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

threading.Thread(target=run_health_check_server, daemon=True).start()
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ১. টেলিগ্রাম এপিআই ও মূল চ্যানেল কনফিগারেশন
API_ID = int(os.environ.get("API_ID", 1234567)) 
API_HASH = os.environ.get("API_HASH", "your_api_hash")

SESSION_STRING = os.environ.get("USER_SESSION", "") 
BOT_TOKEN = os.environ.get("BOT_TOKEN", "") 

SOURCE_CHANNEL = int(os.environ.get("SOURCE_CHANNEL", -1003962440092)) # আপনার মূল প্রধান লগ চ্যানেল আইডি

# ২. এনভায়রনমেন্ট ভেরিয়েবল "BACKUP_CHANNELS" থেকে আইডি রিড করার ডাইনামিক পার্সার
backup_channels_env = os.environ.get("BACKUP_CHANNELS", "")
BACKUP_CHANNELS = []
if backup_channels_env:
    for x in backup_channels_env.split(","):
        x = x.strip().replace('"', '').replace("'", "").replace("[", "").replace("]", "")
        if x:
            try:
                BACKUP_CHANNELS.append(int(x))
            except ValueError:
                print(f"Warning: Failed to parse backup channel ID '{x}' as integer")

print(f"Loaded SOURCE_CHANNEL: {SOURCE_CHANNEL}")
print(f"Loaded BACKUP_CHANNELS: {BACKUP_CHANNELS}")

# ৩. ফায়ারবেস ক্লাউড ফায়ারস্টোর ইনিশিয়ালাইজেশন
db = None
creds_json = os.environ.get("FIREBASE_CREDENTIALS")
if creds_json:
    try:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(creds_dict)
        db = firestore.Client(credentials=creds)
        print("Successfully connected to Firebase Firestore!")
    except Exception as e:
        print(f"Failed to initialize Firestore: {e}")
else:
    print("Warning: FIREBASE_CREDENTIALS environment variable is empty. DB mapping is disabled.")

# ৪. ক্লায়েন্ট সেটআপ
if SESSION_STRING:
    app = Client("mirror_userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
else:
    app = Client("mirror_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ৫. নতুন মেসেজ মনিটরিং এবং ফায়ারবেস ম্যাপিং হ্যান্ডলার
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


# ৬. মূল চ্যানেল থেকে মেসেজ ডিলিট হওয়া মাত্রই তা ব্যাকআপ চ্যানেল ও ডাটাবেস থেকে ডিলিট করার লজিক
@app.on_deleted_messages(filters.chat(SOURCE_CHANNEL))
async def on_deleted_messages(client, messages):
    for message in messages:
        deleted_msg_id = message.id
        print(f"Detected deletion of message {deleted_msg_id} in Main Channel.")

        if db:
            try:
                # Firestore থেকে মেইন মেসেজ আইডি কুয়েরি করে ওই মুভি ডকুমেন্টটি বের করা হচ্ছে
                docs = db.collection("files").where("main_msg_id", "==", deleted_msg_id).limit(1).stream()
                for doc in docs:
                    data = doc.to_dict()
                    backup_mappings = data.get("backup_mappings", {})
                    
                    # প্রতিটি ব্যাকআপ চ্যানেল থেকে মেসেজগুলো স্বয়ংক্রিয়ভাবে মুছে দেওয়া হচ্ছে
                    for ch_id_str, b_msg_id in backup_mappings.items():
                        ch_id = int(ch_id_str)
                        try:
                            await client.delete_messages(chat_id=ch_id, message_ids=b_msg_id)
                            print(f"Successfully deleted mirrored message {b_msg_id} in backup channel {ch_id}")
                        except Exception as e:
                            print(f"Failed to delete mirrored message in backup channel {ch_id}: {e}")
                    
                    # সবশেষে ফায়ারবেস ডাটাবেস থেকেও ডকুমেন্টটি রিমুভ করা হলো
                    doc.reference.delete()
                    print(f"Successfully deleted Firestore document for main_msg_id {deleted_msg_id}")
            except Exception as e:
                print(f"Error handling deleted messages in Firestore: {e}")

print("Dynamic Channel Mirroring CDN Bot is fully active!")
app.run()
