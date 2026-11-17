"""Recompute bounded public E0 results without credentials or model requests."""
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiment/src'))
from reference_metrics import mean_pairwise_edit, contraction, extra_contraction


def main():
    folder = ROOT / 'results/e0_20261117'
    read = lambda name: json.loads((folder / name).read_text('utf8'))
    provenance = read('provenance.json')
    for name, expected in provenance['files'].items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Published file hash changed: ' + name)
    seqs = read('structure_sequences.json')['sequences']
    mapping = {row['slot_id']: row['sequence'] for row in seqs}
    if len(seqs) != 15 or len(mapping) != 15:
        raise ValueError('Expected 15 unique review sequences')
    distances = {}
    for t in range(3):
        for group in ('A_LOOP', 'A_INDEPENDENT'):
            distances[group, t] = mean_pairwise_edit([
                mapping[f'seed_k{k}' if t == 0 else f'{group}_k{k}_t{t}'] for k in (1, 2, 3)], expected_k=3)
    for point in read('structure_metrics.json')['curves']:
        t = point['round']
        expected = {'D_loop': distances['A_LOOP', t], 'D_independent': distances['A_INDEPENDENT', t],
            'C_loop': contraction(distances['A_LOOP', 0], distances['A_LOOP', t]),
            'C_independent': contraction(distances['A_INDEPENDENT', 0], distances['A_INDEPENDENT', t]),
            'delta_C': extra_contraction(distances['A_LOOP', 0], distances['A_LOOP', t],
                                        distances['A_INDEPENDENT', 0], distances['A_INDEPENDENT', t])}
        for key, value in expected.items():
            if not math.isclose(point[key], value, abs_tol=1e-12):
                raise ValueError(f'Round {t}, {key}: recomputation differs')
    for group in read('quality_summary.json')['transition_groups']:
        expected = None if group['eligible'] == 0 else group['retained'] / group['eligible']
        if expected is None or not math.isclose(group['J03_micro'], expected, abs_tol=1e-12):
            raise ValueError('Retention numerator/denominator inconsistency')
    print('Verified 15 sequences, all E0 structural metrics, published file hashes, and four retention fractions. No model calls.')


if __name__ == '__main__':
    main()
