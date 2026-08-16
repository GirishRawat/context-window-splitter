import os
import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

print("Available models:")
for m in genai.list_models():
    print(m.name)
