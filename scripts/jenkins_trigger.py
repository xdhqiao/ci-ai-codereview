from __future__ import annotations

import argparse
import json
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger a ci-ai-codereview task from Jenkins")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--review-version", required=True)
    parser.add_argument("--copy-from-version", default="0_version")
    parser.add_argument("--review-version-path", required=True)
    parser.add_argument("--copy-from-version-path", default="")
    parser.add_argument("--submitter", default="jenkins")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    payload = {
        "project_id": args.project_id,
        "review_version": args.review_version,
        "copy_from_version": args.copy_from_version,
        "review_version_path": args.review_version_path,
        "copy_from_version_path": args.copy_from_version_path,
        "submitter": args.submitter,
        "created_by": "jenkins",
    }
    request = urllib.request.Request(
        f"{args.server.rstrip('/')}/tasks/trigger",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=max(1, args.timeout)) as response:
        print(response.read().decode("utf-8"))


if __name__ == "__main__":
    main()
