"""
test_workers.py — самопроверка фоновых потоков перевода (ШАГ 3).

Запуск:  python test_workers.py
Сеть НЕ нужна: ошибка подключения проверяется на заведомо закрытом порте,
режим «Обычный» — на подменённом GoogleTranslator (детерминированно).
"""

import os
import sys
import tempfile
from pathlib import Path

# ДО импорта PyQt6: рисуем в «виртуальный» экран, реальный дисплей не нужен.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import workers
from config import ConfigManager
from workers import TranslationWorker


def make_config(tmp: str, **overrides) -> ConfigManager:
    cfg = ConfigManager(Path(tmp) / "config.json")
    for key, value in overrides.items():
        cfg.set(key, value, autosave=False)
    return cfg


def run_worker(app, cfg, text):
    """Запускает воркер и ждёт finished_ok/failed (до ~6 с)."""
    ok, err = [], []
    worker = TranslationWorker(cfg, text)
    worker.finished_ok.connect(lambda t: ok.append(t))
    worker.failed.connect(lambda m: err.append(m))
    worker.start()
    for _ in range(120):
        QTest.qWait(50)
        if ok or err:
            break
    QTest.qWait(200)
    return ok, err


def main() -> int:
    app = QApplication(sys.argv)

    # 1. Эвристика языка ru/en.
    assert workers._detect_ru_en("Hello, world!") == "en"
    assert workers._detect_ru_en("Привет, мир!") == "ru"
    assert workers._detect_ru_en("Смешанный text с обоими алфавитами, кириллицы больше") == "ru"
    assert workers._detect_ru_en("12345 !!!") is None
    print("[OK] 1. _detect_ru_en — эвристика языка ru/en")

    with tempfile.TemporaryDirectory() as tmp:
        # 2. ИИ-режим: порт 9 закрыт всегда → понятная ошибка подключения.
        cfg = make_config(tmp, mode="ai",
                          api_url="http://127.0.0.1:9/v1/chat/completions")
        ok, err = run_worker(app, cfg, "Какой-нибудь текст")
        assert not ok and len(err) == 1, (ok, err)
        assert "подключ" in err[0], err[0]
        print("[OK] 2. ИИ-режим: понятная ошибка «не удалось подключиться»")

        # 3. ИИ-режим: пустой api_url → понятная ошибка про настройки.
        cfg2 = make_config(tmp, mode="ai", api_url="")
        ok, err = run_worker(app, cfg2, "текст")
        assert not ok and "api_url" in err[0], (ok, err)
        print("[OK] 3. ИИ-режим: нет адреса API → понятная ошибка")

        # 4. «Обычный» режим: подменяем GoogleTranslator — сеть не нужна.
        class _FakeTranslator:
            def __init__(self, source, target):
                self.target = target

            def translate(self, text):
                return f"[{self.target}] {text.upper()}"

        original = workers.GoogleTranslator
        workers.GoogleTranslator = _FakeTranslator
        try:
            cfg3 = make_config(tmp, mode="standard", target_lang="ru")
            ok, err = run_worker(app, cfg3, "hello")     # en → цель ru
            assert ok == ["[ru] HELLO"], (ok, err)
            ok, err = run_worker(app, cfg3, "привет")     # ru → переворот на en
            assert ok == ["[en] ПРИВЕТ"], (ok, err)

            # 4b. Лимит запросов Google → отдельное понятное сообщение.
            class _RateLimited:
                def __init__(self, source, target):
                    pass

                def translate(self, text):
                    raise workers.TooManyRequests()

            workers.GoogleTranslator = _RateLimited
            ok, err = run_worker(app, cfg3, "ещё текст")
            assert not ok and "ограничил" in err[0], (ok, err)
        finally:
            workers.GoogleTranslator = original
        print("[OK] 4. «Обычный» режим: перевод, автоопределение ru↔en, лимит Google")

        # 4c. DeepL: без ключа — понятная ошибка; с ключом (мок-класс) — перевод.
        cfg4 = make_config(tmp, mode="standard", standard_engine="deepl",
                           target_lang="ru")
        ok, err = run_worker(app, cfg4, "hello")
        assert not ok and "DeepL" in err[0] and "ключ" in err[0], (ok, err)

        class _FakeDeepl:
            def __init__(self, api_key, source, target):
                self.target = target

            def translate(self, text):
                return f"[deepl:{self.target}] {text.upper()}"

        original_deepl = workers._DeeplTranslator
        workers._DeeplTranslator = _FakeDeepl
        try:
            cfg4.set("deepl_api_key", "TEST-KEY", autosave=False)
            ok, err = run_worker(app, cfg4, "hello")
            assert ok == ["[deepl:ru] HELLO"], (ok, err)
            ok, err = run_worker(app, cfg4, "привет")  # флип ru→en
            assert ok == ["[deepl:en] ПРИВЕТ"], (ok, err)
        finally:
            workers._DeeplTranslator = original_deepl
        print("[OK] 4c. DeepL: ключ проверяется, перевод идёт, ru↔en флип работает")

        # 4d. ИИ-режим: автоопределение подставляет язык в промпт (ru ↔ en).
        class _FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": "OK"}}]}

        captured = {}

        def _fake_post(url, json=None, headers=None, timeout=None):
            captured["payload"] = json
            return _FakeResponse()

        original_post = workers.requests.post
        workers.requests.post = _fake_post
        try:
            cfg5 = make_config(tmp, mode="ai", target_lang="ru",
                               api_url="http://fake/api")
            ok, err = run_worker(app, cfg5, "Привет, как дела?")
            assert ok == ["OK"], (ok, err)
            system_prompt = captured["payload"]["messages"][0]["content"]
            assert "«en»" in system_prompt, system_prompt  # русский → англ.
            ok, err = run_worker(app, cfg5, "Hello, how are you?")
            assert ok == ["OK"], (ok, err)
            system_prompt = captured["payload"]["messages"][0]["content"]
            assert "«ru»" in system_prompt, system_prompt  # англ. → русский
        finally:
            workers.requests.post = original_post
        print("[OK] 4d. ИИ-режим: автоопределение подставляет язык в промпт")

    # 5. Реестр потоков должен опустеть (finished → discard).
    QTest.qWait(300)
    assert len(TranslationWorker._all_workers) == 0, TranslationWorker._all_workers
    print("[OK] 5. Реестр TranslationWorker очищается после завершения")

    print("\nВсе проверки Шага 3 пройдены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
