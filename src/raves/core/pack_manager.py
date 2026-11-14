"""Empacotamento de workflows (.winbotpack) — Etapa 9, 100% local."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from raves.commands.workflow import WORKFLOWS_DIR
from raves.core.logger import logger
from raves.core.security import RiskLevel


def _collect_images(workflow_path: Path) -> list[Path]:
    """Encontra imagens referenciadas por gui_click_image no YAML."""
    import yaml

    try:
        data = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    images: list[Path] = []
    steps = data.get("steps", []) if isinstance(data, dict) else []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("action") != "gui_click_image":
            continue
        params = step.get("params", {})
        if not isinstance(params, dict):
            continue
        image = params.get("image")
        if isinstance(image, str):
            path = Path(image)
            if path.is_file():
                images.append(path)
    return images


def export_pack(workflow_name: str, output_dir: Path) -> Path:
    """Gera ``<workflow_name>.winbotpack`` (ZIP com manifest + yaml + imagens)."""
    workflow_path = WORKFLOWS_DIR / f"{workflow_name}.yaml"
    if not workflow_path.exists():
        raise FileNotFoundError(f"Workflow não encontrado: {workflow_path}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{workflow_name}.winbotpack"

    images = _collect_images(workflow_path)
    manifest_files = [f"{workflow_name}.yaml"] + [img.name for img in images]
    manifest = {
        "name": workflow_name,
        "version": "1",
        "files": manifest_files,
        "risk_level": RiskLevel.YELLOW.value,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    manifest["hash"] = manifest_hash
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest_bytes)
        archive.write(workflow_path, f"{workflow_name}.yaml")
        for image in images:
            archive.write(image, image.name)

    logger.info(f"pack exportado: {output_path} ({len(manifest_files)} arquivo(s))")
    return output_path


def import_pack(pack_path: Path) -> str:
    """Valida SHA-256 do manifest e extrai para ~/.winbot/workflows."""
    pack_path = Path(pack_path)
    if not pack_path.is_file():
        raise FileNotFoundError(f"Pack não encontrado: {pack_path}")

    WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(pack_path, "r") as archive:
        if "manifest.json" not in archive.namelist():
            raise ValueError("Pack inválido: manifest.json ausente")
        manifest_bytes = archive.read("manifest.json")
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        expected_hash = manifest.pop("hash", None)
        if not isinstance(expected_hash, str):
            raise ValueError("Pack inválido: hash ausente")
        recomputed = hashlib.sha256(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if recomputed != expected_hash:
            raise ValueError("Pack corrompido: hash do manifest não confere")

        # Extrai apenas os arquivos listados no manifest (defesa contra path traversal).
        allowed = set(manifest.get("files", []))
        extracted: list[str] = []
        for member in archive.namelist():
            if member == "manifest.json":
                continue
            if member not in allowed:
                continue
            # Defesa contra path traversal.
            target = (WORKFLOWS_DIR / Path(member).name).resolve()
            if WORKFLOWS_DIR.resolve() not in target.parents and target != WORKFLOWS_DIR.resolve():
                continue
            archive.extract(member, WORKFLOWS_DIR)
            extracted.append(member)

    return f"Pack importado: {', '.join(extracted) if extracted else 'sem arquivos'}"
