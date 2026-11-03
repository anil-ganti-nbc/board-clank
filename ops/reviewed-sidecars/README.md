# Historical reviewed Board operational sidecars

These are exact preserved bytes, **not a repair or deployment instruction**.

| File | SHA-256 | Disposition |
|---|---|---|
| `seven_delivery.py` | `fafe732c0e0a66bae50d84d0f2c0cc815274248bcbfa4c6fb0c989fd9f29ee19` | Independently reviewed seven-source native-drain binding; activated historically, now stopped |
| `test_seven_delivery.py` | `351a6050a3631aeaa7fbcf82dbcf9e6612a78073eef8343a2ebbd7961bf857f5` | Original synthetic component/launcher tests, including network and native-transport denial |
| `hourly_controller.py` | `4e6d95a3a56f1a66895786ebc8745aa9c74f459a2303224c84ae56887d4dd035` | Historical controller with the diagnosed fatal-contention/empty-stdout failure; NOT recovery-qualified |

The adapter pins the installed native delivery module SHA-256
`ea706ad3974d5a385125c7fd9d4a246a51452ec599c473ee558d4af3d6954bd2`.
It binds private function globals, not module-global source overrides, and does
not grant collection/delivery authority. Only the matched admitted Linux image
and separately authenticated finite policy/secret/layout were qualified.
No enabled policy, secret, approval, database or catalogue is included here.

The original test file deliberately retains its historical workstation checkout
binding. It is an archival witness, **not a portable automatic CI target**. Its
webhook text is explicitly synthetic and its transport is denied/mocked; do not
replace it with a real credential. Current hosted native CI's 38 selected causal
cases do not include these archival tests and do not qualify writer coexistence.

Known missed integration: sender skip-on-busy coverage did not exercise the
collector starting while the sender holds the canonical lock. The controller
parses empty stdout before inspecting the native exit code, masking the typed
refusal. The runtime lock must not be bypassed; neither historical script should
be restarted to recover the retained inflight slot. See the dated incident report
in `docs/operations/2026-11-03-board-incident.md` for bounded next requirements.

Git attributes preserve these Python files without newline conversion. Compare
raw byte hashes before use. Publication/merge does not change installed runtime
bytes, repair the incident or authorise a new schedule.
