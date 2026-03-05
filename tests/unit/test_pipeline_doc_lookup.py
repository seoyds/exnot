from exnot.workers.pipelines import _get_approved_document_urls


def test_get_approved_document_urls_exists():
    assert callable(_get_approved_document_urls)
