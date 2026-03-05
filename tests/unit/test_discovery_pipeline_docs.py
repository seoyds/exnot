from exnot.discovery.pipeline import _create_exchange_documents


def test_create_exchange_documents_function_exists():
    assert callable(_create_exchange_documents)
