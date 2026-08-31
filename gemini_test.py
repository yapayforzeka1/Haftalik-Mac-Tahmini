import os
from google import genai

api_key = os.environ["GEMINI_API_KEY"]

client = genai.Client(api_key=api_key)

response = client.models.generate_content(
    model="gemini-3.7-flash",
    contents="Sadece 'GEMINI ÇALIŞIYOR' yaz. Başka hiçbir şey yazma."
)

print(response.text)
