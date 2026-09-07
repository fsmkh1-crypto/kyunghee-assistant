#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected block not found in {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "settings.py",
    '''def _builtin_set_choice(value: object, default: str = "random") -> str:\n    value = str(value).strip().lower()\n    if value == "random":\n        return "random"\n    if value.isdigit() and 1 <= int(value) <= 99:\n        return f"{int(value):02d}"\n    return default\n''',
    '''def _builtin_set_choice(value: object, default: str = "random") -> str:\n    value = str(value).strip().lower()\n    if value in {"random", "canonical"}:\n        return value\n    if value.isdigit() and 1 <= int(value) <= 99:\n        return f"{int(value):02d}"\n    return default\n''',
)

replace_once(
    "settings.py",
    '''def _builtin_override_choice(value: object) -> str:\n    value = str(value).strip()\n    if not value:\n        return ""\n    if value.isdigit() and 1 <= int(value) <= 99:\n        return f"{int(value):02d}"\n    return ""\n''',
    '''def _builtin_override_choice(value: object) -> str:\n    value = str(value).strip().lower()\n    if not value:\n        return ""\n    if value == "canonical":\n        return "canonical"\n    if value.isdigit() and 1 <= int(value) <= 99:\n        return f"{int(value):02d}"\n    return ""\n''',
)

replace_once(
    "asset_manager.py",
    '''def resolve_asset_for_set(role: str, set_number: int, asset_dir: Path = ASSET_DIR) -> Path | None:\n    """Resolve one explicit built-in numbered set, then fall back safely."""\n    numbered = variant_asset(role, set_number, asset_dir)\n    if numbered is not None:\n        return numbered\n    names = ROLE_FILES.get(role, ROLE_FILES["default"])\n    return first_existing(names, asset_dir)\n''',
    '''def resolve_canonical_asset(role: str, asset_dir: Path = ASSET_DIR) -> Path | None:\n    """Resolve the original reviewed Kyunghee artwork for one runtime role."""\n    names = ROLE_FILES.get(role, ROLE_FILES["default"])\n    return first_existing(names, asset_dir)\n\n\ndef resolve_asset_for_set(role: str, set_number: int, asset_dir: Path = ASSET_DIR) -> Path | None:\n    """Resolve one explicit built-in numbered set, then fall back safely."""\n    numbered = variant_asset(role, set_number, asset_dir)\n    if numbered is not None:\n        return numbered\n    return resolve_canonical_asset(role, asset_dir)\n''',
)

replace_once(
    "asset_manager.py",
    '''    names = ROLE_FILES.get(role, ROLE_FILES["default"])\n    return first_existing(names, asset_dir)\n\n\ndef resolve_configured_asset(\n''',
    '''    return resolve_canonical_asset(role, asset_dir)\n\n\ndef resolve_configured_asset(\n''',
)

replace_once(
    "asset_manager.py",
    '''    """Resolve role override > selected base set > process-stable random set."""\n    override_text = str(role_override).strip()\n    if override_text.isdigit() and 1 <= int(override_text) <= 99:\n        return resolve_asset_for_set(role, int(override_text), asset_dir)\n\n    base_text = str(base_set).strip().lower()\n    if base_text != "random" and base_text.isdigit() and 1 <= int(base_text) <= 99:\n        return resolve_asset_for_set(role, int(base_text), asset_dir)\n\n    return resolve_asset(role, asset_dir)\n''',
    '''    """Resolve role override > selected base set > process-stable random set."""\n    override_text = str(role_override).strip().lower()\n    if override_text == "canonical":\n        return resolve_canonical_asset(role, asset_dir)\n    if override_text.isdigit() and 1 <= int(override_text) <= 99:\n        return resolve_asset_for_set(role, int(override_text), asset_dir)\n\n    base_text = str(base_set).strip().lower()\n    if base_text == "canonical":\n        return resolve_canonical_asset(role, asset_dir)\n    if base_text != "random" and base_text.isdigit() and 1 <= int(base_text) <= 99:\n        return resolve_asset_for_set(role, int(base_text), asset_dir)\n\n    return resolve_asset(role, asset_dir)\n''',
)

replace_once(
    "desktop_compact.py",
    '''    def _builtin_base_label(value: str) -> str:\n        return "랜덤" if str(value) == "random" else str(value)\n\n    @staticmethod\n    def _builtin_base_value(label: str) -> str:\n        return "random" if str(label) == "랜덤" else str(label)\n\n    @staticmethod\n    def _builtin_override_label(value: str) -> str:\n        return "세트 기본값" if not str(value) else str(value)\n\n    @staticmethod\n    def _builtin_override_value(label: str) -> str:\n        return "" if str(label) == "세트 기본값" else str(label)\n''',
    '''    def _builtin_base_label(value: str) -> str:\n        value = str(value)\n        if value == "canonical":\n            return "기본 모델"\n        return "랜덤" if value == "random" else value\n\n    @staticmethod\n    def _builtin_base_value(label: str) -> str:\n        label = str(label)\n        if label == "기본 모델":\n            return "canonical"\n        return "random" if label == "랜덤" else label\n\n    @staticmethod\n    def _builtin_override_label(value: str) -> str:\n        value = str(value)\n        if value == "canonical":\n            return "기본 모델"\n        return "세트 기본값" if not value else value\n\n    @staticmethod\n    def _builtin_override_value(label: str) -> str:\n        label = str(label)\n        if label == "기본 모델":\n            return "canonical"\n        return "" if label == "세트 기본값" else label\n''',
)

replace_once(
    "desktop_compact.py",
    '''            built_in_row, self.builtin_image_set_var, "랜덤", *built_in_labels,\n''',
    '''            built_in_row, self.builtin_image_set_var, "기본 모델", "랜덤", *built_in_labels,\n''',
)

replace_once(
    "desktop_compact.py",
    '''                options, self.image_builtin_vars[key], "세트 기본값", *self._builtin_set_labels,\n''',
    '''                options, self.image_builtin_vars[key], "세트 기본값", "기본 모델", *self._builtin_set_labels,\n''',
)

replace_once(
    "tests/test_asset_manager.py",
    '''            for role in folders:\n                folder = root / role\n                folder.mkdir()\n                for number in (3, 5):\n                    (folder / f"{role}_{number:02d}.png").write_bytes(b"x")\n\n            set_session_set(3, root)\n''',
    '''            for role in folders:\n                folder = root / role\n                folder.mkdir()\n                for number in (3, 5):\n                    (folder / f"{role}_{number:02d}.png").write_bytes(b"x")\n\n            canonical_default = root / "default" / "main_kyunghee.png"\n            canonical_default.write_bytes(b"x")\n            canonical_warning = root / "warning" / "warning_kyunghee.png"\n            canonical_warning.write_bytes(b"x")\n\n            set_session_set(3, root)\n''',
)

replace_once(
    "tests/test_asset_manager.py",
    '''            self.assertEqual(\n                resolve_configured_asset("praise", "random", "", root),\n                root / "leave" / "leave_03.png",\n            )\n''',
    '''            self.assertEqual(\n                resolve_configured_asset("praise", "random", "", root),\n                root / "leave" / "leave_03.png",\n            )\n            self.assertEqual(\n                resolve_configured_asset("default", "canonical", "", root),\n                canonical_default,\n            )\n            self.assertEqual(\n                resolve_configured_asset("nag", "03", "canonical", root),\n                canonical_warning,\n            )\n''',
)

replace_once(
    "tests/test_settings.py",
    '''        self.assertEqual(parsed.builtin_image_warning, "")\n        self.assertEqual(settings_from_dict({"builtin_image_set": "bad"}).builtin_image_set, "random")\n''',
    '''        self.assertEqual(parsed.builtin_image_warning, "")\n        self.assertEqual(settings_from_dict({"builtin_image_set": "bad"}).builtin_image_set, "random")\n        canonical = settings_from_dict({\n            "builtin_image_set": "canonical",\n            "builtin_image_warning": "canonical",\n        })\n        self.assertEqual(canonical.builtin_image_set, "canonical")\n        self.assertEqual(canonical.builtin_image_warning, "canonical")\n        canonical.validate_widget_style()\n''',
)

print("canonical asset selection fix applied")
