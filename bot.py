import httpx
import os
import re
import random
import urllib.parse
from dotenv import load_dotenv
import cv2  # OpenCV for frame extraction
from pypdf import PdfReader, PdfWriter
from gradio_client import Client
import shutil
import time
import asyncio

#for storing data
import sqlite3
import json
from datetime import datetime

#for analysing images
import io
import base64


# Telegram imports
from telegram import Update, ReplyParameters
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# AI Client
from groq import Groq
import assemblyai as aai
from gradio_client import Client

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OCR_API_KEY = os.getenv("OCR_SPACE_KEY")
aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")
# Initialize Groq Client
client = Groq(api_key=GROQ_API_KEY)
# 1. Load the token from your .env file
HF_TOKEN = os.getenv("HF_TOKEN")

# 2. Define hf_api globally so all functions can see it
from huggingface_hub import HfApi
hf_api = HfApi(token=HF_TOKEN)

# 3. Your Space ID
SPACE_ID = "zai-org/CogVideoX-5B-Space"



# Initialize Database
def init_db():
    conn = sqlite3.connect('bot_memory.db')
    cursor = conn.cursor()
    # Table for logs (every message)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            action TEXT,
            input_data TEXT,
            timestamp DATETIME
        )
    ''')
    # Table for persistent chat history (Llama context)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_context (
            chat_id INTEGER PRIMARY KEY,
            history_json TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_activity(user_id, username, action, input_data):
    conn = sqlite3.connect('bot_memory.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO activity_logs (user_id, username, action, input_data, timestamp) VALUES (?, ?, ?, ?, ?)',
                   (user_id, username, action, input_data, datetime.now()))
    conn.commit()
    conn.close()

def update_context(chat_id, history):
    conn = sqlite3.connect('bot_memory.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO chat_context (chat_id, history_json) VALUES (?, ?)',
                   (chat_id, json.dumps(history)))
    conn.commit()
    conn.close()

def load_all_contexts():
    conn = sqlite3.connect('bot_memory.db')
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id, history_json FROM chat_context')
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: json.loads(row[1]) for row in rows}

# Initialize on startup
init_db()
user_histories = load_all_contexts()



# Dictionary to store chat history
user_histories = {}
# remove useless signs
def remove_markdown(text):
    if not text: return ""
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    return text.strip()
#
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_histories[chat_id] = [
        {"role": "system", "content": "You are a helpful assistant."}
    ]
    await update.message.reply_text(
        "“Hello! I'm powered by Groq (Llama 3.1) and Pollinations AI, now with persistent SQLite memory.”\n\n"
        "“• Use /start to Chat with me normally for text—I’ll remember our conversation!”\n"
        "“• Use /draw [prompt] to generate images.”\n"
        "“• Use /generatevideo [prompt] to create AI videos.”\n"
        "“• Send a photo with /explain to analyze it or /edit to modify it.”\n"
        "“• Send a PDF with /explainpdf for a detailed summary.”\n"
        "“• Use /tojson or /videojson on media to extract structured data.”"
    )

async def request_style(update, context):
    keyboard = [
        [InlineKeyboardButton("Cyberpunk", callback_data='style_cyberpunk'),
         InlineKeyboardButton("Anime", callback_data='style_anime')],
        [InlineKeyboardButton("Realistic", callback_data='style_realistic')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Please choose a style:', reply_markup=reply_markup)

async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prompt = " ".join(context.args)

    if not prompt:
        await update.message.reply_text("Please provide a description! Example: /draw a cat")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")

    try:
        seed = random.randint(1, 1000000)
        encoded_prompt = urllib.parse.quote(prompt)
        
        # We use model=turbo for speed
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={seed}&model=turbo"

        # BYPASSING TELEGRAM'S URL FETCHING:
        # We download the image ourselves first.
        async with httpx.AsyncClient() as client:
            # We wait up to 120 seconds for the AI to finish drawing
            response = await client.get(image_url, timeout=120.0)
            
            if response.status_code == 200:
                # We send the RAW BYTES of the image. 
                # This prevents the "Failed" message from appearing if the image exists.
                await update.message.reply_photo(
                    photo=response.content, 
                    caption=f"🎨 Generated: {prompt}"
                )
            else:
                await update.message.reply_text("The image server is having trouble. Try again in a moment.")

    except Exception as e:
        print(f"Detailed Error: {e}")
        # Only show error if the download actually crashed
        await update.message.reply_text("Request timed out. The AI is a bit slow today!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    
    # 1. Initialize history if new user
    if chat_id not in user_histories:
        user_histories[chat_id] = [{"role": "system", "content": "You are a helpful assistant."}]

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # 2. Add user message to local memory
    user_histories[chat_id].append({"role": "user", "content": user_text})

    try:
        # 3. Get AI Response
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=user_histories[chat_id],
            max_tokens=1000,
            temperature=0.7
        )

        response_text = completion.choices[0].message.content
        
        # 4. Add AI response to local memory
        user_histories[chat_id].append({"role": "assistant", "content": response_text})
        
        # --- DATABASE UPDATES START HERE ---
        # Save the activity (Log what happened)
        save_activity(chat_id, username, "CHAT", user_text)
        
        # Save the full history (Memory for next time)
        update_context(chat_id, user_histories[chat_id])
        # --- DATABASE UPDATES END HERE ---

        full_text = remove_markdown(response_text)
        
        # 5. Send response to Telegram
        MAX_CHARS = 4000
        if len(full_text) <= MAX_CHARS:
            await update.message.reply_text(full_text)
        else:
            for i in range(0, len(full_text), MAX_CHARS):
                await update.message.reply_text(full_text[i:i + MAX_CHARS])

    except Exception as e:
        print(f"Groq Error: {e}")
        await update.message.reply_text("I'm having trouble thinking right now. Try /start.")

# --- NEW FUNCTION: ANALYSE IMAGE WITH GROQ ---
async def analyze_image_with_groq(image_bytes):
    """Uses Groq's current Vision model (Llama 4 Scout) to describe the image content."""
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    try:
        completion = client.chat.completions.create(
            # UPDATED MODEL ID HERE
            model="meta-llama/llama-4-scout-17b-16e-instruct", 
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image briefly so I can use it to generate a similar but modified one."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"Vision Error: {e}")
        return "a high quality photo"
    
async def handle_photo_wish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main handler for Image Editing."""
    if not update.message.photo:
        return

    # 1. Check for instructions
    user_wish = update.message.caption
    if not user_wish:
        await update.message.reply_text("📸 I received your photo! Now send it again with a CAPTION (like 'make the shirt blue') so I know what to change.")
        return

    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")

    try:
        # 2. Get image data
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        
        # 3. Analyze what is in the original image
        await update.message.reply_text("Analyzing image context... 🔍")
        image_description = await analyze_image_with_groq(image_bytes)
        
        # 4. Generate the new modified image
        # Combining user wish + original description for the best result
        final_prompt = f"{user_wish}, based on this scene: {image_description}"
        encoded_prompt = urllib.parse.quote(final_prompt)
        seed = random.randint(1, 1000000)
        
        # Using Pollinations 'flux' model for higher quality
        edit_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={seed}&model=flux"

        async with httpx.AsyncClient() as h_client:
            response = await h_client.get(edit_url, timeout=120.0)
            if response.status_code == 200:
                await update.message.reply_photo(
                    photo=response.content,
                    caption=f"✅ Magic applied: {user_wish}"
                )
            else:
                await update.message.reply_text("The image server is busy. Try again in a moment!")

    except Exception as e:
        print(f"Error in handler: {e}")
        await update.message.reply_text("Something went wrong with the vision analysis.")

async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /edit when sent as a photo caption."""
    if not update.message or not update.message.caption:
        return

    # Extract the actual instruction by removing '/edit'
    instruction = update.message.caption.replace("/edit", "").strip()

    if not instruction:
        await update.message.reply_text("Please provide an instruction after /edit! Example: /edit make the shirt blue")
        return

    # Call your processing logic
    await process_image_edit(update, context, instruction)

async def process_image_edit(update, context, user_wish):
    """Logic to branch between explaining an image or editing it."""
    chat_id = update.effective_chat.id
    
    try:
        # 1. Download the image
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        
        # 2. Get the AI to look at the image
        await update.message.reply_text("Analyzing image... 🔍")
        image_description = await analyze_image_with_groq(image_bytes)
        
        # 3. BRANCH: Check if the user wants an explanation or an edit
        explain_keywords = ["explain", "describe", "what is", "tell me about"]
        if any(word in user_wish.lower() for word in explain_keywords):
            # Send ONLY the text description
            await update.message.reply_text(f"📝 **Image Description:**\n\n{image_description}")
            return # Exit function here so no new image is generated

        # 4. Otherwise, continue to generate the edited image
        await update.message.reply_text("Applying magic... ✨")
        
        # Improved prompt to try and keep the person's identity
        final_prompt = (
            f"A professional photo of the same person. Maintain facial identity. "
            f"Change only this: {user_wish}. "
            f"Original scene context: {image_description}"
        )
        
        encoded_prompt = urllib.parse.quote(final_prompt)
        seed = random.randint(1, 1000000)
        edit_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={seed}&model=flux"

        async with httpx.AsyncClient() as h_client:
            response = await h_client.get(edit_url, timeout=120.0)
            if response.status_code == 200:
                await update.message.reply_photo(
                    photo=response.content, 
                    caption=f"✅ Transformation for: {user_wish}"
                )
            else:
                await update.message.reply_text("Server is busy. Try again!")

    except Exception as e:
        print(f"Error: {e}")
        await update.message.reply_text("Something went wrong during processing.")

async def explain_pdf_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extracts text from a PDF document using OCR.space."""
    if not update.message.document or update.message.document.mime_type != "application/pdf":
        await update.message.reply_text("Please send a PDF file with the /explainpdf command!")
        return

    await update.message.reply_text("Cloud OCR is reading your PDF... 📄🔍")

    try:
        pdf_file = await update.message.document.get_file()
        pdf_bytes = await pdf_file.download_as_bytearray()
        
        # FIX: Wrap bytes in BytesIO so httpx can 'read' it
        file_like_pdf = io.BytesIO(pdf_bytes)

        async with httpx.AsyncClient() as h_client:
            files = {'file': ('document.pdf', file_like_pdf, 'application/pdf')}
            payload = {
                'apikey': OCR_API_KEY,
                'language': 'eng',
                'OCREngine': 2,
                'isTable': True
            }
            
            response = await h_client.post(
                "https://api.ocr.space/parse/image",
                data=payload,
                files=files,
                timeout=120.0
            )
            result = response.json()

        if result.get("OCRExitCode") == 1:
            pages_text = [f"--- Page {p.get('PageNumber', '?')} ---\n{p.get('ParsedText', '')}" for p in result.get("ParsedResults", [])]
            full_text = "\n\n".join(pages_text)
            await update.message.reply_text(f"📝 **PDF Extracted Text:**\n\n`{full_text[:4000]}`", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ OCR Error: {result.get('ErrorMessage')}")

    except Exception as e:
        print(f"PDF OCR Error: {e}")
        await update.message.reply_text("Failed to process the PDF.")

async def explain_ocr_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extracts text from an image using OCR.space API."""
    if not update.message.photo:
        return

    await update.message.reply_text("Cloud OCR is reading your image... ☁️📖")

    try:
        # 1. Download the photo
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        
        # 2. Wrap bytes in BytesIO to make it 'readable' for the API client
        file_like_image = io.BytesIO(image_bytes)

        async with httpx.AsyncClient() as h_client:
            # DEFINING PAYLOAD AND FILES INSIDE THE FUNCTION
            payload = {
                'apikey': OCR_API_KEY,
                'language': 'eng',
                'OCREngine': 2
            }
            files = {
                'file': ('image.jpg', file_like_image, 'image/jpeg')
            }
            
            response = await h_client.post(
                "https://api.ocr.space/parse/image",
                data=payload,
                files=files,
                timeout=60.0
            )

            if response.status_code != 200:
                await update.message.reply_text(f"❌ API Server Error: {response.status_code}")
                return

            result = response.json()

            # Safety check to ensure we got a dictionary back
            if isinstance(result, str):
                await update.message.reply_text("❌ OCR service returned a message instead of data.")
                return

        # 3. Process the dictionary result
        if result.get("OCRExitCode") == 1:
            parsed_results = result.get("ParsedResults", [])
            if parsed_results:
                extracted_text = parsed_results[0].get("ParsedText", "")
                if extracted_text.strip():
                    await update.message.reply_text(f"📝 **Extracted Text:**\n\n`{extracted_text[:4000]}`", parse_mode="Markdown")
                else:
                    await update.message.reply_text("I couldn't find any text in that image.")
            else:
                await update.message.reply_text("OCR finished but found no results.")
        else:
            # Extract specific error message from the API
            error_msg = result.get("ErrorMessage", "Unknown OCR error")
            if isinstance(error_msg, list): error_msg = ", ".join(error_msg)
            await update.message.reply_text(f"❌ OCR Error: {error_msg}")

    except Exception as e:
        print(f"Critical OCR Error: {e}")
        await update.message.reply_text("Something went wrong with the OCR request.")


async def video_to_json_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video = update.message.video or update.message.document
    if not video or (update.message.document and not update.message.document.mime_type.startswith('video/')):
        return

    await update.message.reply_text("📥 Processing video... Checking for audio and visual data.")
    video_path = f"temp_{video.file_unique_id}.mp4"

    try:
        # 1. Download video
        video_file = await video.get_file()
        await video_file.download_to_drive(video_path)

        # 2. Try AssemblyAI first
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(video_path)

        # 3. IF NO AUDIO: Switch to Visual JSON
        if transcript.error and "No audio stream found" in transcript.error:
            await update.message.reply_text("🔇 No audio detected. Extracting visual data instead... 📸")
            
            # Extract a frame at 1 second mark (or middle of video)
            visual_json = await extract_visual_json(video_path)
            
            # Send the visual data
            await update.message.reply_text(f"🎨 **Visual Scene Analysis (JSON):**\n\n`{visual_json}`", parse_mode="Markdown")
        
        elif transcript.error:
            await update.message.reply_text(f"❌ Error: {transcript.error}")
            
        else:
            # Standard Transcription Logic here...
            await update.message.reply_text(f"✅ Transcript extracted:\n{transcript.text[:500]}...")

    except Exception as e:
        print(f"Video Error: {e}")
    finally:
        if os.path.exists(video_path): os.remove(video_path)

async def extract_visual_json(video_path):
    """Captures a frame and uses Groq Vision to return JSON."""
    cap = cv2.VideoCapture(video_path)
    ret, frame = cap.read() # Capture the first frame
    cap.release()
    
    if not ret: return "Could not extract frame."

    # Convert frame to bytes
    _, buffer = cv2.imencode('.jpg', frame)
    frame_bytes = buffer.tobytes()
    
    # Use your existing analyze function with a JSON prompt
    base64_image = base64.b64encode(frame_bytes).decode('utf-8')
    completion = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Analyze this video frame and return ONLY a valid JSON object describing the objects, setting, and dominant colors."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        }],
        response_format={"type": "json_object"} # Force JSON mode
    )
    return completion.choices[0].message.content



# --- NEW FUNCTION: CONVERT MEDIA TO STRUCTURED JSON ---
async def media_to_json_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unified handler: OCR for PDFs, with a robust fallback Vision system for Photos."""
    message = update.message
    file_obj = None
    is_pdf = False

    if message.photo:
        file_obj = message.photo[-1]
        is_pdf = False
    elif message.document:
        file_obj = message.document
        is_pdf = message.document.mime_type == "application/pdf"
    else:
        await message.reply_text("Please send a Photo or a PDF with the /tojson caption.")
        return

    await update.message.reply_text("📥 Receiving file... Analyzing content.")

    try:
        tg_file = await file_obj.get_file()
        file_bytes = await tg_file.download_as_bytearray()
        json_output = None

        # --- BRANCH A: MULTI-PAGE PDF (OCR LOGIC) ---
        if is_pdf:
            await message.reply_text("📄 Reading PDF text via OCR...")
            full_extracted_text = ""
            reader = PdfReader(io.BytesIO(file_bytes))
            total_pages = len(reader.pages)

            for start_page in range(0, total_pages, 3):
                writer = PdfWriter()
                for page_num in range(start_page, min(start_page + 3, total_pages)):
                    writer.add_page(reader.pages[page_num])
                
                chunk_io = io.BytesIO()
                writer.write(chunk_io)
                chunk_io.seek(0)

                async with httpx.AsyncClient() as h_client:
                    payload = {'apikey': OCR_API_KEY, 'language': 'eng', 'OCREngine': 2, 'isTable': True}
                    files = {'file': ("chunk.pdf", chunk_io, 'application/pdf')}
                    response = await h_client.post("https://api.ocr.space/parse/image", data=payload, files=files, timeout=120.0)
                    result = response.json()
                    if result.get("OCRExitCode") == 1:
                        for res in result.get("ParsedResults", []):
                            full_extracted_text += res.get("ParsedText", "") + "\n"
                
                await message.reply_text(f"✅ Processed pages {start_page+1} to {min(start_page+3, total_pages)}...")

            # Use Groq to structure the extracted text
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile", # Using a more modern stable model for 2026
                messages=[
                    {"role": "system", "content": "Return ONLY a valid JSON object based on the text provided."},
                    {"role": "user", "content": f"Text:\n{full_extracted_text}"}
                ],
                response_format={"type": "json_object"}
            )
            json_output = completion.choices[0].message.content

        # --- BRANCH B: PHOTO (VISION FALLBACK LOGIC) ---
        else:
            await message.reply_text("🖼️ Analyzing image with Vision AI... 👁️")
            base64_image = base64.b64encode(file_bytes).decode('utf-8')
            
            # List of models to try in order (Updated for 2026 stable IDs)
            vision_models = [
                "meta-llama/llama-4-scout-17b-16e-instruct", # Latest Llama 4 Scout
                "llama-3.2-90b-vision-instruct",           # Stable Production 90B
                "llama-3.2-11b-vision-instruct"            # Faster 11B fallback
            ]

            for model_id in vision_models:
                try:
                    completion = client.chat.completions.create(
                        model=model_id,
                        messages=[{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Analyze this image and return a valid JSON object describing the objects, colors, setting, and mood."},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                            ]
                        }],
                        response_format={"type": "json_object"}
                    )
                    json_output = completion.choices[0].message.content
                    break # Success! Exit the loop
                except Exception as model_err:
                    print(f"⚠️ Model {model_id} failed: {model_err}")
                    continue # Try the next model if this one is decommissioned

        if not json_output:
            raise Exception("All vision models failed. Please check Groq console for new model IDs.")

        # FINAL STEP: SEND JSON (with message splitting for Telegram limits)
        if len(json_output) > 4000:
            for i in range(0, len(json_output), 4000):
                await message.reply_text(f"`{json_output[i:i+4000]}`", parse_mode="Markdown")
        else:
            await message.reply_text(f"📋 **Structured JSON Result:**\n\n`{json_output}`", parse_mode="Markdown")

    except Exception as e:
        print(f"Final Error: {e}")
        await message.reply_text(f"⚠️ Failed to process: {str(e)}")

async def generate_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prompt = " ".join(context.args)

    if not prompt:
        await update.message.reply_text("Please provide a prompt! /generatevideo [prompt]")
        return

    await update.message.reply_text("🎬 Establishing connection to the Dreamachine...")

    try:
        seed = random.randint(1, 1000000)
        encoded_prompt = urllib.parse.quote(prompt)
        
        # 2026 UNIFIED ENDPOINT (More stable for DNS resolution)
        # Try using 'image.pollinations.ai' with the video model parameter
        video_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?seed={seed}&model=veo&width=512&height=512&video=true"

        async with httpx.AsyncClient() as v_client:
            response = await v_client.get(video_url, timeout=180.0)
            
            if response.status_code == 200:
                video_bytes = io.BytesIO(response.content)
                await update.message.reply_video(video=video_bytes, caption=f"✅ Video: {prompt}")
            else:
                await update.message.reply_text(f"❌ Server Error: {response.status_code}")

    except httpx.ConnectError:
        # This specifically catches the 'getaddrinfo failed' error
        await update.message.reply_text("🌐 DNS Error: I can't find the AI server. Please check your internet connection or DNS settings.")
    except Exception as e:
        print(f"Error: {e}")
        await update.message.reply_text("⚠️ Something went wrong. The video engine stalled.")





# async def generate_video_hf(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     chat_id = update.effective_chat.id
#     prompt = " ".join(context.args)

#     if not prompt:
#         return await update.message.reply_text("Please provide a prompt!")

#     try:
#         # 1. WAKE UP LOGIC (Check status first)
#         runtime = hf_api.get_space_runtime(repo_id=SPACE_ID)
#         if runtime.stage != "RUNNING":
#             status_msg = await update.message.reply_text(f"😴 Engine is {runtime.stage}. Waking it up...")
#             hf_api.restart_space(repo_id=SPACE_ID)
#             for _ in range(15):
#                 await asyncio.sleep(15)
#                 if hf_api.get_space_runtime(repo_id=SPACE_ID).stage == "RUNNING": break
#             await status_msg.edit_text("✅ GPU Online! Generating...")

#         await context.bot.send_chat_action(chat_id=chat_id, action="upload_video")
        
#         # 2. CONNECT WITH TOKEN
#         gr_client = Client(SPACE_ID, token=HF_TOKEN)
        
#         # 3. FAST-INFERENCE PARAMETERS
#         # We disable RIFE and Scaling to keep the duration under 120s
#         result = gr_client.predict(
#             prompt=prompt[:200],      # hard cap characters
#             image_input=None,
#             video_input=None,
#             video_strength=0.6,       # faster than 0.75
#             seed_value=random.randint(0, 99999),
#             scale_status=False,
#             rife_status=False,
#             api_name="/generate"
#             )


#         # 4. SEND VIDEO
#         video_path = result[0]['video']
#         with open(video_path, 'rb') as video_file:
#             await update.message.reply_video(video=video_file, caption=f"🎥 CogVideoX Engine\n📝 {prompt}")

#     except Exception as e:
#         if "duration" in str(e).lower():
#             await update.message.reply_text("⚠️ This prompt is too complex for the free GPU tier. Try a simpler, shorter prompt!")
#         else:
#             print(f"HF Error: {e}")
#             await update.message.reply_text("⚠️ Engine busy. Try again in a few minutes.")

if __name__ == '__main__':
    # 1. Initialize the database file and tables
    init_db()
    
    # 2. Load existing memories into the user_histories dictionary
    # This prevents the bot from "forgetting" conversations after a restart
    user_histories = load_all_contexts()
    
    print(f"📊 Memory loaded for {len(user_histories)} users.")

    # 3. Increase global timeouts for the bot session
    request_config = HTTPXRequest(connect_timeout=30, read_timeout=120)
    
    # 4. Build the application
    app = ApplicationBuilder() \
        .token(TELEGRAM_TOKEN) \
        .request(request_config) \
        .build()
    
    # 5. Register all your handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("draw", draw))
    # app.add_handler(CommandHandler("generatevideo", generate_video_hf))
    app.add_handler(CommandHandler("generatevideo", generate_video))

    app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(r'^/explain'), explain_ocr_handler))
    app.add_handler(MessageHandler(
        (filters.PHOTO | filters.Document.ALL) & filters.CaptionRegex(r'^/tojson'), 
        media_to_json_handler
    ))
    
    app.add_handler(MessageHandler(filters.VIDEO & filters.CaptionRegex(r'^/videojson'), video_to_json_handler))
    app.add_handler(MessageHandler(filters.Document.VIDEO & filters.CaptionRegex(r'^/videojson'), video_to_json_handler))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.CaptionRegex(r'^/explainpdf'), explain_pdf_handler))
    app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(r'^/edit'), edit_command))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.CaptionRegex(r'^/edit'), handle_photo_wish))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🚀 Bot is running with high-stability image handling and SQLite storage...")
    
    # 6. Start the bot
    app.run_polling()
    #used pythonanywhere to run it in real time