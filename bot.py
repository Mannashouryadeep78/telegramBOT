import httpx
import os
import re
import random
import urllib.parse
import io
import base64
import sqlite3
import json
import asyncio
import cv2
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

# AI Clients
from groq import Groq
from google import genai
from google.genai import types
from openai import OpenAI  # used for OpenRouter fallback

# Load environment
load_dotenv()
TELEGRAM_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY        = os.getenv("GROQ_API_KEY")
FAL_KEY             = os.getenv("FAL_KEY")
OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY")
PIXAZO_API_KEY      = os.getenv("PIXAZO_API_KEY")

# --- AI Client Initialisation ---
groq_client    = Groq(api_key=GROQ_API_KEY)
gemini_client  = genai.Client(api_key=GEMINI_API_KEY)
or_client      = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY
)

# fal.ai — imported lazily so missing package doesn't crash the bot
try:
    import fal_client
    FAL_AVAILABLE = True
except ImportError:
    FAL_AVAILABLE = False

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect('bot_memory.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS activity_logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER, username TEXT,
                  action TEXT, input_data TEXT, timestamp DATETIME)''')
    c.execute('''CREATE TABLE IF NOT EXISTS chat_context
                 (chat_id INTEGER PRIMARY KEY, history_json TEXT)''')
    conn.commit(); conn.close()

def save_activity(user_id, username, action, input_data):
    conn = sqlite3.connect('bot_memory.db')
    conn.execute('INSERT INTO activity_logs VALUES (NULL,?,?,?,?,?)',
                 (user_id, username, action, str(input_data)[:500], datetime.now()))
    conn.commit(); conn.close()

def update_context(chat_id, history):
    conn = sqlite3.connect('bot_memory.db')
    conn.execute('INSERT OR REPLACE INTO chat_context VALUES (?,?)',
                 (chat_id, json.dumps(history)))
    conn.commit(); conn.close()

def load_all_contexts():
    conn = sqlite3.connect('bot_memory.db')
    rows = conn.execute('SELECT chat_id, history_json FROM chat_context').fetchall()
    conn.close()
    return {r[0]: json.loads(r[1]) for r in rows}

init_db()
user_histories: dict = load_all_contexts()

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def strip_markdown(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    return text.strip()

def chunk_text(text: str, size: int = 4000):
    return [text[i:i+size] for i in range(0, len(text), size)]

async def send_long(update: Update, text: str):
    for part in chunk_text(text):
        await update.message.reply_text(part)

# ─────────────────────────────────────────────
# SMART CHAT — Gemini with OpenRouter fallback
# ─────────────────────────────────────────────
async def gemini_chat(history: list) -> str:
    """Send full chat history to Gemini 2.5 Flash."""
    # Convert our stored format → Gemini Content objects
    contents = []
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction="You are a helpful, friendly AI assistant.",
            max_output_tokens=1500,
            temperature=0.7,
        )
    )
    return response.text

async def openrouter_fallback(messages: list) -> str:
    """Fallback using OpenRouter free tier if Gemini fails."""
    resp = or_client.chat.completions.create(
        model="meta-llama/llama-3.3-70b-instruct:free",
        messages=messages,
        max_tokens=1000,
    )
    return resp.choices[0].message.content

async def smart_chat(history: list) -> str:
    """Try Gemini first; fall back to OpenRouter."""
    try:
        return await asyncio.to_thread(gemini_chat_sync, history)
    except Exception as e:
        print(f"[Gemini] failed: {e} — switching to OpenRouter")
        msgs = [{"role": m["role"], "content": m["content"]} for m in history]
        return await asyncio.to_thread(openrouter_fallback_sync, msgs)

def gemini_chat_sync(history):
    contents = []
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction="You are a helpful, friendly AI assistant.",
            max_output_tokens=1500,
            temperature=0.7,
        )
    )
    return response.text

def openrouter_fallback_sync(messages):
    resp = or_client.chat.completions.create(
        model="meta-llama/llama-3.3-70b-instruct:free",
        messages=messages,
        max_tokens=1000,
    )
    return resp.choices[0].message.content

# ─────────────────────────────────────────────
# GEMINI VISION helper
# ─────────────────────────────────────────────
def gemini_vision_sync(image_bytes: bytes, prompt: str, json_mode: bool = False) -> str:
    """Send image + prompt to Gemini. Optionally request JSON output."""
    img = Image.open(io.BytesIO(image_bytes))
    cfg = types.GenerateContentConfig(max_output_tokens=2000)
    if json_mode:
        cfg = types.GenerateContentConfig(
            max_output_tokens=2000,
            response_mime_type="application/json"
        )
    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[prompt, img],
        config=cfg,
    )
    return response.text

async def gemini_vision(image_bytes: bytes, prompt: str, json_mode: bool = False) -> str:
    return await asyncio.to_thread(gemini_vision_sync, image_bytes, prompt, json_mode)

# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_histories[chat_id] = []
    update_context(chat_id, [])
    await update.message.reply_text(
        "👋 Hello! I'm your upgraded AI assistant.\n\n"
        "🧠 Powered by: Gemini 2.5 Flash · Groq Whisper · fal.ai\n\n"
        "📌 Commands:\n"
        "• Just chat — I remember our conversation!\n"
        "• /draw [prompt] — Generate an image\n"
        "• /generatevideo [prompt] — Create an AI video\n"
        "• /explain (as photo caption) — Extract text from photo (OCR)\n"
        "• /edit [instruction] (as photo caption) — Edit a photo\n"
        "• /explainpdf (with PDF) — Extract text from PDF\n"
        "• /tojson (with photo or PDF) — Convert to structured JSON\n"
        "• /videojson (with video) — Analyse video content"
    )

# ─────────────────────────────────────────────
# TEXT CHAT
# ─────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    chat_id   = update.effective_chat.id
    username  = update.effective_user.username

    if chat_id not in user_histories:
        user_histories[chat_id] = []

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    user_histories[chat_id].append({"role": "user", "content": user_text})

    try:
        reply = await smart_chat(user_histories[chat_id])
        user_histories[chat_id].append({"role": "model", "content": reply})
        save_activity(chat_id, username, "CHAT", user_text)
        update_context(chat_id, user_histories[chat_id])
        await send_long(update, strip_markdown(reply))
    except Exception as e:
        print(f"Chat error: {e}")
        await update.message.reply_text("⚠️ Something went wrong. Try /start to reset.")

# ─────────────────────────────────────────────
# /draw — IMAGE GENERATION
# ─────────────────────────────────────────────
async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prompt  = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Please provide a prompt! Example: /draw a sunset over mountains")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")

    seed = random.randint(1, 999999)
    encoded = urllib.parse.quote(prompt)

    # Primary: Pollinations Flux
    primary_url  = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed={seed}&model=flux"
    # Fallback: Pixazo API
    fallback_url = f"https://api.pixazo.ai/generate?prompt={encoded}&width=1024&height=1024&apikey={PIXAZO_API_KEY}"

    for url, label in [(primary_url, "Pollinations"), (fallback_url, "Pixazo")]:
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(url, timeout=120.0)
            if r.status_code == 200 and len(r.content) > 5000:
                await update.message.reply_photo(photo=r.content, caption=f"🎨 {prompt}")
                return
        except Exception as e:
            print(f"[draw] {label} failed: {e}")

    await update.message.reply_text("❌ Image generation is unavailable right now. Try again soon!")

# ─────────────────────────────────────────────
# /generatevideo — VIDEO GENERATION via fal.ai
# ─────────────────────────────────────────────
async def generate_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prompt  = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Please provide a prompt! Example: /generatevideo a cat playing piano")
        return

    await update.message.reply_text("🎬 Generating your video via fal.ai (Wan 2.6)... This takes ~1-2 minutes.")
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_video")

    if not FAL_AVAILABLE:
        await update.message.reply_text("⚠️ Video engine not installed. Run: pip install fal-client")
        return

    try:
        os.environ["FAL_KEY"] = FAL_KEY  # ensure env var is set for fal_client

        def run_fal():
            return fal_client.subscribe(
                "fal-ai/wan/v2.6/1080p",
                arguments={"prompt": prompt, "num_frames": 65},
            )

        result = await asyncio.to_thread(run_fal)
        video_url = result["video"]["url"]

        async with httpx.AsyncClient() as c:
            r = await c.get(video_url, timeout=180.0)
        if r.status_code == 200:
            await update.message.reply_video(
                video=io.BytesIO(r.content),
                caption=f"🎥 {prompt}"
            )
        else:
            raise Exception(f"Download failed: {r.status_code}")

    except Exception as e:
        print(f"[video] fal.ai error: {e}")
        await update.message.reply_text("⚠️ Video generation failed. Try a shorter, simpler prompt!")

# ─────────────────────────────────────────────
# /explain — OCR via Gemini Vision
# ─────────────────────────────────────────────
async def explain_ocr_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        return
    await update.message.reply_text("🔍 Reading text in your image with Gemini Vision...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        photo_file  = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        result = await gemini_vision(
            bytes(image_bytes),
            "Extract ALL text visible in this image exactly as written. "
            "If no text is visible, describe the image instead."
        )
        await send_long(update, f"📝 Extracted Text:\n\n{result}")
    except Exception as e:
        print(f"[OCR] {e}")
        await update.message.reply_text("❌ Could not read the image. Please try again.")

# ─────────────────────────────────────────────
# /edit — Photo editing via Gemini + Pollinations
# ─────────────────────────────────────────────
async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for photo + /edit caption."""
    if not update.message or not update.message.photo:
        return
    instruction = (update.message.caption or "").replace("/edit", "").strip()
    if not instruction:
        await update.message.reply_text("Please add an instruction after /edit!\nExample: /edit make the sky red")
        return
    await process_image_edit(update, context, instruction)

async def process_image_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, user_wish: str):
    """Describe image with Gemini, then generate edited version with Pollinations."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
    try:
        photo_file  = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()

        await update.message.reply_text("🔍 Analysing image with Gemini...")
        description = await gemini_vision(
            bytes(image_bytes),
            "Describe this image briefly so I can generate a similar but modified version."
        )

        # Check if user just wants a description
        if any(w in user_wish.lower() for w in ["explain", "describe", "what is", "tell me"]):
            await update.message.reply_text(f"📝 Image Description:\n\n{description}")
            return

        await update.message.reply_text("✨ Applying your changes...")
        final_prompt = f"{user_wish}. Scene context: {description}"
        encoded = urllib.parse.quote(final_prompt)
        seed    = random.randint(1, 999999)
        url     = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed={seed}&model=flux"

        async with httpx.AsyncClient() as c:
            r = await c.get(url, timeout=120.0)
        if r.status_code == 200:
            await update.message.reply_photo(photo=r.content, caption=f"✅ Applied: {user_wish}")
        else:
            await update.message.reply_text("❌ Image server busy. Try again!")
    except Exception as e:
        print(f"[edit] {e}")
        await update.message.reply_text("❌ Something went wrong during editing.")

async def handle_photo_wish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generic photo + caption handler (not a command)."""
    if not update.message.photo:
        return
    caption = update.message.caption
    if not caption:
        await update.message.reply_text(
            "📸 Photo received! Send it again with a caption to edit it.\n"
            "Example: 'make the sky purple'"
        )
        return
    await process_image_edit(update, context, caption)

# ─────────────────────────────────────────────
# /explainpdf — PDF text extraction via Gemini
# ─────────────────────────────────────────────
async def explain_pdf_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document or update.message.document.mime_type != "application/pdf":
        await update.message.reply_text("Please send a PDF file with the /explainpdf caption.")
        return

    await update.message.reply_text("📄 Reading your PDF with Gemini AI...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        doc_file   = await update.message.document.get_file()
        pdf_bytes  = await doc_file.download_as_bytearray()

        def extract_pdf_text():
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part(inline_data=types.Blob(
                        mime_type="application/pdf",
                        data=bytes(pdf_bytes)
                    )),
                    "Extract ALL text from this PDF document, page by page. "
                    "Preserve structure (headings, lists, tables)."
                ],
                config=types.GenerateContentConfig(max_output_tokens=4000)
            )
            return response.text

        result = await asyncio.to_thread(extract_pdf_text)
        await send_long(update, f"📝 PDF Content:\n\n{result}")

    except Exception as e:
        print(f"[PDF] {e}")
        await update.message.reply_text(f"❌ Failed to read PDF: {str(e)[:200]}")

# ─────────────────────────────────────────────
# /tojson — Media to structured JSON via Gemini
# ─────────────────────────────────────────────
async def media_to_json_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    is_pdf  = False

    if message.photo:
        file_obj = message.photo[-1]
    elif message.document:
        file_obj = message.document
        is_pdf   = message.document.mime_type == "application/pdf"
    else:
        await message.reply_text("Please send a Photo or PDF with the /tojson caption.")
        return

    await message.reply_text("📥 Analysing content and generating JSON...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        tg_file    = await file_obj.get_file()
        file_bytes = bytes(await tg_file.download_as_bytearray())

        if is_pdf:
            def pdf_to_json():
                response = gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        types.Part(inline_data=types.Blob(
                            mime_type="application/pdf",
                            data=file_bytes
                        )),
                        "Analyse this PDF and return a valid JSON object capturing "
                        "all key information (headings, data, tables, lists)."
                    ],
                    config=types.GenerateContentConfig(
                        max_output_tokens=4000,
                        response_mime_type="application/json"
                    )
                )
                return response.text
            json_output = await asyncio.to_thread(pdf_to_json)
        else:
            json_output = await gemini_vision(
                file_bytes,
                "Analyse this image and return a valid JSON object describing: "
                "objects, colors, setting, visible text, and mood.",
                json_mode=True
            )

        for part in chunk_text(json_output):
            await message.reply_text(f"```json\n{part}\n```", parse_mode="Markdown")

    except Exception as e:
        print(f"[tojson] {e}")
        await message.reply_text(f"❌ Failed to generate JSON: {str(e)[:200]}")

# ─────────────────────────────────────────────
# /videojson — Video analysis (Groq Whisper + Gemini Vision)
# ─────────────────────────────────────────────
async def video_to_json_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video = update.message.video or update.message.document
    if not video:
        return
    if update.message.document and not update.message.document.mime_type.startswith("video/"):
        return

    await update.message.reply_text("📥 Processing video... checking for audio and visual data.")
    video_path = f"temp_{video.file_unique_id}.mp4"

    try:
        video_file = await video.get_file()
        await video_file.download_to_drive(video_path)

        # ── Step 1: Try Groq Whisper for audio transcription ──
        transcript_text = None
        try:
            def transcribe():
                with open(video_path, "rb") as af:
                    return groq_client.audio.transcriptions.create(
                        file=af,
                        model="whisper-large-v3-turbo",
                        response_format="text"
                    )
            transcript_text = await asyncio.to_thread(transcribe)
        except Exception as whisper_err:
            print(f"[Whisper] {whisper_err}")

        # ── Step 2: If no audio/transcript → fall back to visual analysis ──
        if not transcript_text or len(transcript_text.strip()) < 5:
            await update.message.reply_text("🔇 No speech detected. Extracting visual scene data...")
            cap = cv2.VideoCapture(video_path)
            # Grab frame from the middle of the video
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total_frames // 2))
            ret, frame = cap.read()
            cap.release()

            if not ret:
                await update.message.reply_text("❌ Could not extract a frame from the video.")
                return

            _, buf = cv2.imencode('.jpg', frame)
            frame_bytes = buf.tobytes()

            json_output = await gemini_vision(
                frame_bytes,
                "Analyse this video frame and return ONLY a valid JSON object "
                "describing: objects, setting, dominant colors, estimated mood.",
                json_mode=True
            )
            await update.message.reply_text(
                f"🎨 Visual Scene Analysis:\n```json\n{json_output[:3800]}\n```",
                parse_mode="Markdown"
            )
        else:
            # We have a good transcript — also do a brief visual check
            await update.message.reply_text(
                f"🎤 Transcript (Groq Whisper):\n\n{transcript_text[:2000]}"
            )

    except Exception as e:
        print(f"[videojson] {e}")
        await update.message.reply_text(f"❌ Video processing failed: {str(e)[:200]}")
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    user_histories = load_all_contexts()
    print(f"[DB] Loaded memory for {len(user_histories)} chats.")

    request_cfg = HTTPXRequest(connect_timeout=30, read_timeout=180)
    app = ApplicationBuilder() \
        .token(TELEGRAM_TOKEN) \
        .request(request_cfg) \
        .build()

    # Commands
    app.add_handler(CommandHandler("start",         start))
    app.add_handler(CommandHandler("draw",          draw))
    app.add_handler(CommandHandler("generatevideo", generate_video))

    # Photo + caption-based commands (order matters — specific before generic)
    app.add_handler(MessageHandler(
        filters.PHOTO & filters.CaptionRegex(r'^/explain'),   explain_ocr_handler))
    app.add_handler(MessageHandler(
        (filters.PHOTO | filters.Document.ALL) & filters.CaptionRegex(r'^/tojson'),
        media_to_json_handler))
    app.add_handler(MessageHandler(
        filters.Document.PDF & filters.CaptionRegex(r'^/explainpdf'), explain_pdf_handler))
    app.add_handler(MessageHandler(
        filters.PHOTO & filters.CaptionRegex(r'^/edit'),      edit_command))

    # Video
    app.add_handler(MessageHandler(
        (filters.VIDEO | filters.Document.VIDEO) & filters.CaptionRegex(r'^/videojson'),
        video_to_json_handler))

    # Generic photo (no special command)
    app.add_handler(MessageHandler(
        filters.PHOTO & ~filters.CaptionRegex(r'^/(explain|edit|tojson)'),
        handle_photo_wish))

    # Plain text chat
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("[BOT] Running: Gemini 2.5 Flash | Groq Whisper | fal.ai | OpenRouter fallback")
    app.run_polling()