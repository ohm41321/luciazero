#!/usr/bin/env python3
"""Verify raw campaign integrity and generate human-facing evidence blocks."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Optional

from result_schema import validate_result_row


ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results"
REGISTRY = RESULTS / "campaigns.json"
BEGIN = "<!-- BEGIN GENERATED: benchmark-evidence -->"
END = "<!-- END GENERATED: benchmark-evidence -->"


def load_registry() -> list[dict]:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or not isinstance(data.get("campaigns"), list)):
        raise SystemExit("FAIL: eval/results/campaigns.json has an unsupported schema")
    campaigns = data["campaigns"]
    for index, campaign in enumerate(campaigns):
        source = f"eval/results/campaigns.json campaign {index + 1}"
        if not isinstance(campaign, dict):
            raise SystemExit(f"FAIL: {source} is not an object")
        required_strings = (
            "id", "date", "provider", "display_model", "observed_model",
            "status", "file", "sha256", "model_provenance",
        )
        bad = [field for field in required_strings
               if not isinstance(campaign.get(field), str) or not campaign[field]]
        if bad:
            raise SystemExit(f"FAIL: {source} needs non-empty {', '.join(bad)}")
        if campaign["provider"] not in {"claude", "codex"}:
            raise SystemExit(f"FAIL: {source} has unsupported provider")
        if campaign["status"] not in {"published", "preliminary", "exploratory"}:
            raise SystemExit(f"FAIL: {source} has unsupported status")
        if not campaign["file"].endswith(".jsonl") or Path(campaign["file"]).name != campaign["file"]:
            raise SystemExit(f"FAIL: {source} has unsafe result filename")
        if len(campaign["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in campaign["sha256"]):
            raise SystemExit(f"FAIL: {source} has malformed SHA-256")
        tasks = campaign.get("tasks")
        lessons = campaign.get("lessons_tasks")
        if (not isinstance(tasks, list) or not tasks
                or any(not isinstance(task, str) or not task for task in tasks)
                or len(tasks) != len(set(tasks))):
            raise SystemExit(f"FAIL: {source} has malformed or duplicate tasks")
        if (not isinstance(lessons, list)
                or any(not isinstance(task, str) or task not in tasks for task in lessons)
                or len(lessons) != len(set(lessons))):
            raise SystemExit(f"FAIL: {source} has malformed lessons_tasks")
        runs = campaign.get("expected_runs_per_cell")
        model_rows = campaign.get("expected_model_rows")
        result_schema = campaign.get("expected_result_schema")
        if isinstance(result_schema, bool) or result_schema not in {1, 2}:
            raise SystemExit(f"FAIL: {source} has invalid expected_result_schema")
        if isinstance(runs, bool) or not isinstance(runs, int) or runs < 1:
            raise SystemExit(f"FAIL: {source} has invalid expected_runs_per_cell")
        if isinstance(model_rows, bool) or not isinstance(model_rows, int) or model_rows < 0:
            raise SystemExit(f"FAIL: {source} has invalid expected_model_rows")
        expected_invalid = campaign.get("expected_invalid")
        if not isinstance(expected_invalid, dict):
            raise SystemExit(f"FAIL: {source} has malformed expected_invalid")
        valid_cells = {f"{task}/{arm}" for task in tasks for arm in ("doctrine", "bare")}
        valid_cells.update(f"{task}/lessons" for task in lessons)
        for cell, count in expected_invalid.items():
            if (cell not in valid_cells or isinstance(count, bool)
                    or not isinstance(count, int) or count < 1 or count > runs):
                raise SystemExit(f"FAIL: {source} has invalid expected_invalid entry {cell!r}")
        effort = campaign.get("reasoning_effort")
        if effort is not None and (not isinstance(effort, str) or not effort):
            raise SystemExit(f"FAIL: {source} has malformed reasoning_effort")
        if "featured" in campaign and not isinstance(campaign["featured"], bool):
            raise SystemExit(f"FAIL: {source} has non-boolean featured")
        expected_hashes = campaign.get("expected_task_sha256")
        if result_schema == 2:
            if not isinstance(expected_hashes, dict) or set(expected_hashes) != set(tasks):
                raise SystemExit(f"FAIL: {source} must pin hashes for every schema-v2 task")
            for task, hashes in expected_hashes.items():
                if (not isinstance(hashes, dict)
                        or set(hashes) != {"task", "prompt"}
                        or any(not isinstance(value, str) or len(value) != 64
                               or any(c not in "0123456789abcdef" for c in value)
                               for value in hashes.values())):
                    raise SystemExit(f"FAIL: {source} has malformed hashes for {task}")
        elif expected_hashes is not None:
            raise SystemExit(f"FAIL: {source} cannot pin v2 hashes for schema v1")
        limitations = campaign.get("limitations")
        if (not isinstance(limitations, list)
                or any(not isinstance(item, str) or not item for item in limitations)):
            raise SystemExit(f"FAIL: {source} has malformed limitations")
    return campaigns


def load_rows(campaign: dict) -> list[dict]:
    path = RESULTS / campaign["file"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != campaign["sha256"]:
        raise SystemExit(
            f"FAIL: {path.relative_to(ROOT)} digest {digest} != registry {campaign['sha256']}"
        )
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            raw = json.loads(line)
            row = validate_result_row(
                raw, source=f"{path.relative_to(ROOT)}:{line_number}"
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise SystemExit(f"FAIL: {path}:{line_number}: {exc}") from exc
        if row.get("task") not in campaign["tasks"]:
            raise SystemExit(f"FAIL: {path}:{line_number}: unregistered task {row.get('task')!r}")
        if row["provider"] != campaign["provider"]:
            raise SystemExit(f"FAIL: {path}:{line_number}: provider does not match registry")
        if row.get("model") not in (None, campaign["observed_model"]):
            raise SystemExit(f"FAIL: {path}:{line_number}: model does not match registry")
        if campaign["reasoning_effort"] is None:
            effort_matches = row.get("reasoning_effort") is None
        else:
            effort_matches = row.get("reasoning_effort") == campaign["reasoning_effort"]
        if not effort_matches:
            raise SystemExit(f"FAIL: {path}:{line_number}: reasoning effort does not match registry")
        if row["offline"]:
            raise SystemExit(f"FAIL: {path}:{line_number}: synthetic row registered as evidence")
        rows.append(row)
    if not rows:
        raise SystemExit(f"FAIL: {path}: empty campaign")

    validate_campaign_rows(campaign, rows, path)
    return rows


def validate_campaign_rows(campaign: dict, rows: list[dict], path: Path) -> None:
    """Enforce registry semantics after each row passes the shared schema."""
    schemas = {row["result_schema"] for row in rows}
    if schemas != {campaign["expected_result_schema"]}:
        raise SystemExit(
            f"FAIL: {path}: result schemas {sorted(schemas)} do not match registry "
            f"{campaign['expected_result_schema']}"
        )
    expected_cells = {
        (task, arm)
        for task in campaign["tasks"]
        for arm in ("doctrine", "bare")
    }
    expected_cells.update((task, "lessons") for task in campaign["lessons_tasks"])
    actual_cells = {(row["task"], row["arm"]) for row in rows}
    if actual_cells != expected_cells:
        raise SystemExit(
            f"FAIL: {path}: task/arm cells differ from registry: "
            f"expected={sorted(expected_cells)}, actual={sorted(actual_cells)}"
        )
    expected_runs = campaign["expected_runs_per_cell"]
    for task, arm in expected_cells:
        cell = [row for row in rows if row["task"] == task and row["arm"] == arm]
        if len(cell) != expected_runs:
            raise SystemExit(
                f"FAIL: {path}: {task}/{arm} has {len(cell)} rows; expected {expected_runs}"
            )
        invalid = sum(row["invalid"] for row in cell)
        expected_invalid = campaign["expected_invalid"].get(f"{task}/{arm}", 0)
        if invalid != expected_invalid:
            raise SystemExit(
                f"FAIL: {path}: {task}/{arm} has {invalid} invalid rows; "
                f"expected {expected_invalid}"
            )
    model_rows = sum(row.get("model") == campaign["observed_model"] for row in rows)
    if model_rows != campaign["expected_model_rows"]:
        raise SystemExit(
            f"FAIL: {path}: {model_rows} rows encode model identity; "
            f"expected {campaign['expected_model_rows']}"
        )
    if campaign["expected_result_schema"] == 2:
        if any(row["repository_dirty"] for row in rows):
            raise SystemExit(f"FAIL: {path}: dirty-checkout rows cannot be published")
        for field in (
            "campaign_id", "seed", "repository_commit", "runner_profile",
            "requested_model", "reasoning_effort", "cli_version", "system",
            "architecture", "campaign_started_at",
        ):
            values = {row.get(field) for row in rows}
            if len(values) != 1:
                raise SystemExit(f"FAIL: {path}: mixed schema-v2 {field} values")
        if rows[0]["campaign_id"] != campaign["id"]:
            raise SystemExit(f"FAIL: {path}: campaign_id does not match registry")
        invocation_ids = [row["invocation_id"] for row in rows]
        if len(invocation_ids) != len(set(invocation_ids)):
            raise SystemExit(f"FAIL: {path}: duplicate schema-v2 invocation_id")
        expected_identities = {
            (task, arm, run)
            for task, arm in expected_cells
            for run in range(1, expected_runs + 1)
        }
        actual_identities = {(row["task"], row["arm"], row["run"]) for row in rows}
        if actual_identities != expected_identities:
            raise SystemExit(
                f"FAIL: {path}: schema-v2 task/arm/run identities differ from registry"
            )
        for task in campaign["tasks"]:
            task_rows = [row for row in rows if row["task"] == task]
            for field, registry_field in (
                ("task_sha256", "task"), ("prompt_sha256", "prompt")
            ):
                values = {row[field] for row in task_rows}
                expected = campaign["expected_task_sha256"][task][registry_field]
                if values != {expected}:
                    raise SystemExit(
                        f"FAIL: {path}: {task} {field} does not match registry"
                    )
        for pair_id in {row["pair_id"] for row in rows}:
            pair = [row for row in rows if row["pair_id"] == pair_id]
            orders = {tuple(row["arm_order"]) for row in pair}
            if len(orders) != 1:
                raise SystemExit(f"FAIL: {path}: inconsistent arm_order in {pair_id}")
            expected_arms = {"doctrine", "bare"}
            if pair[0]["task"] in campaign["lessons_tasks"]:
                expected_arms.add("lessons")
            task = pair[0]["task"]
            run = pair[0]["run"]
            seed = pair[0]["seed"]
            expected_order = tuple(sorted(
                expected_arms,
                key=lambda arm: hashlib.sha256(
                    f"{seed}\0{task}\0{run}\0{arm}".encode()
                ).digest(),
            ))
            if next(iter(orders)) != expected_order:
                raise SystemExit(
                    f"FAIL: {path}: arm_order in {pair_id} does not match seed"
                )
    for task in campaign["tasks"]:
        criterion_sets = {
            frozenset(row["criteria"])
            for row in rows
            if row["task"] == task and not row["invalid"]
        }
        if len(criterion_sets) != 1:
            raise SystemExit(f"FAIL: {path}: {task} has inconsistent criterion sets")


def passed(row: dict) -> bool:
    criteria = row["criteria"]
    return bool(criteria) and all(criteria.values())


def arm_rows(rows: list[dict], arm: str, task: Optional[str] = None) -> list[dict]:
    return [
        row
        for row in rows
        if row.get("arm") == arm
        and not row.get("invalid", False)
        and (task is None or row.get("task") == task)
    ]


def rate_cell(rows: list[dict]) -> str:
    wins = sum(passed(row) for row in rows)
    total = len(rows)
    pct = int(100 * wins / total + 0.5) if total else 0
    return f"{wins}/{total} ({pct}%)"


def percent(rows: list[dict]) -> int:
    return int(100 * sum(passed(row) for row in rows) / len(rows) + 0.5)


def valid_range(rows: list[dict], tasks: list[str]) -> str:
    counts = [len(arm_rows(rows, arm, task))
              for task in tasks for arm in ("doctrine", "bare")]
    return str(counts[0]) if len(set(counts)) == 1 else f"{min(counts)}–{max(counts)}"


def claude_campaigns(campaigns: list[dict]) -> list[dict]:
    return [campaign for campaign in campaigns if campaign["provider"] == "claude"]


def featured_codex(campaigns: list[dict]) -> dict:
    featured = [campaign for campaign in campaigns
                if campaign["provider"] == "codex" and campaign.get("featured")]
    if len(featured) != 1:
        raise SystemExit("FAIL: campaign registry needs exactly one featured Codex campaign")
    return featured[0]


def english_readme(campaigns: list[dict], data: dict[str, list[dict]]) -> str:
    claude = claude_campaigns(campaigns)
    lines = [
        "### Claude results",
        "",
        "Snapshot: 2026-08-11. All-criteria pass rate generated from checked-in raw rows:",
        "",
        "| Claude model | Luciazero | Bare | Difference |",
        "|---|---:|---:|---:|",
    ]
    for campaign in claude:
        rows = data[campaign["id"]]
        doctrine = arm_rows(rows, "doctrine")
        bare = arm_rows(rows, "bare")
        n = valid_range(rows, campaign["tasks"])
        suffix = "*" if campaign["status"] == "preliminary" else ""
        prefix = "Claude "
        label = campaign["display_model"]
        if label.startswith(prefix):
            label = label[len(prefix):]
        valid_rows = sum(not row["invalid"] for row in rows)
        if campaign["expected_model_rows"] < valid_rows:
            label += "†"
        lines.append(
            f"| {label}, {n} valid/task{suffix} | {rate_cell(doctrine)} | "
            f"{rate_cell(bare)} | {percent(doctrine) - percent(bare):+d}pp |"
        )
    lines += [
        "",
        "The `Luciazero` arm installs the classic pack without hooks; it is not a clean",
        "doctrine-only ablation. *Sonnet is preliminary because eight invalid rows leave",
        "several arms at four valid runs. The previously stated `+37pp` top-up is retired",
        "because its replacement raw rows could not be recovered.",
        "",
        "†Model provenance is incomplete for Haiku: only 70/140 rows encode model",
        "identity. The other 70 are attributed at campaign-file/report level and",
        "cannot be independently verified per row.",
        "",
        "### GPT/Codex pilot — exploratory",
        "",
        "Snapshot: 2026-08-12.",
        "",
        "| Model | Valid invocations | Paired tasks | Luciazero | Bare | Observed difference |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    terra = featured_codex(campaigns)
    rows = data[terra["id"]]
    paired_tasks = [
        task
        for task in terra["tasks"]
        if arm_rows(rows, "doctrine", task) and arm_rows(rows, "bare", task)
    ]
    doctrine = [row for task in paired_tasks for row in arm_rows(rows, "doctrine", task)]
    bare = [row for task in paired_tasks for row in arm_rows(rows, "bare", task)]
    doctrine_criteria = sum(sum(bool(value) for value in row["criteria"].values()) for row in doctrine)
    doctrine_criteria_total = sum(len(row["criteria"]) for row in doctrine)
    bare_criteria = sum(sum(bool(value) for value in row["criteria"].values()) for row in bare)
    bare_criteria_total = sum(len(row["criteria"]) for row in bare)
    valid = sum(not row.get("invalid", False) for row in rows)
    lines += [
        f"| {terra['display_model']} | {valid}/{len(rows)}* | {len(paired_tasks)} | "
        f"{sum(passed(row) for row in doctrine)}/{len(doctrine)} runs, {doctrine_criteria}/{doctrine_criteria_total} criteria | "
        f"{sum(passed(row) for row in bare)}/{len(bare)} runs, {bare_criteria}/{bare_criteria_total} criteria | "
        f"{percent(doctrine) - percent(bare):+d}pp† |",
        "",
        "*One Luciazero run was invalidated by model capacity. †This is a",
        "**ceiling-effect warning, not evidence of uplift or no effect**: the pilot has",
        "only one run per arm per task. See the [full benchmark](docs/benchmark.md),",
        "[campaign registry](eval/results/campaigns.json), and",
        "[raw pilot rows](eval/results/gpt-5.6-terra-medium-pilot-2026-08-12.jsonl).",
    ]
    return "\n".join(lines)


def thai_readme(campaigns: list[dict], data: dict[str, list[dict]]) -> str:
    english = english_readme(campaigns, data)
    table_start = english.index("| Claude model")
    table_end = english.index("\n\nThe `Luciazero`", table_start)
    claude_table = (english[table_start:table_end]
                    .replace("Claude model", "โมเดล Claude")
                    .replace("Difference", "ผลต่าง"))
    gpt_start = english.index("| Model | Valid invocations")
    gpt_table_end = english.index("\n\n*One Luciazero", gpt_start)
    gpt_table = (english[gpt_start:gpt_table_end]
                 .replace("Model", "โมเดล")
                 .replace("Valid invocations", "invocation ที่ valid")
                 .replace("Paired tasks", "task ที่จับคู่ได้")
                 .replace("Observed difference", "ผลต่างที่พบ"))
    return "\n".join(
        [
            "### ผล Claude",
            "",
            "Snapshot: 2026-08-11 อัตราผ่านทุกเกณฑ์ สร้างจาก raw rows ที่ commit ไว้:",
            "",
            claude_table,
            "",
            "Arm `Luciazero` ติดตั้ง classic pack แบบไม่มี hook จึงไม่ใช่การแยกผลของ",
            "doctrine เพียงอย่างเดียว *Sonnet ยังเป็นผล preliminary เพราะ invalid 8 rows",
            "ทำให้หลาย arm มี valid run เพียง 4 รอบ ส่วนผล top-up `+37pp` เดิมถูกยกเลิก",
            "เพราะหา replacement raw rows ที่ใช้ตรวจสอบซ้ำไม่ได้",
            "",
            "†Provenance ของโมเดล Haiku ยังไม่สมบูรณ์: มีเพียง 70/140 rows ที่บันทึก",
            "model identity ส่วนอีก 70 rows ระบุได้แค่ระดับไฟล์/รายงานของ campaign",
            "จึงตรวจสอบโมเดลซ้ำแบบราย row ไม่ได้",
            "",
            "### GPT/Codex pilot — ผลสำรวจเบื้องต้น",
            "",
            "Snapshot: 2026-08-12.",
            "",
            gpt_table,
            "",
            "*Luciazero 1 run ถูกตัดเป็น invalid เพราะ model capacity เต็ม †นี่คือ",
            "**สัญญาณว่า benchmark อาจง่ายเกินไป ไม่ใช่หลักฐานว่ามีหรือไม่มี uplift** เพราะ",
            "pilot มีเพียง 1 run ต่อ arm ต่อ task ดู [ผลเต็ม](docs/benchmark.md),",
            "[campaign registry](eval/results/campaigns.json) และ",
            "[raw pilot](eval/results/gpt-5.6-terra-medium-pilot-2026-08-12.jsonl)",
        ]
    )


def benchmark_doc(campaigns: list[dict], data: dict[str, list[dict]]) -> str:
    claude = claude_campaigns(campaigns)
    lines = [
        "## Claude campaigns",
        "",
        "Snapshot: 2026-08-11. Tables below are generated from digest-verified raw JSONL.",
        "",
        "| Model | Luciazero | Bare | Difference | Valid runs per task | Status |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for campaign in claude:
        rows = data[campaign["id"]]
        doctrine = arm_rows(rows, "doctrine")
        bare = arm_rows(rows, "bare")
        lines.append(
            f"| {campaign['display_model']} | {rate_cell(doctrine)} | {rate_cell(bare)} | "
            f"{percent(doctrine) - percent(bare):+d}pp | "
            f"{valid_range(rows, campaign['tasks'])} | {campaign['status']} |"
        )
    lines += [
        "",
        "> **Canonical Sonnet result:** the checked-in campaign contains eight invalid",
        "> rows and leaves several arms at four valid runs. Commit `b24f6a2` described",
        "> replacement runs yielding +37pp, but those raw rows could not be recovered.",
        "> The auditable preliminary campaign below is canonical; do not quote +37pp.",
        "",
        "> **Haiku model-provenance limitation:** only 70/140 rows encode model",
        "> identity. Attribution of the other 70 comes from the original campaign",
        "> file/report and cannot be independently verified per row.",
    ]
    for campaign in reversed(claude):
        rows = data[campaign["id"]]
        lines += ["", f"### {campaign['display_model']}", "", "| Task | Luciazero | Bare | Difference | Lessons arm |", "|---|---:|---:|---:|---:|"]
        for task in campaign["tasks"]:
            doctrine = arm_rows(rows, "doctrine", task)
            bare = arm_rows(rows, "bare", task)
            lessons = arm_rows(rows, "lessons", task)
            delta = f"{percent(doctrine) - percent(bare):+d}pp" if doctrine and bare else "n/a"
            lines.append(
                f"| {task} | {sum(passed(row) for row in doctrine)}/{len(doctrine)} | "
                f"{sum(passed(row) for row in bare)}/{len(bare)} | {delta} | "
                f"{sum(passed(row) for row in lessons)}/{len(lessons)}" if lessons else
                f"| {task} | {sum(passed(row) for row in doctrine)}/{len(doctrine)} | "
                f"{sum(passed(row) for row in bare)}/{len(bare)} | {delta} | — |"
            )
            if lessons:
                lines[-1] += " |"
        lines += ["", f"Raw: [`{campaign['file']}`](../eval/results/{campaign['file']}) · SHA-256 `{campaign['sha256']}`"]
    terra = featured_codex(campaigns)
    rows = data[terra["id"]]
    lines += [
        "",
        "These samples are small. Compare rates, never a single run, and do not treat a",
        "provider difference as a Luciazero effect.",
        "",
        "## GPT/Codex pilot — exploratory only",
        "",
        "Snapshot: 2026-08-12. Codex CLI 0.147.0, `gpt-5.6-terra`, medium reasoning;",
        f"{sum(not row.get('invalid', False) for row in rows)}/{len(rows)} valid invocations.",
        "",
        "| Task | Luciazero | Bare |",
        "|---|---:|---:|",
    ]
    for task in terra["tasks"]:
        doctrine = arm_rows(rows, "doctrine", task)
        bare = arm_rows(rows, "bare", task)
        dcell = f"{sum(passed(row) for row in doctrine)}/{len(doctrine)}" if doctrine else "invalid: capacity"
        bcell = f"{sum(passed(row) for row in bare)}/{len(bare)}" if bare else "invalid"
        lines.append(f"| {task} | {dcell} | {bcell} |")
    lines += [
        "",
        "Five tasks have a valid pair. Both arms passed 5/5 runs and 28/28 individual",
        "criteria, an observed 0pp delta. This is a ceiling-effect warning, not evidence",
        "that Luciazero has zero effect. With n=1, one sample can move a task by 100pp.",
        "",
        f"Raw: [`{terra['file']}`](../eval/results/{terra['file']}) · SHA-256 `{terra['sha256']}`",
    ]
    return "\n".join(lines)


def replace_block(path: Path, generated: str, write: bool) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise SystemExit(f"FAIL: {path.relative_to(ROOT)} needs exactly one generated evidence block")
    start = text.index(BEGIN) + len(BEGIN)
    finish = text.index(END, start)
    expected = f"\n\n{generated.rstrip()}\n\n"
    actual = text[start:finish]
    if actual == expected:
        return
    if not write:
        raise SystemExit(
            f"FAIL: {path.relative_to(ROOT)} evidence drifted; run python3 eval/evidence.py --write"
        )
    path.write_text(text[:start] + expected + text[finish:], encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()

    campaigns = load_registry()
    ids = [campaign["id"] for campaign in campaigns]
    files = [campaign["file"] for campaign in campaigns]
    if len(ids) != len(set(ids)) or len(files) != len(set(files)):
        raise SystemExit("FAIL: campaign IDs and files must be unique")
    registered = set(files)
    present = {path.name for path in RESULTS.glob("*.jsonl")}
    if registered != present:
        raise SystemExit(
            f"FAIL: campaign registry/file drift: registered={sorted(registered)}, "
            f"present={sorted(present)}"
        )
    data = {campaign["id"]: load_rows(campaign) for campaign in campaigns}

    replace_block(ROOT / "README.md", english_readme(campaigns, data), args.write)
    replace_block(ROOT / "README.th.md", thai_readme(campaigns, data), args.write)
    replace_block(ROOT / "docs" / "benchmark.md", benchmark_doc(campaigns, data), args.write)
    print("ok  benchmark evidence digests + generated docs")


if __name__ == "__main__":
    main()
