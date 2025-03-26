import os
import wave
import json
import subprocess

from vosk import Model, KaldiRecognizer

class Voice:
    def __init__(self, model_path="model"):
        if not os.path.exists(model_path):
            raise RuntimeError(f"Не найдена папка с Vosk-моделью: {model_path}")
        self.model = Model(model_path)

    def recognize(self, file_path: str) -> str:
        """
        Конвертируем file_path (ogg) -> wav (16k mono) -> распознаём
        Возвращаем распознанный текст (str) или "" (если не удалось).
        """
        if not os.path.exists(file_path):
            return ""

        # 1) конвертим ogg -> wav
        base, _ = os.path.splitext(file_path)
        wav_path = base + ".wav"
        cmd = [
            "/opt/homebrew/bin/ffmpeg", "-y",
            "-i", file_path,
            "-ar", "16000",
            "-ac", "1",
            wav_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # 2) Распознаём
        if not os.path.exists(wav_path):
            return ""

        with wave.open(wav_path, "rb") as wf:
            rec = KaldiRecognizer(self.model, wf.getframerate())
            text_result = []
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                rec.AcceptWaveform(data)
            result_json = rec.FinalResult()
            result_dict = json.loads(result_json)
            text = result_dict.get("text", "").strip()

        # Удалим .wav
        try:
            os.remove(wav_path)
        except:
            pass

        return text