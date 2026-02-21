from gradio_client import Client

# Test with a specific CogVideoX space
SPACE_ID = "zai-org/CogVideoX-5B-Space"

try:
    print(f"🔄 Connecting to {SPACE_ID}...")
    client = Client(SPACE_ID)
    
    # This command prints all available API endpoints for that Space
    # VERY USEFUL to see if the input name is 'prompt' or something else
    client.view_api()
    print("✅ Connection Successful!")
except Exception as e:
    print(f"❌ Connection Failed: {e}")