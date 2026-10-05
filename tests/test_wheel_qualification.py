"""Exact-archive distribution test: repo fixtures and editable imports cannot mask omissions."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def test_archive_wheel_supports_all_nine_offline_adapters_and_documentation(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("wheel_qualification", repo / "tools/qualify_wheel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    receipt = module.qualify(repo, tmp_path / "isolated-wheel")
    assert receipt["build_process_exit"] == receipt["proof_process_exit"] == 0
    assert len(receipt["accepted_product_vendors"]) == 9
    assert receipt["documentation_mappings"] == 7
    assert receipt["repository_fallback"] is False
    assert receipt["backup_occurrence_coverage"] == "COMPLETE"
