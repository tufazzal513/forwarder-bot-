import os
import json
import asyncio
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pyrogram import Client, filters, idle
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

MAIN_CHANNEL = int(os.environ.get("MAIN_CHANNEL", os.environ.get("SOURCE_CHANNEL", -1003962440092)))

# ২. এনভায়রনমেন্ট ভেরিয়েবল "BACKUP_CHANNELS" রিড করার ডাইনামিক পার্সার
backup_channels_env = os.environ.get("BACKUP_CHANNELS")
if not backup_channels_env:
    backup_channels_env = os.environ.get("BACKUP_CHANNALS", "") 

BACKUP_CHANNELS = []
if backup_channels_env:
    for x in backup_channels_env.split(","):
        x = x.strip().replace('"', '').replace("'", "").replace("[", "").replace("]", "")
        if x:
            try:
                BACKUP_CHANNELS.append(int(x))
            except ValueError:
                print(f"Warning: Failed to parse backup channel ID '{x}' as integer")

print(f"Loaded MAIN_CHANNEL: {MAIN_CHANNEL}")
print(f"Loaded BACKUP_CHANNELS: {BACKUP_CHANNELS}")

# ৩. ফায়ারবেস ক্লাউড ফায়ারস্টোর ইনিশিয়ালাইজেশন
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

# ৪. ক্লায়েন্ট সেটআপ
if SESSION_STRING:
    app = Client("mirror_userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
else:
    app = Client("mirror_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ৫. নতুন মেসেজ মনিটরিং এবং ফায়ারবেস ম্যাপিং হ্যান্ডলার
@app.on_message(filters.chat(MAIN_CHANNEL))
async def mirror_messages(client, message: Message):
    # কেস ১: যদি মেসেজটি মিডিয়া ফাইল হয় (যেমন: মেইন চ্যানেলে ফরোয়ার্ড করা মূল ফাইল)
    if message.media:
        # Go বটকে ফায়ারবেসে ডেটা সেভ করার জন্য ২ সেকেন্ড সময় দেওয়া হচ্ছে (Race Condition এড়াতে)
        await asyncio.sleep(2.0)

        backup_mappings = {}
        for target in BACKUP_CHANNELS:
            # ডুপ্লিকেট ফরোয়ার্ড এড়াতে ব্যাকআপ আইডি যদি মেইন চ্যানেলের আইডি হয়, তবে স্কিপ করা হবে
            if target == MAIN_CHANNEL:
                continue
                
            try:
                # মেইন চ্যানেলের অরিজিনাল ফাইলটি ব্যাকআপ চ্যানেলে কপি করা হচ্ছে
                copied_msg = await message.copy(target)
                backup_mappings[str(target)] = copied_msg.id
                print(f"Copied raw file to backup channel {target} (New Msg ID: {copied_msg.id})")
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

    # কেস ২: যদি মেসেজটি সাধারণ টেক্সট হয় এবং এটি কোনো রিপ্লাই মেসেজ হয় (যেমন: বটের পাঠানো আলাদা তথ্যকার্ড রিপ্লাই মেসেজ)
    elif not message.media and message.reply_to_message_id:
        parent_msg_id = message.reply_to_message_id
        print(f"Detected caption reply message {message.id} replying to {parent_msg_id} in Main Channel.")

        # ডাটাবেস আপডেট হওয়ার জন্য ১ সেকেন্ড সময় দেওয়া হচ্ছে
        await asyncio.sleep(1.0)

        if db:
            try:
                # ফায়ারবেস থেকে মূল ভিডিও ফাইলের মেইন মেসেজ আইডি কুয়েরি করা হচ্ছে
                docs = db.collection("files").where("main_msg_id", "==", parent_msg_id).limit(1).stream()
                for doc in docs:
                    data = doc.to_dict()
                    backup_mappings = data.get("backup_mappings", {})
                    
                    # প্রতিটি ব্যাকআপ চ্যানেলে এই ক্যাপশন মেসেজটি কপি করে ভিডিও ফাইলকে রিপ্লাই (Reply) করে পাঠানো হচ্ছে
                    for ch_id_str, b_msg_id in backup_mappings.items():
                        ch_id = int(ch_id_str)
                        try:
                            # reply_to_message_id ব্যবহার করে ব্যাকআপ চ্যানেলে হুবহু রিপ্লাই করা হলো
                            await message.copy(ch_id, reply_to_message_id=b_msg_id)
                            print(f"Successfully replied caption to backup channel {ch_id} on message {b_msg_id}")
                        except Exception as e:
                            print(f"Failed to reply caption to backup channel {ch_id}: {e}")
            except Exception as e:
                print(f"Error handling reply message in Firestore: {e}")


# ৬. মূল চ্যানেল থেকে মেসেজ ডিলিট হওয়া মাত্রই তা ব্যাকআপ চ্যানেল ও ডাটাবেস থেকে ডিলিট করার লজিক
@app.on_deleted_messages(filters.chat(MAIN_CHANNEL))
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


# ━━━ স্টার্টআপ মেথড (অটো-চ্যানেল রেজোলভার) ━━━
async def main():
    await app.start()
    print("Auto-Resolver: Fetching dialogs to automatically cache channel access hashes...")
    try:
        # বটের অ্যাডমিন থাকা সকল সচল চ্যানেল স্বয়ংক্রিয়ভাবে ক্যাশ করার লুপ
        async for dialog in app.get_dialogs():
            print(f"Auto-Resolver resolved: {dialog.chat.title} ({dialog.chat.id})")
    except Exception as e:
        print(f"Auto-Resolver Warning: {e}")
    print("Auto-Resolver: Successfully resolved and cached all active channels! Listening for new messages...")
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
