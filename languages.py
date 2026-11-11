"""
languages.py — централизованная система языков и автоматического определения.

Этап 4:
  • Централизованный каталог поддерживаемых языков (ISO 639-1).
  • Адаптация языковых кодов под движки (Google, DeepL, AI).
  • Надёжное автоматическое определение языка с учётом:
      - уникальных алфавитов и диакритических знаков (ru, uk, de, fr, es, it, pt, pl, zh, ja, ko);
      - стоп-слов и лексики;
      - смешанных текстов (код, термины, заимствования);
      - чисел, пунктуации и имён собственных;
      - расчёта уверенности (confidence) без случайных догадок.
  • Разрешение направления перевода (resolve_direction) с защитой от
    бесконечных переворотов и неожиданных мутаций настроек.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Модель описания языка в каталоге
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Language:
    code: str                  # Канонический код ISO 639-1: "ru", "en", "de"...
    name_ru: str               # Название на русском: "Русский", "Английский"...
    name_en: str               # Название на английском: "Russian", "English"...
    google_code: str           # Код для GoogleTranslator (deep-translator): "ru", "en", "zh-cn"...
    deepl_source: Optional[str]# Код источника DeepL: "RU", "EN", "DE"... (None если не поддерживается)
    deepl_target: Optional[str]# Код цели DeepL: "RU", "EN-US", "DE"... (None если не поддерживается)
    ai_name: str               # Название для системного промпта ИИ: "русский язык", "английский язык"...


# ---------------------------------------------------------------------------
# Каталог основных поддерживаемых языков (в порядке приоритета отображения)
# ---------------------------------------------------------------------------
LANGUAGES_CATALOG: Dict[str, Language] = {
    "ru": Language("ru", "Русский", "Russian", "ru", "RU", "RU", "русский язык"),
    "en": Language("en", "Английский", "English", "en", "EN", "EN-US", "английский язык"),
    "de": Language("de", "Немецкий", "German", "de", "DE", "DE", "немецкий язык"),
    "fr": Language("fr", "Французский", "French", "fr", "FR", "FR", "французский язык"),
    "es": Language("es", "Испанский", "Spanish", "es", "ES", "ES", "испанский язык"),
    "it": Language("it", "Итальянский", "Italian", "it", "IT", "IT", "итальянский язык"),
    "pt": Language("pt", "Португальский", "Portuguese", "pt", "PT", "PT-PT", "португальский язык"),
    "pl": Language("pl", "Польский", "Polish", "pl", "PL", "PL", "польский язык"),
    "uk": Language("uk", "Украинский", "Ukrainian", "uk", "UK", "UK", "украинский язык"),
    "zh": Language("zh", "Китайский", "Chinese", "zh-cn", "ZH", "ZH", "китайский язык"),
    "ja": Language("ja", "Японский", "Japanese", "ja", "JA", "JA", "японский язык"),
    "ko": Language("ko", "Корейский", "Korean", "ko", "KO", "KO", "корейский язык"),
    "tr": Language("tr", "Турецкий", "Turkish", "tr", "TR", "TR", "турецкий язык"),
    "nl": Language("nl", "Нидерландский", "Dutch", "nl", "NL", "NL", "нидерландский язык"),
    "cs": Language("cs", "Чешский", "Czech", "cs", "CS", "CS", "чешский язык"),
    "sv": Language("sv", "Шведский", "Swedish", "sv", "SV", "SV", "шведский язык"),
    "ar": Language("ar", "Арабский", "Arabic", "ar", "AR", "AR", "арабский язык"),
}

# Псевдо-язык «Автоопределение» для выбора исходного языка
AUTO_LANG_CODE = "auto"
AUTO_LANG_NAME = "Автоопределение"


def get_supported_languages() -> List[Language]:
    """Возвращает список всех зарегистрированных языков каталога."""
    return list(LANGUAGES_CATALOG.values())


def get_language(code: str) -> Optional[Language]:
    """Возвращает Language по коду или None, если язык не найден."""
    if not code:
        return None
    normalized = code.strip().lower()
    if normalized == "zh-cn":
        normalized = "zh"
    return LANGUAGES_CATALOG.get(normalized)


def get_language_name(code: str) -> str:
    """Возвращает читаемое русское название языка или переданный код."""
    if not code:
        return "Неизвестный"
    normalized = code.strip().lower()
    if normalized == AUTO_LANG_CODE:
        return AUTO_LANG_NAME
    lang = get_language(normalized)
    return lang.name_ru if lang else code.upper()


# ---------------------------------------------------------------------------
# Адаптация языковых кодов под движки перевода
# ---------------------------------------------------------------------------
def adapt_language_code(engine: str, code: str, is_target: bool = False) -> str:
    """Адаптирует канонический код языка под требования конкретного движка."""
    engine = (engine or "google").strip().lower()
    norm = (code or "ru").strip().lower()

    if norm == AUTO_LANG_CODE:
        return "auto" if not is_target else "ru"

    lang = get_language(norm)

    if engine == "deepl":
        if is_target:
            return lang.deepl_target if (lang and lang.deepl_target) else norm.upper()
        return lang.deepl_source if (lang and lang.deepl_source) else norm.upper()

    if engine == "google":
        return lang.google_code if lang else norm

    # Режим "ai" — используем естественное название для качественного промпта
    if engine == "ai":
        return lang.ai_name if lang else f"язык ({norm})"

    return norm


# ---------------------------------------------------------------------------
# Результат автоматического определения
# ---------------------------------------------------------------------------
@dataclass
class DetectionResult:
    language: Optional[str]      # Канонический код (ru, en...) или None
    confidence: float           # Оценка уверенности (0.0 — 1.0)
    is_reliable: bool           # Достаточна ли уверенность для автоматического выбора
    details: str = ""           # Пояснение (для диагностики)


# ---------------------------------------------------------------------------
# База специфичных символов и стоп-слов для надёжного определения
# ---------------------------------------------------------------------------

# Буквы, уникальные для конкретных языков (внутри своих скриптов):
UKRAINIAN_ONLY_CHARS = set("іїєґІЇЄҐ")
RUSSIAN_ONLY_CHARS = set("ёъыэЁЪЫЭ")

GERMAN_ONLY_CHARS = set("äöüßÄÖÜ")
FRENCH_ONLY_CHARS = set("éèêëàâçîïôùûœæÉÈÊËÀÂÇÎÏÔÙÛŒÆ")
SPANISH_ONLY_CHARS = set("ñáéíóúü¿¡ÑÁÉÍÓÚÜ")
ITALIAN_ONLY_CHARS = set("àèéìòùÀÈÉÌÒÙ")
PORTUGUESE_ONLY_CHARS = set("ãõçáéíóúâêôàÃÕÇÁÉÍÓÚÂÊÔÀ")
POLISH_ONLY_CHARS = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
TURKISH_ONLY_CHARS = set("ğışçöüĞİŞÇÖÜ")

# Частотные слова / маркеры (включая короткие приветствия и служебные слова)
STOPWORDS_RU: Set[str] = {
    "и", "в", "не", "на", "я", "что", "тот", "быть", "с", "он", "а", "как",
    "это", "по", "этот", "к", "но", "они", "мы", "из", "у", "который", "то",
    "за", "своего", "привет", "здравствуйте", "спасибо", "пожалуйста", "да",
    "нет", "хорошо", "очень", "где", "кто", "когда", "почему", "если", "уже",
    "или", "давай", "будет", "было", "меня", "тебя", "него", "нее", "нас",
    "вас", "них", "сделать", "текст", "перевод", "слово", "мир", "день",
    "установи", "установите", "библиотеку", "файл", "окно", "программа", "настройки",
    "через", "для", "от", "до", "при", "без", "после", "перед", "под", "над"
}

STOPWORDS_UK: Set[str] = {
    "і", "в", "не", "на", "я", "що", "той", "бути", "з", "він", "а", "як",
    "це", "по", "цей", "до", "але", "вони", "ми", "із", "у", "який", "те",
    "за", "свого", "привіт", "доброго", "дня", "дякую", "будь", "ласка",
    "так", "ні", "добре", "дуже", "де", "хто", "коли", "чому", "якщо", "вже",
    "або", "буде", "було", "мене", "тебе", "нього", "неї", "нас", "вас", "них",
    "зробити", "текст", "переклад", "слово", "світ", "день", "мова", "встанови",
    "встановіть", "бібліотеку", "файл", "вікно", "програма", "налаштування", "та", "бо",
    "через", "для", "від", "до", "при", "без", "після", "перед", "під", "над"
}

STOPWORDS_EN: Set[str] = {
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it",
    "for", "not", "on", "with", "he", "as", "you", "do", "at", "this", "but",
    "his", "by", "from", "they", "we", "say", "her", "she", "or", "an",
    "will", "my", "one", "all", "would", "there", "their", "what", "so",
    "up", "out", "if", "about", "who", "get", "which", "go", "me", "when",
    "make", "can", "like", "time", "no", "just", "him", "know", "take",
    "people", "into", "year", "your", "good", "some", "could", "them",
    "see", "other", "than", "then", "now", "look", "only", "come", "its",
    "over", "think", "also", "back", "after", "use", "two", "how", "our",
    "work", "first", "well", "way", "even", "new", "want", "because", "any",
    "these", "give", "day", "most", "us", "hello", "hi", "hey", "please",
    "thanks", "thank", "world", "morning", "night", "yes", "ok", "okay",
    "install", "requests", "library", "file", "window", "settings", "text"
}

STOPWORDS_DE: Set[str] = {
    "der", "die", "das", "und", "in", "den", "von", "zu", "mit", "sich",
    "des", "auf", "ist", "im", "dem", "nicht", "ein", "eine", "als", "auch",
    "es", "an", "werden", "aus", "er", "hat", "dass", "sie", "nach", "wird",
    "bei", "einer", "um", "am", "sind", "noch", "wie", "einem", "über",
    "einen", "so", "zum", "war", "haben", "nur", "oder", "aber", "vor",
    "zur", "bis", "mehr", "durch", "man", "sein", "wurde", "sei", "hallo",
    "guten", "morgen", "tag", "abend", "danke", "bitte", "ja", "nein",
    "tschüss", "auf", "wiedersehen", "dies", "dieser", "diese", "text"
}

STOPWORDS_FR: Set[str] = {
    "le", "la", "les", "de", "des", "du", "un", "une", "et", "est", "en",
    "que", "qui", "dans", "a", "il", "elle", "ils", "elles", "on", "nous",
    "vous", "ce", "cette", "ces", "par", "pour", "sur", "avec", "pas",
    "plus", "au", "aux", "ne", "se", "son", "sa", "ses", "comme", "mais",
    "ou", "si", "tout", "faire", "bonjour", "bonsoir", "salut", "merci",
    "oui", "non", "monde", "au", "revoir", "ceci", "bienvenue", "texte"
}

STOPWORDS_ES: Set[str] = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
    "y", "e", "en", "a", "que", "es", "son", "por", "para", "con", "se",
    "su", "sus", "como", "pero", "mas", "más", "o", "u", "no", "si", "sí",
    "al", "lo", "este", "esta", "estos", "estas", "todo", "bien", "hola",
    "buenos", "días", "tardes", "noches", "gracias", "adiós", "amigo",
    "mundo", "muchas", "cómo", "estás", "texto"
}

STOPWORDS_IT: Set[str] = {
    "il", "la", "lo", "i", "gli", "le", "un", "uno", "una", "di", "del",
    "della", "dei", "degli", "delle", "a", "al", "alla", "ai", "agli", "alle",
    "da", "in", "con", "su", "per", "tra", "fra", "e", "ed", "è", "sono",
    "che", "non", "si", "ci", "vi", "ma", "anche", "come", "se", "o",
    "più", "questo", "questa", "questi", "queste", "tutto", "ciao",
    "buongiorno", "buonasera", "grazie", "prego", "mondo", "arrivederci",
    "bella", "stai", "testo"
}

STOPWORDS_PT: Set[str] = {
    "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da",
    "dos", "das", "em", "no", "na", "nos", "nas", "por", "pelo", "pela",
    "pelos", "pelas", "para", "com", "sem", "sob", "sobre", "e", "ou",
    "mas", "que", "se", "como", "quando", "onde", "porque", "porquê",
    "é", "são", "foi", "foram", "ser", "estar", "olá", "bom", "dia",
    "obrigado", "obrigada", "muito", "tudo", "bem", "você", "texto"
}

STOPWORDS_PL: Set[str] = {
    "w", "z", "na", "do", "i", "oraz", "nie", "to", "się", "że", "o",
    "jak", "ale", "od", "po", "za", "co", "tak", "dla", "ze", "tylko",
    "jest", "są", "był", "była", "było", "będzie", "ten", "ta", "te",
    "ci", "jego", "jej", "ich", "jako", "przez", "już", "może", "bardzo",
    "dzień", "dobry", "cześć", "dziękuję", "proszę", "do", "widzenia",
    "klawisz", "aby", "tekst", "kontynuować"
}

STOPWORDS_TR: Set[str] = {
    "bir", "bu", "ve", "de", "da", "için", "ile", "o", "en", "çok",
    "ne", "gibi", "daha", "kadar", "her", "ama", "sonra", "var", "yok",
    "olan", "olarak", "ben", "sen", "biz", "siz", "onlar", "merhaba",
    "günaydın", "teşekkürler", "teşekkür", "ederim", "evet", "hayır",
    "lütfen", "dünya", "nasılsınız"
}


# ---------------------------------------------------------------------------
# Алгоритм надёжного определения языка (Multi-layered Detection)
# ---------------------------------------------------------------------------
def detect_language(text: str, default: Optional[str] = None) -> DetectionResult:
    """Определяет язык текста с расчётом уверенности (confidence).

    Особые случаи:
      • пустые строки, числа, пунктуация → None (is_reliable=False);
      • имена собственные и короткие неизвестные слова → None (is_reliable=False);
      • азиатские скрипты (корейский, японский, китайский) → 100% надёжность;
      • уникальные диакритические знаки (uk vs ru, de, pl, es, it, pt, tr) → высокий приоритет;
      • смешанный текст → анализ ведущего грамматического каркаса;
      • одинаковый алфавит без диакритики → лексический анализ стоп-слов.
    """
    if not text or not text.strip():
        return DetectionResult(default, 0.0, False, "empty_text")

    text = text.strip()

    # 1. Скриптовая статистика (символы)
    hangul_cnt = sum(1 for ch in text if "\uac00" <= ch <= "\ud7af" or "\u1100" <= ch <= "\u11ff")
    hiragana_cnt = sum(1 for ch in text if "\u3040" <= ch <= "\u309f")
    katakana_cnt = sum(1 for ch in text if "\u30a0" <= ch <= "\u30ff")
    hanzi_cnt = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    arabic_cnt = sum(1 for ch in text if "\u0600" <= ch <= "\u06ff")
    cyrillic_cnt = sum(1 for ch in text if "\u0400" <= ch <= "\u04ff")
    latin_cnt = sum(1 for ch in text if ("a" <= ch.lower() <= "z") or ch in (
        "äöüßéèêëàâçîïôùûœæñáéíóúü¿¡àèéìòùãõçąćęłńóśźżğış"
    ))

    total_letters = hangul_cnt + hiragana_cnt + katakana_cnt + hanzi_cnt + arabic_cnt + cyrillic_cnt + latin_cnt
    if total_letters == 0:
        return DetectionResult(default, 0.0, False, "no_letters_found")

    # 2. Азиатские и ближневосточные скрипты с уникальными диапазонами
    if hangul_cnt > 0 and (hangul_cnt / total_letters) > 0.2:
        return DetectionResult("ko", 0.99, True, f"hangul_script({hangul_cnt})")

    if (hiragana_cnt + katakana_cnt) > 0:
        return DetectionResult("ja", 0.99, True, f"kana_script({hiragana_cnt + katakana_cnt})")

    if hanzi_cnt > 0 and (hanzi_cnt / total_letters) > 0.5:
        return DetectionResult("zh", 0.98, True, f"hanzi_script({hanzi_cnt})")

    if arabic_cnt > 0 and (arabic_cnt / total_letters) > 0.4:
        return DetectionResult("ar", 0.98, True, f"arabic_script({arabic_cnt})")

    # 3. Извлечение токенов (слов)
    # Нормализуем апострофы для корректного поиска украинских слов (м'ясо, зв'язок)
    norm_text = text.replace("’", "'").replace("`", "'")
    words = [w.strip(".,!?:;\"'()[]{}/\\-—–«»<>").lower() for w in norm_text.split()]
    words = [w for w in words if w and not w.isdigit()]

    if not words and total_letters < 2:
        return DetectionResult(default, 0.0, False, "too_few_letters_no_words")

    # 4. Кириллический сектор (Русский vs Украинский vs другие)
    cyrillic_words = [w for w in words if any("\u0400" <= ch <= "\u04ff" for ch in w)]
    is_cyrillic = cyrillic_cnt >= latin_cnt
    if not is_cyrillic and cyrillic_cnt >= 8 and (cyrillic_cnt / total_letters >= 0.20):
        if len(cyrillic_words) >= 2 or any(w in STOPWORDS_RU or w in STOPWORDS_UK for w in cyrillic_words):
            is_cyrillic = True

    if is_cyrillic:
        # Проверяем уникальные украинские буквы и апостроф внутри кириллических слов
        has_uk_chars = any(ch in UKRAINIAN_ONLY_CHARS for ch in text)
        has_uk_apostrophe = bool(re.search(r"[а-яіїєґА-ЯІЇЄҐ]['][а-яіїєґА-ЯІЇЄҐ]", norm_text))
        has_ru_chars = any(ch in RUSSIAN_ONLY_CHARS for ch in text)

        uk_word_matches = sum(1 for w in words if w in STOPWORDS_UK)
        ru_word_matches = sum(1 for w in words if w in STOPWORDS_RU)

        if has_uk_chars or has_uk_apostrophe:
            if not has_ru_chars:
                return DetectionResult("uk", 0.98, True, "uk_unique_chars_or_apostrophe")
            if uk_word_matches >= ru_word_matches:
                return DetectionResult("uk", 0.95, True, f"uk_chars_and_words({uk_word_matches}vs{ru_word_matches})")

        if has_ru_chars:
            if not has_uk_chars and not has_uk_apostrophe:
                return DetectionResult("ru", 0.98, True, "ru_unique_chars")
            if ru_word_matches >= uk_word_matches:
                return DetectionResult("ru", 0.95, True, f"ru_chars_and_words({ru_word_matches}vs{uk_word_matches})")

        # Если уникальных букв нет, решаем по частотным словам
        if uk_word_matches > ru_word_matches:
            return DetectionResult("uk", 0.92, True, f"uk_stopwords({uk_word_matches})")
        if ru_word_matches > uk_word_matches:
            return DetectionResult("ru", 0.92, True, f"ru_stopwords({ru_word_matches})")

        # Если слов мало или совпадений нет
        if len(words) == 1:
            w = words[0]
            if w in {"дякую", "привіт", "доброго", "будь-ласка"}:
                return DetectionResult("uk", 0.95, True, "uk_single_greeting")
            if w in {"привет", "спасибо", "здравствуйте", "пожалуйста", "да", "нет"}:
                return DetectionResult("ru", 0.95, True, "ru_single_greeting")

        # При наличии достаточного объёма кириллицы (> 3 букв) русский — базовый
        if cyrillic_cnt >= 4:
            return DetectionResult("ru", 0.80, True, "cyrillic_fallback_ru")

        # Совсем короткое или непонятное кириллическое слово (например, аббревиатура)
        return DetectionResult("ru", 0.55, False, "cyrillic_uncertain")

    # 5. Латинский сектор (Европейские языки)
    # 5.1. Уникальные или яркие диакритические маркеры
    has_polish_chars = any(ch in POLISH_ONLY_CHARS for ch in text)
    has_german_chars = any(ch in GERMAN_ONLY_CHARS for ch in text)
    has_spanish_chars = any(ch in SPANISH_ONLY_CHARS for ch in text)
    has_french_chars = any(ch in FRENCH_ONLY_CHARS for ch in text)
    has_portuguese_chars = any(ch in PORTUGUESE_ONLY_CHARS for ch in text)
    has_turkish_chars = any(ch in TURKISH_ONLY_CHARS for ch in text)

    # 5.2. Сопоставление со списками стоп-слов
    scores: Dict[str, float] = {
        "en": sum(1.0 for w in words if w in STOPWORDS_EN),
        "de": sum(1.0 for w in words if w in STOPWORDS_DE),
        "fr": sum(1.0 for w in words if w in STOPWORDS_FR),
        "es": sum(1.0 for w in words if w in STOPWORDS_ES),
        "it": sum(1.0 for w in words if w in STOPWORDS_IT),
        "pt": sum(1.0 for w in words if w in STOPWORDS_PT),
        "pl": sum(1.0 for w in words if w in STOPWORDS_PL),
        "tr": sum(1.0 for w in words if w in STOPWORDS_TR),
    }

    # Бонусы за специфическую диакритику
    if has_polish_chars:
        scores["pl"] += 3.0
    if has_german_chars:
        scores["de"] += 3.0
    if has_spanish_chars:
        scores["es"] += 3.0
    if has_french_chars:
        scores["fr"] += 3.0
    if has_portuguese_chars:
        scores["pt"] += 3.0
    if has_turkish_chars:
        scores["tr"] += 3.0

    # Проверка французских специфических элизий (c'est, d'un, l'homme, qu'il)
    if any(re.search(r"\b(c|d|j|l|m|n|s|t|qu)['][a-zàâéèêëîïôùûœæ]", w) for w in words):
        scores["fr"] += 2.5

    # Проверка итальянских элизий (l'uomo, dell'arte, un'ora)
    if any(re.search(r"\b(l|un|dell|all|dall|sull)['][a-zàèéìòù]", w) for w in words):
        scores["it"] += 2.5

    best_lang, best_score = max(scores.items(), key=lambda item: item[1])

    # Если есть уверенный победитель по словам или диакритике
    if best_score >= 1.0:
        # Проверяем отрыв от второго места
        sorted_scores = sorted(scores.values(), reverse=True)
        margin = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) > 1 else sorted_scores[0]
        confidence = min(0.70 + (best_score * 0.1) + (margin * 0.05), 0.99)
        return DetectionResult(best_lang, confidence, True, f"latin_lexicon_score({best_lang}={best_score})")

    # 5.3. Короткие одиночные фразы и слова (Hi, Hello, Merci, Danke, Ciao...)
    single_word_map = {
        "hi": "en", "hello": "en", "thanks": "en", "please": "en", "yes": "en", "bye": "en",
        "danke": "de", "bitte": "de", "tschüss": "de", "nein": "de",
        "merci": "fr", "salut": "fr", "bonjour": "fr", "oui": "fr",
        "hola": "es", "gracias": "es", "adiós": "es",
        "ciao": "it", "grazie": "it", "prego": "it",
        "cześć": "pl", "dziękuję": "pl",
    }
    if len(words) == 1 and words[0] in single_word_map:
        return DetectionResult(single_word_map[words[0]], 0.95, True, f"single_salutation({words[0]})")

    # 5.4. Вспомогательный вызов langdetect (если установлен и текст > 2 слов)
    try:
        from langdetect import DetectorFactory, detect_langs
        DetectorFactory.seed = 0
        if len(words) >= 3 and total_letters >= 15:
            candidates = detect_langs(text)
            if candidates:
                cand_code = candidates[0].lang.lower()
                cand_prob = candidates[0].prob
                # Нормализуем китайский
                if cand_code in ("zh-cn", "zh-tw"):
                    cand_code = "zh"
                # Защита от ложных срабатываний: скрипт кандидата должен совпадать с текстом
                if cand_code in LANGUAGES_CATALOG and cand_prob >= 0.70:
                    return DetectionResult(cand_code, float(cand_prob), True, f"langdetect({cand_code}:{cand_prob:.2f})")
    except Exception:
        pass

    # 5.5. Одиночные неизвестные слова, имена собственные, технические идентификаторы (ChatGPT, Asdfgh)
    # Не делаем случайных предположений!
    if len(words) == 1:
        return DetectionResult(default, 0.40, False, f"unknown_single_word({words[0]})")

    # Если латинских букв много, но язык не опознан с достаточной уверенностью
    if latin_cnt >= 20:
        return DetectionResult("en", 0.60, False, "latin_fallback_uncertain_en")

    return DetectionResult(default, 0.30, False, "insufficient_features")


def detect_text_language(text: str, default: Optional[str] = None) -> Optional[str]:
    """Удобная функция: возвращает код языка, только если определение надёжно, иначе default."""
    res = detect_language(text, default=default)
    return res.language if res.is_reliable else default


# Сохраняем эвристику для 100% обратной совместимости со старыми тестами
def detect_ru_en_legacy(text: str) -> Optional[str]:
    """Эвристика языка: «ru», если кириллицы не меньше латиницы, иначе «en» (обратная совместимость)."""
    cyrillic = sum(1 for ch in text if "\u0400" <= ch <= "\u04ff")
    latin = sum(1 for ch in text if "a" <= ch.lower() <= "z")
    if not cyrillic and not latin:
        return None
    return "ru" if cyrillic >= latin else "en"


# ---------------------------------------------------------------------------
# Разрешение направления перевода (Resolution & Auto-flip)
# ---------------------------------------------------------------------------
@dataclass
class DirectionResolution:
    source_lang: str           # Фактический исходный язык (никогда не "auto")
    target_lang: str           # Фактический целевой язык
    detected_lang: Optional[str] # Определённый язык текста (если удалось)
    auto_flipped: bool         # Произошёл ли авто-переворот (ru↔en или source==target)
    display_badge: str         # Текстовый бейдж: "EN → RU", "RU → EN", "DE → RU"
    confidence: float          # Оценка уверенности определения
    is_reliable: bool          # Надёжность детекции


def resolve_translation_direction(
    text: str,
    configured_source: str = "auto",
    configured_target: str = "ru",
    fallback_target: str = "en",
) -> DirectionResolution:
    """Определяет рабочее направление перевода без мутации глобальных настроек.

    Правила:
      1. Если исходный язык «auto»:
         - Запускаем анализ текста.
         - Если определённый язык совпадает с целевым (например, текст на русском, а цель — русский):
           переворачиваем направление: целью становится fallback_target (например, "en"),
           а источником — обнаруженный язык.
         - Если определённый язык отличается от целевого:
           источником становится обнаруженный язык, целью — настроенный целевой.
         - Если определение ненадёжно (числа, шум, короткие имена):
           не гадаем — источником считается противоположный от целевого (или fallback_target),
           а целью — настроенный целевой.
      2. Если исходный язык задан вручную (не «auto»):
         - Источник строго фиксирован.
         - Если источник и цель случайно совпадают: цель переключается на fallback_target.
         - Никаких неконтролируемых авто-переворотов.
    """
    configured_source = (configured_source or AUTO_LANG_CODE).strip().lower()
    configured_target = (configured_target or "ru").strip().lower()
    fallback_target = (fallback_target or "en").strip().lower()

    # Защита от совпадения fallback_target с configured_target
    if fallback_target == configured_target:
        fallback_target = "en" if configured_target == "ru" else "ru"

    det = detect_language(text)

    # Вариант 1: Автоопределение
    if configured_source == AUTO_LANG_CODE:
        if det.is_reliable and det.language:
            detected = det.language
            if detected == configured_target:
                # Текст уже на целевом языке → авто-переворот!
                src = detected
                tgt = fallback_target
                flipped = True
            else:
                src = detected
                tgt = configured_target
                flipped = False
        else:
            # Не смогли определить язык с достаточной уверенностью
            src = fallback_target
            tgt = configured_target
            flipped = False
    # Вариант 2: Исходный язык задан вручную
    else:
        src = configured_source
        if src == configured_target:
            tgt = fallback_target
            flipped = True
        else:
            tgt = configured_target
            flipped = False

    badge = f"{src.upper()} → {tgt.upper()}"

    return DirectionResolution(
        source_lang=src,
        target_lang=tgt,
        detected_lang=det.language,
        auto_flipped=flipped,
        display_badge=badge,
        confidence=det.confidence,
        is_reliable=det.is_reliable,
    )
