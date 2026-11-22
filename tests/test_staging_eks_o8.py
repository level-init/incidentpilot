"""O8: staging EKS ephemeral apply / smoke / teardown contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "deploy" / "terraform" / "environments" / "staging"


def test_docs_and_scripts_exist() -> None:
    assert (ROOT / "docs/staging-eks.md").is_file()
    smoke = ROOT / "scripts/staging_eks_smoke.sh"
    tear = ROOT / "scripts/staging_eks_teardown.sh"
    assert smoke.is_file()
    assert tear.is_file()
    smoke_text = smoke.read_text(encoding="utf-8")
    tear_text = tear.read_text(encoding="utf-8")
    assert "secrets_arns" in smoke_text
    assert "irsa_privilege_class_role_arns" in smoke_text
    assert "temporal_cloud" in smoke_text
    assert "terraform destroy" in tear_text
    assert "FORCE" in tear_text


def test_backend_example_and_versions_comment() -> None:
    assert (STAGING / "backend.hcl.example").is_file()
    be = (STAGING / "backend.hcl.example").read_text(encoding="utf-8")
    assert "bucket" in be
    assert "key" in be
    versions = (STAGING / "versions.tf").read_text(encoding="utf-8")
    assert "backend.hcl" in versions
    assert 'backend "s3"' in versions


def test_tfvars_example_points_at_ephemeral_runbook() -> None:
    text = (STAGING / "terraform.tfvars.example").read_text(encoding="utf-8")
    assert "staging-eks.md" in text
    assert "enable_expensive_resources" in text


def test_runbook_covers_apply_smoke_teardown() -> None:
    text = (ROOT / "docs/staging-eks.md").read_text(encoding="utf-8")
    for needle in (
        "terraform apply",
        "staging-eks-smoke",
        "terraform destroy",
        "IRSA",
        "RDS",
        "S3",
        "Secrets",
        "enable_expensive_resources",
    ):
        assert needle in text, needle


def test_makefile_targets() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "staging-eks-smoke" in makefile
    assert "staging-eks-teardown" in makefile


def test_gitignore_keeps_local_tf_secrets_out() -> None:
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "terraform.tfvars" in gi
    assert "backend.hcl" in gi
