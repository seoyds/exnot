from exnot.dashboard.routes import router


def test_documents_routes_registered():
    route_paths = [r.path for r in router.routes if hasattr(r, "path")]
    assert "/dashboard/exchanges/{code}/documents" in route_paths
    assert "/dashboard/exchanges/{code}/documents/{doc_id}/approve" in route_paths
    assert "/dashboard/exchanges/{code}/documents/{doc_id}/approve-pin" in route_paths
    assert "/dashboard/exchanges/{code}/documents/{doc_id}/reject" in route_paths
    assert "/dashboard/exchanges/{code}/documents/{doc_id}/pin" in route_paths
    assert "/dashboard/exchanges/{code}/documents/{doc_id}/unpin" in route_paths
