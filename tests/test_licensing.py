import base64
import json
from datetime import date, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from raves.core import licensing


@pytest.fixture
def hwid(mocker):
    mocker.patch("win32api.GetComputerName", return_value="TECH_ONE")
    mocker.patch(
        "win32api.GetVolumeInformation",
        return_value=("label", 123456, 255, 0, "NTFS"),
    )
    return licensing.get_hardware_id()


@pytest.fixture
def private_key(mocker):
    private = Ed25519PrivateKey.generate()
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    mocker.patch.object(licensing, "PUBLIC_KEY_PEM", public_pem)
    return private


def _token(private: Ed25519PrivateKey, payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    return f"RAVES1.{encode(raw)}.{encode(private.sign(raw))}"


def test_hwid_estavel(hwid) -> None:
    assert licensing.get_hardware_id() == hwid
    assert len(hwid) == 19


def test_licenca_valida(hwid, private_key) -> None:
    token = _token(
        private_key,
        {
            "hwid": hwid,
            "plan": "pro",
            "issued": date.today().isoformat(),
            "exp": (date.today() + timedelta(days=30)).isoformat(),
        },
    )
    status = licensing.verify_license(token)
    assert status.state == "LICENSED"
    assert status.plan == "pro"


def test_payload_adulterado(hwid, private_key) -> None:
    token = _token(private_key, {"hwid": hwid})
    parts = token.split(".")
    parts[1] = parts[1][:-2] + "AA"
    assert licensing.verify_license(".".join(parts)).state == "INVALID"


def test_hwid_divergente(hwid, private_key) -> None:
    token = _token(private_key, {"hwid": "0000-0000-0000-0000"})
    assert licensing.verify_license(token, grace_days=0).state == "HWID_MISMATCH"


def test_expirada(hwid, private_key) -> None:
    token = _token(
        private_key,
        {"hwid": hwid, "exp": (date.today() - timedelta(days=1)).isoformat()},
    )
    assert licensing.verify_license(token).state == "EXPIRED"


def test_formato_invalido(hwid) -> None:
    assert licensing.verify_license("lixo").state == "INVALID"
