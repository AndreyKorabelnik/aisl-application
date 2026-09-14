"""Reviewer-only F4.103 production CLI/TCP probe; never edits reference source.

Raw execution evidence goes outside the source tree. This is not a scored LLM run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import socket
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request

from derive_reference import dump, module

REFERENCE_SHA = "dae19d29160b464b91235652c3b012cf96a2becc8c0ded25ec4ca1ca81b40557"
REFERENCE_COMMIT = "ecb6ae4833049cc382316bd11f9d2a6c7bb0b006"


def environment(source, dependencies, work):
    # Explicit core-only deployment: pilot inputs require no technology extension.
    # The canonical deployment policy remains unchanged in reference source.
    policy = work / "core-only-policy.json"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(json.dumps({"schema_version": "technology_extension_deployment_policy/v1",
        "spi_version": "technology-extension-spi/v1", "extensions": []}) + "\n")
    # Source-mode launchers project existing package script metadata. This is
    # NOT wheel/installation acceptance and supplies no alternate implementation.
    bin_dir = work / "bin"
    bin_dir.mkdir(parents=True)
    for config in (source / "packages").glob("*/pyproject.toml"):
        for name, entry in tomllib.loads(config.read_text()).get("project", {}).get("scripts", {}).items():
            mod, func = entry.split(":", 1)
            launcher = bin_dir / name
            launcher.write_text(f"#!{sys.executable}\nfrom {mod} import {func}\nraise SystemExit({func}())\n")
            launcher.chmod(0o755)
    paths = [str(dependencies)] + [str(p / "src" if (p / "src").is_dir() else p)
        for p in sorted((source / "packages").iterdir()) if p.is_dir()]
    return {**os.environ, "PYTHONPATH": os.pathsep.join(paths), "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "AISL_TECHNOLOGY_EXTENSION_POLICY": str(policy),
        "STATIC_ANALYSIS_RUNNER_COMMAND": shlex.join([sys.executable, "-B", "-m", "static_analysis_runner"]),
        "AISL_INTEGRATION_CONTENT_DIR": str(source / "integration-content"),
        "KNOWLEDGE_CONTROL_PLANE_RUNTIME_ROOT": str(work / "control-plane"),
        "KNOWLEDGE_CONTROL_PLANE_ANALYSIS_OUTPUT_ROOT": str(work / "analysis")}


def run(source, archive, dependencies, pack, work):
    if work.exists():
        raise ValueError("evidence destination must be new; preserve previous runs")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != REFERENCE_SHA:
        raise ValueError("wrong reference archive")
    owner = module("production_integrity", source / "tools/build-aisl-deliveries.py")
    manifest = owner.read_source_manifest(source)
    if len(manifest["files"]) != 799:
        raise ValueError("unexpected F4.103 file count")
    work.mkdir(parents=True)
    env = environment(source, dependencies, work)
    checks, commands, replies = [], [], []
    report = {"status": "RUNNING", "reference": "F4.103", "source_zip_sha256": REFERENCE_SHA,
        "reference_commit": REFERENCE_COMMIT, "manifest_entries": 799,
        "deployment": "explicit core-only policy; source-mode entry points; no wheel/install claim",
        "scored_run": False, "checks": checks, "commands": commands,
        "boundary": "production KCP CLI -> Runner/Core/KLC -> KCP publication adapter -> Knowledge API import CLI -> TCP API -> deterministic consumer"}

    def check(name, passed, detail=None):
        checks.append({"name": name, "status": "PASS" if passed else "FAIL", "detail": detail})
        dump(work / "report.json", report)
        if not passed:
            raise AssertionError(name)

    def cli(name, args, success=True):
        cmd = [sys.executable, "-B", "-m", args[0] + ".cli", *args[1:]]
        proc = subprocess.run(cmd, cwd=work, env=env, text=True, capture_output=True, timeout=180)
        (work / (name + ".stdout")).write_text(proc.stdout, encoding="utf-8")
        (work / (name + ".stderr")).write_text(proc.stderr, encoding="utf-8")
        commands.append({"name": name, "argv": cmd, "exit_code": proc.returncode})
        check(name + "_exit", (proc.returncode == 0) == success, proc.stderr[-2000:] if proc.returncode else None)
        return json.loads(proc.stdout)

    server = None
    try:
        profiles = cli("profiles", ["knowledge_control_plane", "profile", "list", "--json"])
        dump(work / "profiles.json", profiles)
        repo = work / "fixture"
        repo.mkdir()
        for name in ["Sample.java", "declared-openapi.json", "sql-cases.sql"]:
            shutil.copyfile(pack / "learner/examples" / name, repo / name)
        # Repository discovery uses normal build metadata, not a hidden repository registry.
        (repo / "pom.xml").write_text('<project><modelVersion>4.0.0</modelVersion><groupId>sdd</groupId><artifactId>pilot</artifactId><version>1</version></project>\n', encoding="utf-8")
        storage = ["--database", str(work / "server/catalog.sqlite3"), "--artifact-store", str(work / "server/artifacts")]
        revisions = {}
        for label, profile_id in [("sql", "sql-source-inventory-v1"), ("declared", "data-model-v1")]:
            resolved = cli(label + "_resolve", ["knowledge_control_plane", "profile", "resolve", profile_id, "--json"])
            dump(work / (label + "-resolved.json"), resolved)
            job = cli(label + "_run", ["knowledge_control_plane", "run", "--knowledge-profile", profile_id,
                "--system-id", "sdd-" + label, "--repository", str(repo), "--output", str(work / "analysis" / (label + "-output")),
                "--process-timeout-seconds", "120", "--json"])
            dump(work / (label + "-job.json"), job)
            bundles = list((work / "analysis" / (label + "-output")).rglob("*.zip"))
            check(label + "_one_publication_bundle", len(bundles) == 1, [str(p) for p in bundles])
            imported = cli(label + "_import", ["knowledge_api", "import", *storage, "--bundle", str(bundles[0]), "--format", "json"])
            check(label + "_published", imported["status"] == "published")
            revisions[label] = imported["revision_id"]
            duplicate = cli(label + "_duplicate", ["knowledge_api", "import", *storage, "--bundle", str(bundles[0]), "--format", "json"])
            check(label + "_duplicate_same_revision", duplicate["status"] == "already_published" and duplicate["revision_id"] == revisions[label])
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        log = (work / "server.log").open("w", encoding="utf-8")
        server_cmd = [sys.executable, "-B", "-m", "knowledge_api.cli", "serve", *storage, "--host", "127.0.0.1", "--port", str(port)]
        server = subprocess.Popen(server_cmd, cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT)
        commands.append({"name": "serve", "argv": server_cmd})
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("server exited; inspect server.log")
            try:
                with urllib.request.urlopen(base + "/openapi.json", timeout=1) as response:
                    live_openapi = json.load(response)
                break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.1)
        else:
            raise TimeoutError("TCP server did not become ready")
        check("tcp_server_openapi", bool(live_openapi["paths"]))
        sys.path.insert(0, str(dependencies))
        import jsonschema

        def get(label, suffix, params, status=200):
            url = base + "/api/knowledge/v1/systems/sdd-" + label + "/" + suffix
            url += "?" + urllib.parse.urlencode(params)
            try:
                response = urllib.request.urlopen(url, timeout=15)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                body = json.load(response)
                actual_status = response.status
            replies.append({"label": label, "suffix": suffix, "params": params, "status": actual_status, "body": body})
            dump(work / "http-responses.json", replies)
            check("http_" + str(len(replies)), actual_status == status, {"expected": status, "actual": actual_status})
            path = "/api/knowledge/v1/systems/{system_id}/" + suffix
            if "/declared-objects/" in path:
                path = path.rsplit("/", 1)[0] + "/{object_id}"
            schemas = live_openapi["paths"][path]["get"]["responses"][str(status)].get("content", {})
            if "application/json" in schemas:
                schema = {**schemas["application/json"]["schema"], "components": live_openapi["components"]}
                errors = list(jsonschema.Draft202012Validator(schema).iter_errors(body))
                check("http_schema_" + str(len(replies)), not errors, [e.message for e in errors][:2] or None)
            return body

        first = get("sql", "sql/joins", {"revision_id": revisions["sql"], "offset": 0, "limit": 3})
        total = first["page"]["total"]
        rows = list(first["items"])
        for offset in range(3, total, 3):
            rows += get("sql", "sql/joins", {"revision_id": revisions["sql"], "offset": offset, "limit": 3})["items"]
        check("sql_all_eight_joins", len(rows) == total == 8)
        check("sql_no_duplicate_ids", len({r["sql_join_edge_id"] for r in rows}) == total)
        empty = get("sql", "sql/joins", {"revision_id": revisions["sql"], "offset": total, "limit": 3})
        check("empty_page_preserves_total", empty["items"] == [] and empty["page"]["total"] == total)
        get("sql", "sql/joins", {}, 422)
        get("sql", "sql/joins", {"revision_id": "latest"}, 400)
        get("sql", "sql/joins", {"revision_id": "missing"}, 404)
        get("sql", "sql/joins", {"revision_id": revisions["sql"], "limit": 0}, 422)
        tools = json.loads((pack / "learner/public-contracts/tools.selected.json").read_text())
        search_path = tools["search_declared_data_objects"]["api_binding"]["path_template"].split("/systems/{system_id}/", 1)[1]
        objects = get("declared", search_path, {"revision_id": revisions["declared"]})
        dump(work / "declared-objects.json", objects)
        check("declared_objects_nonempty", bool(objects["items"]))
        for label, profile_id in [("sql", "sql-analysis/v1"), ("declared", "data-model/v1")]:
            profile = get(label, "llm-integration-profile", {"revision_id": revisions[label], "profile_id": profile_id})
            check(label + "_pinned_profile", profile["scope"]["revision_id"] == revisions[label])
            if label == "declared":
                enabled = {t["name"] for t in profile["tools"]}
                check("declared_tools_authorized", {"search_declared_data_objects", "get_declared_data_object"} <= enabled)
        customer = next(o for o in objects["items"] if o["fqcn"] == "synthetic.fixture.Customer")
        detail = get("declared", search_path + "/" + urllib.parse.quote(customer["object_id"], safe=""),
            {"revision_id": revisions["declared"]})["object"]
        fields = {f["name"]: f for f in detail["fields"]}
        check("customer_fields", set(fields) == {"id", "nickname", "profile"})
        check("inherited_field_preserved", fields["id"]["is_inherited"] and fields["id"]["inherited_depth"] == 1)
        check("field_evidence_preserved", all(f["source_ref"].get("repository_relative_path") == "Sample.java"
            and f["provenance"] for f in fields.values()))
        check("relationship_evidence_preserved", any(r["source_field"] == "profile"
            and r["target_fqcn"] == "synthetic.fixture.Profile"
            and r["resolution_status"] == "same_package" and r["source_ref"] for r in detail["relationships"]))
        dump(work / "consumer-result.json", {"revision_id": revisions["declared"], "object": detail})
        repo.rename(work / "fixture-unavailable")
        for label in revisions:
            (work / "analysis" / (label + "-output")).rename(work / (label + "-output-unavailable"))
        reread = get("sql", "sql/joins", {"revision_id": revisions["sql"], "offset": 0, "limit": 3})
        check("tcp_read_without_producer_paths", reread == first)
        report["revisions"] = revisions
        report["status"] = "PASS"
    except Exception as exc:
        report["status"] = "FAILED"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        if server is not None:
            server.terminate()
            server.wait(timeout=10)
            log.close()
        owner.read_source_manifest(source)
        report["framework_source_unchanged"] = True
        report["check_count"] = len(checks)
        dump(work / "report.json", report)
    print(json.dumps({"status": report["status"], "checks": len(checks), "evidence": str(work)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ["source", "archive", "dependencies", "pack", "work"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    run(**{k: v.resolve() for k, v in vars(args).items()})
