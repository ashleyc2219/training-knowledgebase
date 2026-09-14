from importlib.resources import files


def test_package_exposes_version() -> None:
    import training_kb

    assert training_kb.__version__ == "0.1.0"


def test_package_ships_py_typed_marker() -> None:
    """沒有 `py.typed`，下游（`infra/`）import `training_kb` 就是 `import-untyped`。

    marker 必須跟著**安裝出來的**套件走，所以這裡查 `importlib.resources`，
    不是查 repo 裡的原始檔。
    """
    assert files("training_kb").joinpath("py.typed").is_file()
