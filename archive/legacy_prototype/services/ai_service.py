import os
from openai import OpenAI

class AIService:
    def __init__(self):
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self.model_name = os.getenv("OLLAMA_MODEL", "qwen2.5")
        self.client = OpenAI(base_url=self.base_url, api_key="ollama")

    async def generate_response(self, prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"حدث خطأ أثناء الاتصال بموديل الذكاء الاصطناعي: {str(e)}"
