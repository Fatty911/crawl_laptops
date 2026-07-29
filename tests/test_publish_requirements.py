import pytest

from scripts.merge_data import classify_cpu_voltage, meets_publish_requirements


def eligible(cpu="Intel Core i7-13700H"):
    return {
        "cpu": cpu,
        "numeric_keypad": True,
        "keyboard_backlight": True,
    }


@pytest.mark.parametrize(
    ("cpu", "expected"),
    [
        ("Intel Core i7-13700H", "standard_performance"),
        ("Intel Core i9-14900HX", "high_performance"),
        ("AMD Ryzen 7 8845HS", "standard_performance"),
        ("Intel Core i9-12900HK", "high_performance"),
        ("Intel Core i5-1235U", "low_power"),
        ("Intel Core i7-1165G7", "low_power"),
        ("Intel Core i5-1340P", "unknown"),
    ],
)
def test_cpu_voltage_classification(cpu, expected):
    assert classify_cpu_voltage(cpu) == expected


def test_publish_accepts_only_all_three_requirements():
    allowed, reasons = meets_publish_requirements(eligible())
    assert allowed is True
    assert reasons == []


@pytest.mark.parametrize("field", ["numeric_keypad", "keyboard_backlight"])
@pytest.mark.parametrize("value", [False, None, "未知"])
def test_keyboard_requirement_is_strict(field, value):
    item = eligible()
    item[field] = value
    allowed, reasons = meets_publish_requirements(item)
    assert allowed is False
    assert any(field in reason for reason in reasons)


@pytest.mark.parametrize(
    "cpu",
    [
        "Intel Core i5-1235U",
        "Intel Core i7-1165G7",
        "Intel Core i7-7Y75",
        "Intel Processor N100",
        "Apple M4",
        "",
    ],
)
def test_low_power_or_unknown_cpu_is_rejected(cpu):
    allowed, reasons = meets_publish_requirements(eligible(cpu))
    assert allowed is False
    assert any(reason.startswith("cpu_voltage_not_allowed") for reason in reasons)

