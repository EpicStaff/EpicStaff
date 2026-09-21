from tables.serializers.delete_serializers import DeleteReportSerializer


def test_serializer_accepts_an_organization_report():
    payload = {
        "dry_run": True,
        "target": {"type": "organization", "id": 7, "name": "Acme Inc"},
        "database": {
            "total": 4,
            "by_model": [
                {"model": "tables.Graph", "count": 3},
                {"model": "tables.Organization", "count": 1},
            ],
        },
        "field_updates": [
            {
                "model": "tables.Graph",
                "field": "created_by",
                "action": "SET_NULL",
                "count": 2,
            }
        ],
        "external": [
            {
                "kind": "object_storage",
                "prefix": "org_7/",
                "objects": 219,
                "bytes": 5123400,
            }
        ],
    }
    serializer = DeleteReportSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors


def test_serializer_accepts_a_user_report():
    payload = {
        "dry_run": False,
        "target": {"type": "user", "id": 42, "email": "bob@acme.com"},
        "database": {
            "total": 1,
            "by_model": [{"model": "tables.User", "count": 1}],
        },
        "field_updates": [],
        "external": [{"kind": "avatar", "path": "avatars/42/abc.png"}],
    }
    serializer = DeleteReportSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors
