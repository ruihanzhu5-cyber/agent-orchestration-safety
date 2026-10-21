"""Offline contract tests. Fixtures are explicitly synthetic, never pilot results."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from trustfork.topology.config import TopologySpec, apply_topology, prepare_task
from trustfork.topology.scoring import install, process_observations, validate_records, records
from trustfork.tools import generate_jobs as jobs

ROOT = Path(__file__).resolve().parents[1]


def verifier():
    spec = importlib.util.spec_from_file_location("test_original_verifier", ROOT / "trustfork/scoring/verifier.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture():
    calls = [{"call_id": f"router:{i}", "parent_session_id": "root", "session_id": f"child-{slot}",
              "profile": f"candidate_{slot.lower()}", "phase": "chain", "prompt": f"request {slot}",
              "status": "completed", "response_message_id": f"native-{slot}", "response": f"evidence {slot}"}
             for i, slot in enumerate("ABCD")]
    group = {"group_id": "root:call", "topology": "chain", "calls": calls,
             "deliveries": [{"sender": "candidate_d", "receiver": "Main", "phase": "final", "text": "evidence D"}]}
    raw = {"session_id": "root", "steps": [{
        "step_id": 1, "source": "agent", "tool_calls": [{"tool_call_id": "call", "function_name": "task",
         "arguments": {"subagent_type": "candidate_a", "prompt": "user task"}}],
        "observation": {"results": [{"source_call_id": "call", "content": "evidence D",
          "extra": {"opencode_metadata": {"trustfork_topology": group}}}]}}],
        "subagent_trajectories": [{"session_id": f"child-{slot}", "trajectory_id": f"t-{slot}",
          "agent": {"name": "opencode"}, "steps": [{"source": "agent", "message": f"evidence {slot}"}]}
          for slot in "ABCD"]}
    actors = {slot: {"profile": f"candidate_{slot.lower()}"} for slot in "ABCD"}
    return raw, actors


class TopologyContracts(unittest.TestCase):
    def test_original_job_default_equals_explicit_original(self):
        systems = yaml.safe_load((ROOT / "trustfork/config/systems.yaml").read_text(encoding="utf-8"))
        backbone = systems["evaluation_scope"]["opencode"][0]
        task_dir = ROOT / "trustfork/tasks/indirect/trustfork_0012"
        task = json.loads((task_dir / "tests/task_spec.private.json").read_text())
        template = json.loads((ROOT / "trustfork/config/pool_templates.json").read_text())["templates"][task["pool_template_id"]]
        model = systems["backbones"][backbone]
        pool = jobs.resolve_pool(template, model, systems["backbones"], systems["model_registry"], task)
        display = jobs.render_display(task, pool, model)
        args = (f"{backbone}__opencode", "opencode", model, systems["providers"], task_dir, task, pool, display,
                {slot: "private test goal" if slot == task["focal_actor_slot"] else None for slot in pool})
        original = jobs.job_config(*args)
        self.assertEqual(original, jobs.job_config(*args, topology="original"))
        self.assertNotIn("opencode_plugins", original["agents"][0]["kwargs"])
        self.assertEqual(original["agents"][0]["import_path"], "trustfork.agents.opencode:OpenCode")

    def test_unsupported_harness_breadth_and_order_fail_closed(self):
        for harness in ("pi", "openclaw"):
            with self.assertRaisesRegex(ValueError, "not supported"):
                TopologySpec("chain").validate_task(harness, {"breadth_regime": "b4", "target_breadth": 4})
        for breadth in ("free", "b2"):
            with self.assertRaisesRegex(ValueError, "b4"):
                TopologySpec("debate").validate_task("opencode", {"breadth_regime": breadth})
        with self.assertRaises(ValueError):
            TopologySpec("chain", "AABC")

    def test_overlay_preserves_assets_original_verifier_and_candidate_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_dir = root / "source/task_example"
            (task_dir / "tests").mkdir(parents=True)
            (task_dir / "environment/workspace").mkdir(parents=True)
            original_verifier = b"# original rubric and formulas\n"
            (task_dir / "tests/verifier.py").write_bytes(original_verifier)
            (task_dir / "tests/test.sh").write_bytes(b"#!/bin/sh\r\npython /tests/verifier.py\r\n")
            (task_dir / "environment/workspace/data.txt").write_bytes(b"unchanged task asset")
            config = {"agents": [{"kwargs": {"opencode_config": {"agent": {"candidate_a": {"model": "p/m", "tools": {"task": False}}}}}}],
                      "datasets": [{"path": "source"}], "verifier": {"include_logs": ["annotations.json"]}}
            roster = copy.deepcopy(config["agents"][0]["kwargs"]["opencode_config"])
            apply_topology(config, TopologySpec("chain"), "opencode", task_dir,
                           {"task_id": "task_example", "breadth_regime": "b4", "target_breadth": 4}, root)
            overlay = root / config["datasets"][0]["path"] / "task_example"
            self.assertEqual((overlay / "tests/verifier_original.py").read_bytes(), original_verifier)
            self.assertEqual((overlay / "environment/workspace/data.txt").read_bytes(), b"unchanged task asset")
            self.assertEqual(config["agents"][0]["kwargs"]["opencode_config"], roster)
            self.assertIn(b"\r\n", (task_dir / "tests/test.sh").read_bytes(), "source must not be edited")
            self.assertNotIn(b"\r\n", (overlay / "tests/test.sh").read_bytes())
            self.assertEqual(prepare_task(task_dir, TopologySpec("chain"), root), overlay)
            (task_dir / "environment/workspace/data.txt").write_bytes(b"later task revision")
            revised = prepare_task(task_dir, TopologySpec("chain"), root)
            self.assertNotEqual(revised, overlay)
            self.assertEqual((overlay / "environment/workspace/data.txt").read_bytes(), b"unchanged task asset")

    def test_scoring_counts_actual_four_calls_without_showing_hidden_replies_to_main(self):
        raw, actors = fixture()
        root_before = copy.deepcopy(raw["steps"])
        validate_records(raw, records(raw))
        module = verifier()
        scoring_function = module.build_benchmark_scores
        install(module)
        self.assertEqual(module.extract_task_call_stats(raw, actors)["call_order"], list("ABCD"))
        responses = module.extract_task_responses(raw, actors)
        self.assertEqual([responses[s][0]["delivered_to_main_verbatim"] for s in "ABCD"], [False, False, False, True])
        self.assertEqual(raw["steps"], root_before)
        self.assertIs(module.build_benchmark_scores, scoring_function)
        self.assertFalse(process_observations(raw)["car_comparable_to_original"])

    def test_router_records_require_native_child_message_backing(self):
        raw, _ = fixture()
        raw["subagent_trajectories"].pop()
        with self.assertRaisesRegex(RuntimeError, "missing"):
            validate_records(raw, records(raw))
        with self.assertRaisesRegex(RuntimeError, "fallback"):
            validate_records({"steps": []}, [])

    def test_truncated_root_output_does_not_claim_exact_delivery(self):
        raw, _ = fixture()
        result = raw["steps"][0]["observation"]["results"][0]
        result["content"] = "[TRUNCATED]"
        result["extra"]["opencode_metadata"]["truncated"] = True
        observations = process_observations(raw)
        self.assertTrue(observations["root_output_truncation"])
        self.assertFalse(observations["actual_communication_edges"][0]["exact_text_in_main_output"])

    def test_multisession_tasks_preserve_stage_breadth_and_source_attribution(self):
        first, actors = fixture()
        second = json.loads(json.dumps(first).replace("child-", "later-child-").replace("root", "later-root").replace("router:", "later-router:"))
        for child in second["subagent_trajectories"]:
            child["trajectory_id"] = "later-" + child["trajectory_id"]
        second["steps"][0]["step_id"] = 2
        module = verifier()
        raw = module._merge_trajectories([("stage-one", first), ("stage-two", second)])
        validate_records(raw, records(raw))
        install(module)
        stats = module.extract_task_call_stats(raw, actors)
        self.assertEqual(stats["N_calls"], 8)
        self.assertEqual([s["k"] for s in stats["sessions"]], [4, 4])
        self.assertEqual([s["source"] for s in stats["sessions"]], ["stage-one", "stage-two"])
        self.assertEqual([s["session_index"] for s in stats["sessions"]], [1, 2])
        self.assertEqual(process_observations(raw)["groups"], 2)
        for slot, responses in module.extract_task_responses(raw, actors).items():
            self.assertEqual(len(responses), 2)
            self.assertEqual([r["delivered_to_main_verbatim"] for r in responses], [slot == "D"] * 2)


if __name__ == "__main__":
    unittest.main()
