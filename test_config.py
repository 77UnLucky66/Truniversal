"""
test_config.py — быстрая самопроверка менеджера конфигурации (Шаг 1).

Запуск:  python test_config.py
Тесты работают во временной папке и не трогают реальный config.json.
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

    print("\nВсе проверки Шага 1 пройдены")


if __name__ == "__main__":
    run_tests()
