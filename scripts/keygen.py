"""Ferramenta ADMINISTRATIVA — NUNCA distribuir com o produto.

Gera o par Ed25519, injeta a chave pública em core/licensing.py e emite
licenças de cliente. A chave PRIVADA fica em keys/ (ignorada pelo git).

Uso:
  python scripts/keygen.py init
  python scripts/keygen.py issue --days 365 --plan pro --install
  python scripts/keygen.py issue --hwid XXXX-XXXX-XXXX-XXXX --days 30
"""

from __future__ import annotations

import argparse
import base64
import json
from datetime import date, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
KEYS_DIR = ROOT / "keys"
PRIVATE_PATH = KEYS_DIR / "private_key.pem"
PUBLIC_PATH = KEYS_DIR / "public_key.pem"
LICENSING_PATH = ROOT / "src" / "winbot" / "core" / "licensing.py"

BEGIN = "# --- BEGIN PUBLIC KEY (gerada por scripts/keygen.py) ---"
END = "# --- END PUBLIC KEY ---"


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def cmd_init() -> None:
    if PRIVATE_PATH.exists() and not _confirm_overwrite():
        return
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    PRIVATE_PATH.write_bytes(private_pem)
    PUBLIC_PATH.write_bytes(public_pem)

    source = LICENSING_PATH.read_text(encoding="utf-8")
    if BEGIN not in source or END not in source:
        raise SystemExit("marcadores BEGIN/END não encontrados em licensing.py")
    before, rest = source.split(BEGIN, 1)
    _, after = rest.split(END, 1)
    block = f'{BEGIN}\nPUBLIC_KEY_PEM = b"""\n{public_pem.decode().strip()}\n"""\n{END}'
    LICENSING_PATH.write_text(before + block + after, encoding="utf-8")

    print("Par Ed25519 gerado e chave pública injetada em licensing.py.")
    print(f"PRIVADA (NÃO VERSIONAR): {PRIVATE_PATH}")
    print(f"PÚBLICA (cópia):         {PUBLIC_PATH}")


def _confirm_overwrite() -> bool:
    answer = input("Chave privada já existe. Substituir? Isso INVALIDA licenças antigas [s/N]: ")
    return answer.strip().lower() == "s"


def cmd_issue(args: argparse.Namespace) -> None:
    if not PRIVATE_PATH.exists():
        raise SystemExit("rode primeiro: python scripts/keygen.py init")
    from winbot.core.licensing import get_hardware_id, license_path

    private = serialization.load_pem_private_key(PRIVATE_PATH.read_bytes(), password=None)
    if not isinstance(private, Ed25519PrivateKey):
        raise SystemExit("chave privada não é Ed25519")
    hwid = (args.hwid or get_hardware_id()).upper()
    payload = {
        "hwid": hwid,
        "plan": args.plan,
        "issued": date.today().isoformat(),
        "exp": (date.today() + timedelta(days=args.days)).isoformat(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    token = f"WINBOT1.{_encode(raw)}.{_encode(private.sign(raw))}"

    out = KEYS_DIR / f"license_{hwid.replace('-', '')}.key"
    out.write_text(token, encoding="utf-8")
    print(f"Licença emitida para {hwid} (expira {payload['exp']}): {out}")

    if args.install:
        target = license_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(token, encoding="utf-8")
        print(f"Instalada em: {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description="WinBot keygen (uso administrativo)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Gera o par de chaves e configura licensing.py")
    issue = sub.add_parser("issue", help="Emite uma licença assinada")
    issue.add_argument("--hwid", help="HWID do cliente (padrão: esta máquina)")
    issue.add_argument("--days", type=int, default=365, help="Validade em dias")
    issue.add_argument("--plan", default="pro", help="Nome do plano")
    issue.add_argument("--install", action="store_true", help="Instala a licença nesta máquina")
    args = parser.parse_args()
    if args.command == "init":
        cmd_init()
    else:
        cmd_issue(args)


if __name__ == "__main__":
    main()
