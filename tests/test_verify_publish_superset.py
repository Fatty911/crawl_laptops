from scripts.verify_publish_superset import identities


def laptop(identity_key, model):
    return {
        "identity_key": identity_key,
        "title": f"惠普{model}(i7-14650HX/16GB/1TB/RTX5060)",
        "model": f"惠普{model}(i7-14650HX/16GB/1TB/RTX5060)",
        "brand": "惠普",
        "cpu": "i7-14650HX",
        "numeric_keypad": True,
        "keyboard_backlight": True,
        "source": "ZOL",
    }


def test_superset_identity_uses_current_schema_instead_of_persisted_hash():
    baseline = {"items": [laptop("legacy-hash", "暗影精灵11")]}
    candidate = {"items": [laptop("current-hash", "暗影精灵11")]}

    assert identities(baseline, eligible_only=True) == identities(candidate)


def test_superset_identity_still_detects_a_genuinely_missing_model():
    baseline = {"items": [laptop("legacy-hash", "暗影精灵11")]}
    candidate = {"items": [laptop("current-hash", "暗影精灵10")]}

    assert identities(baseline, eligible_only=True) - identities(candidate)
