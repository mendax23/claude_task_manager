from rest_framework import serializers
from .models import Task, TaskRun, TaskChain


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at", "completed_at"]


class TaskRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskRun
        fields = "__all__"
        read_only_fields = ["started_at", "created_at", "updated_at"]


class TaskChainSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskChain
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at"]
