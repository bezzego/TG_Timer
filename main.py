import logging
import os
from dotenv import load_dotenv

from ptbot import TimerBot
from storage import Storage
from voice import Voice

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    load_dotenv()  # читаем .env
    TOKEN = os.getenv("TG_TOKEN")
    if not TOKEN:
        raise ValueError("TG_TOKEN не найден в .env")

    STORAGE_FILE = "timers.json"
    VOSK_MODEL_PATH = "model/vosk-model-small-ru-0.22"

    storage = Storage(STORAGE_FILE)
    voice = Voice(VOSK_MODEL_PATH)
    bot = TimerBot(token=TOKEN, storage=storage, voice=voice)
    bot.run()

if __name__ == "__main__":
    main()