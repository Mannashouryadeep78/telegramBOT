🤖 Multi-Modal AI Telegram Bot
A powerful, all-in-one Telegram bot featuring persistent memory, AI image/video generation, Vision analysis, and OCR capabilities. Powered by Groq (Llama 3.3/4), Pollinations AI, and AssemblyAI.

✨ Key Features
🧠 Persistent Memory: Uses SQLite to remember chat history across bot restarts.

🖼️ AI Image Generation: Generate high-quality images using /draw.

🎬 Video Synthesis: Create AI-generated videos using the Dreamachine/Veo engine.

👁️ Vision & Editing: \* Analyze: Send a photo with /explain to get a detailed description.

Edit: Send a photo with a caption like /edit make the sky red to transform it.

📄 Document Intelligence:

OCR: Extract text from images or PDFs with /explainpdf.

JSON Extraction: Use /tojson to turn photos or PDFs into structured data.

🎥 Video Analysis: Extract visual scenes or audio transcripts from video files with /videojson.

🛠️ Tech Stack
Language: Python 3.10+

Bot Framework: python-telegram-bot

AI Models: \* Text: Groq (Llama 3.3-70b & Llama 4 Scout)

Vision: Llama 3.2 Vision

Images/Video: Pollinations AI (Flux/Turbo/Veo)

Audio: AssemblyAI

Database: SQLite3

Processing: OpenCV (CV2), PyPDF, HTTPX

🚀 Setup & Installation

1. Prerequisites

Ensure you have the following API keys:

Telegram Bot Token

Groq API Key

OCR.space API Key

AssemblyAI API Key

HuggingFace Token (Optional)

2. Environment Variables

Create a .env file in the root directory:

TELEGRAM_BOT_TOKEN=your_token_here
GROQ_API_KEY=your_groq_key
OCR_SPACE_KEY=your_ocr_key
ASSEMBLYAI_API_KEY=your_aai_key
HF_TOKEN=your_hf_token

3. Installation

# Clone the repository

git clone https://github.com/yourusername/your-bot-repo.git****************************\*\*\*****************************
cd your-bot-repo

# Install dependencies

pip install httpx python-dotenv opencv-python pypdf gradio_client python-telegram-bot groq assemblyai huggingface_hub

4. Running the Bot
   python bot.py

🕹️ Usage & Commands:

Command,Action
/start,Initialize chat and memory
/draw [prompt],Generate an image from text
/generatevideo [prompt],Create a short AI video
/explain (as photo caption),Describes the content of the image
/edit [prompt] (as photo caption),Modifies the photo based on your wish
/explainpdf (with PDF file),Performs OCR on a PDF and returns text
/tojson (with media),Converts image/PDF content into a JSON object
/videojson (with video),Analyzes video frames and returns visual data in JSON

💾 Data Management
bot_memory.db: An SQLite database automatically created on startup.
Activity Logs: Tracks user interactions and timestamps.
Chat Context: Stores the conversation flow so the AI stays "in character."

☁️ Deployment
This bot is optimized for deployment on PythonAnywhere or Heroku. Because it uses sqlite3, ensure your hosting provider has persistent storage enabled for the .db file.

📜 License
This project is licensed under the MIT License - see the LICENSE file for details.

🚀 Deployment
This bot is configured for high availability and is currently hosted on PythonAnywhere.
Why PythonAnywhere?

1. Persistent Storage: The bot_memory.db (SQLite) is stored on the server's disk, ensuring the bot remembers users even after a script restart.
2. Always-On: Uses a custom "Scheduled Task" or "Always-on task" to keep the Telegram polling loop active 24/7.
3. Environment Safety: All sensitive API keys are stored in a .env file within the PythonAnywhere virtual environment.

Hosting Setup
To replicate this setup on PythonAnywhere:

1. Upload the project files to your /home/username/ directory.

2. Open a Bash Console and create a virtual environment: mkvirtualenv mybot --python=python3.10.

3. Install dependencies: pip install -r requirements.txt.

4. Go to the Tasks tab and add your main.py (or bot.py) as an "Always-on task."

🛠 Challenges Faced & Solutions
Building a multi-modal bot with zero budget presented several engineering challenges:

1. The Search for "Free-Infinity" Models
   Problem: Most high-end AI models (like GPT-4 or Midjourney) require expensive subscriptions or have very strict free-tier limits. Solution: I integrated Pollinations AI for unlimited image generation and Groq for lightning-fast text inference. This allowed the bot to remain free to use while maintaining "pro" performance levels.

2. Code Optimization & Latency
   Problem: Handling images, videos, and large text buffers simultaneously caused the bot to lag or time out. Solution: I implemented Asynchronous programming (asyncio) and optimized httpx request timeouts. I also added "Typing..." and "Uploading..." chat actions to improve the User Experience (UX) while the AI processes data.

3. The "Always-On" Cloud Hurdle
   Problem: Most free cloud hosting (like Heroku) puts the bot to "sleep" after 30 minutes of inactivity. Solution: I deployed the bot on PythonAnywhere. By utilizing their task scheduling and persistent storage, I ensured the bot stays online 24/7 without needing a local machine to be running.

4. Designing Persistent Memory
   Problem: Every time the bot restarted, it "forgot" who the users were and what they were talking about. Solution: I designed a custom SQLite3 database schema. This allows the bot to store JSON-serialized chat histories and activity logs, giving it a "long-term memory" even after server reboots.

5. Multi-AI Orchestration
   Problem: Getting different AI engines (Groq for text, OCR.space for vision, AssemblyAI for audio) to "talk" to each other in a single workflow. Solution: I built a Modular Handler System. The bot identifies the media type (PDF, Photo, or Video) and the user's intent (caption/command) to intelligently route the data to the correct AI engine.

⚙️ Technical Optimizations
To ensure a smooth user experience on Telegram's mobile interface, I implemented several custom optimization layers:

✨ Clean UI: Markdown Stripping
Telegram sometimes struggles with complex nested Markdown (like headers and excessive bolding) generated by LLMs. I developed a custom regex-based cleaner:

The Problem: AI responses often contain ### headers or \*\* syntax that look cluttered on small screens.

The Solution: A remove_markdown() function that uses regular expressions to strip unnecessary symbols while maintaining the core readability of the text.

🧠 Memory Efficiency: Global Context Tracking
Managing chat history for hundreds of users can quickly consume RAM.

The Solution: I implemented a dual-layer memory system. Active conversations are managed in a high-speed user_histories dictionary, while the long-term state is mirrored to the SQLite database.

The Benefit: If the bot crashes, it reloads user_histories from the database on startup, ensuring no "context loss" for the user.

🚀 Stability: High-Performance Network Config
Since this bot interacts with multiple external AI APIs (Groq, Pollinations, OCR.space), network stability was a priority.

Custom Timeout Logic: I configured HTTPXRequest with a 30-second connect timeout and a 120-second read timeout.

Non-Blocking Actions: I integrated Telegram's send_chat_action (e.g., "typing..." or "uploading photo...") so users know the bot is working during long AI inference cycles.
