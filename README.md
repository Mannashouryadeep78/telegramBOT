---
title: Telegram AI Bot
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: docker
pinned: true
license: mit
---

# 🤖 Multi-Modal AI Telegram Bot

Powered by **Gemini 2.5 Flash · Groq Whisper · fal.ai · OpenRouter**

## Features
- 💬 Smart chat with persistent memory (Gemini 2.5 Flash)
- 🎨 Image generation (`/draw`) — Pollinations Flux + Pixazo fallback
- 🎬 Video generation (`/generatevideo`) — fal.ai Wan 2.6
- 👁️ Photo OCR & editing — Gemini Vision
- 📄 PDF text extraction — Gemini native PDF support
- 📋 Media to JSON — Gemini structured output
- 🎤 Video transcription — Groq Whisper v3 Turbo

## Commands
| Command | Description |
|---------|-------------|
| `/start` | Start / reset chat |
| `/draw [prompt]` | Generate an image |
| `/generatevideo [prompt]` | Generate a video |
| `/explain` (photo caption) | Extract text from photo |
| `/edit [instruction]` (photo caption) | Edit a photo |
| `/explainpdf` (PDF caption) | Extract PDF text |
| `/tojson` (photo/PDF caption) | Convert to JSON |
| `/videojson` (video caption) | Analyse video |
