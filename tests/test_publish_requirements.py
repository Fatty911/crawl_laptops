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
        ("Intel 酷睿i9 9900K 旗舰机", "desktop_performance"),
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


def test_source_derived_clevo_barebone_with_desktop_cpu_is_accepted():
    item = eligible("Intel Core i9-11900K")
    item.update(
        {
            "title": "CLEVO X170KM-G 17.3英寸游戏本准系统",
            "model": "X170KM-G",
            "brand": "CLEVO",
            "source": "ZOL",
            "source_category": "ZOL notebook",
            "product_form": "游戏本 准系统 barebone laptop",
            "evidence": {
                "cpu": "socketed desktop LGA1200 CPU, up to Intel i9-11900K",
                "numeric_keypad": "number pad",
                "keyboard_backlight": "individually adjustable RGB lighting",
                "product_form": "Clevo barebone laptop",
            },
        }
    )

    allowed, reasons = meets_publish_requirements(item)

    assert classify_cpu_voltage(item["cpu"]) == "desktop_performance"
    assert allowed is True
    assert reasons == []


def test_proven_rog_compact_gaming_laptop_with_desktop_cpu_is_accepted():
    item = eligible("AMD Ryzen 7 1700")
    item.update(
        {
            "title": "Asus ROG Strix GL702ZC (Ryzen 7 1700) Laptop",
            "model": "ROG Strix GL702ZC",
            "brand": "华硕",
            "source": "ZOL",
            "source_category": "ZOL notebook",
            "product_form": "gaming laptop notebook chassis",
            "evidence": {
                "cpu": "desktop-range Ryzen architecture; gaming laptop with 8-core CPU",
                "numeric_keypad": "number pad",
                "keyboard_backlight": "Keyboard Light: yes",
                "product_form": "Laptop Review; current notebooks",
            },
        }
    )

    assert meets_publish_requirements(item) == (True, [])


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "title": "高性能 i9-14900K 台式整机",
            "source_category": "desktop computers",
            "product_form": "台式机",
        },
        {
            "title": "ROG NUC i9-14900K 迷你主机",
            "source_category": "mini PCs",
            "product_form": "NUC 迷你主机",
        },
        {
            "title": "蓝天 i9-14900K 高性能产品",
            "source_category": "ZOL notebook",
            "product_form": "",
        },
        {
            "title": "仁宝 Compal i9-14900K 台式整机",
            "source_category": "ZOL notebook",
            "product_form": "台式机",
        },
    ],
)
def test_desktop_cpu_requires_positive_portable_product_form(overrides):
    item = eligible("Intel Core i9-14900K")
    item.update(overrides)

    allowed, reasons = meets_publish_requirements(item)

    assert allowed is False
    assert "desktop_cpu_product_form_not_confirmed" in reasons


def test_desktop_cpu_exception_never_waives_keyboard_requirements():
    item = eligible("Intel Core i9-11900K")
    item.update(
        {
            "title": "CLEVO X170KM-G 游戏本准系统",
            "source_category": "ZOL notebook",
            "product_form": "barebone laptop",
            "numeric_keypad": None,
        }
    )

    allowed, reasons = meets_publish_requirements(item)

    assert allowed is False
    assert "numeric_keypad_not_confirmed" in reasons
