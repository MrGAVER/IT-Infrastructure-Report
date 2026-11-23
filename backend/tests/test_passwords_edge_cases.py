"""
A-06 (код-ревью main @ b375f58): граничные случаи services/auth/passwords.py — чужой алгоритм, повреждённый хэш, мусор в
needs_rehash, правила стойкости пароля.

Контракт verify_password: хэш из БД может быть чужим или повреждённым (ручная правка, импорт, обрыв записи) — тогда это «пароль не подошёл»
(False), а не необработанное исключение, которое на экране входа превратилось бы в 500. Раньше так вели себя чужой алгоритм и мусор в
соли/хэше, но не нулевое,
отрицательное и непомерное число итераций: hashlib.pbkdf2_hmac бросал ValueError/OverflowError за пределами try. Теперь вычисление под
защитой.

Запуск: pytest backend/tests/test_passwords_edge_cases.py -v
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.config import AUTH_MIN_PASSWORD_LENGTH
from app.constants import ErrorCode
from app.services.auth import passwords
from app.services.auth.passwords import hash_password, needs_rehash, validate_password_strength, verify_password

# Соль и «хэш» для вручную собранных строк; настоящий хэш делает фикстура stored.
_SALT, _DIGEST = "c2FsdA==", "ZGlnZXN0"


def _current_iterations() -> int:
    """Число итераций читается с модуля при вызове: conftest.py на время теста снижает его до 1000 (иначе каждый hash_password
    считал бы 600 000)."""
    return passwords.PBKDF2_ITERATIONS


@pytest.fixture()
def stored() -> str:
    return hash_password("Correct-Horse-9")


class TestVerifyPassword:
    def test_right_password_matches_and_wrong_one_does_not(self, stored):
        assert verify_password("Correct-Horse-9", stored) is True
        assert verify_password("correct-horse-9", stored) is False

    @pytest.mark.parametrize(
        "broken",
        [
            "",  # пустая строка
            "just-a-string",  # не по формату
            "pbkdf2_sha256$600000$only$three",  # лишнее поле
            "pbkdf2_sha256$600000$onlythree",  # не хватает поля
            f"bcrypt$12${_SALT}${_DIGEST}",  # чужой алгоритм
            f"PBKDF2_SHA256$1000${_SALT}${_DIGEST}",  # регистр имени алгоритма важен
            f"pbkdf2_sha256$many${_SALT}${_DIGEST}",  # число итераций — не число
            f"pbkdf2_sha256$1000$QQ${_DIGEST}",  # соль с битым выравниванием base64
            f"pbkdf2_sha256$1000${_SALT}$QQ",  # то же для хэша
            f"pbkdf2_sha256$0${_SALT}${_DIGEST}",  # ноль итераций
            f"pbkdf2_sha256$-5${_SALT}${_DIGEST}",  # отрицательное число итераций
            f"pbkdf2_sha256$99999999999999999999${_SALT}${_DIGEST}",  # число не помещается в C long
        ],
        ids=[
            "empty",
            "no-separators",
            "extra-field",
            "missing-field",
            "foreign-algorithm",
            "algorithm-case",
            "iterations-nan",
            "bad-salt",
            "bad-hash",
            "zero-iterations",
            "negative-iterations",
            "huge-iterations",
        ],
    )
    def test_foreign_or_corrupted_hash_is_a_failed_check_not_an_exception(self, broken):
        assert verify_password("anything", broken) is False

    def test_hash_with_the_right_format_but_other_content_does_not_match(self):
        assert verify_password("anything", f"pbkdf2_sha256$1000${_SALT}${_DIGEST}") is False


class TestNeedsRehash:
    def test_fresh_hash_does_not_need_rehash(self, stored):
        assert needs_rehash(stored) is False

    def test_hash_with_fewer_iterations_needs_rehash(self):
        assert needs_rehash(f"pbkdf2_sha256${_current_iterations() - 1}${_SALT}${_DIGEST}") is True

    def test_hash_with_more_iterations_does_not(self):
        assert needs_rehash(f"pbkdf2_sha256${_current_iterations() + 1}${_SALT}${_DIGEST}") is False

    def test_foreign_algorithm_needs_rehash(self):
        assert needs_rehash(f"bcrypt$12${_SALT}${_DIGEST}") is True

    @pytest.mark.parametrize(
        "garbage",
        ["", "garbage", "a$b$c", "a$b$c$d$e", f"pbkdf2_sha256$many${_SALT}${_DIGEST}"],
        ids=["empty", "no-separators", "three-fields", "five-fields", "iterations-nan"],
    )
    def test_garbage_needs_rehash(self, garbage):
        assert needs_rehash(garbage) is True


class TestPasswordStrength:
    @staticmethod
    def _rejected(password: str, **kwargs) -> dict:
        with pytest.raises(HTTPException) as caught:
            validate_password_strength(password, **kwargs)
        assert caught.value.status_code == 422
        assert caught.value.detail["code"] == ErrorCode.WEAK_PASSWORD
        return caught.value.detail

    def test_too_short_password_is_rejected_with_the_limit_in_the_message(self):
        short = "a1" * ((AUTH_MIN_PASSWORD_LENGTH - 1) // 2)  # короче предела, но с буквами и цифрами

        assert len(short) < AUTH_MIN_PASSWORD_LENGTH
        assert self._rejected(short)["message"] == f"Пароль должен быть не короче {AUTH_MIN_PASSWORD_LENGTH} символов."

    def test_password_equal_to_the_username_is_rejected_ignoring_case_and_outer_spaces(self):
        detail = self._rejected("Administrator1", username="  administrator1 ")

        assert detail["message"] == "Пароль не должен совпадать с именем пользователя."

    def test_other_username_does_not_matter(self):
        validate_password_strength("Administrator1", username="operator")

    @pytest.mark.parametrize("password", ["только-буквы-без-цифр", "123456789012"], ids=["letters-only", "digits-only"])
    def test_password_needs_both_letters_and_digits(self, password):
        assert self._rejected(password)["message"] == "Пароль должен содержать и буквы, и цифры."

    def test_symbols_do_not_replace_letters_and_digits(self):
        assert self._rejected("!!!!????####")["message"] == "Пароль должен содержать и буквы, и цифры."

    def test_good_password_passes_with_or_without_a_username(self):
        validate_password_strength("Надёжный-пароль-2026")
        validate_password_strength("Надёжный-пароль-2026", username="admin")
