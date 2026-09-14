def test_package_exposes_version() -> None:
    import training_kb

    assert training_kb.__version__ == "0.1.0"
