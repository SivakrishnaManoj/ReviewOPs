"""Update only the image of a stable ECS Express service, verify, and attempt rollback."""

import argparse
import copy
import json
import re
import time
from pathlib import Path

import boto3

from scripts.smoke import smoke


def stable_configuration(service: dict) -> dict:
    configurations = service.get("activeConfigurations", [])
    if service.get("status", {}).get("statusCode") != "ACTIVE" or len(configurations) != 1:
        raise RuntimeError("Service must have exactly one stable ACTIVE configuration")
    return configurations[0]


def wait_for_image(client, arn, image, *, attempts=120, pause=time.sleep):
    for _ in range(attempts):
        service = client.describe_express_gateway_service(serviceArn=arn)["service"]
        status = service.get("status", {}).get("statusCode", "")
        if "FAILED" in status or status in {"DELETED", "DRAINING"}:
            raise RuntimeError(f"Service deployment entered {status}")
        configurations = service.get("activeConfigurations", [])
        if status == "ACTIVE" and len(configurations) == 1:
            configuration = configurations[0]
            if configuration["primaryContainer"]["image"] == image:
                return configuration
        pause(5)
    raise TimeoutError("Service did not converge to the requested image within ten minutes")


def endpoint(configuration: dict) -> str:
    for path in configuration.get("ingressPaths", []):
        value = path.get("endpoint", "")
        if value:
            url = value if "://" in value else "https://" + value
            if not url.startswith("https://"):
                raise RuntimeError("Deployment smoke checks require HTTPS")
            return url
    raise RuntimeError("No HTTPS endpoint was returned by ECS")


def deploy(client, arn, image, sha, *, verify=smoke, pause=time.sleep):
    if not re.search(r"@sha256:[a-f0-9]{64}$", image):
        raise ValueError("Deployment requires a sha256 image digest")
    old = stable_configuration(client.describe_express_gateway_service(serviceArn=arn)["service"])
    previous_container = copy.deepcopy(old["primaryContainer"])
    updated_container = copy.deepcopy(previous_container)
    updated_container["image"] = image
    try:
        client.update_express_gateway_service(serviceArn=arn, primaryContainer=updated_container)
        current = wait_for_image(client, arn, image, pause=pause)
        verify(endpoint(current), sha)
    except Exception as error:
        # Never race a deployment that is still in flight. ECS may be rolling itself back.
        try:
            observed = stable_configuration(
                client.describe_express_gateway_service(serviceArn=arn)["service"]
            )
            observed_image = observed["primaryContainer"]["image"]
            if observed_image == image and image != previous_container["image"]:
                client.update_express_gateway_service(
                    serviceArn=arn, primaryContainer=previous_container
                )
                restored = wait_for_image(client, arn, previous_container["image"], pause=pause)
                verify(endpoint(restored), None)
                raise RuntimeError("Deployment failed; previous image restored") from error
            if observed_image == previous_container["image"]:
                raise RuntimeError("Deployment failed; previous image remains active") from error
        except RuntimeError as rollback_error:
            raise RuntimeError(f"{rollback_error}. Inspect the ECS deployment events.") from error
        raise RuntimeError(
            "Deployment failed; inspect ECS before retrying or rolling back"
        ) from error
    return {
        "service_arn": arn,
        "image": image,
        "previous_image": previous_container["image"],
        "build_sha": sha,
        "url": endpoint(current),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-arn", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    result = deploy(boto3.client("ecs"), args.service_arn, args.image, args.sha)
    Path("deployment.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
