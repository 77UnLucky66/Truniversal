"""
test_config.py — самопроверка менеджера конфигурации (Шаг 1 + Этап 1).

Запуск:  python test_config.py
Тесты работают во временной папке и не трогают реальный config.json.
Проверяются: создание/чтение/сохранение, нормализация битых значений,
восстановление повреждённого JSON, версионирование и миграции схемы,
сохранность кириллицы, ошибки диска без исключений, полный сброс.
"""

import json
import tempfile
from pathlib import Path

from config import ConfigManager


def run_tests() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        cfg_path = Path(tmp_dir) / "config.json"

        # 1. Первый запуск: файл создаётся с дефолтами.
        cm = ConfigManager(cfg_path)
        assert cfg_path.exists(), "config.json должен быть создан автоматически"
        assert cm.get("hotkey") == "alt+q"
        assert cm.get("mode") == "ai"
        assert cm.get("standard_engine") == "google"
        assert cm.get("target_lang") == "ru"
        assert cm.get("api_url") == "http://localhost:11434/v1/chat/completions"
        assert cm.get("model_name") == "llama3"
        assert cm.get("temperature") == 0.3
        assert cm.get("top_p") == 0.9
        assert cm.get("active_prompt_name") == "Живой перевод"
        assert cm.get("config_version") == 2
        assert cm.get("hotkey_enabled") is True
        assert cm.get("diagnostics") is False
        assert cm.get("capture_delay_ms") == 120
        assert cm.get("capture_attempts") == 2
        assert set(cm.get("prompts")) == {
            "Живой перевод",
            "3 варианта перефразирования",
            "Исправление стилистики и грамматики",
        }
        assert "{target_lang}" in cm.get_prompt("Живой перевод")
        print("[OK] 1. Первый запуск — config.json создан с дефолтами")

        # 2. Изменения сохраняются и перечитываются с диска.
        cm.set("hotkey", "ctrl+shift+t")
        cm.set("active_prompt_name", "3 варианта перефразирования")
        cm.set("temperature", 0.7)
        cm_reloaded = ConfigManager(cfg_path)
        assert cm_reloaded.get("hotkey") == "ctrl+shift+t"
        assert cm_reloaded.get("active_prompt_name") == "3 варианта перефразирования"
        assert cm_reloaded.get("temperature") == 0.7
        print("[OK] 2. Сохранение и повторное чтение работают")

        # 3. Битые значения нормализуются, неизвестные ключи сохраняются.
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        raw["temperature"] = "совсем не число"
        raw["mode"] = "hacker_mode"
        raw["top_p"] = 99  # вне диапазона → прижмётся к 1.0
        raw["new_future_key"] = 42
        cfg_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        cm_fixed = ConfigManager(cfg_path)
        assert cm_fixed.get("temperature") == 0.3
        assert cm_fixed.get("mode") == "ai"
        assert cm_fixed.get("top_p") == 1.0
        assert cm_fixed.get("new_future_key") == 42
        print("[OK] 3. Нормализация битых значений + сохранение новых ключей")

        # 4. Повреждённый JSON → бэкап .bak + свежий конфиг с дефолтами.
        cfg_path.write_text("{ это не json ...", encoding="utf-8")
        cm_recovered = ConfigManager(cfg_path)
        assert cm_recovered.get("hotkey") == "alt+q"
        assert (cfg_path.with_name("config.json.bak")).exists()
        print("[OK] 4. Повреждённый JSON → бэкап + восстановление дефолтов")

        # 5. Удалённый пользователем пресет не «воскресает».
        del cm_recovered.data["prompts"]["3 варианта перефразирования"]
        cm_recovered.save()
        cm_after = ConfigManager(cfg_path)
        assert "3 варианта перефразирования" not in cm_after.get("prompts")
        assert "Живой перевод" in cm_after.get("prompts")
        print("[OK] 5. Удаление пресета промпта сохраняется между запусками")

        # 6. Активный пресет, которого нет, откатывается к существующему.
        cm_after.set("active_prompt_name", "Удалённый пресет")
        cm_final = ConfigManager(cfg_path)
        assert cm_final.get("active_prompt_name") in cm_final.get("prompts")
        assert cm_final.get_active_prompt()
        print("[OK] 6. Fallback активного промпта работает")

        # 7. Старый конфиг БЕЗ «config_version» миграцией получает штамп
        #    текущей версии — и штамп сохраняется на диск сразу.
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        raw.pop("config_version", None)
        cfg_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        cm_migrated = ConfigManager(cfg_path)
        assert cm_migrated.get("config_version") == 2
        on_disk = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert on_disk["config_version"] == 2, "версия не штампуется на диск"
        print("[OK] 7. Конфиг без версии мигрируется и штампуется на диске")

        # 8. Конфиг из БУДУЩЕЙ версии читается без потерь и не откатывается
        #    (обратная совместимость при даунгрейде приложения).
        future = json.loads(cfg_path.read_text(encoding="utf-8"))
        future["config_version"] = 99
        future["future_key"] = {"nested": [1, 2]}
        cfg_path.write_text(json.dumps(future, ensure_ascii=False), encoding="utf-8")
        cm_future = ConfigManager(cfg_path)
        assert cm_future.get("config_version") == 99, "версию из будущего откатили"
        assert cm_future.get("future_key") == {"nested": [1, 2]}
        print("[OK] 8. Конфиг из будущей версии не ломается и не откатывается")

        # 9. Кириллица в промптах переживает цикл запись → чтение без порчи.
        cyr_prompt = "Ёлки-палки: «{target_lang}», №1 — проверка кириллицы!"
        cm_cyr = ConfigManager(cfg_path)
        assert cm_cyr.set_prompt("Кириллический тест", cyr_prompt) is True
        assert ConfigManager(cfg_path).get_prompt("Кириллический тест") == cyr_prompt
        print("[OK] 9. Кириллица промптов сохраняется без повреждений")

        # 10. Ошибка диска не роняет приложение: save/set/update возвращают
        #     False, а не бросают исключение (GUI-слоты PyQt этого не прощают).
        bad_path = Path(tmp_dir) / "нет_такой_папки" / "config.json"
        cm_bad = ConfigManager(bad_path)            # первый запуск тоже не падает
        assert cm_bad.save() is False
        assert cm_bad.set("hotkey", "ctrl+q") is False
        assert cm_bad.get("hotkey") == "ctrl+q"    # в памяти значение есть
        assert cm_bad.update({"mode": "standard"}) is False
        print("[OK] 10. Ошибка записи config.json не бросает исключения")

        # 11. Полный сброс возвращает заводское состояние (вместе с версией).
        cm_reset = ConfigManager(cfg_path)
        cm_reset.data["prompts"]["Мой личный промпт"] = "мой текст"
        cm_reset.set("hotkey", "ctrl+shift+d")
        assert cm_reset.reset_to_defaults() is True
        assert cm_reset.get("hotkey") == "alt+q"
        assert "Мой личный промпт" not in cm_reset.get("prompts")
        assert cm_reset.get("config_version") == 2
        assert ConfigManager(cfg_path).data == cm_reset.data
        print("[OK] 11. Сброс к дефолтам возвращает исходное состояние")

        # 12. Ключи Этапа 2: пустой хоткей допустим («не задан»), числовые
        #     границы соблюдаются, строковые булевы значения распознаются.
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        raw["hotkey"] = ""
        raw["capture_delay_ms"] = 99999
        raw["capture_attempts"] = 0
        raw["hotkey_enabled"] = "да"
        raw["diagnostics"] = 1
        cfg_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        cm12 = ConfigManager(cfg_path)
        assert cm12.get("hotkey") == "", "пустой хоткей должен сохраняться"
        assert cm12.get("capture_delay_ms") == 2000, "верхняя граница"
        assert cm12.get("capture_attempts") == 1, "нижняя граница"
        assert cm12.get("hotkey_enabled") is True, "строка «да» распознаётся"
        assert cm12.get("diagnostics") is True, "число 1 распознаётся как true"
        print("[OK] 12. Ключи Этапа 2: пустой хоткей, границы, булевы строки")

        # 13. Мягкая очистка JSON: концевые запятые и комментарии не приводят к сбросу
        relaxed_json = """{
            // Пользовательский комментарий
            # Ещё один комментарий
            "hotkey": "ctrl+alt+z",
            "api_url": "http://custom:11434/v1/chat/completions",
            "temperature": 0.45,
        }"""
        cfg_path.write_text(relaxed_json, encoding="utf-8")
        cm13 = ConfigManager(cfg_path)
        assert cm13.get("hotkey") == "ctrl+alt+z"
        assert cm13.get("temperature") == 0.45
        assert cm13.get("api_url") == "http://custom:11434/v1/chat/completions"
        print("[OK] 13. Мягкая очистка JSON: комментарии и запятые исправлены без потери настроек")

        # 14. Восстановление из .tmp при повреждении/исчезновении config.json (сбой записи)
        tmp_file = cfg_path.with_name(cfg_path.name + ".tmp")
        tmp_content = {"hotkey": "win+alt+t", "target_lang": "de"}
        tmp_file.write_text(json.dumps(tmp_content, ensure_ascii=False), encoding="utf-8")
        cfg_path.unlink()  # имитируем прерывание os.replace
        cm14 = ConfigManager(cfg_path)
        assert cm14.get("hotkey") == "win+alt+t"
        assert cm14.get("target_lang") == "de"
        assert not tmp_file.exists()  # временный файл перенесён на место
        print("[OK] 14. Восстановление config.json из .tmp файла при аварийном прерывании")

        # 15. Спасение пользовательских промптов при невалидном синтаксисе JSON
        broken_json = """{
            "prompts": {
                "Уникальный авторский промпт": "Точно сохрани авторский стиль и сленг."
            },
            "api_key": "secret-user-key",
            это не json и парсер упадёт тут...
        """
        cfg_path.write_text(broken_json, encoding="utf-8")
        cm15 = ConfigManager(cfg_path)
        assert "Уникальный авторский промпт" in cm15.get("prompts")
        assert cm15.get_prompt("Уникальный авторский промпт") == "Точно сохрани авторский стиль и сленг."
        assert cm15.get("api_key") == "secret-user-key"
        print("[OK] 15. Спасение пользовательских промптов и настроек из повреждённого файла")

        # 16. Бэкап при сбросе настроек: старые настройки сохраняются в *.bak
        cm16 = ConfigManager(cfg_path)
        cm16.set_prompt("Важный промпт перед сбросом", "Не потеряй меня!")
        bak_file = cfg_path.with_name(cfg_path.name + ".bak")
        cm16.reset_to_defaults()
        assert bak_file.exists()
        bak_data = json.loads(bak_file.read_text(encoding="utf-8"))
        assert "Важный промпт перед сбросом" in bak_data.get("prompts", {})
        print("[OK] 16. reset_to_defaults создаёт резервную копию .bak для защиты данных")

        # 17. Последовательная цепочка миграций схемы
        import config as cfg_module
        orig_version = cfg_module.CONFIG_VERSION
        orig_migrations = dict(cfg_module._CONFIG_MIGRATIONS)
        try:
            cfg_module.CONFIG_VERSION = 3
            cfg_module._CONFIG_MIGRATIONS[1] = lambda d: d.update({"migrated_to_2": True})
            cfg_module._CONFIG_MIGRATIONS[2] = lambda d: d.update({"migrated_to_3": "done"})
            v1_data = {"config_version": 1, "hotkey": "alt+m"}
            cfg_path.write_text(json.dumps(v1_data), encoding="utf-8")
            cm17 = ConfigManager(cfg_path)
            assert cm17.get("config_version") == 3
            assert cm17.get("migrated_to_2") is True
            assert cm17.get("migrated_to_3") == "done"
            assert cm17.get("hotkey") == "alt+m"
        finally:
            cfg_module.CONFIG_VERSION = orig_version
            cfg_module._CONFIG_MIGRATIONS = orig_migrations
        print("[OK] 17. Цепочка последовательных миграций схемы v1 → v2 → v3")

        # 18. Этап 3: Профили ИИ (CRUD, дублирование, выбор активного)
        cm18 = ConfigManager(cfg_path)
        profiles = cm18.get_profiles()
        assert len(profiles) >= 3, "Должно быть минимум 3 профиля по умолчанию"
        active = cm18.get_active_profile()
        assert active is not None
        assert active["id"] == cm18.get_active_profile_id()

        # Создание нового профиля
        new_prof = {
            "name": "Тестовый профиль",
            "provider_type": "custom",
            "api_url": "http://127.0.0.1:8080/v1/chat/completions",
            "model_name": "qwen2.5:7b",
            "temperature": 0.5,
            "top_p": 0.95,
        }
        res = cm18.save_profile(new_prof, api_key="test-key-18")
        assert res is True
        prof_id = new_prof["id"]
        assert cm18.get_profile_by_id(prof_id)["name"] == "Тестовый профиль"
        assert cm18.get_profile_api_key(prof_id) == "test-key-18"

        # Переключение активного профиля
        assert cm18.set_active_profile(prof_id) is True
        assert cm18.get_active_profile_id() == prof_id
        # Проверка обратной совместимости get("api_url") и get("model_name")
        assert cm18.get("api_url") == "http://127.0.0.1:8080/v1/chat/completions"
        assert cm18.get("model_name") == "qwen2.5:7b"
        assert cm18.get("temperature") == 0.5

        # Дублирование профиля
        dup_id = cm18.duplicate_profile(prof_id)
        assert dup_id is not None
        assert dup_id != prof_id
        dup = cm18.get_profile_by_id(dup_id)
        assert dup is not None
        assert "копия" in dup["name"].lower()
        assert dup["api_url"] == new_prof["api_url"]
        assert cm18.get_profile_api_key(dup_id) == "test-key-18"

        # Удаление профиля (нельзя удалить последний)
        assert cm18.delete_profile(dup_id) is True
        assert cm18.get_profile_by_id(dup_id) is None
        print("[OK] 18. Этап 3: Профили ИИ — CRUD, дублирование и синхронизация legacy-ключей")

        # 19. Этап 3: Безопасное хранение ключей в Credential Manager
        from credentials import is_secure_storage_available, mask_key
        assert mask_key("sk-1234567890abcdef") == "sk-••••cdef"
        assert mask_key("short") == "••••••••"
        assert mask_key("") == ""
        # Проверяем, что в config.json ключ не лежит в открытом виде, если доступно защищённое хранилище
        if is_secure_storage_available():
            on_disk = json.loads(cfg_path.read_text(encoding="utf-8"))
            for p in on_disk.get("ai_profiles", {}).values():
                if isinstance(p, dict) and p.get("id") == prof_id:
                    assert not p.get("api_key"), "Ключ не должен сохраняться в JSON при рабочем Credential Manager"
        print("[OK] 19. Этап 3: Безопасное хранение и маскирование API-ключей")

        # 20. Этап 3: Миграция v1 → v2 с сохранением пользовательских настроек ИИ
        v1_cfg = {
            "config_version": 1,
            "hotkey": "ctrl+shift+x",
            "api_url": "https://api.mycustomai.com/v1/chat/completions",
            "model_name": "my-custom-model",
            "temperature": 0.42,
            "api_key": "v1-migrated-secret",
        }
        cfg_path.write_text(json.dumps(v1_cfg, ensure_ascii=False), encoding="utf-8")
        cm20 = ConfigManager(cfg_path)
        assert cm20.get("config_version") == 2
        active20 = cm20.get_active_profile()
        assert active20 is not None
        assert active20["api_url"] == "https://api.mycustomai.com/v1/chat/completions"
        assert active20["model_name"] == "my-custom-model"
        assert active20["temperature"] == 0.42
        assert cm20.get_profile_api_key(active20["id"]) == "v1-migrated-secret"
        print("[OK] 20. Этап 3: Миграция старого конфига v1 → v2 с профилями и защитой ключей")

    print("\nВсе проверки конфигурации пройдены (Этапы 1–3)")


if __name__ == "__main__":
    run_tests()
