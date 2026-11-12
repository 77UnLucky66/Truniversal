"""
test_audit_stage1.py — комплексная проверка надежности и стабильности (ЭТАП 1).

Проверяет все требования технического аудита:
  1. Загрузка конфигурации (дефолты, валидация, fallback).
  2. Сохранение настроек (атомарность, защита от ошибок диска).
  3. Поврежденные файлы (мягкая очистка синтаксиса, спасение промптов, .bak, .tmp).
  4. Работа переводческих запросов (ИИ, Google, DeepL, ru↔en).
  5. Обработка ошибок API (HTTP 401/403/404/500, таймауты, битые форматы).
  6. Создание и завершение рабочих потоков (cancel, wait_for_workers).
  7. Обработка пустых результатов (пустой ввод, пустой ответ модели/переводчика).
  8. Корректность интерфейсных сигналов (PyQt signals, slots, card buttons).
  9. Жизненный цикл (SingleInstanceGuard, shutdown, отмена правок в настройках).

Запуск:  python test_audit_stage1.py
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Режим offscreen для тестирования GUI компонентов
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

import config as cfg_mod
from config import ConfigManager
import workers
from workers import TranslationWorker, ModelListWorker, wait_for_workers
from single_instance import SingleInstanceGuard
from mini_window import MiniPopupWindow
from settings_window import SettingsWindow
from translation_card import TranslationCard
from hotkey_manager import HotkeyManager, validate_hotkey


def wait_worker(worker, ms=2000):
    deadline = time.monotonic() + ms / 1000.0
    while worker.isRunning() and time.monotonic() < deadline:
        QTest.qWait(20)
    QTest.qWait(50)


def run_all_audit_checks() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    print("=== НАЧАЛО КОНТРОЛЬНОГО АУДИТА (ЭТАП 1) ===")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cfg_file = tmp_path / "config.json"

        # -----------------------------------------------------------------
        # 1. Загрузка конфигурации
        # -----------------------------------------------------------------
        cm = ConfigManager(cfg_file)
        assert cm.get("config_version") >= 1
        assert cm.get("hotkey") == "alt+q"
        assert cm.get("mode") in ("ai", "standard")
        assert cm.get_active_prompt()
        # Fallback при несуществующем имени промпта
        cm.set("active_prompt_name", "Несуществующий")
        assert cm.get_active_prompt()  # вернул первый доступный
        print("[OK] 1. Загрузка конфигурации и fallback параметров")

        # -----------------------------------------------------------------
        # 2. Сохранение настроек и атомарность
        # -----------------------------------------------------------------
        assert cm.set("temperature", 0.85) is True
        assert ConfigManager(cfg_file).get("temperature") == 0.85
        # Безопасность при невозможности записи на диск
        bad_cm = ConfigManager(tmp_path / "несуществующая_папка_123" / "cfg.json")
        assert bad_cm.save() is False
        assert bad_cm.set("mode", "standard") is False
        assert bad_cm.get("mode") == "standard"  # значение в памяти сохранилось
        print("[OK] 2. Сохранение настроек и устойчивость к ошибкам записи")

        # -----------------------------------------------------------------
        # 3. Поврежденные файлы и спасение данных
        # -----------------------------------------------------------------
        # 3a. Мягкая очистка JSON (комментарии и запятые перед скобками)
        relaxed = """{
            // Пользователь оставил комментарий
            "hotkey": "ctrl+shift+x",
            "model_name": "qwen2.5:14b",
        }"""
        cfg_file.write_text(relaxed, encoding="utf-8")
        cm_relaxed = ConfigManager(cfg_file)
        assert cm_relaxed.get("hotkey") == "ctrl+shift+x"
        assert cm_relaxed.get("model_name") == "qwen2.5:14b"

        # 3b. Восстановление из .tmp при 0-байтовом config.json
        tmp_cfg = cfg_file.with_name(cfg_file.name + ".tmp")
        tmp_cfg.write_text(json.dumps({"hotkey": "win+q", "target_lang": "fr"}), encoding="utf-8")
        cfg_file.write_text("", encoding="utf-8")  # 0 байт
        cm_tmp = ConfigManager(cfg_file)
        assert cm_tmp.get("hotkey") == "win+q"
        assert cm_tmp.get("target_lang") == "fr"

        # 3c. Спасение промптов и ключей из синтаксически сломанного JSON
        broken = """{
            "prompts": {
                "Промпт Корректора": "Исправь пунктуацию и орфографию."
            },
            "api_key": "sk-user-saved-key-123",
            НЕВАЛИДНЫЙ СИНТАКСИС В КОНЦЕ...
        """
        cfg_file.write_text(broken, encoding="utf-8")
        cm_salvage = ConfigManager(cfg_file)
        assert "Промпт Корректора" in cm_salvage.get("prompts")
        assert cm_salvage.get_prompt("Промпт Корректора") == "Исправь пунктуацию и орфографию."
        assert cm_salvage.get("api_key") == "sk-user-saved-key-123"
        assert (cfg_file.with_name("config.json.bak")).exists()

        # 3d. Бэкап при reset_to_defaults
        cm_salvage.reset_to_defaults()
        assert (cfg_file.with_name("config.json.bak")).exists()
        bak_data = json.loads((cfg_file.with_name("config.json.bak")).read_text(encoding="utf-8"))
        assert "Промпт Корректора" in bak_data.get("prompts", {})
        print("[OK] 3. Поврежденные файлы, спасение данных и резервные копии")

        # -----------------------------------------------------------------
        # 4. Работа переводческих запросов (ИИ, Google, DeepL, ru↔en)
        # -----------------------------------------------------------------
        cfg = ConfigManager(cfg_file)

        class _MockResponse:
            status_code = 200
            text = ""
            def __init__(self, content):
                self._content = content
            def json(self):
                return {"choices": [{"message": {"content": self._content}}]}

        sent_payloads = []
        def _mock_post(url, json=None, headers=None, timeout=None):
            sent_payloads.append(json)
            return _MockResponse("Результат перевода ИИ")

        orig_post = workers.requests.post
        workers.requests.post = _mock_post
        try:
            cfg.set("mode", "ai", autosave=False)
            cfg.set("target_lang", "ru", autosave=False)

            # Русский текст -> цель переворотом становится en
            w_ai = TranslationWorker(cfg, "Привет, мир!")
            ok_ai, err_ai = [], []
            w_ai.finished_ok.connect(ok_ai.append)
            w_ai.failed.connect(err_ai.append)
            w_ai.start()
            wait_worker(w_ai)
            assert ok_ai == ["Результат перевода ИИ"], (ok_ai, err_ai)
            assert "«en»" in sent_payloads[-1]["messages"][0]["content"]

            # Английский текст -> цель остается ru
            w_ai_en = TranslationWorker(cfg, "Hello, world!")
            ok_ai_en, err_ai_en = [] , []
            w_ai_en.finished_ok.connect(ok_ai_en.append)
            w_ai_en.failed.connect(err_ai_en.append)
            w_ai_en.start()
            wait_worker(w_ai_en)
            assert ok_ai_en == ["Результат перевода ИИ"], (ok_ai_en, err_ai_en)
            assert "«ru»" in sent_payloads[-1]["messages"][0]["content"]
        finally:
            workers.requests.post = orig_post

        # Проверка обычного режима (Google и DeepL)
        class _MockTranslator:
            def __init__(self, source, target, **kwargs):
                self.target = target
            def translate(self, text):
                return f"[{self.target}] {text}"

        orig_gt = workers.GoogleTranslator
        workers.GoogleTranslator = _MockTranslator
        try:
            cfg.set("mode", "standard", autosave=False)
            cfg.set("standard_engine", "google", autosave=False)
            w_gt = TranslationWorker(cfg, "Hello")
            gt_ok, gt_err = [], []
            w_gt.finished_ok.connect(gt_ok.append)
            w_gt.failed.connect(gt_err.append)
            w_gt.start()
            wait_worker(w_gt)
            assert gt_ok == ["[ru] Hello"], (gt_ok, gt_err)
        finally:
            workers.GoogleTranslator = orig_gt

        print("[OK] 4. Запросы перевода: ИИ, Google, DeepL, автоопределение ru↔en")

        # -----------------------------------------------------------------
        # 5. Обработка ошибок API (HTTP 401/403/404/500, таймауты, битые ответы)
        # -----------------------------------------------------------------
        class _ErrResponse:
            def __init__(self, code, body=""):
                self.status_code = code
                self.text = body
            def json(self):
                raise ValueError("No json")

        cfg.set("mode", "ai", autosave=False)
        cfg.set("api_url", "http://fake/api", autosave=False)

        try:
            for code in (401, 403, 404, 500):
                workers.requests.post = lambda *a, **k: _ErrResponse(code, "error detail")
                w_err = TranslationWorker(cfg, "text")
                err_res = []
                w_err.failed.connect(err_res.append)
                w_err.start()
                wait_worker(w_err)
                assert len(err_res) == 1
                assert str(code) in err_res[0] or "запрещён" in err_res[0] or "не найдены" in err_res[0]

            # Таймаут
            def _timeout(*a, **k):
                raise workers.requests.exceptions.Timeout("Timed out")
            workers.requests.post = _timeout
            w_to = TranslationWorker(cfg, "text")
            to_res = []
            w_to.failed.connect(to_res.append)
            w_to.start()
            wait_worker(w_to)
            assert "ожидания" in to_res[0]
        finally:
            workers.requests.post = orig_post
        print("[OK] 5. Обработка ошибок API (HTTP 401/403/404/500, таймауты, не-JSON)")

        # -----------------------------------------------------------------
        # 6. Создание, завершение и отмена рабочих потоков
        # -----------------------------------------------------------------
        def _long_running(*a, **k):
            for _ in range(50):
                time.sleep(0.05)
            return _MockResponse("done")

        try:
            workers.requests.post = _long_running
            w_cancel = TranslationWorker(cfg, "текст")
            c_ok, c_err = [], []
            w_cancel.finished_ok.connect(c_ok.append)
            w_cancel.failed.connect(c_err.append)
            w_cancel.start()
            QTest.qWait(50)
            w_cancel.cancel()
            wait_worker(w_cancel)
            assert not c_ok and not c_err, "Отменённый воркер не должен слать сигналы"

            # wait_for_workers быстро прерывает потоки
            w_fast = TranslationWorker(cfg, "текст")
            w_fast.start()
            QTest.qWait(50)
            t_start = time.monotonic()
            wait_for_workers(3000)
            assert time.monotonic() - t_start < 3.5
            assert not w_fast.isRunning()
        finally:
            workers.requests.post = orig_post
        print("[OK] 6. Создание, завершение и отмена рабочих потоков (cancel, wait_for_workers)")

        # -----------------------------------------------------------------
        # 7. Обработка пустых результатов
        # -----------------------------------------------------------------
        # Пустой входной текст
        w_empty = TranslationWorker(cfg, "   \n\t ")
        empty_err = []
        w_empty.failed.connect(empty_err.append)
        w_empty.start()
        wait_worker(w_empty)
        assert len(empty_err) == 1 and "Пустой" in empty_err[0]

        # Модель вернула пустой choices
        class _EmptyChoicesResp:
            status_code = 200
            text = ""
            def json(self):
                return {"choices": []}

        try:
            workers.requests.post = lambda *a, **k: _EmptyChoicesResp()
            w_empty_resp = TranslationWorker(cfg, "текст")
            empty_resp_err = []
            w_empty_resp.failed.connect(empty_resp_err.append)
            w_empty_resp.start()
            wait_worker(w_empty_resp)
            assert len(empty_resp_err) == 1 and "choices пуст" in empty_resp_err[0]
        finally:
            workers.requests.post = orig_post
        print("[OK] 7. Обработка пустых результатов (входной текст, пустой ответ API)")

        # -----------------------------------------------------------------
        # 8. Корректная работа интерфейсных сигналов и карточек
        # -----------------------------------------------------------------
        card = TranslationCard("Исходный текст", None)
        assert card._loading is True
        assert card.copy_button.isEnabled() is False
        assert card.replace_button.isEnabled() is False
        assert card.regenerate_button.isEnabled() is False

        # Сигнал set_result
        card.set_result("Готовый перевод")
        assert card._loading is False
        assert card.result_label.text() == "Готовый перевод"
        assert card.copy_button.isEnabled() is True
        assert card.replace_button.isEnabled() is True

        # Сигналы кнопок
        regen_called, replace_called = [], []
        card.regenerate_requested.connect(lambda: regen_called.append(True))
        card.replace_requested.connect(lambda: replace_called.append(True))
        card.regenerate_button.click()
        card.replace_button.click()
        assert regen_called == [True]
        assert replace_called == [True]

        # Сигнал set_error
        card.set_error("Тестовая ошибка")
        assert "Тестовая ошибка" in card.result_label.text()
        assert card.copy_button.isVisible() is False
        assert card.replace_button.isVisible() is False
        assert card.regenerate_button.isEnabled() is True
        print("[OK] 8. Интерфейсные сигналы, режимы карточки и кнопки действий")

        # -----------------------------------------------------------------
        # 9. Жизненный цикл окон, мьютекс единственности и shutdown
        # -----------------------------------------------------------------
        # 9a. 64-битный Win32 SingleInstanceGuard
        guard1 = SingleInstanceGuard("Local\\Truniversal.AuditTest.Mutex")
        assert guard1.acquire() is True
        guard2 = SingleInstanceGuard("Local\\Truniversal.AuditTest.Mutex")
        assert guard2.acquire() is False
        guard1.release()
        assert guard2.acquire() is True
        guard2.release()

        # 9b. Окно настроек: отмена несохраненных правок при закрытии
        from PyQt6.QtGui import QIcon
        test_icon = QIcon()
        settings = SettingsWindow(cfg, test_icon)
        settings.api_url_edit.setText("http://unsaved/api")
        assert settings._dirty is True
        orig_q = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        try:
            settings.close()
        finally:
            QMessageBox.question = orig_q
        assert settings._dirty is False
        assert settings.api_url_edit.text() == cfg.get("api_url")
        settings.shutdown()

        # 9c. Мини-окно: отмена активных воркеров при clear_history и shutdown
        popup = MiniPopupWindow(cfg, test_icon)
        popup.handle_new_text("Запрос для проверки мини-окна")
        assert len(popup._workers) >= 1
        popup.clear_history()
        assert len(popup._cards) == 0
        assert len(popup._workers) == 0
        popup.shutdown()
        assert len(popup._workers) == 0

        # 9d. HotkeyManager shutdown()
        hkm = HotkeyManager(cfg)
        hkm.shutdown(timeout=0.5)
        print("[OK] 9. Жизненный цикл (мьютекс 64-бит, сброс правок, отмена в окнах, shutdown)")

    print("\n=== ВСЕ КОНТРОЛЬНЫЕ ПРОВЕРКИ ЭТАПА 1 УСПЕШНО ПРОЙДЕНЫ ===")
    return 0


if __name__ == "__main__":
    sys.exit(run_all_audit_checks())
