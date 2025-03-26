import os
from pytimeparse import parse
from dotenv import load_dotenv
import ptbot
import progressbar


load_dotenv()
TG_TOKEN = os.getenv('TG_TOKEN')


def wait(chat_id, question):
    seconds = parse(question)
    message_id = bot.send_message(chat_id, f"Осталось: {seconds} секунд\n{progressbar.render_progressbar(seconds, seconds)}")
    bot.create_countdown(seconds, notify_progress, chat_id=chat_id, message_id=message_id, total=seconds)
    bot.create_timer(seconds, reply, chat_id=chat_id)
    print("Мне написал пользователь с ID:", chat_id)
    print("Пользователь попросил поставить таймер на:", question)


def notify_progress(secs_left, chat_id, message_id, total):
    bar = progressbar.render_progressbar(total, secs_left)
    bot.update_message(chat_id, message_id, f"Осталось: {secs_left} секунд\n{bar}")


def reply(chat_id):
    bot.send_message(chat_id, "Время вышло!")


if __name__ == '__main__':
    bot = ptbot.Bot(TG_TOKEN)
    bot.reply_on_message(wait)
    bot.run_bot()