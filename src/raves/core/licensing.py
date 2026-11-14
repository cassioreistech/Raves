"""Licenciamento comercial offline (Ed25519).

LIMITAÇÃO DE SEGURANÇA: validar com chave pública embutida é inerentemente
contornável por patch no binário. Nuitka dificulta a engenharia reversa, mas a
mitigação real é checar em múltiplos pontos do fluxo e/ou validação online
periódica. Nenhuma chave privada existe neste módulo nem no repositório.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from raves.core.logger import audit

LicenseState = Literal["LICENSED", "TRIAL", "UNLICENSED", "EXPIRED", "INVALID", "HWID_MISMATCH"]

# --- BEGIN PUBLIC KEY (gerada por scripts/keygen.py) ---
PUBLIC_KEY_PEM = b"""
-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA/2feuPdkppKWDvAmmxSWK3nA5NxIjlxFYhYJ8URq6Go=
-----END PUBLIC KEY-----
"""
# --- END PUBLIC KEY ---


class LicenseError(Exception):
    """Licença ausente, expirada ou inválida para operações protegidas."""


@dataclass(frozen=True)
class LicenseStatus:
    state: LicenseState
    detail: str
    hwid: str
    plan: str = ""
    expires: str = ""


def get_hardware_id() -> str:
    """ID estável: nome da máquina + serial do volume do sistema (SHA-256)."""
    import win32api

    computer = win32api.GetComputerName()
    drive = f"{os.environ.get('SYSTEMDRIVE', 'C:')}\\"
    try:
        serial = win32api.GetVolumeInformation(drive)[1]
    except OSError:
        serial = 0
    raw = f"{computer}|{serial}".encode()
    digest = hashlib.sha256(raw).hexdigest()[:16].upper()
    return "-".join(digest[index : index + 4] for index in range(0, 16, 4))


def _raves_home() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "RAVES"


def license_path() -> Path:
    return _raves_home() / "license.key"


def _state_path() -> Path:
    return _raves_home() / "state.json"


def _decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def verify_license(token: str, *, grace_days: int = 7) -> LicenseStatus:
    """Valida assinatura, HWID e expiração. Nunca acessa a rede."""
    hwid = get_hardware_id()
    payload: dict[str, Any] = {}
    try:
        prefix, payload_b64, sig_b64 = token.strip().split(".")
        if prefix != "RAVES1":
            raise ValueError("prefixo inválido")
        payload_bytes = _decode(payload_b64)
        public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM)
        if not isinstance(public_key, Ed25519PublicKey):
            raise ValueError("chave pública não é Ed25519")
        public_key.verify(_decode(sig_b64), payload_bytes)
        payload = json.loads(payload_bytes)
    except (InvalidSignature, ValueError, TypeError, json.JSONDecodeError) as exc:
        return LicenseStatus("INVALID", f"assinatura/formato inválido: {exc}", hwid)

    if not isinstance(payload, dict):
        return LicenseStatus("INVALID", "payload inválido", hwid)
    plan = str(payload.get("plan", ""))
    expires = str(payload.get("exp") or "")

    if payload.get("hwid") != hwid:
        issued = payload.get("issued")
        if isinstance(issued, str):
            try:
                if date.today() - date.fromisoformat(issued) <= timedelta(days=grace_days):
                    return LicenseStatus(
                        "TRIAL", "HWID divergente dentro do grace period", hwid, plan, expires
                    )
            except ValueError:
                pass
        return LicenseStatus("HWID_MISMATCH", "licença emitida para outro hardware", hwid)

    if expires:
        try:
            if date.fromisoformat(expires) < date.today():
                return LicenseStatus(
                    "EXPIRED", f"licença expirada em {expires}", hwid, plan, expires
                )
        except ValueError:
            return LicenseStatus("INVALID", "campo 'exp' inválido", hwid)

    return LicenseStatus("LICENSED", "licença válida", hwid, plan, expires)


def _trial_status(hwid: str, trial_days: int) -> LicenseStatus:
    """Trial de primeiro uso. É SPOOFÁVEL (apagar state.json reinicia o contador).

    Não é proteção real: serve apenas como conveniência de avaliação. A barreira
    comercial é a licença assinada + o binário compilado.
    """
    state_file = _state_path()
    if state_file.exists():
        try:
            raw_state = json.loads(state_file.read_text(encoding="utf-8"))
            first = date.fromisoformat(raw_state["first_run"])
        except (ValueError, KeyError, OSError):
            first = date.today()
    else:
        first = date.today()
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({"first_run": first.isoformat()}), encoding="utf-8")

    remaining = trial_days - (date.today() - first).days
    if remaining <= 0:
        return LicenseStatus("EXPIRED", "período de avaliação encerrado", hwid)
    return LicenseStatus("TRIAL", f"avaliação: {remaining} dia(s) restante(s)", hwid)


def current_status() -> LicenseStatus:
    """Status efetivo: licença instalada ou período de avaliação."""
    from raves.core.config import load_settings

    settings = load_settings()
    hwid = get_hardware_id()
    path = license_path()
    if path.exists():
        return verify_license(
            path.read_text(encoding="utf-8"), grace_days=settings.licensing.grace_days
        )
    return _trial_status(hwid, settings.licensing.trial_days)


def check_license_or_raise() -> LicenseStatus:
    """Gate para comandos operacionais quando licensing.enabled = true."""
    status = current_status()
    audit(f"license state={status.state} hwid={status.hwid}")
    if status.state in {"EXPIRED", "INVALID", "HWID_MISMATCH"}:
        raise LicenseError(f"{status.detail}. HWID: {status.hwid}")
    return status
