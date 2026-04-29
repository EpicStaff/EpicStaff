MOCK_FOLDER_TREE = {
    "path": "/",
    "items": [
        {"name": "reports", "type": "folder", "modified": "2026-03-15T10:30:00Z"},
        {"name": "datasets", "type": "folder", "modified": "2026-03-20T14:00:00Z"},
        {"name": "archive", "type": "folder", "modified": "2026-02-28T09:00:00Z"},
        {
            "name": "summary.csv",
            "type": "file",
            "size": 245760,
            "modified": "2026-03-25T16:45:00Z",
        },
        {
            "name": "config.json",
            "type": "file",
            "size": 1024,
            "modified": "2026-03-22T11:20:00Z",
        },
        {
            "name": "model_weights.bin",
            "type": "file",
            "size": 52428800,
            "modified": "2026-03-18T08:15:00Z",
        },
        {
            "name": "README.md",
            "type": "file",
            "size": 4096,
            "modified": "2026-03-10T12:00:00Z",
        },
        {
            "name": "pipeline_output.log",
            "type": "file",
            "size": 89200,
            "modified": "2026-03-28T19:30:00Z",
        },
    ],
}

MOCK_FILE_INFO = {
    "path": "/summary.csv",
    "name": "summary.csv",
    "type": "file",
    "size": 245760,
    "modified": "2026-03-25T16:45:00Z",
    "created": "2026-03-20T09:00:00Z",
    "content_type": "text/csv",
    "etag": "a1b2c3d4e5f6",
}

MOCK_SAMPLE_FILE_CONTENT = "id,name,value\n1,alpha,100\n2,beta,200\n3,gamma,300\n"

MOCK_SESSION_OUTPUTS = [
    {
        "path": "/sessions/42/output_data.csv",
        "size": 102400,
        "created": "2026-03-29T10:00:00Z",
    },
    {
        "path": "/sessions/42/predictions.json",
        "size": 20480,
        "created": "2026-03-29T10:05:00Z",
    },
    {
        "path": "/sessions/42/run.log",
        "size": 8192,
        "created": "2026-03-29T10:10:00Z",
    },
]
