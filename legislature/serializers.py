from rest_framework import serializers
from .models import Parliamentarian, Party, Project, Theme, Voting, Vote


class PartySerializer(serializers.ModelSerializer):
    class Meta:
        model = Party
        fields = ["id", "name", "acronym"]


class ParliamentarianSerializer(serializers.ModelSerializer):
    party = PartySerializer(read_only=True)
    class Meta:
        model = Parliamentarian
        fields = ["id", "external_id", "name", "civil_name", "photo_url", "role", "state", "city", "level", "party", "is_mock", "is_active"]


class ThemeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Theme
        fields = ["id", "name"]


class ProjectSerializer(serializers.ModelSerializer):
    author = ParliamentarianSerializer(read_only=True)
    themes = ThemeSerializer(many=True, read_only=True)
    source_name = serializers.CharField(source="source.name", read_only=True)
    class Meta:
        model = Project
        fields = ["id", "external_id", "code", "title", "description", "type_description", "keywords", "situation", "regime", "full_text_url", "presented_at", "status", "level", "author", "themes", "source_name", "is_mock"]


class VoteSerializer(serializers.ModelSerializer):
    parliamentarian_name = serializers.CharField(source="parliamentarian.name", read_only=True)
    class Meta:
        model = Vote
        fields = ["parliamentarian_name", "choice"]


class VotingSerializer(serializers.ModelSerializer):
    votes = VoteSerializer(many=True, read_only=True)
    class Meta:
        model = Voting
        fields = ["id", "external_id", "title", "description", "voted_at", "result", "level", "project", "votes"]
