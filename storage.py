import json
import os

class Storage:
    def __init__(self, filename="timers.json"):
        self.filename = filename
        self.data = {
            "active": [],     # одноразовые таймеры (ещё не кончились)
            "repeat": [],     # повторяющиеся таймеры
            "completed": [],  # завершённые таймеры
            "settings": {},   # напр. sound
            "next_id": 1      # для уникальных ID
        }
        self._load()

    def _load(self):
        """Загружаем из JSON-файла, если есть."""
        if os.path.exists(self.filename):
            with open(self.filename, "r", encoding="utf-8") as f:
                try:
                    self.data = json.load(f)
                except json.JSONDecodeError:
                    pass
        # Убедимся, что все ключи есть
        for key in ["active", "repeat", "completed", "settings", "next_id"]:
            if key not in self.data:
                if key == "next_id":
                    self.data[key] = 1
                elif key == "settings":
                    self.data[key] = {}
                else:
                    self.data[key] = []

    def save(self):
        """Сохраняем в JSON."""
        with open(self.filename, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def allocate_new_id(self):
        nid = self.data["next_id"]
        self.data["next_id"] += 1
        return nid

    # ======= Для одноразовых таймеров =======
    def add_active_timer(self, timer_entry: dict):
        self.data["active"].append(timer_entry)
        self.save()

    def get_active_timer(self, timer_id: int):
        for t in self.data["active"]:
            if t["id"] == timer_id:
                return t
        return None

    def remove_active_timer(self, timer_id: int):
        before = len(self.data["active"])
        self.data["active"] = [t for t in self.data["active"] if t["id"] != timer_id]
        after = len(self.data["active"])
        if before != after:
            self.save()

    # ======= Для повторяющихся =======
    def add_repeat_timer(self, rep_entry: dict):
        self.data["repeat"].append(rep_entry)
        self.save()

    def get_repeat_timer(self, timer_id: int):
        for r in self.data["repeat"]:
            if r["id"] == timer_id:
                return r
        return None

    def remove_repeat_timer(self, timer_id: int):
        before = len(self.data["repeat"])
        self.data["repeat"] = [r for r in self.data["repeat"] if r["id"] != timer_id]
        after = len(self.data["repeat"])
        if before != after:
            self.save()

    # ======= Для завершённых =======
    def add_completed_timer(self, comp_entry: dict):
        self.data["completed"].append(comp_entry)
        self.save()

    def find_completed(self, timer_id: int):
        for c in self.data["completed"]:
            if c["id"] == timer_id:
                return c
        return None

    # ======= Настройки =======
    # Сохранены в self.data["settings"], там же "sound"