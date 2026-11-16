def test_dashboard_exposes_document_status_breakdown(client, admin_token):
    response = client.get(
        "/api/stats/dashboard",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_documents"] >= data["ready_documents"]
    assert {"pending_documents", "processing_documents", "error_documents"} <= data.keys()


def test_system_logs_are_paginated(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    client.get("/api/stats/dashboard", headers=headers)
    response = client.get("/api/system/logs?page=1&size=2", headers=headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["page"] == 1
    assert data["size"] == 2
    assert data["total"] >= len(data["records"])
    assert len(data["records"]) <= 2

