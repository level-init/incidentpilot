"""O3: namespaces + SAs + IRSA — no shared admin."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ROOT / "deploy" / "k8s" / "identity"
IRSA = ROOT / "deploy" / "terraform" / "modules" / "irsa"
CHART = ROOT / "deploy" / "helm" / "incidentpilot"

CLASSES = (
    "api",
    "worker",
    "evidence",
    "remediation",
    "web",
    "evaluator",
    "runner",
)


def test_identity_kustomization_has_namespaces_and_sas() -> None:
    assert (IDENTITY / "kustomization.yaml").is_file()
    ns = (IDENTITY / "namespaces.yaml").read_text(encoding="utf-8")
    assert "incidentpilot-system" in ns
    assert "incidentpilot-eval" in ns
    sas = (IDENTITY / "serviceaccounts.yaml").read_text(encoding="utf-8")
    for cls in CLASSES:
        assert f"incidentpilot-{cls}" in sas
        assert f"privilege-class: {cls}" in sas
    assert "incidentpilot-admin" not in sas
    assert "cluster-admin" not in sas.lower()


def test_remediation_kustomize_uses_identity_not_duplicate_sa() -> None:
    kust = (ROOT / "deploy/k8s/remediation/kustomization.yaml").read_text(
        encoding="utf-8"
    )
    assert "../identity" in kust
    assert "serviceaccount.yaml" not in kust
    assert not (ROOT / "deploy/k8s/remediation/serviceaccount.yaml").exists()


def test_irsa_module_maps_each_class() -> None:
    vars_tf = (IRSA / "variables.tf").read_text(encoding="utf-8")
    main = (IRSA / "main.tf").read_text(encoding="utf-8")
    for cls in CLASSES:
        assert cls in vars_tf
    assert "AssumeRoleWithWebIdentity" in main
    assert "AdministratorAccess" not in main
    assert "incidentpilot-eval" in vars_tf
    staging = (
        ROOT / "deploy/terraform/environments/staging/main.tf"
    ).read_text(encoding="utf-8")
    assert 'source = "../../modules/irsa"' in staging
    assert "aws_iam_openid_connect_provider" in staging


def test_helm_renders_sas_and_eval_namespace() -> None:
    values = (CHART / "values.yaml").read_text(encoding="utf-8")
    assert "evalNamespace:" in values
    assert "irsa:" in values
    assert "serviceAccounts:" in values
    assert (CHART / "templates/serviceaccounts.yaml").is_file()
    evaluator = (CHART / "templates/evaluator.yaml").read_text(encoding="utf-8")
    assert "evalNamespace.name" in evaluator
    runner = (CHART / "templates/scenario-runner.yaml").read_text(encoding="utf-8")
    assert "evalNamespace.name" in runner
