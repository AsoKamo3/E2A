import importlib

def test_versions_smoke():
    app = importlib.import_module("app")
    svc = importlib.import_module("services.eight_to_atena")
    addr = importlib.import_module("converters.address")
    txn  = importlib.import_module("utils.textnorm")
    kana = importlib.import_module("utils.kana")

    assert getattr(svc, "__version__", None) == "v2.31"
    assert getattr(addr, "__version__", None) == "v1.1.0"
    assert getattr(txn, "__version__", None)  == "v1.15"
    assert getattr(kana, "__version__", None) == "v1.0"
