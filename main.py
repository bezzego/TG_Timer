import os
from dotenv import load_dotenv
from pytimeparse import parse

import ptbot
import progressbar


def wait(chat_id, question, bot):
    seconds = parse(question)
    message_id = bot.send_message(
        chat_id,
        f"Осталось: {seconds} секунд\n"
        f"{progressbar.render_progressbar(seconds, seconds)}"
    )

    bot.create_countdown(
        seconds,
        notify_progress,
        chat_id=chat_id,
        message_id=message_id,
        total=seconds,
        bot=bot
    )

    bot.create_timer(
        seconds,
        reply,
        chat_id=chat_id,
        bot=bot
    )

    print("Мне написал пользователь с ID:", chat_id)
    print("Пользователь попросил поставить таймер на:", question)


def notify_progress(secs_left, chat_id, message_id, total, bot):
    bar = progressbar.render_progressbar(total, secs_left)
    bot.update_message(
        chat_id,
        message_id,
        f"Осталось: {secs_left} секунд\n{bar}"
    )


def reply(chat_id, bot):
    bot.send_message(chat_id, "Время вышло!")


def main():
    load_dotenv()
    tg_token = os.getenv('TG_TOKEN')
    bot = ptbot.Bot(tg_token)
    bot.reply_on_message(wait, bot=bot)
    bot.run_bot()


if __name__ == '__main__':
    main()
