#!/usr/bin/env python3
"""Вендорский CLI лицензирования: ключи подписи и выпуск лицензионных ключей.

НЕ входит в сборку приложения (EXE и Docker-образ его не содержат), а каталог с приватным ключом не должен попадать
в репозиторий (``license_keys/`` в .gitignore). Приватный ключ — единственный секрет всей схемы: потеряв его,
вы не сможете выпускать ключи; утратив контроль над ним — не сможете отличить свои ключи от подделок (тогда нужна
ротация: новый ``kid``, новая версия приложения, см. docs/licensing.md).

Команды:
  gen-keypair   создать пару ключей подписи (приватный — в файл с правами 0600, публичный — в вывод)
  issue         выпустить лицензионный ключ (временный или постоянный, с привязками)
  inspect       разобрать и проверить ключ; можно смоделировать хост и время («подойдёт ли ключ вот там?»)

Примеры:
  python tools/license_admin.py gen-keypair --kid k1
  python tools/license_admin.py issue --kid k1 --licensee 'ООО «Организация»' --days 365 \\
      --network 10.20.0.0/16 --hostname 'srv-*' --claim edition=pro
  python tools/license_admin.py issue --kid k1 --licensee 'ООО «Организация»' --perpetual --ip 192.168.1.205 \\
      --bind-param machine_id=958cb539779791d6d919782081485e9d
  python tools/license_admin.py inspect KEY.lic --public-key k1=<публичный ключ> --host-ip 10.20.1.5 --host-name srv-205
"""
from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import os
import sys
import time
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.licensing.codec import normalize_token, sign_token  # noqa: E402
from app.licensing.context import HostContext  # noqa: E402
from app.licensing.keys import KeyRing, default_key_ring, export_public_key  # noqa: E402
from app.licensing.models import SECONDS_PER_DAY, Binding, LicensePayload, LicenseState  # noqa: E402
from app.licensing.validator import evaluate_token  # noqa: E402

DEFAULT_KEYS_DIR = Path("license_keys")
PASSPHRASE_ENV = "LICENSE_KEY_PASSPHRASE"
ARMOR_WIDTH = 64


class CliError(Exception):
    """Ошибка ввода пользователя: печатается одной строкой, без traceback, код выхода 2."""


# --- разбор значений ---------------------------------------------------------------------------------------

def parse_moment(text: str, *, end_of_day: bool = False) -> int:
    """ISO-дата или дата-время → секунды Unix. Без часового пояса считается UTC; дата без времени с
    ``end_of_day`` означает последнюю секунду этих суток («до 31.12» включает 31 декабря целиком)."""
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CliError(f"не удалось разобрать дату {text!r}: ожидается ГГГГ-ММ-ДД или ГГГГ-ММ-ДДTЧЧ:ММ") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    timestamp = int(moment.timestamp())
    return timestamp + SECONDS_PER_DAY - 1 if end_of_day and len(text) == 10 else timestamp


def parse_pairs(items: Sequence[str], option: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise CliError(f"{option}: ожидается имя=значение, получено {item!r}")
        result[key.strip()] = value
    return result


def parse_claim_value(raw: str) -> Any:
    """``500`` → число, ``true`` → булево, ``["a","b"]`` → список, остальное — строка как есть."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


# --- ключи подписи -----------------------------------------------------------------------------------------

def load_private_key(path: Path) -> Ed25519PrivateKey:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CliError(f"не удалось прочитать приватный ключ {path}: {exc}") from exc
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except TypeError:    # ключ зашифрован парольной фразой
        passphrase = os.environ.get(PASSPHRASE_ENV) or getpass.getpass(f"Парольная фраза для {path}: ")
        try:
            key = serialization.load_pem_private_key(data, password=passphrase.encode("utf-8"))
        except ValueError as exc:
            raise CliError("неверная парольная фраза или повреждённый ключ") from exc
    except ValueError as exc:
        raise CliError(f"{path} — не приватный ключ в формате PEM: {exc}") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise CliError("ожидался приватный ключ Ed25519")
    return key


def _encryption(args: argparse.Namespace) -> serialization.KeySerializationEncryption:
    passphrase = os.environ.get(PASSPHRASE_ENV)
    if args.ask_passphrase and not passphrase:
        passphrase = getpass.getpass("Парольная фраза для приватного ключа: ")
        if passphrase != getpass.getpass("Повторите: "):
            raise CliError("парольные фразы не совпадают")
    if passphrase:
        return serialization.BestAvailableEncryption(passphrase.encode("utf-8"))
    print("ВНИМАНИЕ: приватный ключ сохранён БЕЗ парольной фразы. Задайте переменную "
          f"{PASSPHRASE_ENV} или --ask-passphrase и держите файл вне репозитория и общих папок.", file=sys.stderr)
    return serialization.NoEncryption()


def cmd_gen_keypair(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{args.kid}.private.pem"
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, _encryption(args))
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # O_EXCL: существующий ключ не затирается
    except FileExistsError as exc:
        raise CliError(f"{target} уже существует — ключ подписи не перезаписывается") from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(pem)
    print(f"Приватный ключ: {target}  (храните вне репозитория, сделайте резервную копию)", file=sys.stderr)
    print("Вставьте публичный ключ в backend/app/licensing/keys.py → EMBEDDED_PUBLIC_KEYS:", file=sys.stderr)
    print(f'    "{args.kid}": "{export_public_key(key)}",')
    return 0


# --- выпуск ключа ------------------------------------------------------------------------------------------

def _expiry(args: argparse.Namespace, not_before: int) -> int | None:
    if args.perpetual:
        return None
    if args.days is not None:
        if args.days <= 0:
            raise CliError("--days должно быть положительным")
        return not_before + args.days * SECONDS_PER_DAY
    return parse_moment(args.until, end_of_day=True)


def build_payload(args: argparse.Namespace, *, now: int) -> LicensePayload:
    not_before = parse_moment(args.not_before) if args.not_before else now
    bind_fields = {
        "ips": tuple(args.ip), "networks": tuple(args.network), "hostnames": tuple(args.hostname),
        "params": parse_pairs(args.bind_param, "--bind-param"),
    }
    claims = {name: parse_claim_value(value) for name, value in parse_pairs(args.claim, "--claim").items()}
    try:
        bind = Binding(**bind_fields)
        if bind.is_empty and not args.unbound:
            raise CliError("ключ без привязок подойдёт любому компьютеру. Задайте --ip/--network/--hostname/--bind-param "
                           "или подтвердите это флагом --unbound.")
        return LicensePayload(
            id=uuid.uuid4().hex, licensee=args.licensee.strip(), iat=now, nbf=not_before, exp=_expiry(args, not_before),
            grace_days=args.grace_days, bind=bind, claims=claims,
        )
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise CliError(f"параметры ключа недопустимы: {details}") from exc


def armor(token: str) -> str:
    lines = [token[i:i + ARMOR_WIDTH] for i in range(0, len(token), ARMOR_WIDTH)]
    return "\n".join(["-----BEGIN RIS LICENSE-----", *lines, "-----END RIS LICENSE-----"]) + "\n"


def _append_ledger(path: Path, payload: LicensePayload, kid: str) -> None:
    """Журнал выданных ключей (без самих токенов): по нему поддержка отвечает «кому, на что и до когда выдано»."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"kid": kid, **json.loads(payload.canonical_json())}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _summary(payload: LicensePayload) -> str:
    expires = "бессрочно" if payload.exp is None else datetime.fromtimestamp(payload.exp, tz=timezone.utc).isoformat()
    bind = payload.bind
    parts = [f"ips={list(bind.ips)}" if bind.ips else "", f"networks={list(bind.networks)}" if bind.networks else "",
             f"hostnames={list(bind.hostnames)}" if bind.hostnames else "", f"params={sorted(bind.params)}" if bind.params else ""]
    return f"id={payload.id} licensee={payload.licensee!r} {payload.kind} до {expires}; привязки: {' '.join(p for p in parts if p) or 'нет'}"


def cmd_issue(args: argparse.Namespace) -> int:
    key = load_private_key(Path(args.private_key) if args.private_key else DEFAULT_KEYS_DIR / f"{args.kid}.private.pem")
    payload = build_payload(args, now=int(time.time()))
    token = sign_token(key, args.kid, payload)
    print(_summary(payload), file=sys.stderr)
    if args.out:
        Path(args.out).write_text(armor(token) if args.armor else token + "\n", encoding="utf-8")
        print(f"Ключ записан в {args.out}", file=sys.stderr)
    else:
        print(armor(token) if args.armor else token)
    if not args.no_ledger:
        _append_ledger(Path(args.ledger), payload, args.kid)
    return 0


# --- проверка ключа ----------------------------------------------------------------------------------------

def _ring_from_args(args: argparse.Namespace) -> KeyRing:
    pairs = parse_pairs(args.public_key, "--public-key")
    if pairs:
        return KeyRing(pairs)
    if args.private_key:
        return KeyRing({args.kid: export_public_key(load_private_key(Path(args.private_key)))})
    ring = default_key_ring()
    if not ring:
        raise CliError("нет публичных ключей: укажите --public-key kid=<ключ> или --private-key файл")
    return ring


def cmd_inspect(args: argparse.Namespace) -> int:
    source = Path(args.token)
    text = source.read_text(encoding="utf-8") if source.is_file() else args.token
    params = parse_pairs(args.host_param, "--host-param")
    host = HostContext(
        hostname=args.host_name or "",
        addresses=frozenset(ipaddress.ip_address(item) for item in args.host_ip),
        params=params,
    )
    now = parse_moment(args.now) if args.now else int(time.time())
    report = evaluate_token(normalize_token(text), ring=_ring_from_args(args), host=host, now=now)
    print(json.dumps(report.to_public_dict(), ensure_ascii=False, indent=2))
    return 0 if report.state in (LicenseState.VALID, LicenseState.GRACE) else 1


# --- командная строка --------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Вендорский CLI лицензирования РИС", formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("gen-keypair", help="создать пару ключей подписи")
    gen.add_argument("--kid", default="k1", help="идентификатор ключа подписи (латиница, цифры, _ и -; по умолчанию k1)")
    gen.add_argument("--out-dir", default=str(DEFAULT_KEYS_DIR))
    gen.add_argument("--ask-passphrase", action="store_true", help="запросить парольную фразу (или задайте переменную LICENSE_KEY_PASSPHRASE)")
    gen.set_defaults(handler=cmd_gen_keypair)

    issue = sub.add_parser("issue", help="выпустить лицензионный ключ")
    issue.add_argument("--kid", default="k1")
    issue.add_argument("--private-key", help=f"файл приватного ключа (по умолчанию {DEFAULT_KEYS_DIR}/<kid>.private.pem)")
    issue.add_argument("--licensee", required=True, help="на кого выдан ключ (показывается в интерфейсе)")
    term = issue.add_mutually_exclusive_group(required=True)
    term.add_argument("--perpetual", action="store_true", help="постоянный ключ (без срока окончания)")
    term.add_argument("--days", type=int, help="временный ключ: действует N суток с момента начала")
    term.add_argument("--until", help="временный ключ: по эту дату включительно (ГГГГ-ММ-ДД или ГГГГ-ММ-ДДTЧЧ:ММ, UTC)")
    issue.add_argument("--not-before", help="начало действия (по умолчанию — сейчас)")
    issue.add_argument("--grace-days", type=int, default=0, help="льготный период после окончания срока, сутки (0–365)")
    issue.add_argument("--ip", action="append", default=[], help="IP-адрес хоста (можно повторять)")
    issue.add_argument("--network", action="append", default=[], help="подсеть CIDR: у хоста должен быть адрес из неё (можно повторять)")
    issue.add_argument("--hostname", action="append", default=[], help="имя компьютера, допускается шаблон srv-* (можно повторять)")
    issue.add_argument("--bind-param", action="append", default=[], metavar="ИМЯ=ЗНАЧЕНИЕ", help="параметр привязки, например machine_id=… (можно повторять)")
    issue.add_argument("--claim", action="append", default=[], metavar="ИМЯ=ЗНАЧЕНИЕ", help="подписанные данные ключа без проверки привязки, например max_devices=500")
    issue.add_argument("--unbound", action="store_true", help="разрешить ключ без привязок (подойдёт любому компьютеру)")
    issue.add_argument("--out", help="записать ключ в файл вместо вывода на экран")
    issue.add_argument("--armor", action="store_true", help="обрамить ключ строками BEGIN/END и разбить на строки по 64 символа")
    issue.add_argument("--ledger", default=str(DEFAULT_KEYS_DIR / "issued.jsonl"), help="журнал выданных ключей")
    issue.add_argument("--no-ledger", action="store_true")
    issue.set_defaults(handler=cmd_issue)

    inspect = sub.add_parser("inspect", help="проверить ключ (строка или файл)")
    inspect.add_argument("token")
    inspect.add_argument("--kid", default="k1", help="kid для --private-key")
    inspect.add_argument("--public-key", action="append", default=[], metavar="KID=КЛЮЧ", help="публичный ключ проверки (иначе — встроенные)")
    inspect.add_argument("--private-key", help="взять публичный ключ из приватного файла")
    inspect.add_argument("--host-name", help="смоделировать имя компьютера")
    inspect.add_argument("--host-ip", action="append", default=[], help="смоделировать IP-адрес компьютера (можно повторять)")
    inspect.add_argument("--host-param", action="append", default=[], metavar="ИМЯ=ЗНАЧЕНИЕ", help="смоделировать параметр хоста")
    inspect.add_argument("--now", help="смоделировать момент времени (ГГГГ-ММ-ДД[ТЧЧ:ММ], UTC)")
    inspect.set_defaults(handler=cmd_inspect)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except CliError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
