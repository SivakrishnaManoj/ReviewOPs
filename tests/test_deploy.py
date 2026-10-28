import copy

import pytest

from scripts.deploy import deploy

OLD = "example.ecr/reviewops@sha256:" + "a" * 64
NEW = "example.ecr/reviewops@sha256:" + "b" * 64


class FakeECS:
    def __init__(self):
        self.status = "ACTIVE"
        self.container = {
            "image": OLD,
            "containerPort": 8000,
            "environment": [{"name": "APP_ENV", "value": "demo"}],
            "secrets": [{"name": "DATABASE_URL", "valueFrom": "secret-arn"}],
        }
        self.updates = []

    def describe_express_gateway_service(self, **kwargs):
        return {
            "service": {
                "status": {"statusCode": self.status},
                "activeConfigurations": [
                    {
                        "primaryContainer": copy.deepcopy(self.container),
                        "ingressPaths": [{"endpoint": "demo.ecs.eu-west-2.on.aws"}],
                    }
                ],
            }
        }

    def update_express_gateway_service(self, **kwargs):
        self.container = copy.deepcopy(kwargs["primaryContainer"])
        self.updates.append(copy.deepcopy(self.container))
        return {}


def test_deploy_preserves_environment_secrets_and_verifies_commit():
    client = FakeECS()
    checks = []
    result = deploy(client, "arn", NEW, "commit-1", verify=lambda *args: checks.append(args))
    assert result["previous_image"] == OLD
    assert result["image"] == NEW
    assert client.container["secrets"][0]["valueFrom"] == "secret-arn"
    assert client.container["environment"][0]["value"] == "demo"
    assert checks == [("https://demo.ecs.eu-west-2.on.aws", "commit-1")]


def test_failed_smoke_restores_previous_image():
    client = FakeECS()

    def verify(url, sha):
        if sha:
            raise RuntimeError("Wrong commit")

    with pytest.raises(RuntimeError, match="previous image restored"):
        deploy(client, "arn", NEW, "commit-1", verify=verify)
    assert [item["image"] for item in client.updates] == [NEW, OLD]


def test_does_not_race_an_in_flight_deployment():
    client = FakeECS()
    client.status = "DEPLOYING"
    with pytest.raises(RuntimeError, match="stable ACTIVE"):
        deploy(client, "arn", NEW, "commit-1")
    assert client.updates == []


def test_rejects_mutable_image_tags():
    client = FakeECS()
    with pytest.raises(ValueError, match="sha256"):
        deploy(client, "arn", "example.ecr/reviewops:latest", "commit-1")
    assert client.updates == []
