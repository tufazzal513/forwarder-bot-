import os
import json
import asyncio
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

SOURCE_CHANNEL = int(os.environ.get("SOURCE_CHANNEL", -1003962440092)) 

# ২. এনভায়রনমেন্ট ভেরিয়েবল থেকে আইডি রিড করার ডাইনামিক পার্সার (উভয় বানানই সাপোর্ট করবে)
backup_channels_env = os.environ.get("BACKUP_CHANNELS")
if not backup_channels_env:
    backup_channels_env = os.environ.get("BACKUP_CHANNALS", "") # ভুল বানান থাকলেও ব্যাকআপ হিসেবে রিড করবে

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
creds_json = os.Getenv("FIREBASE_CREDENTIALS") if hasattr(os, "Getenv") else os.environ.get("FIREBASE_CREDENTIALS")
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

# ফাইলের সাইজ ফরম্যাটিং হেল্পার ফাংশন (টাইপ সেফ)
def format_size(bytes_size):
    try:
        bytes_size = int(bytes_size)
    except:
        return "Unknown"
    const_unit = 1024
    if bytes_size < const_unit:
        return f"{bytes_size} B"
    div, exp = const_unit, 0
    n = bytes_size // const_unit
    while n >= const_unit:
        div *= const_unit
        exp += 1
        n //= const_unit
    units = "KMGTPE"
    return f"{bytes_size / div:.2f} {units[exp]}B"

# ৪. ক্লায়েন্ট সেটআপ
if SESSION_STRING:
    app = Client("mirror_userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
else:
    app = Client("mirror_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ৫. নতুন মেসেজ মনিটরিং এবং ফায়ারবেস ম্যাপিং হ্যান্ডলার
@app.on_message(filters.chat(SOURCE_CHANNEL))
async def mirror_messages(client, message: Message):
    # যদি মেসেজটি সাধারণ টেক্সট হয় (যেমন: মেইন চ্যানেলে আসা বটের আলাদা ক্যাপশন মেসেজ), তবে তা স্কিপ করবে
    if not message.media:
        return

    # Go বটকে ফায়ারবেসে ডেটা সেভ করার জন্য ২ সেকেন্ড সময় দেওয়া হচ্ছে (Race Condition এড়াতে)
    await asyncio.sleep(2.0)

    backup_mappings = {}
    custom_caption = ""

    # ফায়ারবেস থেকে স্ট্রিমিং লিংক ও অন্যান্য তথ্য তুলে নিয়ে ক্যাপশন সাজানো হচ্ছে
    if db:
        try:
            docs = db.collection("files").where("main_msg_id", "==", message.id).limit(1).stream()
            for doc in docs:
                data = doc.to_dict()
                file_name = data.get("file_name", "Unknown")
                size_bytes = data.get("size", 0)
                link = data.get("link", "")
                file_id = data.get("file_id", "N/A")
                date_str = data.get("date", "")

                # ভিডিও বা অডিওর Duration বের করার লজিক
                duration = "N/A"
                if message.video:
                    dur_seconds = message.video.duration
                    mins = dur_seconds // 60
                    secs = dur_seconds % 60
                    duration = f"{mins:02d}:{secs:02d} Min"
                elif message.audio:
                    dur_seconds = message.audio.duration
                    mins = dur_seconds // 60
                    secs = dur_seconds % 60
                    duration = f"{mins:02d}:{secs:02d} Min"

                # তারিখ ফরম্যাটিং
                try:
                    from datetime import datetime
                    dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
                    upload_time = dt.strftime("%d-%b-%Y %I:%M %p")
                except:
                    upload_time = "N/A"

                formatted_size = format_size(size_bytes)

                # ফায়ারবেস ডেটা ব্যবহার করে হুবহু অরিজিনাল সুন্দর ক্যাপশন কার্ড তৈরি
                custom_caption = f"""📂 File Information
━━━━━━━━━━━━━━━━━━━━━━
📝 Name: {file_name}
📦 Size: {formatted_size}
⏱ Duration: {duration}
🆔 File ID: {file_id}
📅 Date: {upload_time}
━━━━━━━━━━━━━━━━━━━━━━
⚡ Streaming & Download Links:
🔗 Stream: {link}
📥 Download: {link}&d=true"""
        except Exception as e:
            print(f"Error reading Firestore: {e}")

    # প্রতিটি ব্যাকআপ চ্যানেলে ফাইলের ক্যাপশন হিসেবে সম্পূর্ণ ডিটেইলস কার্ডটি সরাসরি যুক্ত করে কপি করা হচ্ছে
    for target in BACKUP_CHANNELS:
        try:
            if custom_caption:
                # copy মেথডে caption প্যারামিটার ব্যবহার করে ফাইলের ভেতরেই ক্যাপশন সেট করা হলো
                copied_msg = await message.copy(target, caption=custom_caption)
            else:
                copied_msg = await message.copy(target)
            
            backup_mappings[str(target)] = copied_msg.id
            print(f"Copied file to backup channel {target} with united caption!")
        except Exception as e:
            print(f"Failed to copy file to {target}: {e}")

    # ফায়ারবেস ডকুমেন্টে নতুন ব্যাকআপ আইডি ম্যাপিং আপডেট করা হচ্ছে
    if db and len(backup_mappings) > 0:
        try:
            docs = db.collection("files").where("main_msg_id", "==", message.id).limit(1).stream()
            for doc in docs:
                doc.reference.update({
                    "backup_mappings": backup_mappings
                })
                print(f"Successfully mapped backup IDs in Firestore for main_msg_id {message.id}!")
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
                docs = db.collection("files").where("main_msg_id", "==", deleted_msg_id).limit(1).stream()
                for doc in docs:
                    data = doc.to_dict()
                    backup_mappings = data.get("backup_mappings", {})
                    
                    for ch_id_str, b_msg_id in backup_mappings.items():
                        ch_id = int(ch_id_str)
                        try:
                            await client.delete_messages(chat_id=ch_id, message_ids=b_msg_id)
                            print(f"Successfully deleted mirrored message {b_msg_id} in backup channel {ch_id}")
                        except Exception as e:
                            print(f"Failed to delete mirrored message in backup channel {ch_id}: {e}")
                    
                    doc.reference.delete()
                    print(f"Successfully deleted Firestore document for main_msg_id {deleted_msg_id}")
            except Exception as e:
                print(f"Error handling deleted messages in Firestore: {e}")

print("Dynamic Channel Mirroring CDN Bot is fully active!")
app.run()
