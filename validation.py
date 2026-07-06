# CELL 6.5: INPUT VALIDATION LAYER — V17.0 (professional CAD/BIM-style pre-flight checks)
# ════════════════════════════════════════════════════════════════════════════════
# This cell adds a validation layer that runs BEFORE any topology generation.
# It does NOT modify the generation engine, scoring, or topology selection —
# it only decides whether generation is allowed to start, the same way a
# CAD/BIM tool validates a program brief before it lets you draw.
#
#   validate_user_program(...)   -> report dict (see docstring below)
#   print_validation_report(...) -> prints the CAD/BIM-style banner,
#                                    returns True  -> proceed to generation
#                                                False -> STOP, do not generate
# ════════════════════════════════════════════════════════════════════════════════

from planning_engine import ROOM_MIN_AREA

def _estimate_min_net_area(n_bed, n_bath, n_kit, has_dining=False, has_master_bath=False):
    """Professional space-programming estimate of the minimum NET area
    required to physically fit the requested program (bedrooms + bathrooms +
    kitchen + living [+ dining] + circulation).

    Calibrated against realistic, buildable room sizes (a primary bedroom,
    secondary bedrooms, full bathrooms, a working kitchen, a living/reception
    room, circulation) -- deliberately generous enough that programs the
    engine already builds comfortably (e.g. 2 bed / 1-2 bath on 75-110 m2,
    matching this notebook's own working examples) are NOT flagged, while
    programs that are genuinely too large for the requested area ARE caught.
    """
    BED_MASTER        = 15.0   # primary/master-sized bedroom
    BED_SECONDARY     = 13.0   # each additional bedroom
    BATH_MIN          = 3.5    # per full bathroom
    KITCHEN_MIN       = 7.0
    LIVING_MIN        = 16.0
    DINING_MIN        = 6.0    # only if a separate dining room is requested
    CIRCULATION_FRAC  = 0.15   # corridor(s)/foyer as a fraction of the program

    n_bed  = max(n_bed, 0)
    n_bath = max(n_bath, 0)
    n_kit  = max(n_kit, 0)

    # One primary/master-sized bedroom + the rest at secondary size -- this is
    # standard residential practice whether or not it has an en-suite.
    bedrooms_area = (BED_MASTER + (n_bed - 1) * BED_SECONDARY) if n_bed >= 1 else 0.0
    bathrooms_area = n_bath * BATH_MIN
    kitchens_area  = n_kit * KITCHEN_MIN
    living_area    = LIVING_MIN if (n_bed or n_bath or n_kit) else 0.0
    dining_area    = DINING_MIN if has_dining else 0.0

    program_sum = bedrooms_area + bathrooms_area + kitchens_area + living_area + dining_area

    # Circulation allowance (corridor(s)/foyer linking every room).
    circulation = max(ROOM_MIN_AREA.get('corridor', 2.5), CIRCULATION_FRAC * program_sum)

    return round(program_sum + circulation, 1)

def validate_user_program(n_bed=2, n_bath=2, n_kit=1, area=90.0,
                           has_bal=True, has_dining=False, has_master_bath=False):
    """CAD/BIM-style pre-flight validation of a requested program.

    Must be called BEFORE any topology generation. Returns:
        {
          'status'        : 'PASS' | 'FAIL',
          'errors'        : [str, ...]   # any non-empty -> status == 'FAIL'
          'warnings'      : [str, ...]   # never blocks generation
          'checks'        : [(label, 'PASS'|'FAIL'), ...]   # summary table rows
          'est_min_area'  : float
          'est_suggested' : (lo, hi)
        }
    """
    errors, warnings, checks = [], [], []

    # ── 1. Room-count sanity (hard errors) ─────────────────────────────────
    if n_bed is None or n_bed < 1:
        errors.append(f'Bedrooms = {n_bed} — at least 1 bedroom is required.')
    if n_bath is None or n_bath < 1:
        errors.append(f'Bathrooms = {n_bath} — at least 1 bathroom is required.')
    if n_kit is None or n_kit < 1:
        errors.append(f'Kitchens = {n_kit} — at least 1 kitchen is required.')
    if area is None or area <= 0:
        errors.append(f'Requested area = {area} m² — area must be a positive number.')
    for label, val in (('Bedrooms', n_bed), ('Bathrooms', n_bath), ('Kitchens', n_kit)):
        if val is not None and val < 0:
            errors.append(f'{label} = {val} — negative room counts are not allowed.')
    if (n_bed or 0) >= 1 and (n_bath or 0) >= 1 and n_bath > n_bed + 2:
        errors.append(
            f'Bathrooms ({n_bath}) greatly exceed Bedrooms ({n_bed}) — '
            f'no residential program supports this ratio.')

    checks.append(('Bedrooms',  'FAIL' if (n_bed is None or n_bed < 1) else 'PASS'))
    checks.append(('Bathrooms', 'FAIL' if (n_bath is None or n_bath < 1 or
                                            (n_bed is not None and n_bath > n_bed + 2)) else 'PASS'))
    checks.append(('Kitchen',   'FAIL' if (n_kit is None or n_kit < 1) else 'PASS'))

    safe_bed  = max(n_bed, 0) if n_bed is not None else 0
    safe_bath = max(n_bath, 0) if n_bath is not None else 0
    safe_kit  = max(n_kit, 0) if n_kit is not None else 0
    est_min = _estimate_min_net_area(safe_bed, safe_bath, safe_kit,
                                      has_dining=has_dining,
                                      has_master_bath=has_master_bath)
    est_suggested = (est_min, round(est_min * 1.20, 1))

    # ── 2. Area feasibility (hard error) ────────────────────────────────────
    area_ok = (area is not None and area > 0 and area >= est_min * 0.98)
    if area is not None and area > 0 and area < est_min * 0.98:
        program_bits = [f'{safe_bed} Bedroom(s)', f'{safe_bath} Bathroom(s)',
                         f'{safe_kit} Kitchen(s)', 'Living']
        if has_dining:
            program_bits.append('Dining')
        errors.append(
            'Requested program (' + ', '.join(program_bits) + ') cannot '
            f'physically fit inside {area:.0f} m² (needs ≥{est_min:.0f} m²).')
    checks.append(('Requested Area', 'PASS' if area_ok else 'FAIL'))
    checks.append(('Program Feasibility', 'PASS' if area_ok else 'FAIL'))

    # ── 3. Logical / architectural-quality checks (soft warnings only) ─────
    if has_master_bath and (n_bed is None or n_bed < 1):
        errors.append('has_master_bath=True requires at least 1 (master) bedroom.')
    if has_master_bath and n_bath is not None and n_bath < 2:
        warnings.append(
            'has_master_bath=True with only 1 bathroom — there will be no '
            'separate guest bath; every visitor uses the master en-suite.')
    if has_dining and area is not None and area > 0 and area < 70:
        warnings.append(
            f'Separate dining room requested for a very small apartment '
            f'({area:.0f} m²) — consider open-plan living+dining instead.')
    if n_bed is not None and n_bath is not None and n_bed >= 1 and n_bath > n_bed and n_bath <= n_bed + 2:
        warnings.append(
            f'{n_bath} bathrooms for {n_bed} bedroom(s) is generous — verify this is intentional.')
    if n_kit is not None and n_kit > 1:
        warnings.append(f'{n_kit} kitchens requested — unusual for a single residential unit.')
    if area_ok and area < est_min * 1.05:
        warnings.append(
            f'Requested area ({area:.0f} m²) is only just above the estimated '
            f'minimum ({est_min:.0f} m²) — layouts will be tight.')

    status = 'FAIL' if errors else 'PASS'
    return {
        'status': status,
        'errors': errors,
        'warnings': warnings,
        'checks': checks,
        'est_min_area': est_min,
        'est_suggested': est_suggested,
    }


def print_validation_report(report, n_bed, n_bath, n_kit, area):
    """Prints the CAD/BIM-style validation banner.
    Returns True  -> input is valid, proceed to the existing generation engine.
    Returns False -> input is invalid, generation must NOT start.
    """
    W = 70
    safe_area = area if area else 0.0
    print('=' * W)
    if report['status'] == 'PASS':
        print('INPUT VALIDATION')
        for label, res in report['checks']:
            print(f'  {label + " ":.<22} {res}')
        print(f'\n  Estimated Minimum Area : {report["est_min_area"]:.0f} m²')
        print(f'  Requested Area         : {safe_area:.0f} m²')
        if report['warnings']:
            print('\n  WARNINGS (generation will continue):')
            for w in report['warnings']:
                print(f'    ⚠ {w}')
        print('\nSTATUS')
        print('  VALID INPUT')
        print('  Generation Started...')
        print('=' * W)
        return True
    else:
        print('INPUT VALIDATION FAILED')
        print(f'\n  Requested Area         : {safe_area:.0f} m²')
        print(f'  Estimated Minimum Area : {report["est_min_area"]:.0f} m²')
        print('\n  Reason:')
        for e in report['errors']:
            print(f'    ✗ {e}')
        lo, hi = report['est_suggested']
        print(f'\n  Suggested Area : {lo:.0f}–{hi:.0f} m²')
        if report['warnings']:
            print('\n  Additional warnings:')
            for w in report['warnings']:
                print(f'    ⚠ {w}')
        print('\nGeneration Cancelled.')
        print('=' * W)
        return False


print('validate_user_program() ready ✓  (Input Validation Layer — runs before every generation call)')
