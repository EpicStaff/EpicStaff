from django_filters import rest_framework as filters

from tables.models.session_models import Session


class CharInFilter(filters.BaseInFilter, filters.CharFilter):
    pass


class SessionFilter(filters.FilterSet):
    status = CharInFilter(field_name="status", lookup_expr="in")

    class Meta:
        model = Session
        fields = ["graph_id", "status"]
