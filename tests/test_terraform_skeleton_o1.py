"""O1: Terraform skeleton layout contracts (no AWS apply)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TF = ROOT / "deploy" / "terraform"

MODULES = ("vpc", "eks", "rds", "s3", "iam", "secrets", "irsa")
MODULE_FILES = ("main.tf", "variables.tf", "outputs.tf", "versions.tf")
STAGING_FILES = (
    "main.tf",
    "variables.tf",
    "outputs.tf",
    "versions.tf",
    "terraform.tfvars.example",
)


def test_modules_exist_with_required_files() -> None:
    for name in MODULES:
        mod = TF / "modules" / name
        assert mod.is_dir(), f"missing module {name}"
        for fname in MODULE_FILES:
            path = mod / fname
            assert path.is_file(), f"missing {path.relative_to(ROOT)}"
            assert path.stat().st_size > 0


def test_staging_env_and_gate() -> None:
    staging = TF / "environments" / "staging"
    for fname in STAGING_FILES:
        path = staging / fname
        assert path.is_file(), f"missing {path.relative_to(ROOT)}"
    main = (staging / "main.tf").read_text(encoding="utf-8")
    assert "enable_expensive_resources" in main
    assert 'source = "../../modules/vpc"' in main
    assert 'source = "../../modules/eks"' in main
    assert 'source = "../../modules/rds"' in main
    assert 'source = "../../modules/s3"' in main
    assert 'source = "../../modules/iam"' in main
    assert 'source = "../../modules/secrets"' in main
    assert 'source = "../../modules/irsa"' in main


def test_docs_and_validate_script() -> None:
    assert (ROOT / "docs" / "terraform.md").is_file()
    assert (TF / "README.md").is_file()
    script = ROOT / "scripts" / "terraform_validate.sh"
    assert script.is_file()
    assert "terraform validate" in script.read_text(encoding="utf-8")


def test_privilege_classes_have_no_shared_admin() -> None:
    irsa = (TF / "modules" / "irsa" / "main.tf").read_text(encoding="utf-8")
    for cls in ("api", "worker", "evidence", "remediation", "runner", "evaluator", "web"):
        # class names live in variables defaults; trust policy is generic
        assert "privilege_class" in irsa or "PrivilegeClass" in irsa
    vars_tf = (TF / "modules" / "irsa" / "variables.tf").read_text(encoding="utf-8")
    for cls in ("api", "worker", "evidence", "remediation", "runner", "evaluator", "web"):
        assert cls in vars_tf
    assert "AdministratorAccess" not in irsa
    assert "no shared admin" in irsa.lower() or "No shared admin" in irsa
