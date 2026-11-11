"""
text_diff.py — утилиты сравнения текстов (Diff) и извлечения вариантов перевода (Этап 6).

Включает:
  • generate_word_diff_html: пословное вычисление различий между оригиналом и результатом
    с HTML-подсветкой удалений и добавлений (SequenceMatcher).
  • extract_text_variants: парсинг нескольких вариантов перевода/перефразирования
    (например, Нейтральный, Разговорный, Литературный).
"""

from __future__ import annotations

import difflib
import html
import re
from typing import List, Tuple


def generate_word_diff_html(original: str, modified: str) -> Tuple[str, int, int]:
    """Генерирует HTML с пословной подсветкой различий между original и modified.

    Возвращает:
      (html_diff, words_added_count, words_deleted_count)
    """
    if not original and not modified:
        return "<span style='color: #8B949E;'>Тексты пусты.</span>", 0, 0

    # Разбиваем на слова и пробельные последовательности с сохранением пунктуации
    tokens_orig = re.findall(r"\S+|\s+", original)
    tokens_mod = re.findall(r"\S+|\s+", modified)

    sm = difflib.SequenceMatcher(None, tokens_orig, tokens_mod)
    out: List[str] = []
    added_words = 0
    deleted_words = 0

    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            eq_text = "".join(html.escape(t) for t in tokens_orig[i1:i2])
            out.append(f"<span style='color: #BAC2D4;'>{eq_text}</span>")
        elif op == "replace":
            del_text = "".join(html.escape(t) for t in tokens_orig[i1:i2])
            ins_text = "".join(html.escape(t) for t in tokens_mod[j1:j2])
            out.append(
                f"<del style='color: #FFA198; background-color: rgba(248, 81, 73, 0.22); "
                f"text-decoration: line-through; padding: 1px 3px; border-radius: 3px;'>{del_text}</del> "
                f"<ins style='color: #7EE787; background-color: rgba(46, 160, 67, 0.22); "
                f"text-decoration: none; font-weight: 600; padding: 1px 3px; border-radius: 3px;'>{ins_text}</ins>"
            )
            deleted_words += len([t for t in tokens_orig[i1:i2] if t.strip()])
            added_words += len([t for t in tokens_mod[j1:j2] if t.strip()])
        elif op == "delete":
            del_text = "".join(html.escape(t) for t in tokens_orig[i1:i2])
            out.append(
                f"<del style='color: #FFA198; background-color: rgba(248, 81, 73, 0.22); "
                f"text-decoration: line-through; padding: 1px 3px; border-radius: 3px;'>{del_text}</del>"
            )
            deleted_words += len([t for t in tokens_orig[i1:i2] if t.strip()])
        elif op == "insert":
            ins_text = "".join(html.escape(t) for t in tokens_mod[j1:j2])
            out.append(
                f"<ins style='color: #7EE787; background-color: rgba(46, 160, 67, 0.22); "
                f"text-decoration: none; font-weight: 600; padding: 1px 3px; border-radius: 3px;'>{ins_text}</ins>"
            )
            added_words += len([t for t in tokens_mod[j1:j2] if t.strip()])

    html_str = "".join(out)
    return html_str, added_words, deleted_words


def extract_text_variants(text: str) -> List[Tuple[str, str]]:
    """Извлекает отдельные варианты текста из ответа модели, если их несколько.

    Поддерживает форматы:
      • Вариант 1 — Нейтральный: ...
        Вариант 2 — Разговорный: ...
      • 1. Нейтральный: ...
        2. Разговорный: ...
      • 1. ...
        2. ...
        3. ...
      • ### Вариант 1 / ### Вариант 2

    Возвращает список кортежей: [(название_варианта, текст_варианта), ...].
    Если вариантов меньше 2, возвращает пустой список (значит, обычный одиночный текст).
    """
    raw = (text or "").strip()
    if not raw:
        return []

    # 1. Попытка поиска по явным маркерам "Вариант 1", "Вариант 2", "Option 1"
    variant_pattern = re.compile(
        r"(?:^|\n)(?:###|\*\*|\*|--|—)?\s*(Вариант\s*\d+|Option\s*\d+)"
        r"(?:\s*[-—–:]\s*([^\n:]+))?[:—–-]?\s*(?:\*\*|\*)?\n*",
        re.IGNORECASE,
    )

    matches = list(variant_pattern.finditer(raw))
    if len(matches) >= 2:
        results: List[Tuple[str, str]] = []
        for i, match in enumerate(matches):
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
            content = raw[start:end].strip()

            base_name = match.group(1).strip()
            extra_desc = (match.group(2) or "").strip()
            if extra_desc:
                title = f"{base_name} — {extra_desc}"
            else:
                title = base_name
            if content:
                results.append((title, content))
        if len(results) >= 2:
            return results

    # 2. Попытка поиска по нумерованному списку строк вида:
    # "1. Текст..." или "1. [Нейтральный]: Текст..."
    numbered_pattern = re.compile(
        r"(?:^|\n)(?:###|\*\*|\*|--|—)?\s*(\d+)[\.\)]\s*(?:\*\*|\*)?"
        r"(?:(?:[-—–:]\s*)?([^\n:]+)[:—–-])?\s*(?:\*\*|\*)?\s*",
        re.IGNORECASE,
    )
    num_matches = list(numbered_pattern.finditer(raw))
    if len(num_matches) >= 2:
        # Проверяем, что номера идут последовательно (1, 2, 3...)
        numbers = []
        for m in num_matches:
            try:
                numbers.append(int(m.group(1)))
            except ValueError:
                pass
        if numbers == list(range(1, len(numbers) + 1)):
            num_results: List[Tuple[str, str]] = []
            for i, match in enumerate(num_matches):
                start = match.end()
                end = num_matches[i + 1].start() if i + 1 < len(num_matches) else len(raw)
                content = raw[start:end].strip()

                num = match.group(1).strip()
                desc = (match.group(2) or "").strip()
                # Если desc выглядит как весь текст, а не описание, не используем его как title
                if desc and len(desc) <= 40 and "\n" not in desc:
                    title = f"Вариант {num} — {desc}"
                else:
                    title = f"Вариант {num}"
                    if desc and len(desc) > 40:
                        content = f"{desc} {content}".strip()
                if content:
                    num_results.append((title, content))
            if len(num_results) >= 2:
                return num_results

    return []
