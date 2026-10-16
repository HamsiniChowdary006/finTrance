from pathlib import Path


def test_no_unsafe_parsing_or_execution():
    root = Path("agent")
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    assert "eval(" not in text
    assert "exec(" not in text
    assert "pickle" not in text
    assert "yaml.load(" not in text
    assert "yaml.unsafe_load(" not in text


def test_no_f_string_sql():
    text = "\n".join(path.read_text(encoding="utf-8") for path in (Path("agent"), Path("store"))
                     if path.is_file())
    assert "f\"SELECT" not in text
    assert "f'SELECT" not in text
