"""Build an exact Git-archive wheel and qualify its offline package without repo fallbacks."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


ISOLATED_PROOF = r'''
import json
import sys
from pathlib import Path
install, execution = (Path(arg).resolve() for arg in sys.argv[1:])
sys.path.insert(0, str(install))
import board_clank
assert Path(board_clank.__file__).resolve().is_relative_to(install)
assert not (execution / 'fixtures').exists()
from board_clank.collectors import get_adapter
from board_clank.collectors import banana_pi, odroid, orange_pi, pine64, radxa, raspberry_pi, friendlyelec, khadas
from board_clank.collectors import radxa_documentation as docs
from board_clank.pipeline import Pipeline
from board_clank.sources import sync_sources_to_store, product_sources, supporting_sources
from board_clank.store import Store
from board_clank.manifest import load_manifest, validate_manifest
from board_clank.backup import create_backup, restore_backup, durable_state_snapshot, verify_backup
from board_clank.observer import full_snapshot
from board_clank.taxonomy import PHASE1_VENDORS, PHASE2_ADMITTED
modules = (raspberry_pi, orange_pi, radxa, banana_pi, odroid, pine64, friendlyelec, khadas)
for module in modules:
    assert module.CORPUS_DIR.resolve().is_relative_to(install), module.CORPUS_DIR
    assert (module.CORPUS_DIR / 'manifest.json').is_file()
    manifest = json.loads((module.CORPUS_DIR / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest
assert docs._FIXTURE.resolve().is_relative_to(install)
provenance = json.loads(docs._FIXTURE.with_name('manifest.json').read_text(encoding='utf-8'))
assert provenance['source_url'] == docs.DOCS_URL and provenance['license'] == 'CC BY 4.0'
assert len(product_sources()) == 8 and len(supporting_sources()) == 1
assert validate_manifest(load_manifest())['valid']
db = execution / 'wheel-eight.db'
vendors = (*PHASE1_VENDORS, *PHASE2_ADMITTED)
accepted = {}
with Store(db) as store:
    sync_sources_to_store(store)
    for vendor in vendors:
        adapter = get_adapter(vendor + '-product')
        request = adapter.collect(vendor + '-wheel', '2026-10-03T00:00:00Z')
        assert request.ok and request.observations, vendor
        result = Pipeline(store).accept_run(request)
        assert result.status == 'accepted' and result.baseline, (vendor, result)
        accepted[vendor] = len(request.observations)
        assert Pipeline(store).accept_run(request).replayed
        request.run_id += '-repeat'
        repeated = Pipeline(store).accept_run(request)
        assert repeated.events == [] and repeated.notifications == 0
    assert {row[0] for row in store.all('SELECT DISTINCT vendor_key FROM boards')} == set(vendors)
    before = durable_state_snapshot(db)
    result = docs.accept_documentation(store, docs._FIXTURE.read_text(encoding='utf-8'), run_id='wheel-docs', observed_at='2026-10-03T00:00:00Z')
    assert not result['unresolved'] and len(result['mappings']) == 7
    after = durable_state_snapshot(db)
    for table in ('boards', 'board_revisions', 'board_variants', 'novelty_evidence', 'notifications'):
        assert before[table] == after[table]
    assert store.one('PRAGMA integrity_check')[0] == 'ok'
backup = create_backup(db, execution / 'backup', name='wheel-qualified')
verified = verify_backup(backup.database_path, backup.metadata_path)
assert verified['metadata_coverage'] == 'COMPLETE'
assert 'observation_occurrences' in verified['verified_tables']
restored_db = execution / 'restored.db'
restore_backup(backup.database_path, backup.metadata_path, restored_db, activate=True)
assert durable_state_snapshot(db) == durable_state_snapshot(restored_db)
assert full_snapshot(restored_db)['status']['schema_version'] == 3
assert docs.main(['--qualification-root', str(execution / 'manual-docs'), '--run-id', 'offline-wheel']) == 0
manual = json.loads((execution / 'manual-docs/offline-wheel/result.json').read_text())
assert not manual['unresolved'] and len(manual['mappings']) == 7
print(json.dumps({'wheel_only_import': True, 'repository_fallback': False, 'accepted_product_vendors': accepted, 'documentation_mappings': len(result['mappings']), 'packaged_provenance': provenance['source_url'], 'backup_occurrence_coverage': verified['metadata_coverage']}, sort_keys=True))
'''


def _run(command: list[str], *, cwd: Path, log: Path) -> None:
    with log.open("w", encoding="utf-8") as output, open(os.devnull, "rb") as stdin:
        result = subprocess.run(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                                stdin=stdin, timeout=600)
    if result.returncode:
        raise RuntimeError(f"process exit {result.returncode}: {command}\n{log.read_text(encoding='utf-8', errors='replace')}")


def qualify(repo: Path, output: Path, *, ref: str = "HEAD") -> dict:
    repo, output = repo.resolve(), output.resolve()
    if output.exists():
        raise ValueError("qualification output must be fresh; never overwrite evidence")
    output.mkdir(parents=True)
    git = ["git", "-c", "safe.directory=" + str(repo), "-C", str(repo)]
    _run([*git, "rev-parse", ref], cwd=output, log=output / "head.log")
    sha = (output / "head.log").read_text(encoding="utf-8").strip()
    archive = output / "source.tar"
    _run([*git, "archive", "--format=tar", "--output=" + str(archive), sha],
         cwd=output, log=output / "archive.log")
    source = output / "archive-source"
    source.mkdir()
    with tarfile.open(archive) as contents:
        contents.extractall(source, filter="data")
    wheels = output / "wheels"
    _run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
          "--wheel-dir", str(wheels), str(source)], cwd=output, log=output / "wheel-build.log")
    wheel, = wheels.glob("*.whl")
    install = output / "wheel-install"
    with zipfile.ZipFile(wheel) as contents:
        contents.extractall(install)
    execution = output / "execution"
    execution.mkdir()
    _run([sys.executable, "-I", "-c", ISOLATED_PROOF, str(install), str(execution)],
         cwd=execution, log=output / "wheel-proof.log")
    proof = json.loads((output / "wheel-proof.log").read_text(encoding="utf-8").splitlines()[-1])
    receipt = {"archive_sha": sha, "wheel": str(wheel), "build_process_exit": 0,
               "proof_process_exit": 0, **proof}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args()
    print(json.dumps(qualify(args.repo, args.out, ref=args.ref), indent=2, sort_keys=True))
