"""Defaults and bounds of the graph index read endpoints (table data, visualization).

The commands take their defaults from here and the REST controller its parameter
defaults and bounds, so the two cannot drift. django_app validates the same bounds
under the same names in `tables/constants/knowledge_constants.py`; they are repeated
here so this service does not rely on its caller to protect it.
"""

__all__ = [
    "GRAPH_SEARCH_MAX_LENGTH",
    "GRAPH_TABLE_DEFAULT_PAGE",
    "GRAPH_TABLE_DEFAULT_PAGE_SIZE",
    "GRAPH_TABLE_MAX_PAGE_SIZE",
    "GRAPH_TABLE_MIN_PAGE",
    "GRAPH_TABLE_MIN_PAGE_SIZE",
    "GRAPH_VISUALIZATION_DEFAULT_MAX_ENTITIES",
    "GRAPH_VISUALIZATION_MIN_MAX_ENTITIES",
]

GRAPH_TABLE_MIN_PAGE = 1
GRAPH_TABLE_DEFAULT_PAGE = 1
GRAPH_TABLE_MIN_PAGE_SIZE = 1
GRAPH_TABLE_MAX_PAGE_SIZE = 100
GRAPH_TABLE_DEFAULT_PAGE_SIZE = 10

GRAPH_SEARCH_MAX_LENGTH = 200

GRAPH_VISUALIZATION_MIN_MAX_ENTITIES = 1
# The highest-degree entities are kept. 200 is what a browser renders smoothly;
# a caller may ask for more, there is no upper cap.
GRAPH_VISUALIZATION_DEFAULT_MAX_ENTITIES = 200
