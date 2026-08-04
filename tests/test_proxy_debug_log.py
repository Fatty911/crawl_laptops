"""mihomo failure diagnostics must never leak proxy credentials."""

from scripts.setup_proxy_runtime import redact_log_content, tail_log_for_diagnostics


def test_redact_masks_url_credentials_and_long_tokens():
    raw = (
        'level=info msg="fetching https://user:hunter2-secret-token@sub.example.com/link"\n'
        "level=error secret=SUPER-SECRET-SUBSCRIPTION-CREDENTIAL-VALUE dropped\n"
        'level=info msg="proxy 10.0.0.1:443 ready"\n'
    )
    redacted = redact_log_content(raw)
    assert "hunter2-secret-token" not in redacted
    assert "SUPER-SECRET-SUBSCRIPTION-CREDENTIAL-VALUE" not in redacted
    assert "https://***@sub.example.com/link" in redacted
    assert "proxy 10.0.0.1:443 ready" in redacted


def test_tail_log_for_diagnostics_redacts_before_print(tmp_path, capsys):
    log_path = tmp_path / "mihomo.log"
    log_path.write_text("SECRET-SUBSCRIPTION-CREDENTIAL", encoding="utf-8")
    tail_log_for_diagnostics(log_path)
    output = capsys.readouterr().out
    assert "SECRET-SUBSCRIPTION-CREDENTIAL" not in output
    assert "redacted" in output


def test_tail_log_missing_file_is_silent(tmp_path, capsys):
    tail_log_for_diagnostics(tmp_path / "nope.log")
    assert capsys.readouterr().out == ""
