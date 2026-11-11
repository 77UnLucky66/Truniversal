"""
test_workers.py — самопроверка фоновых потоков перевода (ШАГ 3 + Этап 1).

Запуск:  python test_workers.py
Сеть НЕ нужна: ошибка подключения проверяется на заведомо закрытом порте,
режим «Обычный» — на подменённом GoogleTranslator, а поведение ИИ-режима
(HTTP-ошибки, пустые и битые ответы, таймауты) — на моках requests.
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
from workers import TranslationWorker, wait_for_workers


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

        # 4e. Пустой текст → понятная ошибка, БЕЗ обращения к сети.
        cfg_empty = make_config(tmp, mode="ai", api_url="http://fake/api")
        ok, err = run_worker(app, cfg_empty, "   \n\t  ")
        assert not ok and "Пустой" in err[0], (ok, err)
        print("[OK] 4e. Пустой текст перевода → понятная ошибка без запроса")

        # --- Моки ответов API для тестов ошибок ИИ-режима (сеть не нужна) ---
        class _FakeApiError:
            def __init__(self, code: int, body: str = ""):
                self.status_code = code
                self.text = body

            def json(self):
                raise ValueError("not a json")

        class _FakeJsonResp:
            status_code = 200
            text = ""

            def __init__(self, data):
                self._data = data

            def json(self):
                return self._data

        original_post = workers.requests.post

        def _post_returning(obj):
            return lambda url, json=None, headers=None, timeout=None: obj

        cfg_api = make_config(tmp, mode="ai", api_url="http://fake/api")

        # 6. ИИ-режим: понятные сообщения об ошибках HTTP API.
        try:
            for code, expected in ((401, "запрещён"), (403, "запрещён"),
                                   (404, "не найдены")):
                workers.requests.post = _post_returning(_FakeApiError(code))
                ok, err = run_worker(app, cfg_api, "текст")
                assert not ok and expected in err[0], (code, err)
            workers.requests.post = _post_returning(_FakeApiError(500, "server boom"))
            ok, err = run_worker(app, cfg_api, "текст")
            assert not ok and "HTTP 500" in err[0] and "server boom" in err[0], err
        finally:
            workers.requests.post = original_post
        print("[OK] 6. ИИ-режим: понятные тексты ошибок HTTP (401/403/404/500)")

        # 7. ИИ-режим: битые и пустые ответы API не роняют воркер.
        try:
            cases = [
                (_FakeJsonResp({}), "нет сгенерированного текста"),
                (_FakeJsonResp({"choices": []}), "нет сгенерированного текста"),
                (_FakeJsonResp({"choices": [{"message": {}}]}), "пустой ответ"),
                # пустой content, но есть запасное поле text — берём его
                (_FakeJsonResp({"choices": [{"message": {"content": ""},
                                             "text": "запасной формат"}]}), None),
                (_FakeApiError(200, "html вместо json"), "не-JSON"),
            ]
            for resp, expected in cases:
                workers.requests.post = _post_returning(resp)
                ok, err = run_worker(app, cfg_api, "текст")
                if expected is None:
                    assert ok == ["запасной формат"], (ok, err)
                else:
                    assert not ok and expected in err[0], (expected, err)
        finally:
            workers.requests.post = original_post
        print("[OK] 7. ИИ-режим: пустые и битые ответы API → понятные ошибки")

        # 8. Таймаут API → понятное сообщение (без реального ожидания 90 с).
        def _raise_timeout(url, json=None, headers=None, timeout=None):
            raise workers.requests.exceptions.Timeout("too slow")

        try:
            workers.requests.post = _raise_timeout
            ok, err = run_worker(app, cfg_api, "текст")
            assert not ok and "время ожидания" in err[0], err
        finally:
            workers.requests.post = original_post
        print("[OK] 8. Таймаут API → понятная ошибка")

        # 9. ModelListWorker: успех, пустой список, ошибки сервера (моки).
        class _FakeGetResp:
            text = ""

            def __init__(self, code, data=None):
                self.status_code = code
                self._data = data

            def json(self):
                return self._data

        def _run_model_worker(base_url):
            loaded, failed = [], []
            w = workers.ModelListWorker(base_url)
            w.models_loaded.connect(lambda names: loaded.extend(names))
            w.failed.connect(lambda message: failed.append(message))
            w.start()
            for _ in range(120):
                QTest.qWait(50)
                if loaded or failed:
                    break
            w.wait(2000)  # поток обязан закончиться до уничтожения ссылки
            QTest.qWait(100)
            return loaded, failed

        original_get = workers.requests.get
        try:
            workers.requests.get = lambda url, timeout=None: _FakeGetResp(
                200, {"models": [{"name": "llama3"}, {"model": "qwen2.5"}]}
            )
            loaded, failed = _run_model_worker("http://localhost:11434")
            assert loaded == ["llama3", "qwen2.5"] and not failed, (loaded, failed)

            workers.requests.get = lambda url, timeout=None: _FakeGetResp(
                200, {"models": []}
            )
            loaded, failed = _run_model_worker("http://localhost:11434")
            assert not loaded and failed and "не установлено" in failed[0], failed

            workers.requests.get = lambda url, timeout=None: _FakeGetResp(500)
            loaded, failed = _run_model_worker("http://localhost:11434")
            assert not loaded and "HTTP 500" in failed[0], failed

            def _raise_conn(url, timeout=None):
                raise workers.requests.exceptions.ConnectionError("refused")

            workers.requests.get = _raise_conn
            loaded, failed = _run_model_worker("http://localhost:11434")
            assert not loaded and "Ollama" in failed[0], failed
        finally:
            workers.requests.get = original_get
        print("[OK] 9. ModelListWorker: список моделей и понятные ошибки")

        # 10. TranslationWorker.cancel(): отменяет долгий запрос, не выдавая сигналов
        def _slow_post(url, json=None, headers=None, timeout=None):
            import time
            for _ in range(50):
                time.sleep(0.05)
            return _FakeResponse()

        original_post = workers.requests.post
        try:
            workers.requests.post = _slow_post
            cfg_cancel = make_config(tmp, mode="ai", api_url="http://fake/api")
            worker_cancel = TranslationWorker(cfg_cancel, "Тестовый длинный текст")
            c_ok, c_err = [], []
            worker_cancel.finished_ok.connect(c_ok.append)
            worker_cancel.failed.connect(c_err.append)
            worker_cancel.start()
            QTest.qWait(50)  # даём потоку запуститься
            worker_cancel.cancel()
            worker_cancel.wait(2000)
            assert not c_ok and not c_err, f"Отменённый воркер не должен слать сигналы: ok={c_ok}, err={c_err}"
        finally:
            workers.requests.post = original_post
        print("[OK] 10. TranslationWorker.cancel() — корректная отмена без побочных сигналов")

        # 11. ModelListWorker.cancel(): отменяет запрос списка моделей
        def _slow_get(url, timeout=None):
            import time
            for _ in range(50):
                time.sleep(0.05)
            return _FakeGetResp(200, {"models": [{"name": "test"}]})

        original_get = workers.requests.get
        try:
            workers.requests.get = _slow_get
            w_model = workers.ModelListWorker("http://localhost:11434")
            m_loaded, m_failed = [], []
            w_model.models_loaded.connect(m_loaded.append)
            w_model.failed.connect(m_failed.append)
            w_model.start()
            QTest.qWait(50)
            w_model.cancel()
            w_model.wait(2000)
            assert not m_loaded and not m_failed, "Отменённый ModelListWorker не должен слать сигналы"
        finally:
            workers.requests.get = original_get
        print("[OK] 11. ModelListWorker.cancel() — прерывание фонового запроса моделей")

        # 12. wait_for_workers(): прерывает активные воркеры и завершает работу быстро
        try:
            workers.requests.post = _slow_post
            w_live = TranslationWorker(cfg_cancel, "Ещё текст для wait_for_workers")
            w_live.start()
            QTest.qWait(50)
            import time
            t0 = time.monotonic()
            wait_for_workers(3000)
            elapsed = time.monotonic() - t0
            assert elapsed < 2.5, f"wait_for_workers должен был прервать воркер быстрее: {elapsed}s"
            assert not w_live.isRunning()
        finally:
            workers.requests.post = original_post
        print("[OK] 12. wait_for_workers() — мгновенное прерывание активных воркеров при выходе")

        # 13. Пустые результаты Google/DeepL дают понятные сообщения
        class _EmptyTranslator:
            def __init__(self, source, target, **kwargs):
                pass
            def translate(self, text):
                return "   "

        orig_gt = workers.GoogleTranslator
        workers.GoogleTranslator = _EmptyTranslator
        try:
            cfg_empty_trans = make_config(tmp, mode="standard", target_lang="ru")
            ok_empty, err_empty = run_worker(app, cfg_empty_trans, "some text")
            assert not ok_empty and "пустой результат" in err_empty[0].lower(), (ok_empty, err_empty)
        finally:
            workers.GoogleTranslator = orig_gt
        print("[OK] 13. Обычный режим: пустой результат переводчика → понятная ошибка")

    # 5. Общий реестр потоков должен опустеть (finished → discard) — в нём
    #    живут и TranslationWorker, и ModelListWorker.
    QTest.qWait(300)
    assert len(TranslationWorker._all_workers) == 0, TranslationWorker._all_workers
    wait_for_workers(1000)
    assert len(workers._live_threads) == 0, workers._live_threads
    print("[OK] 5. Общий реестр воркеров очищается после завершения")

    print("\nВсе проверки фоновых потоков пройдены (Шаг 3 + Этап 1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
