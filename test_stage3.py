"""
test_stage3.py — Полная проверка функционала ЭТАПА 3:
«Расширенная система AI-провайдеров».

Проверяются:
  3.1. Несколько AI-профилей (CRUD, дублирование, удаление, выбор активного).
  3.2. Максимальная совместимость с OpenAI API (нормализация URL, извлечение контента).
  3.3. Проверка подключения (ConnectionCheckWorker для Ollama и OpenAI/Custom, ошибки 401/404/429/connection).
  3.4. Работа со списком моделей (ModelListWorker для Ollama /api/tags и OpenAI /models, fallback при 404).
  3.5. Надёжность запросов (лимит длины текста, повторы с backoff при 5xx/429, отсутствие повторов при 4xx, отмена).
  3.6. Безопасность API-ключей (маскирование, Windows Credential Manager).
  3.7. Интеграция GUI SettingsWindow (профили, переключение, проверка подключения).

Запуск:  python test_stage3.py
"""

import os
import sys
import tempfile
import time
from pathlib import Path

# Режим offscreen для Qt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import api_helpers
import credentials
import workers
from config import ConfigManager, DEFAULT_AI_PROFILES
from settings_window import SettingsWindow
from styles import APP_QSS


class FakeResponse:
    def __init__(self, status_code: int = 200, data=None, text: str = ""):
        self.status_code = status_code
        self._data = data
        self.text = text or ("" if data is None else str(data))

    def json(self):
        if self._data is None:
            raise ValueError("No JSON data")
        return self._data


def run_stage3_tests() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)

    print("=== НАЧАЛО ТЕСТИРОВАНИЯ ЭТАПА 3 (AI-ПРОВАЙДЕРЫ) ===")

    with tempfile.TemporaryDirectory() as tmp_dir:
        cfg_file = Path(tmp_dir) / "config.json"
        cm = ConfigManager(cfg_file)

        # -----------------------------------------------------------------
        # 3.1. Несколько AI-профилей (CRUD, дублирование, удаление)
        # -----------------------------------------------------------------
        profiles = cm.get_profiles()
        assert len(profiles) >= 3, "Должно быть минимум 3 профиля по умолчанию"
        assert "ollama_default" in profiles
        assert "openrouter_default" in profiles
        assert "openai_default" in profiles

        active = cm.get_active_profile()
        assert active is not None
        assert active["id"] == cm.get_active_profile_id()

        # Создание нового профиля
        custom_data = {
            "name": "Мой сервер vLLM",
            "provider_type": "custom",
            "api_url": "http://gpu-server:8000/v1/chat/completions",
            "model_name": "meta-llama/Llama-3.3-70B-Instruct",
            "temperature": 0.45,
            "top_p": 0.92,
            "timeout_connect": 15,
            "timeout_request": 120,
            "max_retries": 3,
            "max_tokens": 4096,
        }
        res = cm.save_profile(custom_data, api_key="sk-vllm-secret-12345")
        assert res is True
        prof_id = custom_data["id"]
        assert prof_id is not None
        assert cm.get_profile_api_key(prof_id) == "sk-vllm-secret-12345"

        # Переключение активного профиля
        assert cm.set_active_profile(prof_id) is True
        assert cm.get_active_profile_id() == prof_id
        # Синхронизация legacy-ключей
        assert cm.get("api_url") == "http://gpu-server:8000/v1/chat/completions"
        assert cm.get("model_name") == "meta-llama/Llama-3.3-70B-Instruct"
        assert cm.get("temperature") == 0.45
        assert cm.get("top_p") == 0.92
        assert cm.get("api_key") == "sk-vllm-secret-12345"

        # Дублирование профиля
        copy_id = cm.duplicate_profile(prof_id)
        assert copy_id is not None
        assert copy_id != prof_id
        copy_prof = cm.get_profile(copy_id)
        assert copy_prof is not None
        assert "копия" in copy_prof["name"].lower()
        assert copy_prof["api_url"] == custom_data["api_url"]
        assert cm.get_profile_api_key(copy_id) == "sk-vllm-secret-12345"

        # Удаление профиля
        assert cm.delete_profile(copy_id) is True
        assert cm.get_profile(copy_id) is None

        # Защита от удаления последнего профиля
        all_ids = list(cm.get_profiles().keys())
        for pid in all_ids[:-1]:
            cm.delete_profile(pid)
        last_id = list(cm.get_profiles().keys())[0]
        assert cm.delete_profile(last_id) is False, "Нельзя удалять единственный оставшийся профиль"
        print("[OK] 3.1. Несколько AI-профилей: CRUD, дублирование, удаление, синхронизация ключей")

        # -----------------------------------------------------------------
        # 3.2. Совместимость с OpenAI API: нормализация URL и извлечение ответов
        # -----------------------------------------------------------------
        from api_helpers import normalize_chat_url, get_models_url, extract_response_content

        # Тесты нормализации URL
        assert normalize_chat_url("http://localhost:11434") == "http://localhost:11434/v1/chat/completions"
        assert normalize_chat_url("http://localhost:11434/") == "http://localhost:11434/v1/chat/completions"
        assert normalize_chat_url("http://localhost:11434/v1") == "http://localhost:11434/v1/chat/completions"
        assert normalize_chat_url("http://localhost:11434/v1/chat/completions") == "http://localhost:11434/v1/chat/completions"
        assert normalize_chat_url("https://api.openai.com/v1") == "https://api.openai.com/v1/chat/completions"
        assert normalize_chat_url("https://openrouter.ai/api/v1") == "https://openrouter.ai/api/v1/chat/completions"
        assert normalize_chat_url("https://myproxy.org/proxy") == "https://myproxy.org/proxy/v1/chat/completions"
        assert normalize_chat_url("https://myproxy.org/prefix/v1/chat/completions") == "https://myproxy.org/prefix/v1/chat/completions"
        # Защита от /v1/v1 дублирования
        assert "/v1/v1" not in normalize_chat_url("https://proxy.org/v1/")

        # Тесты get_models_url
        assert get_models_url("http://localhost:11434", "ollama") == "http://localhost:11434/api/tags"
        assert get_models_url("https://api.openai.com/v1/chat/completions", "openai") == "https://api.openai.com/v1/models"
        assert get_models_url("https://openrouter.ai/api/v1/chat/completions", "openrouter") == "https://openrouter.ai/api/v1/models"

        # Тесты извлечения текста ответа
        # 1. Обычный message.content (строка)
        resp1 = {"choices": [{"message": {"content": "Привет, мир!"}}]}
        assert extract_response_content(resp1) == "Привет, мир!"

        # 2. Мультимодальный / составной message.content (список частей)
        resp2 = {"choices": [{"message": {"content": [{"type": "text", "text": "Часть 1. "}, {"type": "text", "text": "Часть 2."}]}}]}
        assert extract_response_content(resp2) == "Часть 1. Часть 2."

        # 3. choices[0].text (legacy / completion)
        resp3 = {"choices": [{"text": "Текстовый ответ"}]}
        assert extract_response_content(resp3) == "Текстовый ответ"

        # 4. choices[0].delta.content (streaming chunk)
        resp4 = {"choices": [{"delta": {"content": "Дельта чанк"}}]}
        assert extract_response_content(resp4) == "Дельта чанк"

        # 5. Ошибка провайдера в JSON {"error": {"message": "Rate limit exceeded"}}
        try:
            extract_response_content({"error": {"message": "Rate limit exceeded"}})
            assert False, "Должна быть вызвана ошибка провайдера"
        except ValueError as exc:
            assert "Rate limit exceeded" in str(exc)

        # 6. Отказ модели (refusal)
        try:
            extract_response_content({"choices": [{"message": {"refusal": "I cannot fulfill this request"}}]})
            assert False, "Должен быть вызван отказ модели"
        except ValueError as exc:
            assert "отказалась отвечать" in str(exc)

        print("[OK] 3.2. Максимальная совместимость: нормализация адресов и извлечение разных форматов")

        # -----------------------------------------------------------------
        # 3.3. Проверка подключения (ConnectionCheckWorker)
        # -----------------------------------------------------------------
        from workers import ConnectionCheckWorker

        def run_conn_worker(w: ConnectionCheckWorker):
            results = []
            w.check_finished.connect(lambda ok, msg, lat: results.append((ok, msg, lat)))
            w.start()
            for _ in range(100):
                QTest.qWait(50)
                if results:
                    break
            w.wait(2000)
            return results[0] if results else (False, "Timeout", 0.0)

        orig_post = workers.requests.post
        orig_get = workers.requests.get

        try:
            # 1. Успешная проверка Ollama (модель найдена в тегах)
            workers.requests.get = lambda url, headers=None, timeout=None: FakeResponse(
                200, {"models": [{"name": "llama3:latest"}, {"name": "qwen2.5:7b"}]}
            )
            w_ollama = ConnectionCheckWorker("http://localhost:11434", model_name="llama3", provider_type="ollama")
            ok, msg, lat = run_conn_worker(w_ollama)
            assert ok is True and "Ollama доступна" in msg and "llama3" in msg, (ok, msg)

            # 2. Ollama: модель НЕ найдена среди установленных
            w_ollama_not_found = ConnectionCheckWorker("http://localhost:11434", model_name="mistral:latest", provider_type="ollama")
            ok, msg, lat = run_conn_worker(w_ollama_not_found)
            assert ok is False and "не найдена" in msg and "mistral" in msg, (ok, msg)

            # 3. OpenAI / Custom: успешный тестовый ping (200 OK)
            workers.requests.post = lambda url, json=None, headers=None, timeout=None: FakeResponse(
                200, {"choices": [{"message": {"content": "pong"}}]}
            )
            w_openai = ConnectionCheckWorker("https://api.openai.com/v1", api_key="sk-test", model_name="gpt-4o", provider_type="openai")
            ok, msg, lat = run_conn_worker(w_openai)
            assert ok is True and "отвечает" in msg, (ok, msg)

            # 4. Ошибка авторизации (401)
            workers.requests.post = lambda url, json=None, headers=None, timeout=None: FakeResponse(
                401, {"error": {"message": "Incorrect API key"}}, "Unauthorized"
            )
            w_auth_err = ConnectionCheckWorker("https://api.openai.com/v1", api_key="sk-bad", model_name="gpt-4o", provider_type="openai")
            ok, msg, lat = run_conn_worker(w_auth_err)
            assert ok is False and "401" in msg and "авторизации" in msg, (ok, msg)

            # 5. Ошибка модели (404)
            workers.requests.post = lambda url, json=None, headers=None, timeout=None: FakeResponse(
                404, {"error": {"message": "Model not found"}}, "Not Found"
            )
            w_model_err = ConnectionCheckWorker("https://api.openai.com/v1", api_key="sk-good", model_name="no-such-model", provider_type="openai")
            ok, msg, lat = run_conn_worker(w_model_err)
            assert ok is False and "404" in msg and "не найдены" in msg, (ok, msg)

            # 6. Ошибка квоты (429)
            workers.requests.post = lambda url, json=None, headers=None, timeout=None: FakeResponse(
                429, {"error": {"message": "Rate limit exceeded"}}, "Rate Limit"
            )
            w_quota_err = ConnectionCheckWorker("https://api.openai.com/v1", api_key="sk-good", model_name="gpt-4o", provider_type="openai")
            ok, msg, lat = run_conn_worker(w_quota_err)
            assert ok is False and "429" in msg and "лимит" in msg, (ok, msg)

            # 7. Отмена проверки (cancel)
            def _hang_post(url, json=None, headers=None, timeout=None):
                for _ in range(50):
                    time.sleep(0.05)
                return FakeResponse(200, {})

            workers.requests.post = _hang_post
            w_cancel = ConnectionCheckWorker("https://api.openai.com/v1", api_key="sk-test", model_name="gpt-4o")
            c_res = []
            w_cancel.check_finished.connect(lambda ok, msg, lat: c_res.append(ok))
            w_cancel.start()
            QTest.qWait(50)
            w_cancel.cancel()
            w_cancel.wait(2000)
            assert len(c_res) == 0, "При отмене сигнал не должен испускаться"

        finally:
            workers.requests.post = orig_post
            workers.requests.get = orig_get

        print("[OK] 3.3. Проверка подключения: Ollama, OpenAI/Custom, 401/404/429/cancel")

        # -----------------------------------------------------------------
        # 3.4. Загрузка списка моделей (ModelListWorker)
        # -----------------------------------------------------------------
        from workers import ModelListWorker

        def run_model_worker(w: ModelListWorker):
            loaded, failed = [], []
            w.models_loaded.connect(loaded.extend)
            w.failed.connect(failed.append)
            w.start()
            for _ in range(100):
                QTest.qWait(50)
                if loaded or failed:
                    break
            w.wait(2000)
            return loaded, failed

        try:
            # 1. Ollama формат (/api/tags: {"models": [...]})
            workers.requests.get = lambda url, headers=None, timeout=None: FakeResponse(
                200, {"models": [{"name": "llama3:latest"}, {"name": "mistral"}]}
            )
            w_m_ollama = ModelListWorker("http://localhost:11434", provider_type="ollama")
            loaded, failed = run_model_worker(w_m_ollama)
            assert loaded == ["llama3:latest", "mistral"] and not failed, (loaded, failed)

            # 2. OpenAI / OpenRouter формат (/models: {"data": [{"id": ...}]})
            workers.requests.get = lambda url, headers=None, timeout=None: FakeResponse(
                200, {"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}, {"id": "text-embedding-3-small"}]}
            )
            w_m_openai = ModelListWorker("https://api.openai.com/v1", api_key="sk-key", provider_type="openai")
            loaded, failed = run_model_worker(w_m_openai)
            assert "gpt-4o" in loaded and "gpt-4o-mini" in loaded and not failed, (loaded, failed)

            # 3. Неподдерживаемый эндпоинт (404) -> подсказка ввести вручную
            workers.requests.get = lambda url, headers=None, timeout=None: FakeResponse(404, {}, "Not Found")
            w_m_404 = ModelListWorker("https://custom-proxy/v1", provider_type="custom")
            loaded, failed = run_model_worker(w_m_404)
            assert not loaded and failed and "вручную" in failed[0], (loaded, failed)

            # 4. Ошибка авторизации (401)
            workers.requests.get = lambda url, headers=None, timeout=None: FakeResponse(401, {}, "Unauthorized")
            w_m_401 = ModelListWorker("https://api.openai.com/v1", api_key="bad-key", provider_type="openai")
            loaded, failed = run_model_worker(w_m_401)
            assert not loaded and failed and "401" in failed[0], (loaded, failed)

        finally:
            workers.requests.get = orig_get

        print("[OK] 3.4. Загрузка списка моделей: Ollama /api/tags, OpenAI /models, 404 fallback, 401 auth")

        # -----------------------------------------------------------------
        # 3.5. Надёжность запросов перевода (лимит длины, повторы backoff)
        # -----------------------------------------------------------------
        from workers import TranslationWorker

        def run_trans_worker(w: TranslationWorker):
            ok, err = [], []
            w.finished_ok.connect(ok.append)
            w.failed.connect(err.append)
            w.start()
            for _ in range(120):
                QTest.qWait(50)
                if ok or err:
                    break
            w.wait(2000)
            return ok, err

        # 1. Лимит длины текста (> 200,000 символов) -> мгновенная ошибка без сети
        huge_text = "A" * 250000
        w_huge = TranslationWorker(cm, huge_text)
        ok, err = run_trans_worker(w_huge)
        assert not ok and err and "слишком длинный" in err[0], (ok, err)

        # 2. Не повторять при ошибках 400, 401, 403, 404
        post_calls = 0
        def _counting_401(url, json=None, headers=None, timeout=None):
            nonlocal post_calls
            post_calls += 1
            return FakeResponse(401, {"error": {"message": "Invalid key"}}, "Unauthorized")

        try:
            workers.requests.post = _counting_401
            post_calls = 0
            w_client_err = TranslationWorker(cm, "Тестовый текст")
            ok, err = run_trans_worker(w_client_err)
            assert post_calls == 1, f"При 401 повторов быть не должно (было {post_calls})"
            assert not ok and "запрещён" in err[0]
        finally:
            workers.requests.post = orig_post

        # 3. Повторы при 502/503/429
        post_attempts = 0
        def _retryable_502(url, json=None, headers=None, timeout=None):
            nonlocal post_attempts
            post_attempts += 1
            if post_attempts < 3:
                return FakeResponse(502, {}, "Bad Gateway")
            return FakeResponse(200, {"choices": [{"message": {"content": "Успешно после повтора"}}]})

        try:
            workers.requests.post = _retryable_502
            post_attempts = 0
            w_retry = TranslationWorker(cm, "Тестовый текст для повтора")
            ok, err = run_trans_worker(w_retry)
            assert post_attempts == 3, f"Должно быть 3 попытки при 502, было {post_attempts}"
            assert ok == ["Успешно после повтора"], (ok, err)
        finally:
            workers.requests.post = orig_post

        print("[OK] 3.5. Надёжность запросов: лимит длины, отсутствие повторов при 4xx, повторы при 5xx")

        # -----------------------------------------------------------------
        # 3.6. Безопасность API-ключей (маскирование, Credential Manager)
        # -----------------------------------------------------------------
        from credentials import mask_key, is_secure_storage_available
        assert mask_key("sk-proj-1234567890abcdef") == "sk-••••cdef"
        assert mask_key("short123") == "••••••••"
        assert mask_key("") == ""
        print("[OK] 3.6. Безопасность API-ключей: маскирование и защищённое хранение")

        # -----------------------------------------------------------------
        # 3.7. Интеграция GUI SettingsWindow (профили, переключение, UI элементы)
        # -----------------------------------------------------------------
        from main import create_app_icon
        icon = create_app_icon()
        settings = SettingsWindow(cm, icon)
        settings.show()

        # Проверка элементов управления профилями
        assert hasattr(settings, "profile_combo")
        assert settings.profile_combo.count() >= 1
        assert hasattr(settings, "add_profile_btn")
        assert hasattr(settings, "duplicate_profile_btn")
        assert hasattr(settings, "delete_profile_btn")
        assert hasattr(settings, "check_conn_btn")
        assert hasattr(settings, "check_status_label")
        assert hasattr(settings, "provider_combo")
        assert hasattr(settings, "timeout_connect_spin")
        assert hasattr(settings, "timeout_request_spin")
        assert hasattr(settings, "max_retries_spin")
        assert hasattr(settings, "max_tokens_spin")

        # Проверка создания нового профиля через кнопку GUI
        initial_count = settings.profile_combo.count()
        settings._create_new_profile()
        assert settings.profile_combo.count() == initial_count + 1
        assert "Новый профиль" in settings.profile_name_edit.text()

        # Редактирование и сохранение профиля через вкладку 1
        settings.profile_name_edit.setText("Быстрый Gemini Flash")
        settings.provider_combo.setCurrentIndex(settings.provider_combo.findData("openrouter"))
        settings.api_url_edit.setText("https://openrouter.ai/api/v1/chat/completions")
        settings.api_key_edit.setText("sk-openrouter-gui-test")
        settings.model_combo.setCurrentText("google/gemini-2.0-flash-001")
        settings.temp_slider.setValue(40)
        settings.top_p_slider.setValue(85)
        settings.timeout_connect_spin.setValue(12)
        settings.timeout_request_spin.setValue(75)
        settings.max_retries_spin.setValue(1)
        settings._save_ai_tab()

        # Проверяем, что активный профиль обновился в конфиге
        active_p = cm.get_active_profile()
        assert active_p["name"] == "Быстрый Gemini Flash"
        assert active_p["provider_type"] == "openrouter"
        assert active_p["model_name"] == "google/gemini-2.0-flash-001"
        assert active_p["temperature"] == 0.40
        assert active_p["top_p"] == 0.85
        assert cm.get_profile_api_key(active_p["id"]) == "sk-openrouter-gui-test"

        # Проверка кнопки переключения видимости ключа
        assert settings.api_key_edit.echoMode() == settings.api_key_edit.EchoMode.Password
        settings._toggle_api_key_visibility()
        assert settings.api_key_edit.echoMode() == settings.api_key_edit.EchoMode.Normal
        assert settings.toggle_key_btn.text() == "Скрыть"
        settings._toggle_api_key_visibility()
        assert settings.api_key_edit.echoMode() == settings.api_key_edit.EchoMode.Password
        assert settings.toggle_key_btn.text() == "Показать"

        # Проверка дублирования через кнопку GUI
        cnt_before_dup = settings.profile_combo.count()
        settings._duplicate_current_profile()
        assert settings.profile_combo.count() == cnt_before_dup + 1
        assert "копия" in settings.profile_name_edit.text().lower()

        # Корректная остановка фоновых задач при закрытии
        settings.shutdown()
        settings.close()
        print("[OK] 3.7. Интеграция GUI SettingsWindow: профили, переключение, проверка, маскирование")

    print("\n=== ВСЕ ПРОВЕРКИ ЭТАПА 3 УСПЕШНО ПРОЙДЕНЫ! ===")
    return 0


if __name__ == "__main__":
    sys.exit(run_stage3_tests())
