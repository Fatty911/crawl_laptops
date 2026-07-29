from scripts.audit_pages_payload import audit_payload, payload_sources


def item(key="abc", source="ZOL", source_count=1):
    return {
        "identity_key": key,
        "title": "测试电脑",
        "cpu": "Intel Core i7-13700H",
        "cpu_voltage_type": "standard_performance",
        "numeric_keypad": True,
        "keyboard_backlight": True,
        "source": source,
        "atomic_source_names": [source],
        "source_count": source_count,
    }


def payload(rows, sources):
    return {"count": len(rows), "items": rows, "sources": sources}


def test_source_alias_normalization_does_not_report_regression():
    baseline = payload([item(source="中关村在线")], ["中关村在线", "京东商城"])
    current_row = item(source="zol")
    current_row["atomic_source_names"] = ["zol", "JD.com"]
    current_row["source_count"] = 2
    current = payload([current_row], ["ZOL", "JD"])
    assert audit_payload(current, baseline) == []
    assert payload_sources(current) == {"ZOL", "JD"}


def test_actual_source_regression_is_rejected():
    baseline = payload([item()], ["ZOL", "JD"])
    current = payload([item()], ["ZOL"])
    assert "source regression: missing JD" in audit_payload(current, baseline)


def test_ineligible_item_and_duplicate_identity_are_rejected():
    first = item()
    second = item()
    second["keyboard_backlight"] = False
    errors = audit_payload(payload([first, second], ["ZOL"]))
    assert "duplicate identity_key values" in errors
    assert any(error.startswith("ineligible item") for error in errors)


def test_source_count_must_match_atomic_sources():
    errors = audit_payload(payload([item(source_count=2)], ["ZOL"]))
    assert "item abc source_count mismatch" in errors
