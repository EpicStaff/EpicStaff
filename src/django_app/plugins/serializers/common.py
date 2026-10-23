from rest_framework import serializers


class UserRefSerializer(serializers.Serializer):
    """A person as the admin pages name them."""

    id = serializers.IntegerField()
    email = serializers.EmailField()
