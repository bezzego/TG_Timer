import logging
import os
import time
from datetime import datetime, timedelta

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackQueryHandler, CallbackContext
)

import dateparser
from pytimeparse import parse as parse_simple
import progressbar

from storage import Storage
from voice import Voice


def parse_natural_text(text: str):
    """
    Парсит текст вида «поставь таймер на 5 минут», «30s», «завтра в 10» и т.д.
    Возвращает: (seconds, is_repeating, source), где:
        - seconds: int
        - is_repeating: bool
        - source: 'dateparser' | 'pytimeparse' | None
    """

    txt = text.strip().lower()
    repeating = False

    # Фразы, указывающие на повтор
    if "повтор" in txt or "кажд" in txt:
        repeating = True
        txt = txt.replace("повторяй", "").replace("повтор", "").replace("каждые", "").replace("каждый", "").strip()

    # Убираем лишние фразы
    for ph in [
        "поставь таймер на", "сделай интервал", "запусти таймер на",
        "сделай таймер на", "поставь будильник на", "поставь на"
    ]:
        txt = txt.replace(ph, "")

    # Замена "на завтра" → "завтра", "в 5 утра" → "5 am"
    txt = txt.replace("на завтра", "завтра")
    txt = txt.replace(" утра", " am").replace(" вечера", " pm").replace(" дня", " pm").replace(" ночи", " am")

    # Пробуем dateparser
    dt = dateparser.parse(txt, languages=["ru"], settings={"PREFER_DATES_FROM": "future"})
    if dt:
        now = datetime.now()
        if dt <= now:
            return (None, repeating, None)
        secs = int((dt - now).total_seconds())
        return (secs, repeating, "dateparser")

    # Пробуем pytimeparse (поддерживает '30s', '2h30m', '1m')
    secs2 = parse_simple(txt)
    if secs2 and secs2 > 0:
        return (secs2, repeating, "pytimeparse")

    return (None, repeating, None)


class TimerBot:
    def __init__(self, token: str, storage: Storage, voice: Voice):
        self.logger = logging.getLogger("TimerBot")
        self.storage = storage
        self.voice = voice
        self.updater = Updater(token=token, use_context=True)
        self.dispatcher = self.updater.dispatcher
        self.job_queue = self.updater.job_queue

        # Регистрируем хендлеры
        self.dispatcher.add_handler(CommandHandler("start", self.cmd_start))
        self.dispatcher.add_handler(CommandHandler("timers", self.cmd_timers))
        self.dispatcher.add_handler(CommandHandler("repeat", self.cmd_repeat))
        self.dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, self.handle_text))
        self.dispatcher.add_handler(MessageHandler(Filters.voice, self.handle_voice))
        self.dispatcher.add_handler(CallbackQueryHandler(self.handle_callback))

        # Восстанавливаем таймеры из JSON (active + repeat)
        self.restore_timers()

    def run(self):
        self.logger.info("Запускаем бота...")
        self.updater.start_polling()
        self.logger.info("Бот запущен. Нажмите Ctrl+C для остановки.")
        self.updater.idle()

    def cmd_start(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id

        text = (
            "👋 *Привет! Я — Таймер-Бот.*\n\n"
            "⏳ Я умею ставить таймеры на любое время:\n"
            "• Напиши: `30s`, `1m`, `2h`, `завтра в 10 утра`, `через 15 минут`\n"
            "• Или скажи голосом: _поставь таймер на 5 минут_, _повторяй каждый час_\n\n"
            "🔁 *Повторяющиеся таймеры:*\n"
            "`/repeat 10m` — каждые 10 минут\n"
            "или голосом: _повторяй каждые 10 минут_\n\n"
            "📋 *Команды:*\n"
            "`/timers` — список всех таймеров\n"
            "`/repeat` — повторяющийся таймер\n\n"
            "🛠️ *Кнопки в сообщениях:*\n"
            "• 🛑 Стоп — отменить таймер\n"
            "• 🔁 Повторить — заново запустить таймер\n"
            "• ➕ Отложить — на 5 минут\n"
            "• 🔔 Выбрать звук — кастомизируй уведомления\n\n"
            "Готов? Просто напиши мне время или отправь голосовое 🎙️"
        )

        # Inline-кнопка "Выбрать звук"
        keyboard = [[InlineKeyboardButton("🔔 Выбрать звук", callback_data="choose_sound")]]
        update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )


    def cmd_timers(self, update: Update, context: CallbackContext):
        """Показываем список активных и завершённых таймеров."""
        chat_id = update.effective_chat.id
        data = self.storage.data
        # Активные (одноразовые) + повторяющиеся
        active_one = [t for t in data["active"] if t["chat_id"] == chat_id]
        active_rep = [t for t in data["repeat"] if t["chat_id"] == chat_id]
        completed = [t for t in data["completed"] if t["chat_id"] == chat_id]

        msg_lines = []
        msg_lines.append("Активные таймеры:")
        if not active_one and not active_rep:
            msg_lines.append("  – нет активных таймеров")
        else:
            for t in active_one:
                dur = t["duration"]
                msg_lines.append(f"  [ID {t['id']}] Одноразовый: {dur} сек (осталось ~...)")

            for t in active_rep:
                interval = t["interval"]
                msg_lines.append(f"  [ID {t['id']}] Повтор каждые {interval} сек")

        msg_lines.append("\nЗавершённые (история):")
        if not completed:
            msg_lines.append("  – пусто")
        else:
            for c in completed[-5:]:  # покажем последние 5
                if c.get("repeating"):
                    msg_lines.append(f"  [ID {c['id']}] Повтор (остановлен)")
                else:
                    d = c["duration"]
                    msg_lines.append(f"  [ID {c['id']}] Таймер на {d} сек (завершён)")

        text = "\n".join(msg_lines)
        update.message.reply_text(text)

    def cmd_repeat(self, update: Update, context: CallbackContext):
        """
        /repeat <interval>
        """
        chat_id = update.effective_chat.id
        args = context.args
        if not args:
            update.message.reply_text("Пример: /repeat 30s или /repeat завтра в 10 утра (если хотите хитро)")
            return

        user_input = " ".join(args)
        secs, repeating = parse_natural_text(user_input)
        if not secs or secs <= 0:
            update.message.reply_text("Не понял интервал. Пример: /repeat 30s")
            return
        # Раз уже /repeat, мы точно ставим повтор
        self.start_repeating_timer(chat_id, secs)

    def handle_text(self, update: Update, context: CallbackContext):
        """Обработка обычного текстового сообщения с временем."""
        chat_id = update.effective_chat.id
        text = update.message.text

        secs, is_rep, source = parse_natural_text(text)
        if not secs or secs <= 0:
            update.message.reply_text("Не понял время. Пример: 30s, завтра в 10 утра, через 15 минут.")
            return

        # Добавляем +1 секунду только если источник — dateparser (естественный язык)
        if source == "dateparser":
            secs += 1

        if is_rep:
            self.start_repeating_timer(chat_id, secs)
        else:
            self.start_one_time_timer(chat_id, secs)

    def handle_voice(self, update: Update, context: CallbackContext):
        """Обработка голосового сообщения."""
        chat_id = update.effective_chat.id
        voice_file = update.message.voice.get_file()
        temp_path = f"voice_{update.message.message_id}.ogg"
        voice_file.download(temp_path)

        recognized = self.voice.recognize(temp_path)
        try:
            os.remove(temp_path)
        except:
            pass

        if not recognized:
            update.message.reply_text("Не понял голос. Попробуйте сказать иначе.")
            return

        secs, is_rep, source = parse_natural_text(recognized)
        if not secs or secs <= 0:
            update.message.reply_text("Не смог распознать время из голосового сообщения.")
            return

        # Добавляем +1 секунду только если источник — dateparser
        if source == "dateparser":
            secs += 1

        if is_rep:
            self.start_repeating_timer(chat_id, secs)
        else:
            self.start_one_time_timer(chat_id, secs)

    def handle_callback(self, update: Update, context: CallbackContext):
        """Обработчик inline-кнопок."""
        query = update.callback_query
        data = query.data
        chat_id = query.message.chat_id
        query.answer()  # скрываем «загрузка»

        if data == "choose_sound":
            # Показываем варианты звуков
            # В demos: "bell", "siren", "melody"
            kb = [
                [InlineKeyboardButton("🔔 Колокол", callback_data="sound_bell"),
                 InlineKeyboardButton("📢 Сирена", callback_data="sound_siren")],
                [InlineKeyboardButton("🎵 Мелодия", callback_data="sound_melody")]
            ]
            query.edit_message_text("Выберите звук для уведомлений:", reply_markup=InlineKeyboardMarkup(kb))
        elif data.startswith("sound_"):
            # выбрали звук
            choice = data.split("sound_")[1]
            # Сохраним в storage
            self.storage.data["settings"]["sound"] = choice
            self.storage.save()
            query.edit_message_text(f"Звук уведомления обновлён на '{choice}'!")
        elif data.startswith("cancel_timer:"):
            # пользователь нажал «Стоп/Отменить таймер»
            tid = int(data.split(":")[1])
            self.cancel_timer(chat_id, tid, from_callback=True, message_id=query.message.message_id)
        elif data.startswith("repeat_timer:"):
            # пользователь нажал «Повторить» (🔁)
            tid = int(data.split(":")[1])
            self.repeat_finished_timer(chat_id, tid, query.message.message_id)
        elif data.startswith("snooze_timer:"):
            # пользователь нажал «Отложить» (➕)
            tid = int(data.split(":")[1])
            self.snooze_timer(chat_id, tid, query.message.message_id)
        else:
            self.logger.info(f"Неизвестная кнопка: {data}")

    # ========== Логика таймеров ==========

    def start_one_time_timer(self, chat_id: int, secs: int):
        """Запускаем одноразовый таймер."""
        start_ts = time.time()
        end_ts = start_ts + secs

        timer_id = self.storage.allocate_new_id()
        # Сообщение пользователю
        bar = progressbar.render_progressbar(secs, secs)
        text = f"Таймер на {secs} сек!\n⏳ Осталось: {secs} секунд\n{bar}"
        kb = [[InlineKeyboardButton("🛑 Стоп", callback_data=f"cancel_timer:{timer_id}")]]
        msg = self.updater.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(kb))

        # Сохраняем в storage
        entry = {
            "id": timer_id,
            "chat_id": chat_id,
            "start": int(start_ts),
            "duration": secs,
            "end_ts": int(end_ts),
            "message_id": msg.message_id,
            "repeating": False
        }
        self.storage.add_active_timer(entry)
        # Ставим джобу на окончание
        finish_job = self.job_queue.run_once(self.on_timer_finish, secs, context=timer_id)
        # Ставим джобу на обновление прогресса каждую секунду
        progress_job = self.job_queue.run_repeating(self.on_progress_tick, interval=1.0, first=1.0, context=timer_id)

        # Сохраним идентификаторы job
        entry["finish_job_name"] = finish_job.name
        entry["progress_job_name"] = progress_job.name
        self.storage.save()

        self.logger.info(f"Создан таймер (id={timer_id}) на {secs} сек для chat={chat_id}")

    def start_repeating_timer(self, chat_id: int, secs: int):
        """Запускаем повторяющийся таймер (каждые secs)."""
        start_ts = time.time()
        timer_id = self.storage.allocate_new_id()

        text = f"Повторяющийся таймер каждые {secs} сек!\n"
        kb = [[InlineKeyboardButton("🛑 Стоп", callback_data=f"cancel_timer:{timer_id}")]]
        msg = self.updater.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(kb))

        entry = {
            "id": timer_id,
            "chat_id": chat_id,
            "interval": secs,
            "start": int(start_ts),
            "message_id": msg.message_id,
            "repeating": True
        }
        self.storage.add_repeat_timer(entry)
        # Ставим repeating-job
        job = self.job_queue.run_repeating(self.on_repeat_tick, interval=secs, first=secs, context=timer_id)
        entry["job_name"] = job.name
        self.storage.save()

        self.logger.info(f"Создан повторяющийся таймер (id={timer_id}), каждые {secs} секунд")

    def cancel_timer(self, chat_id: int, timer_id: int, from_callback=False, message_id=None):
        """
        Отмена таймера (либо одноразового, либо повторяющегося).
        Удаляем из storage, убиваем job-ы, правим сообщение и пишем «Таймер отменён!».
        """
        # Смотрим в active
        timer = self.storage.get_active_timer(timer_id)
        if timer:
            # убираем из active
            self.storage.remove_active_timer(timer_id)
            # останавливаем job
            finish_job_name = timer.get("finish_job_name")
            progress_job_name = timer.get("progress_job_name")
            if finish_job_name:
                job = self.job_queue.get_jobs_by_name(finish_job_name)
                if job:
                    job[0].schedule_removal()
            if progress_job_name:
                job = self.job_queue.get_jobs_by_name(progress_job_name)
                if job:
                    job[0].schedule_removal()

            if message_id:
                try:
                    # Убрать кнопки
                    self.updater.bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
                except:
                    pass
            self.updater.bot.send_message(chat_id, "🛑 Таймер отменён!")
            self.storage.save()
            return

        # Смотрим в repeat
        rep_timer = self.storage.get_repeat_timer(timer_id)
        if rep_timer:
            self.storage.remove_repeat_timer(timer_id)
            jn = rep_timer.get("job_name")
            if jn:
                job = self.job_queue.get_jobs_by_name(jn)
                if job:
                    job[0].schedule_removal()
            if message_id:
                try:
                    self.updater.bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
                except:
                    pass
            self.updater.bot.send_message(chat_id, "🛑 Повторяющийся таймер отменён!")
            self.storage.save()
            return

        # Не нашли
        self.updater.bot.send_message(chat_id, "Нет такого таймера или уже отменён/завершён!")

    def on_timer_finish(self, context: CallbackContext):
        """
        Когда одноразовый таймер доходит до конца. Вызывается job_queue.run_once(...).
        """
        job = context.job
        timer_id = job.context
        tinfo = self.storage.get_active_timer(timer_id)
        if not tinfo:
            return  # уже отменён
        chat_id = tinfo["chat_id"]
        # Удаляем из active, переносим в completed
        self.storage.remove_active_timer(timer_id)
        # Прекращаем прогресс job
        pjname = tinfo.get("progress_job_name")
        if pjname:
            prjobs = self.job_queue.get_jobs_by_name(pjname)
            if prjobs:
                prjobs[0].schedule_removal()
        # Запишем в completed
        completed = {
            "id": timer_id,
            "chat_id": chat_id,
            "duration": tinfo["duration"],
            "finished_at": int(time.time()),
            "repeating": False
        }
        self.storage.add_completed_timer(completed)
        self.storage.save()
        # Убираем кнопки на сообщении
        msg_id = tinfo["message_id"]
        try:
            self.updater.bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
        except:
            pass
        # Отправим уведомление
        # Звук
        sound_choice = self.storage.data["settings"].get("sound")  # e.g. "bell"
        # Если хотим реальный звуковой файл, надо отправить аудио/voice
        # Пока ограничимся символом
        if sound_choice == "bell":
            prefix = "🔔"
        elif sound_choice == "siren":
            prefix = "📢"
        elif sound_choice == "melody":
            prefix = "🎵"
        else:
            prefix = "⏰"

        # Предложим кнопки «Повторить» и «Отложить»
        kb = [[
            InlineKeyboardButton("🔁 Повторить", callback_data=f"repeat_timer:{timer_id}"),
            InlineKeyboardButton("➕ Отложить на 5 мин", callback_data=f"snooze_timer:{timer_id}")
        ]]
        self.updater.bot.send_message(chat_id, f"{prefix} Время вышло!", reply_markup=InlineKeyboardMarkup(kb))

    def on_repeat_tick(self, context: CallbackContext):
        """
        Каждые N секунд срабатывает повторяющийся таймер.
        Отправляем "Время вышло!", но не убираем таймер.
        """
        job = context.job
        timer_id = job.context
        tinfo = self.storage.get_repeat_timer(timer_id)
        if not tinfo:
            return  # уже отменён
        chat_id = tinfo["chat_id"]

        # Уведомление
        sound_choice = self.storage.data["settings"].get("sound")
        if sound_choice == "bell":
            prefix = "🔔"
        elif sound_choice == "siren":
            prefix = "📢"
        elif sound_choice == "melody":
            prefix = "🎵"
        else:
            prefix = "⏰"

        self.updater.bot.send_message(chat_id, f"{prefix} Повтор! Интервал: {tinfo['interval']} сек.")

    def on_progress_tick(self, context: CallbackContext):
        """
        Каждую секунду обновляем сообщение одноразового таймера:
        "Осталось: XXX сек" + progressbar
        """
        job = context.job
        timer_id = job.context
        tinfo = self.storage.get_active_timer(timer_id)
        if not tinfo:
            # таймер уже отменён или завершён
            job.schedule_removal()
            return
        chat_id = tinfo["chat_id"]
        msg_id = tinfo["message_id"]
        start = tinfo["start"]
        dur = tinfo["duration"]
        end_ts = tinfo["end_ts"]
        now = time.time()
        left = int(end_ts - now)
        if left < 0:
            left = 0
        bar = progressbar.render_progressbar(dur, left)
        text = f"Таймер на {dur} сек!\n⏳ Осталось: {left} секунд\n{bar}"
        kb = [[InlineKeyboardButton("🛑 Стоп", callback_data=f"cancel_timer:{timer_id}")]]
        try:
            context.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except:
            # Возможно, сообщение удалено
            job.schedule_removal()

    def repeat_finished_timer(self, chat_id: int, timer_id: int, message_id: int):
        """
        Нажали «Повторить» после окончания таймера.
        Ищем duration в completed.
        """
        c = self.storage.find_completed(timer_id)
        if not c:
            self.updater.bot.send_message(chat_id, "Не могу повторить: не нашёл инфу о таймере.")
            return
        dur = c["duration"]
        # Стартуем новый одноразовый таймер
        self.start_one_time_timer(chat_id, dur)
        # Убираем кнопки
        try:
            self.updater.bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
        except:
            pass

    def snooze_timer(self, chat_id: int, timer_id: int, message_id: int):
        """
        Нажали «Отложить»: создаём новый одноразовый таймер, скажем, на 300 секунд
        """
        c = self.storage.find_completed(timer_id)
        if not c:
            self.updater.bot.send_message(chat_id, "Не могу отложить: не нашёл инфу о таймере.")
            return
        # 5 мин
        self.start_one_time_timer(chat_id, 5 * 60)
        # Убираем кнопки
        try:
            self.updater.bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
        except:
            pass
        self.updater.bot.send_message(chat_id, "Отложено на 5 минут!")

    def restore_timers(self):
        """
        При запуске бота восстанавливаем активные/повторяющиеся таймеры из storage.
        """
        data = self.storage.data
        now = time.time()

        # 1) Одноразовые
        active_list = data["active"]
        to_remove = []
        for t in active_list:
            end_ts = t["end_ts"]
            left = end_ts - now
            if left <= 0:
                # уже истёк -> перенесём в completed
                c = {
                    "id": t["id"],
                    "chat_id": t["chat_id"],
                    "duration": t["duration"],
                    "finished_at": int(now),
                    "repeating": False
                }
                data["completed"].append(c)
                to_remove.append(t["id"])
            else:
                # Нужно заново запланировать
                finish_job = self.job_queue.run_once(self.on_timer_finish, when=left, context=t["id"])
                prog_job = self.job_queue.run_repeating(self.on_progress_tick, interval=1.0, first=1.0, context=t["id"])
                t["finish_job_name"] = finish_job.name
                t["progress_job_name"] = prog_job.name

        # Убираем истёкшие из active
        for rid in to_remove:
            self.storage.remove_active_timer(rid)
        # 2) Повторяющиеся
        rep_list = data["repeat"]
        for r in rep_list:
            interval = r["interval"]
            job = self.job_queue.run_repeating(self.on_repeat_tick, interval=interval, first=interval, context=r["id"])
            r["job_name"] = job.name
        self.storage.save()

    # Утилиты
    def _format_duration(self, secs: int):
        """Преобразуем секунды -> человекочитаемый вид (напр. 1h5m)."""
        # можно сделать поприкольнее
        if secs < 60:
            return f"{secs}с"
        if secs < 3600:
            mins = secs // 60
            s = secs % 60
            return f"{mins}м{'' if s==0 else str(s)+'с'}"
        hours = secs // 3600
        rem = secs % 3600
        mins = rem // 60
        s = rem % 60
        if hours < 24:
            return f"{hours}ч{'' if mins==0 else str(mins)+'м'}"
        # Если > 24ч
        days = hours // 24
        h2 = hours % 24
        return f"{days}д{h2}ч"