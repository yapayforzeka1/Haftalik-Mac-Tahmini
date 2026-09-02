import os
from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
response = client.models.generate_content(model="gemini-3.7-flash", contents="Sadece 'GEMINI ÇALIŞIYOR' yaz.", config={"max_output_tokens":20})
print(response.text)
