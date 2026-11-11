"""
test_stage4.py — полный комплект тестов для ЭТАПА 4 (Система языков и автоопределение).

Проверяет:
  4.1. Централизованный каталог языков, адаптация кодов под Google, DeepL, AI,
       интеграция и сохранение настроек языков в SettingsWindow.
  4.2. Автоматическое определение языка и обработка сложных случаев:
       - короткие фразы и приветствия;
       - смешанный текст (код, заимствования, технические термины);
       - числа, знаки препинания, имена собственные (без ложных догадок);
       - разделение языков с общим алфавитом: украинский vs русский
         (как с уникальными буквами, так и без них, по словарю);
       - латинские языки с диакритикой (немецкий, французский, испанский, польский);
       - восточноазиатские письменности (китайский, японский, корейский).
  4.3. Автоматический выбор направления (resolve_translation_direction):
       - авто-переворот, если текст уже на целевом языке;
       - отсутствие переворота при отличии от целевого;
       - соблюдение ручного выбора исходного языка;
       - отсутствие мутаций глобального конфига.
  4.4. Интеграция в мини-окно и карточку:
       - отображение бейджа направления (напр. EN → RU);
       - кнопка быстрой смены направления ⇄;
       - выбор другого целевого языка из карточки;
       - перегенерация перевода с обновлённым направлением.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Рисуем offscreen для тестов GUI
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import languages
from languages import (
    LANGUAGES_CATALOG,
    AUTO_LANG_CODE,
    adapt_language_code,
    detect_language,
    get_language,
    get_language_name,
    get_supported_languages,
    resolve_translation_direction,
)
from config import ConfigManager
from settings_window import SettingsWindow
from mini_window import MiniPopupWindow
from translation_card import TranslationCard
from workers import TranslationWorker


def test_4_1_catalog_and_settings(app: QApplication) -> None:
    print("\n--- 4.1. Каталог языков, адаптация кодов и настройки ---")
    # Проверка каталога
    catalog = get_supported_languages()
    assert len(catalog) >= 15, f"Ожидалось >= 15 языков, получено {len(catalog)}"
    codes = {l.code for l in catalog}
    for required in ("ru", "en", "de", "fr", "es", "it", "pt", "pl", "uk", "zh", "ja", "ko"):
        assert required in codes, f"Язык {required} отсутствует в каталоге"

    # Имена и поиск
    assert get_language_name("ru") == "Русский"
    assert get_language_name("en") == "Английский"
    assert get_language_name("auto") == "Автоопределение"
    assert get_language("zh-cn").code == "zh"

    # Адаптация кодов Google
    assert adapt_language_code("google", "zh", is_target=True) == "zh-cn"
    assert adapt_language_code("google", "en", is_target=True) == "en"

    # Адаптация кодов DeepL
    assert adapt_language_code("deepl", "en", is_target=True) == "EN-US"
    assert adapt_language_code("deepl", "pt", is_target=True) == "PT-PT"
    assert adapt_language_code("deepl", "ru", is_target=False) == "RU"

    # Адаптация для системного промпта ИИ
    assert "русский" in adapt_language_code("ai", "ru")
    assert "английский" in adapt_language_code("ai", "en")

    # Интеграция с SettingsWindow
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.json"
        cfg = ConfigManager(cfg_path)
        assert cfg.get("source_lang") == "auto"
        assert cfg.get("target_lang") == "ru"
        assert cfg.get("fallback_target_lang") == "en"

        settings = SettingsWindow(cfg, app_icon=app.windowIcon())
        # Проверяем наличие всех комбо-боксов
        assert hasattr(settings, "source_lang_combo")
        assert hasattr(settings, "lang_combo")
        assert hasattr(settings, "fallback_lang_combo")

        # Меняем значения через GUI
        settings.source_lang_combo.setCurrentIndex(settings.source_lang_combo.findData("en"))
        settings.lang_combo.setCurrentIndex(settings.lang_combo.findData("de"))
        settings.fallback_lang_combo.setCurrentIndex(settings.fallback_lang_combo.findData("fr"))

        settings._save_common_tab()

        # Проверяем запись в конфиг
        assert cfg.get("source_lang") == "en"
        assert cfg.get("target_lang") == "de"
        assert cfg.get("fallback_target_lang") == "fr"

        # Проверяем перезагрузку из конфига
        settings._refresh_all_from_config()
        assert settings.source_lang_combo.currentData() == "en"
        assert settings.lang_combo.currentData() == "de"
        assert settings.fallback_lang_combo.currentData() == "fr"

        # Проверка обратной совместимости: setCurrentText("en") для smoke_test
        settings.lang_combo.setCurrentText("en")
        settings._save_common_tab()
        assert cfg.get("target_lang") == "en"

        settings.close()
    print("[OK] 4.1 успешно пройден!")


def test_4_2_language_detection() -> None:
    print("\n--- 4.2. Надёжное автоматическое определение языка ---")

    # 1. Короткие фразы и приветствия
    assert detect_language("Hi!").language == "en"
    assert detect_language("Hello there").language == "en"
    assert detect_language("Danke schön").language == "de"
    assert detect_language("Merci beaucoup").language == "fr"
    assert detect_language("Hola amigo").language == "es"
    assert detect_language("Ciao").language == "it"
    assert detect_language("Dziękuję").language == "pl"

    # 2. Украинский vs Русский с уникальными буквами
    det_uk_unique = detect_language("Привіт, як твої справи? Дякую за допомогу!")
    assert det_uk_unique.language == "uk", f"Ожидался uk, получен {det_uk_unique}"
    assert det_uk_unique.is_reliable

    det_ru_unique = detect_language("Привет, всё отлично, ещё увидимся!")
    assert det_ru_unique.language == "ru", f"Ожидался ru, получен {det_ru_unique}"
    assert det_ru_unique.is_reliable

    # 3. Украинский vs Русский БЕЗ уникальных букв (чисто по лексике/стоп-словам)
    det_uk_lexicon = detect_language("Доброго дня, як справи?")
    assert det_uk_lexicon.language == "uk", f"Ожидался uk, получен {det_uk_lexicon}"

    det_ru_lexicon = detect_language("Добрый день, как дела?")
    assert det_ru_lexicon.language == "ru", f"Ожидался ru, получен {det_ru_lexicon}"

    # 4. Латинские языки с характерной диакритикой
    det_de = detect_language("Über allen Gipfeln ist Ruh, in allen Wipfeln spürest du kaum einen Hauch.")
    assert det_de.language == "de"

    det_fr = detect_language("C'est une très belle journée d'été à Paris.")
    assert det_fr.language == "fr"

    det_es = detect_language("¿Cómo estás? Muy bien, muchas gracias por todo.")
    assert det_es.language == "es"

    det_pl = detect_language("Zażółć gęślą jaźń i zobacz co się stanie.")
    assert det_pl.language == "pl"

    # 5. Восточноазиатские скрипты
    assert detect_language("你好，世界！").language == "zh"
    assert detect_language("こんにちは世界").language == "ja"
    assert detect_language("안녕하세요 세계").language == "ko"

    # 6. Смешанный текст (код, заимствования, технические токены)
    det_mixed_ru = detect_language("Установите библиотеку requests через pip install requests в Python.")
    assert det_mixed_ru.language == "ru", f"Ожидался ru для смешанного текста, получен {det_mixed_ru}"

    det_mixed_en = detect_language("We need to configure the database connection pool using config.json.")
    assert det_mixed_en.language == "en"

    # 7. Особые случаи: числа, шум, знаки пунктуации, одиночные непонятные имена
    det_numbers = detect_language("12345 67890 + - * /")
    assert not det_numbers.is_reliable, "Числа и символы не должны давать надёжного определения"

    det_punctuation = detect_language("... !? :; ---")
    assert not det_punctuation.is_reliable

    det_single_name = detect_language("ChatGPT")
    assert not det_single_name.is_reliable, "Одиночное имя собственное не должно определять язык"

    print("[OK] 4.2 успешно пройден!")


def test_4_3_direction_resolution() -> None:
    print("\n--- 4.3. Автоматический выбор направления и авто-переворот ---")

    # 1. Текст на английском, цель русский -> EN -> RU
    res1 = resolve_translation_direction("Hello world, this is a test.", configured_source="auto", configured_target="ru")
    assert res1.source_lang == "en"
    assert res1.target_lang == "ru"
    assert not res1.auto_flipped
    assert res1.display_badge == "EN → RU"

    # 2. Текст на русском, цель русский -> авто-переворот на fallback "en" -> RU -> EN
    res2 = resolve_translation_direction("Привет, мир! Это тестовое сообщение.", configured_source="auto", configured_target="ru", fallback_target="en")
    assert res2.source_lang == "ru"
    assert res2.target_lang == "en"
    assert res2.auto_flipped
    assert res2.display_badge == "RU → EN"

    # 3. Текст на немецком, цель русский -> DE -> RU
    res3 = resolve_translation_direction("Guten Morgen, wie geht es Ihnen heute?", configured_source="auto", configured_target="ru")
    assert res3.source_lang == "de"
    assert res3.target_lang == "ru"
    assert not res3.auto_flipped
    assert res3.display_badge == "DE → RU"

    # 4. Ручной выбор исходного языка (не "auto") -> соблюдается строго
    res4 = resolve_translation_direction("Bonjour le monde", configured_source="fr", configured_target="ru")
    assert res4.source_lang == "fr"
    assert res4.target_lang == "ru"
    assert not res4.auto_flipped
    assert res4.display_badge == "FR → RU"

    # 5. Ручной выбор источника совпадает с целью -> переворот на fallback
    res5 = resolve_translation_direction("Любой текст", configured_source="ru", configured_target="ru", fallback_target="en")
    assert res5.source_lang == "ru"
    assert res5.target_lang == "en"
    assert res5.auto_flipped

    # 6. Защита от неопределённого текста (числа, шум) -> не гадаем, используем fallback
    res6 = resolve_translation_direction("1234567890", configured_source="auto", configured_target="ru", fallback_target="en")
    assert res6.source_lang == "en"
    assert res6.target_lang == "ru"
    assert not res6.auto_flipped

    print("[OK] 4.3 успешно пройден!")


def test_4_4_mini_window_and_card(app: QApplication) -> None:
    print("\n--- 4.4. Интеграция направления в мини-окно и карточку ---")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ConfigManager(Path(tmp) / "config.json")
        cfg.set("mode", "standard", autosave=False)
        cfg.set("target_lang", "ru", autosave=False)
        cfg.set("fallback_target_lang", "en", autosave=False)

        # Мокаем GoogleTranslator для оффлайн теста
        class _TestTranslator:
            last_source = None
            last_target = None

            def __init__(self, source, target):
                _TestTranslator.last_source = source
                _TestTranslator.last_target = target

            def translate(self, text):
                return f"[{_TestTranslator.last_source}→{_TestTranslator.last_target}] {text.upper()}"

        import workers
        orig_gt = workers.GoogleTranslator
        workers.GoogleTranslator = _TestTranslator

        try:
            window = MiniPopupWindow(cfg, app_icon=app.windowIcon())

            # 1. Добавляем карточку с английским текстом -> детекция en -> ru
            card1 = window.add_card("Hello world", None)
            window._start_translation(card1, "Hello world")

            for _ in range(50):
                QTest.qWait(40)
                if card1.result_text:
                    break

            assert card1.result_text is not None
            assert card1.direction_badge == "EN → RU"
            assert card1.direction_btn.isVisible()
            assert card1.swap_btn.isVisible()
            assert card1.direction_btn.text() == "EN → RU"
            assert "[auto→ru]" in card1.result_text or "[en→ru]" in card1.result_text

            # 2. Нажимаем кнопку смены направления ⇄
            card1.swap_direction()
            assert card1.direction_badge == "RU → EN"
            assert card1.direction_btn.text() == "RU → EN"
            assert card1.source_lang == "ru"
            assert card1.target_lang == "en"

            # 3. Нажимаем «Повторить» -> перегенерация с новым направлением
            window.regenerate_card(card1)
            for _ in range(50):
                QTest.qWait(40)
                if card1.result_text:
                    break

            assert _TestTranslator.last_target == "en"
            assert "[ru→en]" in card1.result_text

            # 4. Выбор другого целевого языка через _select_target_lang
            card1._select_target_lang("de")
            assert card1.target_lang == "de"
            assert "DE" in card1.direction_badge

            window.regenerate_card(card1)
            for _ in range(50):
                QTest.qWait(40)
                if card1.result_text:
                    break

            assert _TestTranslator.last_target == "de"

            window.clear_history()
            window.close()
        finally:
            workers.GoogleTranslator = orig_gt

    print("[OK] 4.4 успешно пройден!")


def main() -> int:
    app = QApplication(sys.argv)
    print("=== НАЧАЛО ТЕСТИРОВАНИЯ ЭТАПА 4 (СИСТЕМА ЯЗЫКОВ) ===")
    test_4_1_catalog_and_settings(app)
    test_4_2_language_detection()
    test_4_3_direction_resolution()
    test_4_4_mini_window_and_card(app)
    print("\n=== ВСЕ ТЕСТЫ ЭТАПА 4 УСПЕШНО ПРОЙДЕНЫ! ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
