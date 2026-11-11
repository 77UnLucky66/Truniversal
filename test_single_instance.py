"""
test_single_instance.py — проверка защиты от повторного запуска (Этап 1).

Запуск:  python test_single_instance.py
GUI и сеть не нужны. Мьютекс настоящий, но имя уникально для теста,
чтобы не пересекаться с реально работающим приложением.
"""

import sys

from single_instance import SingleInstanceGuard


def run_tests() -> None:
    if sys.platform != "win32":
        print("Проверка единственности работает только на Windows — пропускаем")
        return

    name = "Local\\Truniversal.TestSingleInstance.42ff9a01"

    # 1. Первая копия захватывает мьютекс, вторая получает отказ.
    first = SingleInstanceGuard(name)
    assert first.acquire() is True, "первая копия должна получить мьютекс"
    second = SingleInstanceGuard(name)
    assert second.acquire() is False, "вторая копия должна получить отказ"

    # 2. Повторный acquire того же объекта ничего не ломает.
    assert first.acquire() is True

    # 3. После release() мьютекс снова доступен новой копии.
    first.release()
    third = SingleInstanceGuard(name)
    assert third.acquire() is True, "после release() мьютекс снова доступен"
    third.release()
    print("[OK] 1. Мьютекс единственности: acquire / отказ / release")

    print("\nВсе проверки единственного экземпляра пройдены")


if __name__ == "__main__":
    run_tests()
