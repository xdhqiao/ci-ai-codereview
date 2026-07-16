from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SOURCE_FILES = {
    "auth.c": """#include <stdio.h>
#include <string.h>

int auth_copy_user(char *destination, size_t capacity, const char *source) {
    if (destination == NULL || source == NULL || capacity == 0) {
        return -1;
    }
    int written = snprintf(destination, capacity, "%s", source);
    return written < 0 || (size_t)written >= capacity ? -1 : 0;
}
""",
    "buffer.c": """#include <stddef.h>

int buffer_sum(const int *values, size_t count, int *result) {
    if (values == NULL || result == NULL) {
        return -1;
    }
    int total = 0;
    for (size_t index = 0; index < count; ++index) {
        total += values[index];
    }
    *result = total;
    return 0;
}
""",
    "config_store.c": """#include <stddef.h>

static int active_mode = 0;

int config_set_mode(int mode) {
    if (mode < 0 || mode > 3) {
        return -1;
    }
    active_mode = mode;
    return 0;
}

int config_get_mode(void) {
    return active_mode;
}
""",
    "logger.c": """#include <stdio.h>

int logger_write(const char *message) {
    if (message == NULL) {
        return -1;
    }
    return fprintf(stderr, "%s\\n", message) < 0 ? -1 : 0;
}
""",
    "net_client.c": """#include <stddef.h>

int net_validate_packet(const unsigned char *packet, size_t length) {
    if (packet == NULL || length < 2) {
        return -1;
    }
    return packet[0] == 0x43 && packet[1] == 0x52 ? 0 : -1;
}
""",
    "parser.c": """#include <errno.h>
#include <limits.h>
#include <stdlib.h>

int parser_read_positive(const char *text, int *value) {
    if (text == NULL || value == NULL) {
        return -1;
    }
    errno = 0;
    char *end = NULL;
    long parsed = strtol(text, &end, 10);
    if (errno != 0 || end == text || *end != '\\0' || parsed < 0 || parsed > INT_MAX) {
        return -1;
    }
    *value = (int)parsed;
    return 0;
}
""",
    "queue.c": """#include <stddef.h>

int queue_next_index(size_t current, size_t capacity, size_t *next) {
    if (next == NULL || capacity == 0 || current >= capacity) {
        return -1;
    }
    *next = (current + 1U) % capacity;
    return 0;
}
""",
    "reporter.c": """#include <stdio.h>

int reporter_format(char *output, size_t capacity, int value) {
    if (output == NULL || capacity == 0) {
        return -1;
    }
    int written = snprintf(output, capacity, "value=%d", value);
    return written < 0 || (size_t)written >= capacity ? -1 : 0;
}
""",
    "sensor.c": """#include <stddef.h>

int sensor_average(const int *samples, size_t count, int *average) {
    if (samples == NULL || average == NULL || count == 0) {
        return -1;
    }
    long total = 0;
    for (size_t index = 0; index < count; ++index) {
        total += samples[index];
    }
    *average = (int)(total / (long)count);
    return 0;
}
""",
    "storage.c": """#include <stddef.h>
#include <string.h>

int storage_copy(void *destination, size_t capacity, const void *source, size_t length) {
    if (destination == NULL || source == NULL || length > capacity) {
        return -1;
    }
    memcpy(destination, source, length);
    return 0;
}
""",
}


class IntegrationFailure(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise IntegrationFailure(f"HTTP {exc.code} for {method} {path}: {body}") from exc
        except URLError as exc:
            raise IntegrationFailure(f"Cannot reach {self.base_url}: {exc}") from exc

    def health(self) -> dict[str, Any]:
        return self.request("GET", "/health")

    def trigger(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/tasks/trigger", payload)

    def task(self, task_id: str) -> dict[str, Any]:
        return self.request("GET", f"/tasks/{task_id}")

    def code_files(self, task_id: str) -> list[dict[str, Any]]:
        query = urlencode({"task_id": task_id, "limit": 200})
        response = self.request("GET", f"/code-files?{query}")
        if response["total"] != len(response["items"]):
            raise IntegrationFailure(f"Code-file response was unexpectedly paginated: {response['total']}")
        return sorted(response["items"], key=lambda item: item["file_name"])


class Timeline:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self.events: list[dict[str, Any]] = []
        self._last: dict[str, tuple[Any, ...]] = {}

    def sample(self, label: str, task: dict[str, Any], phase: str) -> None:
        state = (
            task["state"],
            task["completion_status"],
            task["reviewed_file_num"],
            task["resumed_file_num"],
            task["trigger_revision"],
        )
        if self._last.get(label) == state:
            return
        self._last[label] = state
        self.events.append(
            {
                "elapsed_seconds": round(time.monotonic() - self.started, 3),
                "phase": phase,
                "task": label,
                "state": task["state"],
                "completion_status": task["completion_status"],
                "reviewed_file_num": task["reviewed_file_num"],
                "resumed_file_num": task["resumed_file_num"],
                "trigger_revision": task["trigger_revision"],
            }
        )


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise IntegrationFailure(message)


def wait_until(
    description: str,
    predicate: Callable[[], Any],
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> Any:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except (IntegrationFailure, KeyError) as exc:
            last_error = exc
        time.sleep(poll_seconds)
    suffix = f"; last error: {last_error}" if last_error else ""
    raise IntegrationFailure(f"Timed out waiting for {description}{suffix}")


def write_repository(root: Path) -> tuple[Path, Path]:
    master = root / "master"
    feature = root / "wip_qiaodahai_just_demo"
    master_src = master / "src"
    feature_src = feature / "src"
    master_src.mkdir(parents=True, exist_ok=False)
    for file_name, source in SOURCE_FILES.items():
        (master_src / file_name).write_text(source, encoding="utf-8", newline="\n")
    shutil.copytree(master_src, feature_src)

    replace_text(
        feature_src / "auth.c",
        'int written = snprintf(destination, capacity, "%s", source);\n'
        "    return written < 0 || (size_t)written >= capacity ? -1 : 0;",
        "strcpy(destination, source);\n    return 0;",
    )
    replace_text(
        feature_src / "parser.c",
        "long parsed = strtol(text, &end, 10);\n"
        "    if (errno != 0 || end == text || *end != '\\0' || parsed < 0 || parsed > INT_MAX) {",
        "long parsed = strtol(text, &end, 10);\n"
        "    if (end == text) {",
    )
    return master, feature


def replace_text(path: Path, old: str, new: str) -> None:
    source = path.read_text(encoding="utf-8")
    if old not in source:
        raise IntegrationFailure(f"Fixture mutation target not found in {path}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8", newline="\n")


def apply_second_revision(master: Path, feature: Path) -> None:
    storage_suffix = """

int storage_zero(void *destination, size_t capacity) {
    if (destination == NULL || capacity == 0) {
        return -1;
    }
    memset(destination, 0, capacity);
    return 0;
}
"""
    for version_path in (master, feature):
        storage_path = version_path / "src" / "storage.c"
        storage_path.write_text(
            storage_path.read_text(encoding="utf-8").rstrip() + storage_suffix,
            encoding="utf-8",
            newline="\n",
        )
    replace_text(
        feature / "src" / "auth.c",
        "strcpy(destination, source);\n    return 0;",
        'sprintf(destination, "%s", source);\n    return 0;',
    )


def trigger_payload(
    *,
    project_id: str,
    review_version: str,
    copy_from_version: str,
    review_path: str,
    copy_path: str = "",
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "review_version": review_version,
        "copy_from_version": copy_from_version,
        "review_version_path": review_path,
        "copy_from_version_path": copy_path,
        "submitter": "client-server-e2e",
        "created_by": "jenkins-e2e",
    }


def block_signature(code_file: dict[str, Any]) -> list[dict[str, Any]]:
    signatures: list[dict[str, Any]] = []
    for block in code_file["code_blocks"]:
        signatures.append(
            {
                "block_id": block["block_id"],
                "block_hash": block["block_hash"],
                "review_fingerprint": block["review_fingerprint"],
                "main_task_completed": block["main_task_completed"],
                "failure_message": block["failure_message"],
                "llm_total_tokens": block["llm_total_tokens"],
                "main_task_round_count": block["main_task_round_count"],
                "model_rounds": block["model_rounds"],
                "tool_calls": block["tool_calls"],
                "comment": block["comment"],
                "issues": block["issues"],
            }
        )
    return signatures


def file_snapshot(files: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        item["file_name"]: {
            "id": item["id"],
            "state": item["state"],
            "source_hash": item["source_hash"],
            "review_fingerprint": item["review_fingerprint"],
            "trigger_revision": item["trigger_revision"],
            "blocks": block_signature(item),
        }
        for item in files
    }


def compact_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        key: task[key]
        for key in (
            "id",
            "state",
            "completion_status",
            "task_type",
            "trigger_count",
            "trigger_revision",
            "file_num",
            "reviewed_file_num",
            "resumed_file_num",
            "incomplete_file_num",
            "llm_call_count",
            "llm_prompt_tokens",
            "llm_completion_tokens",
            "llm_total_tokens",
            "llm_elapsed_ms",
            "process_time",
        )
    }


def assert_completed_files(files: list[dict[str, Any]], expected_count: int, label: str) -> None:
    assert_true(len(files) == expected_count, f"{label}: expected {expected_count} files, got {len(files)}")
    incomplete = [item["file_name"] for item in files if item["state"] != 2]
    failed_blocks = [
        f"{item['file_name']}#{block['block_id']}:{block['failure_message']}"
        for item in files
        for block in item["code_blocks"]
        if not block["main_task_completed"] or block["failure_message"]
    ]
    assert_true(not incomplete, f"{label}: incomplete files: {incomplete}")
    assert_true(not failed_blocks, f"{label}: incomplete blocks: {failed_blocks}")


def wait_for_terminal_pair(
    client: ApiClient,
    full_id: str,
    incremental_id: str,
    timeline: Timeline,
    phase: str,
    timeout_seconds: float,
    poll_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bool]]:
    deadline = time.monotonic() + timeout_seconds
    observations = {
        "full_interrupted": False,
        "incremental_running": False,
        "incremental_completed_before_full": False,
        "full_resumed_after_incremental": False,
    }
    incremental_completed = False
    last_full: dict[str, Any] = {}
    last_incremental: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_full = client.task(full_id)
        last_incremental = client.task(incremental_id)
        timeline.sample("full", last_full, phase)
        timeline.sample("incremental", last_incremental, phase)
        if last_full["state"] == 0 and last_full["completion_status"] == "interrupted":
            observations["full_interrupted"] = True
        if last_incremental["state"] == 1:
            observations["incremental_running"] = True
        if last_incremental["state"] == 2 and last_full["state"] != 2:
            observations["incremental_completed_before_full"] = True
            incremental_completed = True
        if incremental_completed and last_full["state"] == 1:
            observations["full_resumed_after_incremental"] = True
        if last_full["state"] in {2, 3} and last_incremental["state"] in {2, 3}:
            return last_full, last_incremental, observations
        time.sleep(poll_seconds)
    raise IntegrationFailure(
        f"Timed out waiting for {phase} tasks; full={compact_task(last_full)}, "
        f"incremental={compact_task(last_incremental)}"
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    client = ApiClient(args.server, timeout_seconds=args.http_timeout)
    health = client.health()
    assert_true(health.get("status") == "ok", f"Server is not healthy: {health}")

    host_root = args.host_repository_root.resolve()
    assert_true(not host_root.exists(), f"Run directory already exists: {host_root}")
    master_host, feature_host = write_repository(host_root)
    server_root = args.server_repository_root.rstrip("/")
    master_server = f"{server_root}/master"
    feature_server = f"{server_root}/wip_qiaodahai_just_demo"

    full_payload = trigger_payload(
        project_id=args.project_id,
        review_version="master",
        copy_from_version="0_version",
        review_path=master_server,
    )
    incremental_payload = trigger_payload(
        project_id=args.project_id,
        review_version="wip_qiaodahai_just_demo",
        copy_from_version="master",
        review_path=feature_server,
        copy_path=master_server,
    )

    timeline = Timeline()
    started = time.monotonic()
    full_initial = client.trigger(full_payload)
    full_id = full_initial["id"]
    full_prewrite = client.code_files(full_id)
    assert_true(full_initial["task_type"] == 2, "Full submission has the wrong task_type")
    assert_true(len(full_prewrite) == 10, f"Full client submission persisted {len(full_prewrite)} files, expected 10")
    assert_true(all(item["state"] == 0 for item in full_prewrite), "Full files were not all pending after submission")

    def full_has_active_file() -> dict[str, Any] | None:
        task = client.task(full_id)
        timeline.sample("full", task, "step1")
        if task["state"] != 1:
            return None
        files = client.code_files(full_id)
        return task if any(item["state"] == 1 for item in files) else None

    full_running = wait_until(
        "the full task to start reviewing a file",
        full_has_active_file,
        timeout_seconds=args.task_timeout,
        poll_seconds=args.poll_interval,
    )
    assert_true(full_running["reviewed_file_num"] < 10, "Full task completed before the incremental trigger")

    incremental_initial = client.trigger(incremental_payload)
    incremental_id = incremental_initial["id"]
    incremental_prewrite = client.code_files(incremental_id)
    assert_true(incremental_initial["task_type"] == 1, "Incremental submission has the wrong task_type")
    assert_true(
        [item["file_name"] for item in incremental_prewrite] == ["src/auth.c", "src/parser.c"],
        "Initial incremental diff did not persist exactly auth.c and parser.c",
    )

    full_step1, incremental_step1, observations = wait_for_terminal_pair(
        client,
        full_id,
        incremental_id,
        timeline,
        "step1",
        args.task_timeout,
        args.poll_interval,
    )
    assert_true(full_step1["state"] == 2, f"Full Step1 task failed: {compact_task(full_step1)}")
    assert_true(incremental_step1["state"] == 2, f"Incremental Step1 task failed: {compact_task(incremental_step1)}")
    for name, observed in observations.items():
        assert_true(observed, f"Step1 scheduler observation was not seen: {name}")

    full_files_step1 = client.code_files(full_id)
    incremental_files_step1 = client.code_files(incremental_id)
    assert_completed_files(full_files_step1, 10, "Step1 full")
    assert_completed_files(incremental_files_step1, 2, "Step1 incremental")
    full_snapshot_step1 = file_snapshot(full_files_step1)
    incremental_snapshot_step1 = file_snapshot(incremental_files_step1)
    step1_elapsed = round(time.monotonic() - started, 3)

    apply_second_revision(master_host, feature_host)
    full_retriggered = client.trigger(full_payload)
    incremental_retriggered = client.trigger(incremental_payload)
    assert_true(full_retriggered["id"] == full_id, "Full retrigger created a new task instead of resuming the same identity")
    assert_true(
        incremental_retriggered["id"] == incremental_id,
        "Incremental retrigger created a new task instead of resuming the same identity",
    )

    full_after_sync = client.code_files(full_id)
    incremental_after_sync = client.code_files(incremental_id)
    full_pending = sorted(
        item["file_name"]
        for item in full_after_sync
        if not item["code_blocks"] or not all(block["main_task_completed"] for block in item["code_blocks"])
    )
    incremental_pending = sorted(
        item["file_name"]
        for item in incremental_after_sync
        if not item["code_blocks"] or not all(block["main_task_completed"] for block in item["code_blocks"])
    )
    assert_true(full_pending == ["src/storage.c"], f"Full retrigger pending files were {full_pending}")
    assert_true(incremental_pending == ["src/auth.c"], f"Incremental retrigger pending files were {incremental_pending}")

    step2_started = time.monotonic()
    full_step2, incremental_step2, _ = wait_for_terminal_pair(
        client,
        full_id,
        incremental_id,
        timeline,
        "step2",
        args.task_timeout,
        args.poll_interval,
    )
    assert_true(full_step2["state"] == 2, f"Full Step2 task failed: {compact_task(full_step2)}")
    assert_true(incremental_step2["state"] == 2, f"Incremental Step2 task failed: {compact_task(incremental_step2)}")

    full_files_step2 = client.code_files(full_id)
    incremental_files_step2 = client.code_files(incremental_id)
    assert_completed_files(full_files_step2, 10, "Step2 full")
    assert_completed_files(incremental_files_step2, 2, "Step2 incremental")
    full_snapshot_step2 = file_snapshot(full_files_step2)
    incremental_snapshot_step2 = file_snapshot(incremental_files_step2)

    full_changed = sorted(
        name
        for name in full_snapshot_step1
        if full_snapshot_step1[name]["blocks"] != full_snapshot_step2[name]["blocks"]
    )
    incremental_changed = sorted(
        name
        for name in incremental_snapshot_step1
        if incremental_snapshot_step1[name]["blocks"] != incremental_snapshot_step2[name]["blocks"]
    )
    full_reused = sorted(set(full_snapshot_step1) - set(full_changed))
    incremental_reused = sorted(set(incremental_snapshot_step1) - set(incremental_changed))
    assert_true(full_changed == ["src/storage.c"], f"Full task re-reviewed unexpected files: {full_changed}")
    assert_true(incremental_changed == ["src/auth.c"], f"Incremental task re-reviewed unexpected files: {incremental_changed}")
    assert_true(full_step2["trigger_count"] == 2 and full_step2["trigger_revision"] == 2, "Full trigger counters are wrong")
    assert_true(
        incremental_step2["trigger_count"] == 2 and incremental_step2["trigger_revision"] == 2,
        "Incremental trigger counters are wrong",
    )
    assert_true(full_step2["resumed_file_num"] == 9, f"Full resumed_file_num was {full_step2['resumed_file_num']}, expected 9")
    assert_true(
        incremental_step2["resumed_file_num"] == 1,
        f"Incremental resumed_file_num was {incremental_step2['resumed_file_num']}, expected 1",
    )
    assert_true(full_step2["llm_total_tokens"] > full_step1["llm_total_tokens"], "Full task token total did not accumulate")
    assert_true(
        incremental_step2["llm_total_tokens"] > incremental_step1["llm_total_tokens"],
        "Incremental task token total did not accumulate",
    )
    assert_true(full_step2["llm_call_count"] > full_step1["llm_call_count"], "Full task call count did not accumulate")
    assert_true(
        incremental_step2["llm_call_count"] > incremental_step1["llm_call_count"],
        "Incremental task call count did not accumulate",
    )

    step3_started = time.monotonic()
    full_no_change = client.trigger(full_payload)
    incremental_no_change = client.trigger(incremental_payload)
    assert_true(full_no_change["state"] == 2, "Unchanged full retrigger was queued instead of completed")
    assert_true(
        incremental_no_change["state"] == 2,
        "Unchanged incremental retrigger was queued instead of completed",
    )
    assert_true(
        full_no_change["trigger_count"] == 3 and full_no_change["trigger_revision"] == 3,
        "Unchanged full trigger counters are wrong",
    )
    assert_true(
        incremental_no_change["trigger_count"] == 3 and incremental_no_change["trigger_revision"] == 3,
        "Unchanged incremental trigger counters are wrong",
    )
    for field_name in ("llm_total_tokens", "llm_call_count", "llm_elapsed_ms", "process_time"):
        assert_true(
            full_no_change[field_name] == full_step2[field_name],
            f"Unchanged full retrigger modified {field_name}",
        )
        assert_true(
            incremental_no_change[field_name] == incremental_step2[field_name],
            f"Unchanged incremental retrigger modified {field_name}",
        )

    full_files_step3 = client.code_files(full_id)
    incremental_files_step3 = client.code_files(incremental_id)
    full_snapshot_step3 = file_snapshot(full_files_step3)
    incremental_snapshot_step3 = file_snapshot(incremental_files_step3)
    assert_completed_files(full_files_step3, 10, "Step3 unchanged full")
    assert_completed_files(incremental_files_step3, 2, "Step3 unchanged incremental")
    assert_true(
        all(full_snapshot_step2[name]["blocks"] == full_snapshot_step3[name]["blocks"] for name in full_snapshot_step2),
        "Unchanged full retrigger modified persisted Block review results",
    )
    assert_true(
        all(
            incremental_snapshot_step2[name]["blocks"] == incremental_snapshot_step3[name]["blocks"]
            for name in incremental_snapshot_step2
        ),
        "Unchanged incremental retrigger modified persisted Block review results",
    )

    model_names = sorted(
        {
            trace["model"]
            for item in full_files_step2 + incremental_files_step2
            for block in item["code_blocks"]
            for trace in block["model_rounds"]
            if trace["model"]
        }
    )
    assert_true(bool(model_names), "No real model traces were persisted")

    return {
        "status": "passed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "server": args.server,
        "project_id": args.project_id,
        "repository": {
            "host_root": str(host_root),
            "server_root": server_root,
            "file_count": len(SOURCE_FILES),
        },
        "real_model_names": model_names,
        "step1": {
            "elapsed_seconds": step1_elapsed,
            "full": compact_task(full_step1),
            "incremental": compact_task(incremental_step1),
            "scheduler_observations": observations,
            "full_files": sorted(full_snapshot_step1),
            "incremental_files": sorted(incremental_snapshot_step1),
        },
        "step2": {
            "elapsed_seconds": round(time.monotonic() - step2_started, 3),
            "full": compact_task(full_step2),
            "incremental": compact_task(incremental_step2),
            "full_re_reviewed_files": full_changed,
            "full_reused_files": full_reused,
            "incremental_re_reviewed_files": incremental_changed,
            "incremental_reused_files": incremental_reused,
            "full_token_delta": full_step2["llm_total_tokens"] - full_step1["llm_total_tokens"],
            "incremental_token_delta": incremental_step2["llm_total_tokens"] - incremental_step1["llm_total_tokens"],
            "full_call_delta": full_step2["llm_call_count"] - full_step1["llm_call_count"],
            "incremental_call_delta": incremental_step2["llm_call_count"] - incremental_step1["llm_call_count"],
        },
        "step3": {
            "elapsed_seconds": round(time.monotonic() - step3_started, 3),
            "full": compact_task(full_no_change),
            "incremental": compact_task(incremental_no_change),
            "full_reused_files": sorted(full_snapshot_step3),
            "incremental_reused_files": sorted(incremental_snapshot_step3),
            "llm_call_delta": 0,
            "token_delta": 0,
        },
        "timeline": timeline.events,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a real client/server preemption and resume integration test.")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--host-repository-root", type=Path, required=True)
    parser.add_argument("--server-repository-root", required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--task-timeout", type=float, default=3600.0)
    parser.add_argument("--http-timeout", type=float, default=60.0)
    parser.add_argument("--poll-interval", type=float, default=0.5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = run(args)
    except Exception as exc:
        print(f"E2E FAILED: {exc}", file=sys.stderr)
        return 1
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Artifact: {args.artifact.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
