import io
import os
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml

from scripts.generate_clash_config import ClashConfigGenerator
from scripts import setup_proxy_runtime


ROOT = Path(__file__).resolve().parents[1]


def test_proxy_secret_is_not_printed_outside_github_actions(capsys):
    secret = "https://subscription.example.test/private-token"

    with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": ""}, clear=False):
        subscriptions, _ = setup_proxy_runtime.parse_proxy_secret(secret)

    assert subscriptions == [secret]
    assert secret not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("workflow_name", "test_url"),
    [
        (
            "crawl-zol.yml",
            "https://detail.zol.com.cn/notebook_index/"
            "subcate16_0_list_1_0_1_2_0_1.html",
        ),
        (
            "crawl-jd.yml",
            "https://www.jd.com/hotitem/670a86a27721a2eeea8.html",
        ),
    ],
)
def test_crawler_workflow_requires_proxy_before_crawl_and_clears_before_upload(
    workflow_name, test_url
):
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["crawl"]["steps"]
    names = [step["name"] for step in steps]

    setup_index = names.index("Configure required crawler proxy")
    crawl_index = names.index(
        "Crawl popularity ranking"
        if workflow_name == "crawl-zol.yml"
        else "Crawl sales ranking"
    )
    clear_index = names.index("Clear crawler proxy environment")
    upload_index = names.index("Upload crawler data")

    assert setup_index < crawl_index < clear_index < upload_index
    setup = steps[setup_index]
    assert setup["env"]["PROXY_SUBSCRIPTIONS"] == (
        "${{ secrets.PROXY_SUBSCRIPTIONS }}"
    )
    assert "scripts/setup_proxy_runtime.py" in setup["run"]
    assert "--require-proxy" in setup["run"]
    assert test_url in setup["run"]

    clear = steps[clear_index]
    assert clear["if"] == "always()"
    assert "scripts/setup_proxy_runtime.py --clear" in clear["run"]


def test_required_proxy_missing_fails_closed_and_records_disabled_environment(
    tmp_path, capsys
):
    github_env = tmp_path / "github-env"
    argv = [
        "setup_proxy_runtime.py",
        "--github-env",
        str(github_env),
        "--require-proxy",
    ]
    with mock.patch.object(sys, "argv", argv), mock.patch.dict(
        os.environ, {"PROXY_SUBSCRIPTIONS": ""}, clear=False
    ):
        result = setup_proxy_runtime.main()

    assert result == 2
    assert "required proxy unavailable" in capsys.readouterr().out
    assert "PROXY_ENABLED=false" in github_env.read_text(encoding="utf-8")


def test_successful_proxy_setup_exports_requests_environment(tmp_path):
    github_env = tmp_path / "github-env"
    process = mock.Mock(pid=1234)
    argv = [
        "setup_proxy_runtime.py",
        "--github-env",
        str(github_env),
        "--require-proxy",
        "--test-url",
        "https://source.example.test/ranking",
    ]
    captured_urls = []
    with (
        mock.patch.object(sys, "argv", argv),
        mock.patch.dict(
            os.environ,
            {"PROXY_SUBSCRIPTIONS": "https://subscription.example.test/token"},
            clear=False,
        ),
        mock.patch.object(
            setup_proxy_runtime,
            "parse_proxy_secret",
            return_value=(["https://subscription.example.test/token"], []),
        ),
        mock.patch.object(
            setup_proxy_runtime, "parse_nodes", return_value=[{"name": "node"}]
        ),
        mock.patch.object(setup_proxy_runtime, "write_runtime_files"),
        mock.patch.object(
            setup_proxy_runtime, "find_mihomo", return_value=Path("/tmp/mihomo")
        ),
        mock.patch.object(
            setup_proxy_runtime.subprocess, "Popen", return_value=process
        ),
        mock.patch.object(Path, "open", return_value=io.BytesIO()),
        mock.patch.object(setup_proxy_runtime, "wait_for_controller", return_value=True),
        mock.patch.object(
            setup_proxy_runtime,
            "test_local_proxy",
            side_effect=lambda urls: captured_urls.extend(urls) or True,
        ),
    ):
        result = setup_proxy_runtime.main()

    exported = github_env.read_text(encoding="utf-8")
    assert result == 0
    assert captured_urls == ["https://source.example.test/ranking"]
    assert "PROXY_ENABLED=true" in exported
    assert "HTTP_PROXY=http://127.0.0.1:7890" in exported
    assert "HTTPS_PROXY=http://127.0.0.1:7890" in exported


def test_clear_removes_proxy_environment_for_artifact_transfer(tmp_path):
    github_env = tmp_path / "github-env"
    argv = [
        "setup_proxy_runtime.py",
        "--github-env",
        str(github_env),
        "--clear",
    ]
    with mock.patch.object(sys, "argv", argv):
        assert setup_proxy_runtime.main() == 0

    exported = github_env.read_text(encoding="utf-8")
    assert "PROXY_ENABLED=false" in exported
    assert "HTTP_PROXY=" in exported
    assert "HTTPS_PROXY=" in exported
    assert "NO_PROXY=" in exported
    assert "no_proxy=" in exported


def test_generated_proxy_config_forces_source_traffic_through_nodes():
    link = (
        "vless://00000000-0000-0000-0000-000000000001@proxy.example.test:443"
        "?security=reality&encryption=none&flow=xtls-rprx-vision"
        "&sni=www.microsoft.com&fp=chrome&pbk=sample-public-key&sid=ABCDEF"
        "#RealityVision"
    )
    generator = ClashConfigGenerator()
    proxy = generator.parse_vless(link)
    config = yaml.safe_load(generator.generate_config_from_proxies([proxy]))

    assert proxy["reality-opts"] == {
        "public-key": "sample-public-key",
        "short-id": "ABCDEF",
    }
    assert config["proxy-groups"][0]["proxies"][0] == "BALANCE"
    assert "MATCH,PROXY" in config["rules"]
    assert "GEOIP,CN,DIRECT" not in config["rules"]


def test_subscription_nodes_with_duplicate_names_are_deduplicated():
    duplicate_name_nodes = [
        {"name": "same-node", "type": "ss", "server": "one.example", "port": 443},
        {"name": "same-node", "type": "ss", "server": "two.example", "port": 443},
    ]
    with mock.patch.object(
        setup_proxy_runtime.ClashConfigGenerator,
        "parse_subscription",
        return_value=duplicate_name_nodes,
    ):
        nodes = setup_proxy_runtime.parse_nodes(
            ["https://subscription.example.test/token"], []
        )

    assert nodes == [duplicate_name_nodes[0]]


@pytest.mark.parametrize(
    ("link", "expected_type"),
    [
        (
            "hysteria2://secret@hy.example.test:443?sni=hy.example.test#hy2",
            "hysteria2",
        ),
        (
            "tuic://uuid:secret@tuic.example.test:443?sni=tuic.example.test#tuic",
            "tuic",
        ),
        (
            "wireguard://private@wg.example.test:51820"
            "?publickey=public&ip=10.0.0.2%2F32#wg",
            "wireguard",
        ),
    ],
)
def test_subscription_parser_keeps_mature_node_uri_families(link, expected_type):
    proxy = ClashConfigGenerator().parse_link(link)

    assert proxy is not None
    assert proxy["type"] == expected_type


def test_subscription_indirection_is_bounded(capsys):
    response = mock.Mock(
        text="https://subscription.example.test/loop",
        status_code=200,
    )
    response.raise_for_status.return_value = None
    session = mock.Mock()
    session.get.return_value = response

    with mock.patch(
        "scripts.generate_clash_config.requests.Session",
        return_value=session,
    ):
        content = ClashConfigGenerator().fetch_subscription(
            "https://subscription.example.test/loop"
        )

    assert content == ""
    assert session.get.call_count == 3
    assert "indirection limit reached" in capsys.readouterr().out


def test_proxy_failure_does_not_echo_mihomo_log_contents(tmp_path, capsys):
    log_path = tmp_path / "mihomo.log"
    log_path.write_text("SECRET-SUBSCRIPTION-CREDENTIAL", encoding="utf-8")
    process = mock.Mock()

    setup_proxy_runtime.stop_and_report(process, log_path)

    process.terminate.assert_called_once_with()
    assert "SECRET-SUBSCRIPTION-CREDENTIAL" not in capsys.readouterr().out
