"""Source-structure processor roles, not a silicon-name blacklist."""
from board_clank.collectors.orange_pi import parse_product_html

URL = 'http://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/details/Orange-Pi-Role.html'


def parse(value, label='Processor'):
    return parse_product_html(
        f'<h3>Orange Pi Role</h3><table><tr><td>{label}</td><td>{value}</td></tr></table>',
        page_url=URL, observed_at='2026-10-30T06:18:40Z',
    )


def test_mixed_processor_cell_keeps_primary_and_separates_labelled_units():
    drafts, info = parse('T527, 8-core ARM CortexTM-A55@1.8GHz<br/>'
                         'HIFI4 Audio DSP@600MHz<br/>RISC-V@200MHz<br/>'
                         'GPU:G57 MC1<br/>VPU:H.265<br/>NPU:2TOPS')
    assert info['status'] == 'resolved'
    assert {d.soc_marketing_name for d in drafts} == {'T527'}
    assert all(not d.identity_conflict for d in drafts)


def test_role_not_token_determines_companion_exclusion():
    drafts, _ = parse('NewVendor Z991<br>DSP: Q332<br>GPU: W123 Y456')
    assert {d.soc_marketing_name for d in drafts} == {'Z991'}
    # Those same identifiers in genuinely primary clauses remain candidates.
    drafts, info = parse('Q332<br>W123')
    assert info['status'] == 'identity-conflict'
    assert drafts[0].raw_fields['soc_candidates'] == ['Q332', 'W123']


def test_core_names_do_not_invent_a_chip_identity():
    drafts, info = parse('4-core 64-bit processor + AI processor<br/>'
                         '1 DaVinciV300 AI core at 1.224GHz<br/>'
                         '4 TAISHANV200M processor cores at 1.6GHz', 'CPU')
    assert info['status'] == 'resolved-identity'
    assert {d.soc_marketing_name for d in drafts} == {'UNKNOWN'}
    assert all(d.evidence_insufficient and not d.identity_conflict for d in drafts)


def test_real_multi_soc_and_unlabelled_role_ambiguity_survive():
    for value in ('H2 Quad-core Cortex-A7<br>H3 Quad-core Cortex-A7',
                  'Rockchip RK3399 (4GB)<br>Rockchip RK3399-T(3GB)',
                  'T527<br>Mystery Z999'):
        drafts, info = parse(value)
        assert info['status'] == 'identity-conflict'
        assert drafts[0].identity_conflict
