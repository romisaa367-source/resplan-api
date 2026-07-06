# generator.py
# ════════════════════════════════════════════════════════════════════════════
# High-level wrapper around the procedural planning engine (planning_engine.py),
# the input-validation layer (validation.py), and the AGS-style renderer
# (renderer.py). No trained GAN/GNN model is loaded anywhere in this file or
# its imports — every layout is produced by the deterministic rule-based
# engine (stage1..stage9 in planning_engine.py).
#
# This mirrors the notebook's generate_one() / generate_options() (CELL 12,
# V16.7 STRICT TOPOLOGICAL & ARCHITECTURAL DIVERSITY):
#   1. Runs validate_user_program() FIRST (CELL 6.5, V17.0) — if the
#      requested program cannot physically fit the requested area, no
#      generation is attempted at all; a structured validation-failure
#      response is returned instead (mirrors the notebook's "INPUT
#      VALIDATION FAILED" banner, but as JSON).
#   2. Otherwise sweeps every allowed template x every applicable bath
#      strategy x up to 5 rectangular proportions (Square / Compact
#      Rectangle / Rectangle / Wide Rectangle / Long Rectangle — the exact
#      aspect-ratio targets scale with area/bedroom count, same as the
#      notebook), keeps every valid result, and selects up to n_options
#      GENUINELY DISTINCT layouts (different topology template first,
#      falling back to different bath-strategy/shape, always checked with
#      _is_geometrically_distinct so no two options are just stretched
#      copies of each other).
# ════════════════════════════════════════════════════════════════════════════

import io
import random
import matplotlib
matplotlib.use('Agg')          # headless backend — required on a server
import matplotlib.pyplot as plt

from planning_engine import (
    _run_one_v11, _templates_for_program, stage4_circulation,
    RATIO_BANDS, ROOM_MIN_AREA, ROOM_MAX_AREA,
)
from renderer import render_plan_v11
from validation import validate_user_program

LAYOUT_DESC = {
    'ensuite_living':  'En-suite in the master bedroom + 2nd bathroom off the living room',
    'ensuite_bedroom': 'En-suite in the master bedroom + 2nd bathroom inside another bedroom',
    'corridor_both':   'Classic - both bathrooms open off the corridor (never on the same wall)',
}


def _is_geometrically_distinct(rooms_A, BW_A, BH_A, rooms_B, BW_B, BH_B, tol=0.35):
    """V16.7 — checks if two room layouts are genuinely different in
    geometry and room placement (prevents returning near-duplicate
    drawings even if the template/shape labels differ)."""
    if abs(BW_A - BW_B) > 0.45 or abs(BH_A - BH_B) > 0.45:
        return True
    dict_A = {}
    for r in rooms_A:
        dict_A.setdefault(r.name, []).append((r.x0, r.y0, r.w, r.h))
    dict_B = {}
    for r in rooms_B:
        dict_B.setdefault(r.name, []).append((r.x0, r.y0, r.w, r.h))
    if set(dict_A.keys()) != set(dict_B.keys()):
        return True
    for name, list_A in dict_A.items():
        list_B = dict_B.get(name, [])
        if len(list_A) != len(list_B):
            return True
        list_A = sorted(list_A, key=lambda b: (round(b[0], 2), round(b[1], 2)))
        list_B = sorted(list_B, key=lambda b: (round(b[0], 2), round(b[1], 2)))
        for bA, bB in zip(list_A, list_B):
            if max(abs(a - b) for a, b in zip(bA, bB)) > tol:
                return True
    return False


def _bath_strategies(n_bath, has_master_bath):
    if has_master_bath:
        strategies = ['ensuite_living', 'ensuite_bedroom']
    else:
        strategies = ['corridor_both']
    if n_bath >= 2 and not has_master_bath:
        strategies.append('ensuite_living')
    return strategies


def _shape_profiles(n_bed, area):
    """Dynamically scaled rectangular aspect-ratio targets — identical
    bands to the notebook's generate_one() (V16.5 dynamic area adaptation)."""
    if n_bed >= 3:
        return [
            ('Square', 1.02), ('Compact Rectangle', 1.18), ('Rectangle', 1.35),
            ('Wide Rectangle', 1.50), ('Long Rectangle', 1.68),
        ]
    if area >= 130:
        return [
            ('Square', 1.02), ('Compact Rectangle', 1.25), ('Rectangle', 1.50),
            ('Wide Rectangle', 1.75), ('Long Rectangle', 2.00),
        ]
    if area >= 95:
        return [
            ('Square', 1.02), ('Compact Rectangle', 1.18), ('Rectangle', 1.35),
            ('Wide Rectangle', 1.55), ('Long Rectangle', 1.75),
        ]
    return [
        ('Square', 1.02), ('Compact Rectangle', 1.12), ('Rectangle', 1.22),
        ('Wide Rectangle', 1.35), ('Long Rectangle', 1.48),
    ]


def _room_audit(rooms, BW, BH, target_area):
    """Builds a structured 'data' payload — every fact about the generated
    plan, as JSON-friendly data (equivalent to the notebook's printed
    audit/realism-check info, but structured)."""
    indoor   = [r for r in rooms if r.name != 'balcony']
    net_m2   = sum(r.area for r in indoor)
    gross_m2 = sum(r.gross_area for r in indoor)
    bal_m2   = sum(r.area for r in rooms if r.name == 'balcony')

    by_t = {}
    for r in rooms:
        by_t.setdefault(r.name, []).append(r)

    cor_area  = sum(r.area for r in by_t.get('corridor', []))
    cor_ratio = cor_area / max(net_m2, 1.0) * 100

    reach, isolated_count = stage4_circulation(rooms)

    bal = next((r for r in rooms if r.name == 'balcony'), None)
    balcony_check = None
    if bal:
        bal_adj = [x.name for x in rooms if x is not bal and x.shares_wall(bal)]
        ok = (bal.is_protrusion and 'living' in bal_adj and
              not any(n in bal_adj for n in ('kitchen', 'bedroom', 'bathroom', 'corridor')))
        balcony_check = {'adjacent_to': bal_adj, 'ok': ok}

    entry_room = next((r for r in rooms if any(d.get('entry') for d in r.doors)), None)
    entry_check = {'entry_room': entry_room.name if entry_room else None}

    master_bath_suite = None
    if by_t.get('bathroom') and by_t.get('bedroom'):
        master_bath_suite = any(
            any(b.shares_wall(bd) for bd in by_t['bedroom'])
            for b in by_t['bathroom']
        )

    kitchen_check = None
    if by_t.get('kitchen') and by_t.get('bedroom'):
        mk = max(r.area for r in by_t['kitchen'])
        mb = min(r.area for r in by_t['bedroom'])
        kitchen_check = {'max_kitchen_m2': round(mk, 1),
                          'min_bedroom_m2': round(mb, 1),
                          'ok': mk < mb}

    beds = by_t.get('bedroom', [])
    window_counts = [len(b.windows) for b in beds] if beds else []

    bad_ratios = []
    for r in rooms:
        if r.h < 0.01 or r.name == 'balcony':
            continue
        ratio = r.w / r.h
        lo, hi = RATIO_BANDS.get(r.name, (0.30, 3.50))
        if ratio < lo or ratio > hi:
            bad_ratios.append(f'{r.name}={ratio:.2f}')

    privacy_violations = [
        f'{bi.name}<->{li.name}'
        for bi in by_t.get('bedroom', [])
        for li in by_t.get('living', [])
        if bi.shares_wall(li)
    ]

    room_list = []
    for r in rooms:
        mn = ROOM_MIN_AREA.get(r.name)
        mx = ROOM_MAX_AREA.get(r.name)
        flags = []
        if mn and r.area < mn:
            flags.append(f'below-min({mn})')
        if mx and r.area > mx:
            flags.append(f'above-max({mx})')
        room_list.append({
            'name': r.name,
            'tag': r.tag,
            'net_area_m2': r.area,
            'gross_area_m2': r.gross_area,
            'width_m': r.w,
            'height_m': r.h,
            'touches_exterior': r.touches_outer(BW, BH),
            'is_protrusion': r.is_protrusion,
            'n_windows': len(r.windows),
            'n_doors': len(r.doors),
            'flags': flags,
        })

    return {
        'net_area_m2': round(net_m2, 1),
        'gross_area_m2': round(gross_m2, 1),
        'balcony_area_m2': round(bal_m2, 1),
        'target_area_m2': target_area,
        'area_delta_m2': round(net_m2 - target_area, 1),
        'envelope_w_m': round(BW, 2),
        'envelope_h_m': round(BH, 2),
        'n_rooms': len(rooms),
        'corridor_area_m2': round(cor_area, 1),
        'corridor_pct_of_net': round(cor_ratio, 1),
        'circulation': {
            'reachable_pct': round(reach * 100, 1),
            'isolated_room_count': isolated_count,
        },
        'checks': {
            'balcony_adjacency': balcony_check,
            'entry_door': entry_check,
            'master_bath_suite': master_bath_suite,
            'kitchen_vs_bedroom': kitchen_check,
            'bedroom_window_counts': window_counts,
            'bad_ratio_rooms': bad_ratios,
            'privacy_violations': privacy_violations,
        },
        'rooms': room_list,
    }


def generate_options(n_bed=2, n_bath=1, n_kit=1, has_bal=True, area=75.0,
                      has_master_bath=False, has_dining=False,
                      has_dressing=False, n_options=3, n_attempts=25,
                      seed=None):
    """Generates up to n_options DISTINCT floor plans (mirrors the
    notebook's generate_one()/generate_options(), V16.7).

    Step 1 — validates the requested program BEFORE any generation is
    attempted (validate_user_program). If validation fails, returns a
    single dict: {'ok': False, 'validation_failed': True, 'errors': [...],
    'warnings': [...], 'est_min_area': ..., 'est_suggested': (lo, hi)} and
    does no generation work at all.

    Step 2 — otherwise sweeps every allowed template x every applicable
    bath strategy x up to 5 rectangular proportions, keeps every valid
    result, and returns up to n_options genuinely distinct layouts
    (unique topology first, then unique strategy/shape — always checked
    for real geometric difference).

    Returns a list of dicts. On validation failure: a single-item list
    with 'validation_failed': True. On generation failure (validation
    passed but nothing came out valid): a single-item list with 'ok': False.
    On success: up to n_options dicts with 'ok': True, 'png_bytes', and
    full plan data.
    """
    report = validate_user_program(
        n_bed=n_bed, n_bath=n_bath, n_kit=n_kit, area=area,
        has_bal=has_bal, has_dining=has_dining, has_master_bath=has_master_bath)

    if report['status'] == 'FAIL':
        lo, hi = report['est_suggested']
        return [{
            'ok': False,
            'validation_failed': True,
            'errors': report['errors'],
            'warnings': report['warnings'],
            'checks': report['checks'],
            'requested_area_m2': area,
            'estimated_min_area_m2': report['est_min_area'],
            'suggested_area_range_m2': [lo, hi],
        }]

    rng = random.Random(seed) if seed is not None else random.Random()

    allowed_templates = _templates_for_program(area, n_bed, n_bath)
    bath_strategies = _bath_strategies(n_bath, has_master_bath)
    shape_profiles = _shape_profiles(n_bed, area)
    base_seed = rng.randint(1, 1_000_000)

    all_valid = []
    for tmpl in allowed_templates:
        for bath_layout in bath_strategies:
            for shape_name, target_ar in shape_profiles:
                for attempt in range(n_attempts):
                    attempt_seed = (base_seed + attempt + hash(tmpl) % 9973
                                     + hash(shape_name) % 503)
                    hint = {'aspect_ratio': target_ar, 'shape_name': shape_name,
                            'priv_w_frac': 0.45, 'kit_h_frac': 0.30, 'fallback': False}
                    rooms, BW, BH, sc = _run_one_v11(
                        n_bed, n_bath, n_kit, has_bal, area, tmpl,
                        attempt_seed, hint=hint, _reason_out=None,
                        has_dining=has_dining, has_master_bath=has_master_bath,
                        bath_layout=bath_layout, has_dressing=has_dressing)
                    if sc != float('inf') and rooms:
                        all_valid.append((tmpl, bath_layout, shape_name,
                                           target_ar, rooms, BW, BH, sc, attempt_seed))

    if not all_valid:
        return [{
            'ok': False,
            'validation_failed': False,
            'error': (
                f'Input passed validation but no valid design was found for '
                f'n_bed={n_bed}, n_bath={n_bath}, area={area}m² across any '
                f'template x bath-strategy x shape combination. Try '
                f'increasing area slightly, or raising n_attempts.'
            ),
        }]

    all_valid.sort(key=lambda x: x[7])  # best score first

    selected = []
    used_topologies = set()
    selected_seeds = set()

    # Pass 1: strict topological diversity — unique template per option
    for cand in all_valid:
        tmpl, bath_layout, shape_name, target_ar, rooms, BW, BH, sc, sd = cand
        if tmpl not in used_topologies:
            distinct = all(
                _is_geometrically_distinct(rooms, BW, BH, s[4], s[5], s[6])
                for s in selected
            )
            if distinct:
                selected.append(cand)
                used_topologies.add(tmpl)
                selected_seeds.add(sd)
                if len(selected) == n_options:
                    break

    # Pass 2: fallback — fill remaining slots with any geometrically distinct candidate
    if len(selected) < n_options:
        for cand in all_valid:
            sd = cand[8]
            if sd not in selected_seeds:
                distinct = all(
                    _is_geometrically_distinct(cand[4], cand[5], cand[6], s[4], s[5], s[6])
                    for s in selected
                )
                if distinct:
                    selected.append(cand)
                    selected_seeds.add(sd)
                    if len(selected) == n_options:
                        break

    results = []
    for idx, choice in enumerate(selected, 1):
        tmpl, bath_layout, shape_name, target_ar, rooms, BW, BH, sc, sd = choice
        net_m2 = sum(r.area for r in rooms if r.name != 'balcony')
        entry_room = next((r for r in rooms if any(d.get('entry') for d in r.doors)), None)
        entry_name = entry_room.name if entry_room else 'corridor'

        fig = render_plan_v11(
            rooms, BW, BH, net_area=area,
            title=f'Option {idx} [{shape_name}]: {n_bed} Bed | {n_bath} Bath | '
                  f'{tmpl} | NET {net_m2:.0f}m2 (Door: {entry_name})',
            save_path=None)

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=300, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        buf.seek(0)

        data = _room_audit(rooms, BW, BH, area)
        data.update({
            'ok': True,
            'validation_failed': False,
            'option': idx,
            'shape': shape_name,
            'template': tmpl,
            'bath_layout': bath_layout,
            'bath_layout_description': LAYOUT_DESC.get(bath_layout, ''),
            'score': round(sc, 1),
            'entry_room': entry_name,
            'png_bytes': buf.getvalue(),
        })
        results.append(data)

    return results
