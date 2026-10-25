"""E3: observability compose configs exist and scrape sim services."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OBS = ROOT / "deploy" / "compose" / "observability"


def test_prometheus_scrapes_sim_services() -> None:
    cfg = yaml.safe_load((OBS / "prometheus" / "prometheus.yml").read_text())
    jobs = {j["job_name"]: j for j in cfg["scrape_configs"]}
    assert "sim-services" in jobs
    targets = jobs["sim-services"]["static_configs"][0]["targets"]
    for svc in (
        "sim-gateway:8080",
        "sim-auth:8080",
        "sim-checkout:8080",
        "sim-payment:8080",
        "sim-inventory:8080",
        "sim-notification:8080",
    ):
        assert svc in targets
    assert cfg["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"] == [
        "alertmanager:9093"
    ]


def test_grafana_datasources_and_dashboard() -> None:
    ds = yaml.safe_load(
        (OBS / "grafana" / "provisioning" / "datasources" / "datasources.yml").read_text()
    )
    names = {d["name"] for d in ds["datasources"]}
    assert names >= {"Prometheus", "Loki", "Tempo"}

    dash = OBS / "grafana" / "dashboards" / "sim-traffic.json"
    text = dash.read_text()
    assert "sim_http_requests_total" in text
    assert '"uid": "sim-traffic"' in text or '"uid":"sim-traffic"' in text


def test_compose_evidence_services_defined() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]
    for name in (
        "prometheus",
        "alertmanager",
        "loki",
        "tempo",
        "grafana",
        "promtail",
    ):
        assert name in services
        assert "evidence" in services[name]["profiles"]
    assert "evidence-stack-placeholder" not in services

    gateway_env = services["sim-gateway"]["environment"]
    assert gateway_env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://tempo:4318"


def test_alertmanager_and_tempo_configs_exist() -> None:
    assert (OBS / "alertmanager" / "alertmanager.yml").is_file()
    assert (OBS / "tempo" / "tempo-config.yml").is_file()
    assert (OBS / "loki" / "loki-config.yml").is_file()
    assert (OBS / "promtail" / "promtail-config.yml").is_file()
