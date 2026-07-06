# CELL 6: V13.1.2 ARCHITECTURAL PLANNING ENGINE — PRIVACY + DEAD-SPACE PATCH
# ════════════════════════════════════════════════════════════════════════════════
# V13.1.2 patches on top of V13.1.1g (review-driven; six numbered patches in code):
#
#  PATCH    What it fixes                                          Where
#  ───────  ──────────────────────────────────────────────────     ─────────────
#  1 a-d    GRID_FINE=0.10m for jittered splits; 0.50 collapse     _hstack, _subdivide_private_wing
#  2        Storage emission requires real closet shape + door     _absorb_orphan_strips
#           edge; no more sealed-strip "storage litter"
#  3        Merge priority extended (corridor/kitchen/dining) so   _absorb_orphan_strips
#           more strips disappear instead of becoming storage
#  4        +300 corridor-bath penalty exempts tag='ensuite'       score_plan_v11
#           (was cancelling V12's -25 ensuite reward → net +275)
#  5        Removed fake V11-FIX-#7 master-bath bonus that         score_plan_v11
#           rewarded any wall-share geometry; V12 has the
#           correct version (-25 only if NOT touching corridor)
#  6 / 6b   Hard gates: BFS reachability from entry door; total    _v12_livability_gate
#           dead-space ≤ 2.0 m². Sealed/untileable layouts → ∞
#
# All V13.1.1g content below is preserved. Patches are marked V13.1.2-PATCH-N
# inline so each change is locatable. Original V11/V12 changelog kept below.
# ════════════════════════════════════════════════════════════════════════════════
# CELL 6: V12 ARCHITECTURAL PLANNING ENGINE — REALISM PASS
# ════════════════════════════════════════════════════════════════════════════════
# V11 → V12 — addresses the "boxes inside a box" output. Adds genuine architectural
# realism: hard-livability rejection, real wing template, master-suite cluster,
# bath wet-wall stacking, entry foyer, and area-distribution caps that match real
# Egyptian apartment practice.
#
#  V12-NEW   Change                                                  Where
#  ────────  ──────────────────────────────────────────────────────  ─────────────────────────────
#  V12-A     HARD-REJECT unlivable rooms in score (returns ∞)        score_plan_v12 top guard
#  V12-B     WING template — bedrooms in horizontal row, not stack   stage2_zones_v12 + new subdivision
#  V12-C     Bathrooms BACK-TO-BACK on shared wet-wall (plumbing)    _subdivide_private_v12
#  V12-D     Master-bath = en-suite only (no corridor door)          DOOR_FORBIDDEN add + master-suite logic
#  V12-E     Living-area cap: ≤ 32% of total NET                     score hard-reject
#  V12-F     Bathroom-area cap: each ≤ 5.5 m² (was 7.5)              ROOM_MAX_AREA
#  V12-G     Entry foyer for ≥ 80 m² apartments                      stage6 foyer module
#  V12-H     Aspect-ratio shift: ≥95 m² → square-ish (0.95–1.20)     ASPECT_BY_AREA override
#  V12-I     Bedroom min depth 2.80 m (was 2.70)                     ROOM_MIN_H
#  V12-J     Per-bedroom usable-bed test: w≥2.8 AND h≥2.8            score hard-reject
#  V12-K     Storage placement only inside foyer/corridor zone        stage6 cleanup
# ════════════════════════════════════════════════════════════════════════════════
# V11 fixes (still in effect):  #1 L-shape, #2 balcony→living, #3 swing,
# #4 entry door, #5 anti-collision, #6 corridor-all, #7 master-bath,
# #8 kitchen-vs-bed, #9 multi-window, #10/#12 NET area, #11 door obstacle,
# #13 balcony-living, #14 ratio bands.
# ════════════════════════════════════════════════════════════════════════════════

import numpy as np, math

# ── Adjacency preference weights (from notebook CELL 1 — unchanged) ────────
# Used by stage7b_bfs_polish() and score_plan_v12() to nudge/score room
# adjacency. Not GAN-related; pure rule-based constants.
ADJACENCY_RULES = [
    ('balcony',  'living',   4.0),
    ('kitchen',  'living',   3.5),
    ('corridor', 'living',   3.0),
    ('bedroom',  'corridor', 3.5),
    ('bathroom', 'corridor', 3.5),
    ('kitchen',  'corridor', 2.5),
]

# ── Grid snap (V13.1.2 — hierarchical) ─────────────────────
# V13.1.2-PATCH-1: three-tier grid for distinct purposes.
#   GRID       (0.50m) — coarse structural grid (legacy default, stage1 sizing)
#   GRID_FINE  (0.10m) — jittered partitions (preserves the 0.82–1.18 spread
#                        that GRID-0.50 was collapsing to 2 discrete values)
#   GRID_DOOR  (0.05m) — door positions only
# Default _snap behavior is UNCHANGED (g=GRID=0.50) for back-compat with all
# V11/V12 callers; only the explicit jittered call sites pass GRID_FINE.
GRID      = 0.50
GRID_FINE = 0.10
GRID_DOOR = 0.05
def _snap(v, g=GRID): return round(round(v / g) * g, 4)

# ── Wall thickness ─────────────────────────────────────────
WALL_T = 0.15

# ── Architectural minimums (V12 — hardened) ────────────────
ROOM_MIN_W = {
    'living'  : 3.40, 'bedroom' : 3.00, 'kitchen' : 2.40,
    'bathroom': 1.40, 'balcony' : 1.50,
    'veranda' : 2.00, 'corridor': 1.20, 'foyer'   : 1.20, 'dining'  : 1.80,
}
ROOM_MIN_H = {
    'living'  : 3.20, 'bedroom' : 2.60, 'kitchen' : 2.20,    # V12-I bedroom 2.70→2.80
    'bathroom': 1.30, 'balcony' : 1.40,
    'veranda' : 1.50, 'corridor': 1.20, 'foyer'   : 1.20, 'dining'  : 1.80,
}
# V12 — Hard livability thresholds (anything below → REJECT in score, not penalty)
ROOM_MIN_AREA = {
    'living'  : 14.0,
    'bedroom' : 10.0,
    'kitchen' :  6.0,
    'bathroom':  2.8,
    'balcony' :  3.0,
    'corridor':  2.5,
    'foyer'   :  1.5,
    'dining'  :  3.5,
}
ROOM_MAX_AREA = {
    'kitchen' : 25.0,
    'bathroom': 15.0,
    'corridor': 20.0,
    'foyer'   : 15.0,
    'dining'  : 25.0,
    'living'  : 999.0,
}
BEDROOM_MIN_DIM = 2.60

# V15.6 — AREA-ALLOCATION ENGINE. Target (lo, hi) m² per room TYPE, used to
# decide room sizes BEFORE geometry is drawn, instead of deriving sizes from
# whatever is left over after an arbitrary BW/BH split. ROOM_MIN/MAX_AREA
# above remain the hard SAFETY limits (used as clamps); AREA_TARGET is what
# the engine actually aims for.
AREA_TARGET = {
    'master_bedroom': (16.0, 22.0),
    'bedroom'        : (10.0, 16.0),   # secondary bedroom
    'living'         : (22.0, 35.0),
    'kitchen'        : ( 8.0, 16.0),
    'guest_bath'     : ( 3.0,  6.0),
    'ensuite'        : ( 4.0,  8.0),
    'foyer'          : ( 3.0,  6.0),
}

def _area_tier(net_area):
    """Small / medium / large NET-area tier — drives where in each
    AREA_TARGET range this apartment should sit, AND a handful of
    topology decisions (corridor width, whether a foyer makes sense)."""
    if not net_area or net_area < 85:
        return 'small'
    if net_area < 150:
        return 'medium'
    return 'large'

_TIER_FRACTION = {'small': 0.15, 'medium': 0.50, 'large': 0.85}

def _tier_target(room_key, net_area):
    """Pick a single target m² for `room_key`, positioned inside its
    AREA_TARGET range according to the apartment's size tier (a 70m² flat
    sits near the low end of every range; a 180m² flat sits near the high
    end) — this is what makes a 70/110/180m² apartment actually look like
    different apartments instead of the same plan rescaled."""
    lo, hi = AREA_TARGET[room_key]
    f = _TIER_FRACTION[_area_tier(net_area)]
    return lo + f * (hi - lo)

# V15.9 — AREA-DRIVEN TEMPLATE SELECTION (Priority 2). NET-area decides the
# TOPOLOGY itself before any geometry runs, not just room dimensions inside
# one fixed template. Bands are deliberately overlapping at the edges by a
# couple of templates so the engine still has a fallback to try if a sample
# is rejected, but the dominant shape per band genuinely differs.
def _templates_for_program(net_area, n_bed, n_bath):
    """V16.6 — Evaluate ALL valid templates across ALL bedroom and bathroom counts
    for maximum topological diversity across all envelope proportions.
    No area or bedroom hardcoding: dynamically explores all compatible topologies."""
    return ['wing', 'wing-stack', 'wing-split', 'vsplit', 'corner-core']

def _templates_for_area(net_area, n_bed=2, n_bath=1):
    """V15.10 — alias بالاسم المستخدم في generate_4_options()/generate_one().
    نفس منطق _templates_for_program بالظبط، لكن بيسمح لـ n_bed/n_bath يكون
    لهم قيمة افتراضية عشان أي كود قديم بينادي بمعامل واحد (المساحة بس)
    يفضل شغال، وأي كود جديد يقدر يبعت العدد الحقيقي لتنوّع أدق في القالب."""
    return _templates_for_program(net_area, n_bed, n_bath)

# V12-E — caps on area share of total NET (lower bound and upper bound)
AREA_SHARE_CAP = {
    'living'   : 0.45,
    'bedroom'  : 0.65,
    'bathroom' : 0.20,
    'corridor' : 0.25,
    'kitchen'  : 0.25,
    'foyer'    : 0.15,
    'dining'   : 0.20,
}

# Aspect ratio targets per #bedrooms  AND  by area band  (V12-H)
ASPECT_BY_NBED = {1: 1.10, 2: 1.20, 3: 1.30, 4: 1.25}
def aspect_for(area, n_bed):
    # V12-H — larger apartments → squarer envelope (more articulation room).
    base = ASPECT_BY_NBED.get(n_bed, 1.20)
    if area >= 95.0:  base = min(base, 1.15)
    if area >= 130.0: base = min(base, 1.05)
    return base

# Standard interior-door width (m). Entry door is wider.
DOOR_W_M  = 0.85
ENTRY_W_M = 1.00

CORRIDOR_W = 1.20   # V15.3 — was 1.40; matches ROOM_MIN_W['corridor']

# V13.1.1c — balcony protrusion 1.60 → 1.20 m. Egyptian building code / municipal
# setback rules cap balcony cantilever at ~1.0-1.2 m on ordinary streets (critique
# doc 2 §5). 1.60 m was a code violation in most cases.
BALCONY_PROTRUDE = 1.20
BALCONY_MIN_W    = 2.80

# V12-B — added 'wing' template
TEMPLATES = ['wing', 'wing-stack', 'wing-split', 'vsplit', 'corner-core']
# NOTE: 'wing-split' was fully implemented inside _wing_family_zones (kitchen
# LEFT, living MIDDLE, study/store RIGHT) but was never reachable before
# V15.9 — TEMPLATES never included it, so it was dead code.
# V13.1.1g — 'wing-l' (a pure MIRROR of 'wing') was REMOVED: a mirror is the
# same topological solution, not a new layout. It is replaced by 'wing-split'
# which is genuinely topologically distinct. The three templates differ in
# PUBLIC-zone topology:
#   wing        — kitchen in a full-height RIGHT column, living on the left
#   wing-stack  — kitchen + storage STACKED in a right column, living left
#   wing-split  — kitchen on the LEFT, living in the MIDDLE, study/storage
#                 nook on the RIGHT → a 3-part public band (distinct topology)
_LEGACY_TEMPLATES = ['classic', 'split', 'corridor', 'wing-l']  # retired

# V11-FIX-#14 — per-room aspect-ratio bands (W/H). Outside → heavy score penalty.
# Bands roughly hug the golden ratio range for living rooms;  bedrooms tighter.
RATIO_BANDS = {
    'living'  : (0.55, 1.95),
    'bedroom' : (0.55, 1.95),       # widened — 4.5×2.5 (=1.8) is realistic
    'kitchen' : (0.45, 2.60),       # galley layouts allowed
    'bathroom': (0.50, 2.20),
    'corridor': (0.10, 12.0),
    'balcony' : (0.30, 5.00),
}

# V15.11-FIX — ensuite bathrooms (tag='ensuite') legitimately include the
# merged walk-in/dressing space since V15.0 ("Dressing alcove: merged into
# ensuite bathroom"). The generic 8.0 m² / 2.80-ratio guest-bath envelope
# was never updated to match, which made a full-width ensuite bath fail
# score_plan_v12 almost every time a master bedroom was realistically wide
# (>~4.7 m — i.e. nearly always). This is that room's own, larger envelope.
ENSUITE_MAX_AREA  = 11.5
ENSUITE_MAX_RATIO = 3.5


# ════════════════════════════════════════════════════════════
# ROOM CLASS  (V11 — adds net_area, is_protrusion)
# ════════════════════════════════════════════════════════════
class Room:
    """Single room with absolute meter coordinates. (x0,y0) = bottom-left."""
    __slots__ = ('name','x0','y0','w','h','zone','windows','doors',
                 'is_protrusion','tag')

    def __init__(self, name, x0, y0, w, h, zone='', is_protrusion=False,
                 tag=None):
        self.name          = name
        self.x0            = float(round(x0, 3))
        self.y0            = float(round(y0, 3))
        self.w             = float(round(max(w, 0.50), 3))
        self.h             = float(round(max(h, 0.50), 3))
        self.zone          = zone
        self.windows       = []
        self.doors         = []
        # V11-FIX-#1 — a protruding room sits OUTSIDE the main BW×BH envelope
        self.is_protrusion = bool(is_protrusion)
        # V13.1.1e — optional semantic tag. 'ensuite' marks a bathroom whose
        # door must open FROM the master bedroom only (no corridor door).
        # 'master' marks the master bedroom.
        self.tag           = tag

    @property
    def x1(self): return round(self.x0 + self.w, 3)
    @property
    def y1(self): return round(self.y0 + self.h, 3)
    @property
    def cx(self): return self.x0 + self.w / 2
    @property
    def cy(self): return self.y0 + self.h / 2

    # V11-FIX-#10  — GROSS area (w×h)  vs  NET area (interior, walls deducted)
    @property
    def area(self):
        """NET interior area in m² (the value the user actually 'lives in')."""
        return round(max(self.w - WALL_T, 0.05) * max(self.h - WALL_T, 0.05), 3)

    @property
    def gross_area(self):
        """GROSS area in m² (centre-line of walls; what the footprint occupies)."""
        return round(self.w * self.h, 3)

    def touches_outer(self, BW, BH, tol=0.15):
        return (self.x0 <= tol or self.x1 >= BW - tol or
                self.y0 <= tol or self.y1 >= BH - tol or
                self.is_protrusion)            # protruding balcony is always outer

    def shares_wall(self, other, tol=0.18):
        x_ov = min(self.x1, other.x1) - max(self.x0, other.x0)
        y_ov = min(self.y1, other.y1) - max(self.y0, other.y0)
        h_w  = x_ov > 0.25 and (abs(self.y1 - other.y0) < tol or abs(other.y1 - self.y0) < tol)
        v_w  = y_ov > 0.25 and (abs(self.x1 - other.x0) < tol or abs(other.x1 - self.x0) < tol)
        return h_w or v_w

    def shared_wall_segment(self, other, tol=0.18):
        """Return (axis, fixed_coord, lo, hi) for the segment two rooms share, or None.
        axis = 'h' (horizontal wall, varying x) or 'v' (vertical wall, varying y)."""
        x_ov = min(self.x1, other.x1) - max(self.x0, other.x0)
        y_ov = min(self.y1, other.y1) - max(self.y0, other.y0)
        if x_ov > 0.25:
            if abs(self.y1 - other.y0) < tol:
                return ('h', (self.y1 + other.y0)/2,
                        max(self.x0, other.x0), min(self.x1, other.x1))
            if abs(other.y1 - self.y0) < tol:
                return ('h', (other.y1 + self.y0)/2,
                        max(self.x0, other.x0), min(self.x1, other.x1))
        if y_ov > 0.25:
            if abs(self.x1 - other.x0) < tol:
                return ('v', (self.x1 + other.x0)/2,
                        max(self.y0, other.y0), min(self.y1, other.y1))
            if abs(other.x1 - self.x0) < tol:
                return ('v', (other.x1 + self.x0)/2,
                        max(self.y0, other.y0), min(self.y1, other.y1))
        return None

    def overlap_area(self, other):
        ox = min(self.x1, other.x1) - max(self.x0, other.x0)
        oy = min(self.y1, other.y1) - max(self.y0, other.y0)
        return max(0., ox) * max(0., oy)

    def to_normalized(self, BW, BH):
        return [self.cx / BW, self.cy / BH, self.w / BW, self.h / BH]

    def __repr__(self):
        prot = '*' if self.is_protrusion else ''
        return f'{self.name}{prot}({self.x0:.1f},{self.y0:.1f} {self.w:.1f}x{self.h:.1f}={self.area:.1f}m²)'


# ════════════════════════════════════════════════════════════
# STAGE 1 — SITE ENGINE  (V11-FIX-#10, #12 : target is NET area)
# ════════════════════════════════════════════════════════════
def stage1_site(target_area, n_bed, seed=0, hint=None, has_master_bath=False):
    """target_area is the NET interior area the user requested.
    V16.3 — Envelope Abstraction Layer support: adjusts gross area and aspect ratios
    to accommodate true geometric notches (L-Shape and Wing Shape setbacks).
    """
    rng = np.random.default_rng(seed)
    if hint and not hint.get('fallback', True):
        ar = float(np.clip(hint['aspect_ratio'] + rng.uniform(-0.03, 0.03), 0.55, 2.10))
    else:
        ar = aspect_for(target_area, n_bed) + rng.uniform(-0.06, 0.06)
        lo, hi = (0.60, 1.80) if target_area < 95 else (0.65, 1.70)
        ar = float(np.clip(ar, lo, hi))

    if has_master_bath and target_area <= 95 and (hint is None or hint.get('fallback', True)):
        ar = min(ar, 0.95)
    gross_target = target_area * 1.08
    if hint and isinstance(hint, dict):
        sname = hint.get('shape_name', '')
        if 'L Shape' in sname or 'Wing Shape' in sname or 'حرف L' in sname or 'جناح' in sname:
            gross_target = target_area * 1.15  # Compensate for outdoor notch area loss
    BH = _snap(math.sqrt(gross_target / ar))
    BW = _snap(gross_target / max(BH, 1.0))
    return max(BW, 7.0), max(BH, 6.0)


# ════════════════════════════════════════════════════════════
# STAGE 5 — V4 HINT-FILTER  (unchanged from V10)
# ════════════════════════════════════════════════════════════
def validate_hints_v4(hint, BW):
    if hint is None or hint.get('fallback', True):
        return dict(aspect_ratio=1.20, priv_w_frac=0.45, kit_h_frac=0.30,
                    room_areas={}, raw_score=0.0, fallback=True,
                    has_corridor_proposal=False, force_corridor=True,
                    coords_proposal=None, rt_proposal=None, n_real=0), True

    corrected = False
    h = dict(hint)
    if not h.get('has_corridor_proposal', False):
        bump = CORRIDOR_W / max(BW, 1.0)
        h['priv_w_frac'] = float(np.clip(h['priv_w_frac'] + bump, 0.30, 0.60))
        h['force_corridor'] = True
        corrected = True
    else:
        h['force_corridor'] = True
    return h, corrected


# ════════════════════════════════════════════════════════════
# STAGE 4 — CIRCULATION BFS
# ════════════════════════════════════════════════════════════
def stage4_circulation(rooms):
    N = len(rooms)
    if N == 0: return 0.0, 0
    adj = {i: [] for i in range(N)}
    for i in range(N):
        for j in range(i+1, N):
            if rooms[i].shares_wall(rooms[j]):
                adj[i].append(j); adj[j].append(i)
    start = next((i for i,r in enumerate(rooms) if r.name == 'living'), 0)
    visited = {start}; queue = [start]
    while queue:
        cur = queue.pop(0)
        for nb in adj[cur]:
            if nb not in visited:
                visited.add(nb); queue.append(nb)
    return len(visited)/N, N - len(visited)


# ════════════════════════════════════════════════════════════
# STAGE 6 — ZONES & BSP SUBDIVISION (V11 — corridor + L-shape)
# ════════════════════════════════════════════════════════════
class BuildingEnvelope:
    """Envelope Abstraction Layer for ResPlan V16.3.
    Defines the physical building footprint, boundary polygon, buildable area,
    and notch geometry for 5 distinct architectural shapes:
      1. Square (مربع)
      2. Rectangle (مستطيل)
      3. Long Rectangle (مستطيل طويل)
      4. True L Shape (حرف L حقيقي)
      5. True Wing Shape (جناح عميق حقيقي)
    """
    def __init__(self, shape_name, target_area, n_bed, n_bath):
        self.shape_name = shape_name
        self.target_area = target_area
        self.n_bed = n_bed
        self.n_bath = n_bath
        self.is_l_shape = ('L Shape' in shape_name or 'حرف L' in shape_name)
        self.is_wing_shape = ('Wing Shape' in shape_name or 'جناح' in shape_name)

def _apply_envelope_notches(zones, variant, BW, BH, priv_h, cor_h, pub_h, hint):
    if not hint or not isinstance(hint, dict):
        return zones
    shape_name = hint.get('shape_name', '')
    if not shape_name or ('L Shape' not in shape_name and 'Wing Shape' not in shape_name and 'حرف L' not in shape_name and 'جناح' not in shape_name):
        return zones

    is_l_shape = ('L Shape' in shape_name or 'حرف L' in shape_name)
    is_wing_shape = ('Wing Shape' in shape_name or 'جناح' in shape_name)

    # Calculate safe notch height (approx 38% of pub_h)
    notch_h = _snap(pub_h * 0.38)
    if pub_h - notch_h < 2.50:
        notch_h = _snap(max(0.0, pub_h - 2.60))
    
    # Physical validation check: if pub_h is too small to notch without violating room minimums
    if notch_h < 1.0 or pub_h - notch_h < 2.40:
        zones['_physically_impossible_notch'] = True
        return zones

    if is_l_shape:
        # L-Shape: Notch out TOP-RIGHT corner of public zone
        if variant == 'wing':
            if 'SERVICE' in zones:
                x, y, w, h = zones['SERVICE']
                if h - notch_h >= ROOM_MIN_H['kitchen'] + 0.2:
                    zones['SERVICE'] = (x, y, w, round(h - notch_h, 4))
                else:
                    zones['_physically_impossible_notch'] = True
            elif 'DINING' in zones:
                x, y, w, h = zones['DINING']
                if h - notch_h >= ROOM_MIN_H['dining']:
                    zones['DINING'] = (x, y, w, round(h - notch_h, 4))
        elif variant == 'wing-stack':
            if 'SERVICE' in zones:
                x, y, w, h = zones['SERVICE']
                if h - notch_h >= ROOM_MIN_H['kitchen'] + 0.2:
                    zones['SERVICE'] = (x, y, w, round(h - notch_h, 4))
                else:
                    zones['_physically_impossible_notch'] = True
        elif variant == 'wing-split':
            if 'DINING' in zones:
                x, y, w, h = zones['DINING']
                if h - notch_h >= ROOM_MIN_H['dining']:
                    zones['DINING'] = (x, y, w, round(h - notch_h, 4))
            elif 'PUBLIC' in zones:
                x, y, w, h = zones['PUBLIC']
                nook_w = _snap(max(1.8, w * 0.35))
                liv_w = round(w - nook_w, 4)
                if liv_w >= ROOM_MIN_W['living'] and h - notch_h >= 2.40:
                    zones['PUBLIC'] = (x, y, liv_w, h)
                    zones['PUBLIC2'] = (round(x + liv_w, 4), y, nook_w, round(h - notch_h, 4))
                else:
                    zones['_physically_impossible_notch'] = True

    elif is_wing_shape:
        # Wing Shape: T-Wing or Stepped Wing
        if variant == 'wing-split':
            # T-Wing: Notch BOTH top-left (SERVICE) and top-right (DINING/PUBLIC2)
            notch_ok = True
            if 'SERVICE' in zones:
                x, y, w, h = zones['SERVICE']
                if h - notch_h >= ROOM_MIN_H['kitchen'] + 0.2:
                    zones['SERVICE'] = (x, y, w, round(h - notch_h, 4))
                else:
                    notch_ok = False
            if 'DINING' in zones:
                x, y, w, h = zones['DINING']
                if h - notch_h >= ROOM_MIN_H['dining']:
                    zones['DINING'] = (x, y, w, round(h - notch_h, 4))
            elif 'PUBLIC' in zones:
                x, y, w, h = zones['PUBLIC']
                nook_w = _snap(max(1.8, w * 0.35))
                liv_w = round(w - nook_w, 4)
                if liv_w >= ROOM_MIN_W['living'] and h - notch_h >= 2.40:
                    zones['PUBLIC'] = (x, y, liv_w, h)
                    zones['PUBLIC2'] = (round(x + liv_w, 4), y, nook_w, round(h - notch_h, 4))
                else:
                    notch_ok = False
            if not notch_ok:
                zones['_physically_impossible_notch'] = True
        elif variant in ('wing', 'wing-stack'):
            # Stepped Wing: Notch TOP-LEFT (PUBLIC/living), so right side projects out!
            if 'PUBLIC' in zones:
                x, y, w, h = zones['PUBLIC']
                if h - notch_h >= ROOM_MIN_H['living'] + 0.2:
                    zones['PUBLIC'] = (x, y, w, round(h - notch_h, 4))
                    if 'OUTDOOR' in zones and zones['OUTDOOR'] is not None:
                        ox, oy, ow, oh = zones['OUTDOOR']
                        zones['OUTDOOR'] = (ox, round(oy - notch_h, 4), ow, oh)
                else:
                    zones['_physically_impossible_notch'] = True

    return zones


def _wing_family_zones(BW, BH, variant, has_bal, has_dining, has_master_bath,
                        bal_h_protrude, rng, target_area=None, hint=None):
    """V13.1.1f — shared zone builder for the three WING-family layouts.

    All three share the proven core:
      • a horizontal BEDROOM ROW at the bottom (full BW)
      • a horizontal CORRIDOR SPINE above it (full BW, 1.2 m)
      • the PUBLIC zone (living + kitchen [+ dining]) on top
    They differ only in how the PUBLIC zone is arranged:

      variant 'wing'       kitchen column on the RIGHT, living on the left
      variant 'wing-split' kitchen LEFT, living MIDDLE, study/store RIGHT
      variant 'wing-stack' kitchen + storage stacked in a right column; living
                           is an L that wraps over it (full width on top)

    Returns the zones dict (without the _protrude_outdoor flag).
    """
    # ── shared: bedroom row depth + corridor spine ────────────────
    if has_master_bath:
        priv_h_frac  = float(np.clip(0.43 + rng.uniform(-0.02, 0.03), 0.41, 0.46))
        priv_h_floor = max(ROOM_MIN_H['bedroom'] + 1.90, 4.90)
    else:
        priv_h_frac  = float(np.clip(0.38 + rng.uniform(-0.03, 0.03), 0.34, 0.44))
        priv_h_floor = ROOM_MIN_H['bedroom'] + 0.4
    priv_h = _snap(max(BH * priv_h_frac, priv_h_floor))
    # V13.1.1f — CAP the private-row depth. In STANDARD mode a full-height
    # bathroom must stay within ROOM_MAX_AREA (8 m²); at the minimum bath
    # width that caps the row at ~4.6 m. In EN-SUITE mode the baths live in a
    # fixed-height band so the row may be deeper (it must fit band + bedroom).
    if has_master_bath:
        PRIV_H_CAP = 5.80          # band (~1.9) + bedroom (~3.3) + slack
    else:
        # V13.2.1 — cap row at 3.40m. Full-height baths then read ~1.3×3.4 ≈
        # 4.4 m² with ratio ~0.38 (just above the 0.36 bowling-alley floor).
        # Bedrooms get their area from WIDTH (they are wide, ~3.5-4.5m) so the
        # shallower row does not starve them.
        PRIV_H_CAP = 3.40
    priv_h = min(priv_h, PRIV_H_CAP)

    cor_h = 1.20                                    # horizontal spine
    pub_h = round(BH - priv_h - cor_h, 4)
    # V15.8 — reserve a touch of extra height so a COMPACT foyer band
    # always has somewhere to go (instead of the public zone landing
    # exactly at living's own floor and leaving nothing for the entry
    # sequence at all). V15.9-FIX — this must NEVER eat into priv_h below
    # priv_h_floor (the master-bath height requirement) — on a short
    # building there may not be room for both; in that case the foyer
    # reserve backs off instead of producing an illegally short bedroom
    # row (this was a real regression: net=70 + has_master_bath was
    # failing 10/10 before this fix).
    _pub_h_floor = ROOM_MIN_H['living'] + 1.15
    if pub_h < _pub_h_floor:
        _room_for_pub = round(BH - cor_h - priv_h_floor, 4)
        _pub_h_floor = max(min(_pub_h_floor, _room_for_pub), ROOM_MIN_H['living'])
        priv_h = round(BH - cor_h - _pub_h_floor, 4)
        pub_h  = _pub_h_floor

    cor_y = priv_h
    pub_y = priv_h + cor_h

    # ── PUBLIC zone split — depends on the variant ────────────────
    if variant == 'wing':
        # living column + kitchen column side by side
        living_target_gross = 0.31 * (BW * BH)
        pub_w = living_target_gross / max(pub_h, 1.0)
        pub_w = _snap(float(np.clip(pub_w,
                                    ROOM_MIN_W['living'] + 0.5,
                                    BW - (ROOM_MIN_W['kitchen'] + 0.8))))
        kit_w = round(BW - pub_w, 4)

        # V13.1.1f — when there is NO dining, a full-height kitchen may exceed
        # its area cap; shrink the kitchen column FIRST, then the living
        # column takes the rest. This must happen before placing zones so the
        # two columns never overlap.
        if not has_dining and pub_h * kit_w > ROOM_MAX_AREA['kitchen']:
            kit_w = _snap(max(ROOM_MIN_W['kitchen'] + 0.3,
                              ROOM_MAX_AREA['kitchen'] / pub_h))
        living_w = round(BW - kit_w, 4)

        def _kit_dining_column(col_x):
            """Build SERVICE (+DINING) zones for a kitchen column at col_x.
            kit_w is already finalised above."""
            out = {}
            if has_dining:
                kit_h_ideal = 11.0 / max(kit_w, 1.0)
                din_h_ideal = 12.0 / max(kit_w, 1.0)
                s = kit_h_ideal + din_h_ideal
                kh = pub_h * (kit_h_ideal / s)
                kh = min(kh, (ROOM_MAX_AREA['kitchen'] * 0.92) / kit_w)
                kh = max(kh, ROOM_MIN_H['kitchen'] + 0.4)
                kh = min(kh, kit_w * 1.7)
                kh = _snap(kh)
                dh = round(pub_h - kh, 4)
                if dh * kit_w > ROOM_MAX_AREA['dining']:
                    dh = _snap(ROOM_MAX_AREA['dining'] / kit_w)
                    kh = round(pub_h - dh, 4)
                out['SERVICE'] = (col_x, pub_y + dh, kit_w, kh)
                if dh >= ROOM_MIN_H['dining']:
                    out['DINING'] = (col_x, pub_y, kit_w, dh)
                else:
                    out['SERVICE'] = (col_x, pub_y, kit_w, kh + dh)
            else:
                out['SERVICE'] = (col_x, pub_y, kit_w, pub_h)
            return out

        # kitchen RIGHT (at x=living_w), living LEFT (at x=0)
        zones = {
            'PRIVATE':  (0.0, 0.0,   BW,       priv_h),
            'CORRIDOR': (0.0, cor_y, BW,       cor_h),
            'PUBLIC':   (0.0, pub_y, living_w, pub_h),
            'OUTDOOR':  (0.0, BH, living_w, bal_h_protrude) if has_bal else None,
        }
        zones.update(_kit_dining_column(living_w))

    elif variant == 'wing-split':
        # wing-split — V13.1.1g. A genuinely distinct topology: the public
        # band has THREE parts left-to-right:
        #   kitchen (LEFT)  |  living (MIDDLE)  |  study/storage nook (RIGHT)
        # The living is flanked on BOTH sides — a different adjacency graph
        # from 'wing' (where living touches the kitchen on one side only).
        #
        #   ┌────────┬──────────────────┬────────┐
        #   │ Kitchen│      LIVING      │ Study/ │
        #   │        │     (middle)     │ Store  │
        #   └────────┴──────────────────┴────────┘
        kit_w = _snap(float(np.clip(0.24 * BW, ROOM_MIN_W['kitchen'] + 0.6,
                                    0.32 * BW)))
        if pub_h * kit_w > ROOM_MAX_AREA['kitchen']:
            kit_w = _snap(max(ROOM_MIN_W['kitchen'] + 0.5,
                              ROOM_MAX_AREA['kitchen'] / pub_h))
        # right nook — merged into living (no storage room generated)
        nook_w = _snap(float(np.clip(0.20 * BW, 1.5,
                                     0.26 * BW)))
        living_w = round(BW - kit_w - nook_w, 4)
        if living_w < ROOM_MIN_W['living'] + 0.5:
            nook_w   = round(BW - kit_w - (ROOM_MIN_W['living'] + 0.5), 4)
            nook_w   = max(nook_w, 1.0)
            living_w = round(BW - kit_w - nook_w, 4)

        # V13.1.1g — keep the middle living a livable rectangle: its ratio
        # (living_w / pub_h) must stay within ~0.55-1.9. If the living would
        # be too WIDE (long corridor-shaped slab), widen the kitchen and nook
        # to absorb the excess width.
        max_living_w = 1.9 * pub_h
        if living_w > max_living_w:
            excess = living_w - max_living_w
            kit_w  = _snap(kit_w + excess * 0.55)
            nook_w = _snap(nook_w + excess * 0.45)
            # re-cap the kitchen to its area limit
            if pub_h * kit_w > ROOM_MAX_AREA['kitchen']:
                kit_w = _snap(ROOM_MAX_AREA['kitchen'] / pub_h)
            living_w = round(BW - kit_w - nook_w, 4)

        zones = {
            'PRIVATE':  (0.0,             0.0,   BW,       priv_h),
            'CORRIDOR': (0.0,             cor_y, BW,       cor_h),
            'SERVICE':  (0.0,             pub_y, kit_w,    pub_h),     # kitchen left
            'PUBLIC':   (kit_w,           pub_y, living_w, pub_h),     # living middle
            'OUTDOOR':  (kit_w, BH, living_w, bal_h_protrude) if has_bal else None,
        }
        # right nook: a DINING room if requested, else merged into living
        if has_dining and pub_h >= ROOM_MIN_H['dining'] and nook_w >= ROOM_MIN_W['dining']:
            nook_h = _snap(min(pub_h, ROOM_MAX_AREA['dining'] / max(nook_w, 1.0)))
            zones['DINING'] = (kit_w + living_w, pub_y, nook_w, nook_h)
        else:
            # no storage — fold nook into living
            zones['PUBLIC'] = (kit_w, pub_y, round(living_w + nook_w, 4), pub_h)
            if has_bal:
                zones['OUTDOOR'] = (kit_w, BH, round(living_w + nook_w, 4), bal_h_protrude)

    else:   # variant == 'wing-stack'
        # wing-stack — V13.1.1f. Distinct massing: the RIGHT column is a
        # SERVICE STACK — kitchen on top, a small STORAGE / laundry room
        # below it (or a DINING room when has_dining is set). The LIVING is
        # the LEFT block: one clean rectangle, full public height.
        #
        #   ┌───────────────────────┬──────────┐
        #   │                       │ Kitchen  │
        #   │       LIVING          │          │
        #   │    (one rectangle)    ├──────────┤
        #   │                       │ Storage  │  ← Dining if has_dining
        #   └───────────────────────┴──────────┘
        #
        # vs 'wing' (kitchen = ONE full-height column) this is a 2-room
        # service stack — a genuinely different plan, not a mirror.
        svc_w = _snap(float(np.clip(0.26 * BW, ROOM_MIN_W['kitchen'] + 0.8,
                                    BW - ROOM_MIN_W['living'] - 2.0)))
        living_w = round(BW - svc_w, 4)

        if has_dining:
            # kitchen (top) + dining (bottom) split the column.
            # V13.1.1f — with a separate dining room the living must stay under
            # the 36 % share cap, so the service column is WIDENED (budget-
            # driven) until the living block lands at ~33 % of the envelope.
            living_target_gross = 0.33 * (BW * BH)
            living_w = _snap(float(np.clip(living_target_gross / max(pub_h, 1.0),
                                           ROOM_MIN_W['living'] + 0.5,
                                           BW - ROOM_MIN_W['kitchen'] - 1.0)))
            svc_w = round(BW - living_w, 4)
            din_h = _snap(float(np.clip(0.42 * pub_h, ROOM_MIN_H['dining'] + 0.2,
                                        ROOM_MAX_AREA['dining'] / max(svc_w, 1.0))))
            kit_h = round(pub_h - din_h, 4)
            if kit_h * svc_w > ROOM_MAX_AREA['kitchen']:
                kit_h = _snap(ROOM_MAX_AREA['kitchen'] / svc_w)
                din_h = round(pub_h - kit_h, 4)
            zones = {
                'PRIVATE':  (0.0,      0.0,   BW,       priv_h),
                'CORRIDOR': (0.0,      cor_y, BW,       cor_h),
                'PUBLIC':   (0.0,      pub_y, living_w, pub_h),
                'SERVICE':  (living_w, pub_y + din_h, svc_w, kit_h),
                'DINING':   (living_w, pub_y, svc_w, din_h),
                'OUTDOOR':  (0.0, BH, living_w, bal_h_protrude) if has_bal else None,
            }
        else:
            # kitchen fills the FULL service column — no storage below it
            kit_h = pub_h
            if kit_h * svc_w > ROOM_MAX_AREA['kitchen']:
                svc_w = _snap(max(ROOM_MIN_W['kitchen'] + 0.6,
                                  ROOM_MAX_AREA['kitchen'] / kit_h))
                living_w = round(BW - svc_w, 4)
            zones = {
                'PRIVATE':  (0.0,      0.0,   BW,       priv_h),
                'CORRIDOR': (0.0,      cor_y, BW,       cor_h),
                'PUBLIC':   (0.0,      pub_y, living_w, pub_h),
                'SERVICE':  (living_w, pub_y, svc_w, kit_h),
                'OUTDOOR':  (0.0, BH, living_w, bal_h_protrude) if has_bal else None,
            }

    # V13.6 — VERTICAL FLIP for wing-stack so it is VISUALLY DISTINCT from
    # 'wing'. Both share the horizontal-corridor skeleton; without a flip the
    # bedrooms-on-bottom / living-on-top massing looks identical. Flipping puts
    # wing-stack's BEDROOMS ON TOP and LIVING ON BOTTOM. The balcony, which
    # protrudes off the public zone, moves with it (now off the bottom edge).
    if variant == 'wing-stack':
        def _flip_y(z):
            if z is None: return None
            x, y, w, h = z
            return (x, round(BH - (y + h), 4), w, h)
        flipped = {}
        for k, v in zones.items():
            if isinstance(v, tuple) and len(v) == 4:
                flipped[k] = _flip_y(v)
            else:
                flipped[k] = v
        # NOTE: _flip_y already moves OUTDOOR with the public zone. Originally
        # the balcony sat at y=BH (just above the top); after the vertical flip
        # the public zone is at the BOTTOM, so _flip_y maps the balcony to
        # y = BH-(BH+bal)= -bal — i.e. just BELOW the bottom edge, still glued
        # to the living. The downstream normalisation shifts everything back to
        # min_y=0, keeping the balcony adjacent to the living. No override.
        zones = flipped

    zones = _apply_envelope_notches(zones, variant, BW, BH, priv_h, cor_h, pub_h, hint)
    return zones, priv_h, cor_h, pub_h


def _vsplit_zones(BW, BH, has_bal, has_dining, has_master_bath,
                   bal_h_protrude, rng):
    """V13.2.2 — VERTICAL-SPLIT topology: a genuinely DIFFERENT layout family.

    Instead of the wing family's horizontal spine, the apartment is split by a
    VERTICAL corridor into two wings:

       ┌──────────────┬───┬──────────────┐
       │              │ C │   NIGHT WING │
       │   DAY WING   │ O │  ┌────┬────┐  │
       │  (living +   │ R │  │bed │bed │  │   ← bedrooms stacked vertically
       │   kitchen)   │ R │  ├────┼────┤  │
       │              │ I │  │bath│bath│  │   ← baths below
       │              │ D │  └────┴────┘  │
       └──────────────┴───┴──────────────┘
            day_w       cw      night_w

    Circulation: a SHORTER vertical corridor (height ≈ BH, width 1.1m) that is
    far more efficient than the full-width horizontal spine — it only spans the
    apartment depth once, serving both wings from its two long walls. This pulls
    corridor share down toward ~6-7% from the horizontal spine's ~9%.

    Returns the same zones-dict contract as _wing_family_zones, plus a
    `_vsplit` marker so stage6 routes the private wing to the vertical subdivider.
    """
    # corridor: vertical spine PLUS a short horizontal stub at the bottom that
    # reaches into the night wing so BOTH baths get their own corridor edge.
    # V13.2.5 — the new geometry allows night_w to be WIDE (~5m) so baths fit
    # SIDE-BY-SIDE with acceptable ratio AND each touches the corridor stub.
    cor_w = _snap(max(1.10, ROOM_MIN_W['corridor']))
    # night wing: wider so baths are side-by-side (each ~1.7m wide × ~2m tall
    # = ratio 0.85, area 3.4 → ~4.5 after rescale). Living share stays under
    # 50% because day_w shrinks to ~5.5m.
    night_w = _snap(np.clip(BW * 0.45 + rng.uniform(-0.10, 0.10),
                            4.40, 5.20))
    night_w = min(night_w, BW - cor_w - ROOM_MIN_W['living'] - 0.5)
    day_w   = round(BW - cor_w - night_w, 4)

    cor_x   = round(day_w, 4)
    night_x = round(day_w + cor_w, 4)

    # Sub-corridor STUB at the bottom of the night wing — a short horizontal
    # strip that splits the bath row from the bedroom row above, so each bath
    # gets its own corridor edge instead of relying on neighbouring bath.
    stub_h = 1.10
    # baths band: a short row at the very bottom
    bath_band_h_design = 2.20   # design depth; rescale will adjust
    zones = {
        # DAY WING (left): public stack — living + kitchen
        'PUBLIC':   (0.0, 0.0, day_w, BH),
        # vertical corridor spine
        'CORRIDOR': (cor_x, 0.0, cor_w, BH),
        # NIGHT WING (right): bedrooms + (sub-corridor stub) + baths
        'PRIVATE':  (night_x, 0.0, night_w, BH),
        # balcony protrudes over the DAY wing (living), as elsewhere
        'OUTDOOR':  (0.0, BH, day_w, bal_h_protrude) if has_bal else None,
        '_vsplit':  True,
        '_vsplit_night_w':    night_w,
        '_vsplit_stub_h':     stub_h,
        '_vsplit_bath_band_h': bath_band_h_design,
    }

    # V13.5 — kitchen at the BOTTOM of the day wing, living at the TOP.
    # Scale-aware geometry: day_w ≤ 7.0m → full-width strip (kitchen ratio
    # stays sane after rescale); day_w > 7.0m → side COLUMN on the left
    # (tall + narrow, much better ratio for large apartments where BW grows).
    if not has_dining:
        if day_w <= 7.0:
            kit_h = _snap(np.clip(ROOM_MAX_AREA['kitchen'] / max(day_w, 1.0),
                                  ROOM_MIN_H['kitchen'] + 0.5,
                                  BH * 0.35))
            kit_h = min(kit_h, BH - ROOM_MIN_H['living'])
            zones['SERVICE'] = (0.0, 0.0, day_w, kit_h)                       # kitchen BOTTOM
            zones['PUBLIC']  = (0.0, kit_h, day_w, round(BH - kit_h, 4))      # living TOP
        else:
            kit_w = _snap(max(ROOM_MIN_W['kitchen'] + 0.3,
                              min(day_w - ROOM_MIN_W['living'],
                                  ROOM_MAX_AREA['kitchen'] / max(BH, 1.0))))
            # side-column kitchen on the LEFT (away from corridor) so living
            # spans the right side of the day wing AND the top — touching the
            # balcony directly.
            zones['SERVICE'] = (0.0, 0.0, kit_w, BH)
            zones['PUBLIC']  = (kit_w, 0.0, round(day_w - kit_w, 4), BH)
    else:
        kit_h = _snap(np.clip(ROOM_MAX_AREA['kitchen'] / max(day_w, 1.0),
                              ROOM_MIN_H['kitchen'] + 0.3,
                              BH * 0.30))
        din_h = _snap(min(ROOM_MAX_AREA['dining'] / max(day_w, 1.0),
                          (BH - kit_h - ROOM_MIN_H['living']) * 0.6))
        zones['SERVICE'] = (0.0, 0.0, day_w, kit_h)                       # kitchen BOTTOM
        if din_h >= ROOM_MIN_H['dining']:
            zones['DINING'] = (0.0, kit_h, day_w, din_h)                  # dining above kitchen
            zones['PUBLIC'] = (0.0, round(kit_h + din_h, 4),
                               day_w, round(BH - kit_h - din_h, 4))
        else:
            zones['PUBLIC'] = (0.0, kit_h, day_w, round(BH - kit_h, 4))

    return zones, BH, cor_w, BH


def _subdivide_private_vsplit(zone, n_bed, n_bath, rng, has_master_bath=False,
                              bath_layout=None, target_area=None, has_dressing=False):
    """V16.7 — NIGHT WING subdivision for vertical-split with DYNAMIC ENSUITE SUPPORT.
    When has_master_bath=True or bath_layout in ('ensuite_living', 'ensuite_bedroom'):
    carves the Master Ensuite directly out of the Master Bedroom so they share a wall
    and open into each other, while routing guest baths according to the strategy!
    """
    if bath_layout is None:
        bath_layout = 'ensuite_living' if has_master_bath else 'corridor_both'

    x0, y0, w, h = zone
    n_bed_u  = max(n_bed, 1)
    n_bath_u = max(n_bath, 1)
    rooms = []
    STUB_H = 1.10

    if bath_layout in ('ensuite_living', 'ensuite_bedroom'):
        if bath_layout == 'ensuite_living':
            n_baths_below = 0
            leftover_bath = max(0, n_bath_u - 1)
        else: # ensuite_bedroom
            n_baths_below = min(1, max(0, n_bath_u - 1))
            leftover_bath = max(0, n_bath_u - 1 - n_baths_below)

        if n_baths_below > 0:
            BATH_BAND_H = _snap(np.clip(max(2.20, (ROOM_MIN_AREA['bathroom'] + 0.25) / max(w, 0.1)), 2.20, h - 3.20), GRID_FINE)
            rooms.append(Room('bathroom', x0, y0, w, BATH_BAND_H, 'PRIVATE', tag='guest_bath'))
            stub_y0 = round(y0 + BATH_BAND_H, 4)
        else:
            BATH_BAND_H = 0.0
            stub_y0 = y0

        rooms.append(Room('corridor', x0, stub_y0, w, STUB_H, 'PRIVATE', tag='stub'))
        bed_y0      = round(stub_y0 + STUB_H, 4)
        bed_h_total = round(h - BATH_BAND_H - STUB_H, 4)

        if n_bed_u >= 2:
            msplit = float(rng.uniform(0.54, 0.60))
            master_h = _snap(max(ROOM_MIN_H['bedroom'], bed_h_total * msplit), GRID_FINE)
            min_sec_h = max(2.70, 10.5 / max(w, 0.1)) * (n_bed_u - 1)
            master_h = min(master_h, bed_h_total - min_sec_h)
            master_h = max(master_h, ROOM_MIN_H['bedroom'])
        else:
            master_h = bed_h_total

        bath_w_tgt = np.clip(3.8 / max(master_h, 0.1), 1.80, 2.60)
        bath_w_safe = _snap(min(w * 0.42, bath_w_tgt), GRID_FINE)
        master_bed_w = round(w - bath_w_safe, 4)

        rooms.append(Room('bedroom', x0, bed_y0, master_bed_w, master_h, 'PRIVATE', tag='master'))
        rooms.append(Room('bathroom', round(x0 + master_bed_w, 4), bed_y0, bath_w_safe, master_h, 'PRIVATE', tag='ensuite'))

        if n_bed_u >= 2:
            sec_y0 = round(bed_y0 + master_h, 4)
            sec_h_total = round(bed_h_total - master_h, 4)
            if sec_h_total < 2.65 * (n_bed_u - 1) and w >= 4.8 and (n_bed_u - 1) >= 2:
                rooms += _hstack(x0, sec_y0, w, sec_h_total, ['bedroom']*(n_bed_u-1), 'PRIVATE')
            else:
                rooms += _vstack(x0, sec_y0, w, sec_h_total, ['bedroom']*(n_bed_u-1), 'PRIVATE')

        return rooms, leftover_bath

    # ── bath_layout == 'corridor_both' (or default legacy) ──
    BATH_BAND_H = _snap(np.clip(max(2.20, (ROOM_MIN_AREA['bathroom'] + 0.25) * max(n_bath_u, 1) / max(w, 0.1)), 2.20, h - 2.80), GRID_FINE)
    max_fit_baths = max(1, int(round(w, 4) // ROOM_MIN_W['bathroom']))
    n_baths_here = min(n_bath_u, max_fit_baths, 3)
    leftover_bath = max(0, n_bath_u - n_baths_here)
    if n_baths_here == 3:
        w1 = _snap(w / 3.0, GRID_FINE)
        w2 = _snap((w - w1) / 2.0, GRID_FINE)
        w3 = round(w - w1 - w2, 4)
        rooms.append(Room('bathroom', x0, y0, w1, BATH_BAND_H, 'PRIVATE', tag='master_bath'))
        rooms.append(Room('bathroom', round(x0 + w1, 4), y0, w2, BATH_BAND_H, 'PRIVATE', tag='guest_bath_1'))
        rooms.append(Room('bathroom', round(x0 + w1 + w2, 4), y0, w3, BATH_BAND_H, 'PRIVATE', tag='guest_bath_2'))
        stub_y0 = round(y0 + BATH_BAND_H, 4)
    elif n_baths_here == 2:
        w1 = _snap(w * 0.52, GRID_FINE)
        w2 = round(w - w1, 4)
        rooms.append(Room('bathroom', x0, y0, w1, BATH_BAND_H, 'PRIVATE', tag='master_bath'))
        rooms.append(Room('bathroom', round(x0 + w1, 4), y0, w2, BATH_BAND_H, 'PRIVATE', tag='guest_bath'))
        stub_y0 = round(y0 + BATH_BAND_H, 4)
    else:
        rooms.append(Room('bathroom', x0, y0, w, BATH_BAND_H, 'PRIVATE'))
        stub_y0 = round(y0 + BATH_BAND_H, 4)

    rooms.append(Room('corridor', x0, stub_y0, w, STUB_H, 'PRIVATE', tag='stub'))
    bed_y0      = round(stub_y0 + STUB_H, 4)
    bed_h_total = round(h - BATH_BAND_H - STUB_H, 4)

    if n_bed_u >= 2:
        msplit = float(rng.uniform(0.54, 0.60))
        master_h = _snap(max(ROOM_MIN_H['bedroom'], bed_h_total * msplit), GRID_FINE)
        min_sec_h = max(2.70, 10.5 / max(w, 0.1)) * (n_bed_u - 1)
        master_h = min(master_h, bed_h_total - min_sec_h)
        master_h = max(master_h, ROOM_MIN_H['bedroom'])
        rooms.append(Room('bedroom', x0, bed_y0, w, master_h, 'PRIVATE', tag='master'))
        sec_y0 = round(bed_y0 + master_h, 4)
        sec_h_total = round(bed_h_total - master_h, 4)
        if sec_h_total < 2.65 * (n_bed_u - 1) and w >= 4.8 and (n_bed_u - 1) >= 2:
            rooms += _hstack(x0, sec_y0, w, sec_h_total, ['bedroom']*(n_bed_u-1), 'PRIVATE')
        else:
            rooms += _vstack(x0, sec_y0, w, sec_h_total, ['bedroom']*(n_bed_u-1), 'PRIVATE')
    else:
        rooms.append(Room('bedroom', x0, bed_y0, w, bed_h_total, 'PRIVATE', tag='master'))

    return rooms, leftover_bath


def _ccore_zones(BW, BH, has_bal, has_dining, has_master_bath,
                 bal_h_protrude, rng, n_bed=2):
    """V13.8 — CORNER-CORE topology: a third, fundamentally different family.

    Unlike the wing family (horizontal spine + bedroom row) and vsplit
    (vertical spine + day/night wings), this puts a CENTRAL SERVICE CORE
    (the two baths, stacked) in the middle-bottom, flanked by two bedrooms,
    with the LIVING spanning the FULL WIDTH across the top and the KITCHEN
    tucked into a bottom corner. Circulation is an L: a horizontal strip
    under the living that feeds both bedrooms and the core.

        ┌───────────────────────────────────┐
        │              LIVING               │  full-width, balcony on top
        ├───────────────────────────────────┤
        │ ───────  L-CORRIDOR  ───────────── │  horizontal feeder
        ├──────────┬───────────┬────────────┤
        │          │   bath    │            │
        │ bedroom  ├───────────┤  bedroom   │  bedrooms flank the core
        │          │   bath    │            │
        │          ├───────────┤            │
        │          │  kitchen  │            │
        └──────────┴───────────┴────────────┘

    This is a self-contained zone set: it returns explicit LIVING / CORRIDOR
    plus the private + service zones, with a `_ccore` marker so stage6 routes
    the central column to the dedicated subdivider.
    """
    bal_hp = _snap(BALCONY_PROTRUDE) if has_bal else 0.0

    # V13.8b — LIVING occupies the top-LEFT (not full width); the KITCHEN takes
    # the top-RIGHT corner on the same band. This keeps the living's share under
    # the cap AND its ratio livable, while the bottom band holds the two
    # bedrooms flanking the central bath core.
    #
    #   ┌────────────────────────┬───────────┐
    #   │         LIVING         │  KITCHEN  │   top band
    #   ├────────────────────────┴───────────┤
    #   │ ─────────  CORRIDOR  ───────────── │
    #   ├──────────┬─────────────┬───────────┤
    #   │ bedroom  │ bath | bath │  bedroom  │   bottom band
    #   └──────────┴─────────────┴───────────┘
    top_h = _snap(float(np.clip(BH * (0.52 + rng.uniform(-0.04, 0.04)),
                                ROOM_MIN_H['living'],
                                BH - ROOM_MIN_H['bedroom'] - 1.2)))
    cor_h = 1.10
    lower_h = round(BH - top_h - cor_h, 4)
    # CAP lower band at 3.3m so a full-height core bath stays <= ~7 m2
    if lower_h > 3.30:
        lower_h = 3.30
        top_h = round(BH - lower_h - cor_h, 4)
    if lower_h < ROOM_MIN_H['bedroom'] + 0.3:
        lower_h = round(ROOM_MIN_H['bedroom'] + 0.5, 4)
        top_h = round(BH - lower_h - cor_h, 4)

    # kitchen width in the top-right (sized ~12-13 m² at top_h height), jittered
    kit_w = _snap(float(np.clip(ROOM_MAX_AREA['kitchen'] / max(top_h, 1.0)
                                + rng.uniform(-0.3, 0.3),
                                ROOM_MIN_W['kitchen'] + 0.3, BW * 0.34)))
    liv_w = round(BW - kit_w, 4)

    # central bath core in the bottom band, jittered width
    # V15.10-FIX — core_w was a fixed FRACTION of BW with no cap, while the
    # core's height is capped at a fixed 3.30m (just below). On a large
    # building (exactly what the XL area band uses) this guarantees an
    # over-area master bath: core_w grows with BW, height doesn't, so the
    # bath area (mw * lower_h, mw up to 64% of core_w) keeps growing too —
    # this was THE reason corner-core failed 0/10 at net=170 (confirmed via
    # direct inspection: master bath landing at 8.3-9.3m², all over the
    # 8.0m² hard limit). Cap core_w so the bath stays legal regardless of
    # how wide the building is, instead of just scaling up with it.
    _lower_h_for_core = min(3.30, BH)   # same cap _ccore_zones applies below
    _core_w_area_cap = ROOM_MAX_AREA['bathroom'] / (0.64 * max(_lower_h_for_core, 1.0))
    core_w = _snap(float(np.clip(BW * (0.24 + rng.uniform(-0.02, 0.02)),
                                 2 * ROOM_MIN_W['bathroom'],
                                 min(min(BW * 0.28, 4.20), _core_w_area_cap))))
    n_bed_u = max(n_bed, 1)
    n_left = (n_bed_u + 1) // 2
    n_right = max(1, n_bed_u - n_left)
    left_share = n_left / n_bed_u
    left_w = _snap((BW - core_w) * float(np.clip(left_share, 0.28, 0.72)), GRID_FINE)
    left_w = max((ROOM_MIN_W['bedroom'] + 0.4) * n_left, left_w)
    right_w = round(BW - core_w - left_w, 4)
    if right_w < (ROOM_MIN_W['bedroom'] + 0.4) * n_right:
        right_w = _snap((ROOM_MIN_W['bedroom'] + 0.4) * n_right, GRID_FINE)
        left_w = round(BW - core_w - right_w, 4)
    core_x = round(left_w, 4)
    side_w = round(min(left_w, right_w), 4)

    zones = {
        'PUBLIC':   (0.0, round(BH - top_h, 4), liv_w, top_h),     # living top-left
        'SERVICE':  (liv_w, round(BH - top_h, 4), kit_w, top_h),   # kitchen top-right
        'CORRIDOR': (0.0, lower_h, BW, cor_h),                     # full-width feeder
        'PRIVATE':  (0.0, 0.0, BW, lower_h),                       # bottom band
        'OUTDOOR':  (0.0, BH, liv_w, bal_hp) if has_bal else None, # balcony over living
        '_ccore':   True,
        '_ccore_core_x': core_x,
        '_ccore_core_w': core_w,
        '_ccore_side_w': side_w,
        '_ccore_left_w': left_w,
        '_ccore_right_w': right_w,
        '_ccore_lower_h': lower_h,
        '_ccore_has_dining': bool(has_dining),
        '_ccore_kitchen_in_core': False,   # kitchen is in the top band now
    }
    return zones, lower_h, cor_h, top_h


def _subdivide_ccore_lower(zone, n_bed, n_bath, core_x, core_w, side_w,
                            has_dining, rng, left_w=None, right_w=None,
                            has_master_bath=False, bath_layout=None, target_area=None, has_dressing=False):
    """V16.7 — bottom band of corner-core with DYNAMIC ENSUITE SUPPORT.
    When has_master_bath=True, ensures the Master Bedroom is on the left touching the central
    bath core, and places the Master Ensuite on the left side of the core so they share a wall!
    """
    if bath_layout is None:
        bath_layout = 'ensuite_living' if has_master_bath else 'corridor_both'

    x0, y0, w, h = zone
    rooms = []
    n_bath_u = max(n_bath, 1)
    n_bed_u = max(n_bed, 1)

    core_shift = float(rng.uniform(-0.8, 0.8))
    core_x = round(max(ROOM_MIN_W['bedroom'],
                       min(core_x + core_shift,
                           w - core_w - ROOM_MIN_W['bedroom'])), 4)
    if left_w is None: left_w = round(core_x, 4)
    right_x = round(core_x + core_w, 4)
    if right_w is None: right_w = round(w - right_x, 4)

    n_left = (n_bed_u + 1) // 2
    n_right = max(1, n_bed_u - n_left)

    left_is_master = True if bath_layout in ('ensuite_living', 'ensuite_bedroom') else (left_w >= right_w)

    if n_left == 1:
        rooms.append(Room('bedroom', 0.0, y0, left_w, h, 'PRIVATE', tag='master' if left_is_master else None))
    else:
        rooms += _hstack(0.0, y0, left_w, h, ['bedroom']*n_left, 'PRIVATE', rng=rng)
        if not left_is_master and rooms and rooms[0].name == 'bedroom': rooms[0].tag = 'master'
        elif left_is_master and rooms and rooms[-1].name == 'bedroom': rooms[-1].tag = 'master'

    max_fit_baths = max(1, int(round(core_w, 4) // ROOM_MIN_W['bathroom']))
    n_baths_here = min(n_bath_u, max_fit_baths, 3)

    if bath_layout == 'ensuite_living':
        rooms.append(Room('bathroom', core_x, y0, core_w, h, 'PRIVATE', tag='ensuite'))
        leftover_bath = max(0, n_bath_u - 1)
    elif bath_layout == 'ensuite_bedroom' and n_baths_here >= 2:
        frac = float(np.clip(0.56 + rng.uniform(0.0, 0.06), 0.54, 0.64))
        mw = _snap(max(ROOM_MIN_W['bathroom'], core_w * frac), GRID_FINE)
        gw = round(core_w - mw, 4)
        if gw < ROOM_MIN_W['bathroom']:
            gw = ROOM_MIN_W['bathroom']; mw = round(core_w - gw, 4)
        rooms.append(Room('bathroom', core_x, y0, mw, h, 'PRIVATE', tag='ensuite'))
        rooms.append(Room('bathroom', round(core_x + mw, 4), y0, gw, h, 'PRIVATE', tag='guest_bath'))
        leftover_bath = max(0, n_bath_u - 2)
    else:
        leftover_bath = max(0, n_bath_u - n_baths_here)
        if n_baths_here == 3:
            w1 = _snap(max(ROOM_MIN_W['bathroom'], core_w * 0.40), GRID_FINE)
            w2 = _snap(max(ROOM_MIN_W['bathroom'], (core_w - w1) * 0.50), GRID_FINE)
            w3 = round(core_w - w1 - w2, 4)
            if w3 < ROOM_MIN_W['bathroom']:
                w3 = ROOM_MIN_W['bathroom']
                w2 = round((core_w - w1 - w3), 4)
            rooms.append(Room('bathroom', core_x, y0, w1, h, 'PRIVATE', tag='master_bath'))
            rooms.append(Room('bathroom', round(core_x + w1, 4), y0, w2, h, 'PRIVATE', tag='guest_bath_1'))
            rooms.append(Room('bathroom', round(core_x + w1 + w2, 4), y0, w3, h, 'PRIVATE', tag='guest_bath_2'))
        elif n_baths_here == 2:
            frac = float(np.clip(0.56 + rng.uniform(0.0, 0.06), 0.54, 0.64))
            mw = _snap(max(ROOM_MIN_W['bathroom'], core_w * frac), GRID_FINE)
            gw = round(core_w - mw, 4)
            if gw < ROOM_MIN_W['bathroom']:
                gw = ROOM_MIN_W['bathroom']; mw = round(core_w - gw, 4)
            rooms.append(Room('bathroom', core_x, y0, mw, h, 'PRIVATE', tag='master_bath'))
            rooms.append(Room('bathroom', round(core_x + mw, 4), y0, gw, h, 'PRIVATE', tag='guest_bath'))
        else:
            rooms.append(Room('bathroom', core_x, y0, core_w, h, 'PRIVATE', tag='master_bath' if has_master_bath else None))

    if n_right == 1:
        rooms.append(Room('bedroom', right_x, y0, right_w, h, 'PRIVATE', tag=None if left_is_master else 'master'))
    else:
        rooms += _hstack(right_x, y0, right_w, h, ['bedroom']*n_right, 'PRIVATE', rng=rng)

    return rooms, leftover_bath


def stage2_zones_v11(BW, BH, n_bed, n_bath, n_kit, has_bal,
                      template, rng, hint=None,
                      has_dining=False, has_master_bath=False,
                      target_area=None):
    """V11 zoning. KEY CHANGES vs V10:
      • V11-FIX-#1   : balcony is NO LONGER inside BW×BH — it protrudes (L-shape).
      • V11-FIX-#2,13: balcony zone sits over the living-room only (never over kitchen).
      • V11-FIX-#6   : corridor strip kept full-height so kitchen can also attach to it.

    Returns a dict of zones. OUTDOOR (balcony) carries a `protrude=True` flag
    telling stage6 to place the balcony OUTSIDE the BW×BH rectangle.
    """
    if hint is None or hint.get('fallback', True):
        pwf = 0.42 + CORRIDOR_W / max(BW, 1.0)
        khf = 0.30
    else:
        pwf = hint['priv_w_frac']
        khf = hint['kit_h_frac']

    # All templates: balcony is a PROTRUSION over PUBLIC (living) — never tacked into the corner.
    bal_h_protrude = _snap(BALCONY_PROTRUDE) if has_bal else 0.0

    # ── WING-FAMILY / VSPLIT / CORNER-CORE dispatch ──
    if template not in TEMPLATES:
        raise ValueError(f'Unknown template: {template}')
    if template == 'vsplit':
        zones, priv_h, cor_h, pub_h = _vsplit_zones(
            BW, BH, has_bal, has_dining, has_master_bath, bal_h_protrude, rng)
    elif template == 'corner-core':
        zones, priv_h, cor_h, pub_h = _ccore_zones(
            BW, BH, has_bal, has_dining, has_master_bath, bal_h_protrude, rng, n_bed=n_bed)
    else:
        zones, priv_h, cor_h, pub_h = _wing_family_zones(
            BW, BH, template, has_bal, has_dining, has_master_bath,
            bal_h_protrude, rng, target_area, hint=hint)
    if has_bal:
        zones['_protrude_outdoor'] = True

    return {k: v for k, v in zones.items()
            if k in ('_protrude_outdoor', '_vsplit', '_physically_impossible_notch',
                     '_vsplit_night_w', '_vsplit_stub_h', '_vsplit_bath_band_h',
                     '_ccore', '_ccore_core_x', '_ccore_core_w',
                     '_ccore_side_w', '_ccore_lower_h', '_ccore_has_dining') or
               (v is not None and not isinstance(v, (int, float, bool))
                and v[2] > 0.3 and v[3] > 0.3)}


# ── helpers (BSP) ──────────────────────────────────────────
def _vstack(x0, y0, w, total_h, names, zone=''):
    n = len(names)
    if n == 0: return []
    if n == 1: return [Room(names[0], x0, y0, w, total_h, zone)]
    slice_h = _snap(total_h / n); rooms, cy = [], y0
    for k, name in enumerate(names):
        h = slice_h if k < n-1 else round(y0 + total_h - cy, 4)
        rooms.append(Room(name, x0, cy, w, max(h, 0.5), zone))
        cy = round(cy + h, 4)
    return rooms

def _hstack(x0, y0, total_w, h, names, zone='', rng=None):
    """Place `names` rooms left-to-right across total_w.

    V13.1.1f — when an RNG is supplied, the partition is JITTERED so equal-name
    rooms (e.g. two children's bedrooms) are NOT identical clones. Each room
    gets a weight in [0.82, 1.18]; widths are proportional to the weights and
    then floor-clamped to ROOM_MIN_W. Without an RNG the split is exactly equal
    (back-compatible).
    """
    n = len(names)
    if n == 0: return []
    if n == 1: return [Room(names[0], x0, y0, total_w, h, zone)]

    if rng is not None:
        weights = np.array([rng.uniform(0.82, 1.18) for _ in range(n)])
        weights = weights / weights.sum()
        # V13.1.2-PATCH-1b: snap to GRID_FINE (0.10m), not GRID (0.50m).
        # With GRID=0.50 the [0.82, 1.18] jitter collapsed to 2-3 discrete
        # widths and produced "clone" bedrooms. GRID_FINE preserves variation.
        widths  = [_snap(total_w * w, GRID_FINE) for w in weights]
        # fix rounding drift on the last room
        widths[-1] = round(total_w - sum(widths[:-1]), 4)
        # floor-clamp: if any room fell below its min width, fall back to equal
        min_w = ROOM_MIN_W.get(names[0], 1.0)
        if any(w < min_w for w in widths):
            widths = None
    else:
        widths = None

    rooms, cx = [], x0
    if widths is None:
        slice_w = _snap(total_w / n)
        for k, name in enumerate(names):
            w = slice_w if k < n-1 else round(x0 + total_w - cx, 4)
            rooms.append(Room(name, cx, y0, max(w, 0.5), h, zone))
            cx = round(cx + w, 4)
    else:
        for k, name in enumerate(names):
            w = widths[k]
            rooms.append(Room(name, cx, y0, max(w, 0.5), h, zone))
            cx = round(cx + w, 4)
    return rooms


def _subdivide_private_wing(zone, n_bed, n_bath, rng, has_master_bath=False,
                            bath_layout=None, target_area=None, has_dressing=False):
    """V15.6 — area-FIRST private-wing subdivision. Master/secondary bedroom
    widths are solved from AREA_TARGET (tier-aware: a 70m² flat sits near
    the low end of each range, a 180m² flat near the high end), not from an
    arbitrary fraction of the row width — and any leftover/surplus width
    always goes to the master suite, so it can never end up smaller than a
    secondary bedroom by construction (on top of the hard hierarchy gate in
    _v12_livability_gate, which is the safety net if it ever still happens).

    bath_layout (3 selectable, realistic strategies):
      'corridor_both'   — classic: every bathroom is its OWN column off the
                          corridor, full height, no closet needed (this
                          mode's private-row height is capped <=3.4m by the
                          zone builder specifically so a full-height bath
                          stays within the area/ratio limits on its own).
                          Bedrooms always sit BETWEEN the two bathrooms, so
                          they never share a wall with each other.
      'ensuite_living'  — one bathroom lives INSIDE the master suite; any
                          extra bathroom is carved from the LIVING room
                          instead (see the 'PUBLIC' branch of
                          stage6_subdivide_v11).
      'ensuite_bedroom' — one bathroom lives INSIDE the master suite, the
                          extra bathroom lives INSIDE a SECOND bedroom
                          instead of living (only if that bedroom is wide
                          enough to host it without overlapping its
                          neighbour — otherwise this sample quietly falls
                          back to routing the 2nd bath to living, same as
                          'ensuite_living', rather than ever overlapping).

    `has_master_bath` (legacy bool) is used only when `bath_layout` is not
    given: True -> 'ensuite_living', False -> 'corridor_both'.

    Returns (rooms, leftover_bath) — leftover_bath is bathrooms still
    needed elsewhere (routed to living by stage6 when applicable).
    """
    if bath_layout is None:
        bath_layout = 'ensuite_living' if has_master_bath else 'corridor_both'

    x0, y0, w, h = zone
    n_bed_u  = max(n_bed,  1)
    n_bath_u = max(n_bath, 1)
    n_bed_u = max(n_bed, 1)
    net      = target_area if target_area else w * h * 2.2  # crude fallback
    rooms = []

    if bath_layout in ('ensuite_living', 'ensuite_bedroom'):
        bath_band_h = _snap(np.clip(2.00, ROOM_MIN_H['bathroom'],
                                    max(h - ROOM_MIN_H['bedroom'], ROOM_MIN_H['bathroom'])),
                            GRID_FINE)

        if n_bed_u >= 2:
            # Proportional width allocation between master suite and secondary bedrooms
            master_tgt = _tier_target('master_bedroom', net)
            sec_tgt    = _tier_target('bedroom', net) * (n_bed_u - 1)
            total_tgt  = max(master_tgt + sec_tgt, 1.0)
            
            master_share = float(np.clip(master_tgt / total_tgt, 0.28, 0.62))
            master_w = _snap(w * master_share, GRID_FINE)
            
            h_for_sec = h - bath_band_h if bath_layout == 'ensuite_bedroom' else h
            sec_w_floor = max(ROOM_MIN_W['bedroom'], 10.5 / max(h_for_sec, 0.1)) * (n_bed_u - 1)
            master_w = max(master_w, ROOM_MIN_W['bedroom'] + 0.6)
            master_w = min(master_w, w - sec_w_floor)
            master_w = min(_snap(master_w, GRID_FINE), w - sec_w_floor)
            
            sec_total_w = round(w - master_w, 4)
            sec_rooms = _hstack(x0, y0, sec_total_w, h, ['bedroom']*(n_bed_u-1),
                                'PRIVATE', rng=rng)
            master_x = x0 + sec_total_w
            
            # Realistic ensuite bath width + Walk-In Dressing Room
            bath_w_tgt = np.clip(_tier_target('ensuite', net) / max(bath_band_h, 0.1), 2.20, 3.00)
            bath_w_safe = _snap(min(master_w, bath_w_tgt), GRID_FINE)
            dressing_w  = round(master_w - bath_w_safe, 4)
        else:
            master_w = w
            master_x = x0
            sec_rooms = []
            ensuite_tgt = _tier_target('ensuite', net)
            bath_band_h = _snap(np.clip(ensuite_tgt / max(w, 1.0),
                                        ROOM_MIN_H['bathroom'],
                                        h - ROOM_MIN_H['bedroom']), GRID_FINE)
            bath_band_h = max(bath_band_h, ROOM_MIN_H['bathroom'])
            bath_w_tgt = np.clip(_tier_target('ensuite', net) / max(bath_band_h, 0.1), 2.20, 3.00)
            bath_w_safe = _snap(min(master_w, bath_w_tgt), GRID_FINE)
            dressing_w  = round(master_w - bath_w_safe, 4)

        rooms.append(Room('bedroom', master_x, y0 + bath_band_h,
                          master_w, h - bath_band_h, 'PRIVATE', tag='master'))
        rooms.append(Room('bathroom', master_x, y0, bath_w_safe, bath_band_h,
                          'PRIVATE', tag='ensuite'))
        if has_dressing and dressing_w >= 1.10:
            rooms.append(Room('storage', round(master_x + bath_w_safe, 4), y0,
                              dressing_w, bath_band_h, 'PRIVATE', tag='dressing'))
        elif dressing_w > 0:
            rooms[-1].w = round(bath_w_safe + dressing_w, 4)

        leftover_bath = max(n_bath_u - 1, 0)

        carved_second = False
        if bath_layout == 'ensuite_bedroom' and leftover_bath > 0 and sec_rooms:
            bed2 = sec_rooms[0]
            # Only carve a band into bed2 if it's wide enough to still meet
            # the bedroom area minimum afterwards — otherwise widening it
            # would overlap its neighbour, and shrinking it would just
            # create an illegal bedroom. If it doesn't fit, skip carving
            # this sample and fall through to leftover_bath staying 1 (the
            # PUBLIC/living branch in stage6 will route it to living
            # instead — a safe, no-overlap fallback rather than ever
            # drawing an overlapping room).
            bed2_w_lo = max(ROOM_MIN_W['bathroom'],
                            ROOM_MIN_AREA['bedroom'] / max(bed2.h - bath_band_h, 0.1))
            if bed2.w >= bed2_w_lo and bath_band_h < bed2.h:
                rooms += sec_rooms[1:]
                rooms.append(Room('bedroom', bed2.x0, bed2.y0 + bath_band_h,
                                  bed2.w, bed2.h - bath_band_h, 'PRIVATE'))
                rooms.append(Room('bathroom', bed2.x0, bed2.y0, bed2.w,
                                  bath_band_h, 'PRIVATE', tag='guest_bath'))
                leftover_bath = max(leftover_bath - 1, 0)
                carved_second = True

        if not carved_second:
            rooms += sec_rooms

        return rooms, leftover_bath

    # ── bath_layout == 'corridor_both' ──────────────────────────────────
    # Classic layout: each bathroom is its own FULL-HEIGHT column at an END
    # of the row, bedrooms fill the middle. No band, no closet — this
    # mode's private-row height is capped at 3.40m by the zone builder
    # specifically so a full-height bath fits its area/ratio limits on its
    # own (see _wing_family_zones). Bedrooms always sit BETWEEN the two
    # bathrooms, so they never share a wall with each other.
    n_baths_here = min(n_bath_u, 2)
    guest_tgt = _tier_target('guest_bath', net)
    bath_w = _snap(np.clip(guest_tgt / max(h, 1.0),
                           ROOM_MIN_W['bathroom'],
                           ROOM_MAX_AREA['bathroom'] / max(h, 1.0)), GRID_FINE)

    bath_slots = []
    cursor = x0
    if n_baths_here >= 1:
        bath_slots.append(cursor); cursor = round(cursor + bath_w, 4)
    bed_zone_x = cursor
    bed_zone_w = round(w - bath_w * n_baths_here, 4)
    if n_baths_here >= 2:
        bath_slots.append(round(x0 + w - bath_w, 4))

    rooms += _hstack(bed_zone_x, y0, bed_zone_w, h, ['bedroom']*n_bed_u,
                     'PRIVATE', rng=rng)

    for bx in bath_slots:
        rooms.append(Room('bathroom', bx, y0, bath_w, h,
                          'PRIVATE', tag='guest_bath'))

    leftover_bath = max(n_bath_u - n_baths_here, 0)
    return rooms, leftover_bath


def _subdivide_private_v11(zone, n_bed, n_bath, template, rng):
    """V11 PRIVATE subdivision (rev-3, vertical-stack with corridor-reachability guarantee).

    Layout (left → right):
       ┌──────────────┬───┐
       │  bedroom 1   │ C │   ← top
       │              │ O │
       ├──────────────┤ R │
       │  bedroom 2   │ R │
       ├──────────────┤ I │
       │  bathroom 1  │ D │
       ├──────────────┤ O │
       │  bathroom 2  │ R │
       └──────────────┴───┘   ← bottom

    Every room's RIGHT wall touches the corridor's LEFT wall → corridor distributes
    to ALL of them (V11-FIX-#6).  Bathrooms cluster at bottom (plumbing — V11-FIX-#7).
    Primary bedroom sits directly above the master bath (V11-FIX-#7).
    """
    x0, y0, w, h = zone
    n_bed_u  = max(n_bed,  1)
    n_bath_u = max(n_bath, 1)
    n_bed_u = max(n_bed, 1)

    cor_w = min(CORRIDOR_W, w * 0.30)
    cor_w = max(cor_w, ROOM_MIN_W['corridor'])
    if w - cor_w < ROOM_MIN_W['bedroom']:
        cor_w = max(ROOM_MIN_W['corridor'], w - ROOM_MIN_W['bedroom'])
    rest_w = round(w - cor_w, 4)
    cor_x  = round(x0 + rest_w, 4)

    rooms = [Room('corridor', cor_x, y0, cor_w, h, 'PRIVATE')]

    # Vertical share for bath vs bed block.
    # Each bathroom needs ≥ ROOM_MIN_H['bathroom']; primary bed wants ≥ ROOM_MIN_H['bedroom'].
    bath_min_each = ROOM_MIN_H['bathroom']
    bath_h_total  = max(n_bath_u * bath_min_each, _snap(h * 0.30))
    bath_h_total  = min(bath_h_total, h * 0.55)         # don't crowd out bedrooms
    bath_h_total  = max(bath_h_total, n_bath_u * bath_min_each * 0.80)
    bed_h_total   = round(h - bath_h_total, 4)

    # Bathrooms STACK vertically at bottom (all touch corridor's left wall)
    rooms += _vstack(x0, y0, rest_w, bath_h_total,
                     ['bathroom']*n_bath_u, 'PRIVATE')

    # Bedrooms above. Primary bedroom (larger, 55%) is at the bottom of the bed-block,
    # directly above the master bath → enables master-suite (V11-FIX-#7).
    if n_bed_u >= 2:
        prim_h = _snap(bed_h_total * 0.55)
        prim_h = max(prim_h, ROOM_MIN_H['bedroom'])
        prim_h = min(prim_h, bed_h_total - ROOM_MIN_H['bedroom'] * 0.85)
        if prim_h < ROOM_MIN_H['bedroom'] * 0.85:
            prim_h = bed_h_total / 2
        rooms.append(Room('bedroom', x0, y0 + bath_h_total, rest_w, prim_h, 'PRIVATE'))
        remaining_h = round(bed_h_total - prim_h, 4)
        rooms += _vstack(x0, y0 + bath_h_total + prim_h, rest_w, remaining_h,
                         ['bedroom']*(n_bed_u-1), 'PRIVATE')
    else:
        rooms += _vstack(x0, y0 + bath_h_total, rest_w, bed_h_total,
                         ['bedroom']*n_bed_u, 'PRIVATE')
    return rooms


def _living_cap_frac(indoor_net):
    """V13.6 — single source of truth for the living-area share cap, used by
    BOTH the livability gate AND _subdivide_public. Previously the gate used a
    scale-aware cap (0.50-0.62) while _subdivide_public still carved living at
    the stale 0.36 constant — so large apartments were DESIGNED with an
    under-sized living and the surplus leaked into foyer/dead-space. Now they
    agree."""
    if indoor_net <= 80:
        return 0.60
    elif indoor_net >= 150:
        return 0.60
    elif indoor_net >= 130:
        return 0.56
    else:
        return 0.48


def _subdivide_public(zone, target_area=None):
    """V12 — split PUBLIC into living + (foyer) + (dining). V13.6 — the living
    target now tracks the scale-aware cap (`_living_cap_frac`) instead of the
    fixed 0.36, so the DESIGN matches what the gate will accept. A foyer/dining
    is only carved when the public zone genuinely exceeds that (larger) target.
    """
    x0, y0, w, h = zone
    gross = w * h
    if target_area is None:
        return [Room('living', x0, y0, w, h, 'PUBLIC')]

    # Target living-room area (gross). Use the scale-aware cap, leaving a small
    # margin so the gate (which adds +0.5 slack) virtually always passes.
    cap_frac = _living_cap_frac(target_area)
    living_cap_gross = cap_frac * target_area * 1.06  # gross ≈ net × wall factor
    if gross <= living_cap_gross + 2.0:
        return [Room('living', x0, y0, w, h, 'PUBLIC')]

    excess = gross - living_cap_gross
    # Carve foyer first (1.5–2.5 m strip, area 4-6 m²)
    rooms = []
    if h > w:    # tall zone → carve from top
        # Foyer ~ 5 m² at top
        foyer_h = _snap(min(max(5.0 / w, 1.5), 2.5))
        foyer_h = min(foyer_h, h * 0.30)
        if foyer_h >= 1.2:
            rooms.append(Room('foyer', x0, y0 + h - foyer_h, w, foyer_h, 'PUBLIC'))
            h -= foyer_h
            gross = w * h
        # If still excess, carve a dining strip below the (now-shrunk) zone top
        if gross > living_cap_gross + 2.0:
            dining_h = _snap(min(max((gross - living_cap_gross) / w, 1.8), 3.0))
            dining_h = min(dining_h, h * 0.35)
            if dining_h >= 1.6:
                rooms.append(Room('dining', x0, y0 + h - dining_h, w, dining_h, 'PUBLIC'))
                h -= dining_h
        rooms.insert(0, Room('living', x0, y0, w, h, 'PUBLIC'))
    else:        # wide zone → carve from right
        foyer_w = _snap(min(max(5.0 / h, 1.5), 2.5))
        foyer_w = min(foyer_w, w * 0.25)
        if foyer_w >= 1.2:
            rooms.append(Room('foyer', x0 + w - foyer_w, y0, foyer_w, h, 'PUBLIC'))
            w -= foyer_w
            gross = w * h
        if gross > living_cap_gross + 2.0:
            dining_w = _snap(min(max((gross - living_cap_gross) / h, 1.8), 3.0))
            dining_w = min(dining_w, w * 0.35)
            if dining_w >= 1.6:
                rooms.append(Room('dining', x0 + w - dining_w, y0, dining_w, h, 'PUBLIC'))
                w -= dining_w
        rooms.insert(0, Room('living', x0, y0, w, h, 'PUBLIC'))
    return rooms


def _subdivide_service(zone, n_kit):
    """V12 — produce ONLY a kitchen (or a small storage when n_kit==0).

    Surplus area in the SERVICE zone is now LEFT UNUSED in this stage —
    `_resolve_remaining_overlaps` and `stage9b_dead_space` will absorb it into
    the adjacent PUBLIC room (living/foyer). No more oversized "storage" rooms.
    """
    x0, y0, w, h = zone
    if n_kit <= 0:
        # No kitchen — return empty; caller merges zone into adjacent room
        return []

    max_kit_a = ROOM_MAX_AREA['kitchen']
    if w * h <= max_kit_a + 1.0:
        return [Room('kitchen', x0, y0, w, h, 'SERVICE')]
    # V15.10-FIX — zone is taller than the kitchen needs (this happens on
    # large buildings, exactly the XL area band: kitchen's own ergonomic
    # WIDTH floor can force it past its AREA cap once the zone is tall
    # enough, so it has to give up height instead). The old approach left
    # that leftover strip for stage9b_dead_space to absorb — but the strip
    # isn't a rectangle any neighbouring room can extend into without
    # becoming an L-shape, so it was never actually getting merged (this
    # was confirmed as THE reason corner-core failed 0/15 at net=170 — an
    # ~18m² gap was being reported as "dead space" every time). Filling it
    # with its own STORAGE/pantry room instead is both correct
    # architecturally (kitchen<->storage is an explicitly desired
    # adjacency) and tileable by construction — no absorption needed.
    kit_h = max(ROOM_MIN_H['kitchen'], min(h, max_kit_a / max(w, 0.5)))
    kit_h = _snap(kit_h)
    rooms = [Room('kitchen', x0, y0, w, kit_h, 'SERVICE')]
    leftover_h = round(h - kit_h, 4)
    if leftover_h >= ROOM_MIN_H['kitchen'] * 0.15:
        # absorb leftover into kitchen by extending its height
        rooms[0] = Room('kitchen', x0, y0, w, round(kit_h + leftover_h, 4), 'SERVICE')
    return rooms


def _subdivide_outdoor_protrude(zone, public_zone):
    """V11-FIX-#1, #2, #13 — balcony is a PROTRUSION outside BW×BH.

    `zone` already has y0 = BH (above the main envelope). We additionally clamp its
    x-range to fall within the living-room's x-range so it never overhangs kitchen.
    """
    x0, y0, w, h = zone
    if public_zone is not None:
        px0, py0, pw, ph = public_zone
        # Clamp balcony x-range to public-zone x-range  (V11-FIX-#13)
        x0 = max(x0, px0)
        right = min(x0 + w, px0 + pw)
        w = max(BALCONY_MIN_W, right - x0)
        # Centre the balcony on the public-zone if there's room
        if w > pw * 0.85:
            w = pw                   # full width over living
        else:
            x0 = px0 + (pw - w) / 2
    return [Room('balcony', x0, y0, w, h, 'OUTDOOR', is_protrusion=True)]


def stage6_subdivide_v11(zones, n_bed, n_bath, n_kit, template, rng,
                          target_area=None, has_master_bath=False,
                          bath_layout=None, has_dressing=False):
    rooms = []
    public_zone = zones.get('PUBLIC')
    is_vsplit = bool(zones.get('_vsplit'))
    is_ccore  = bool(zones.get('_ccore'))
    is_wing = (template in TEMPLATES) and not is_vsplit and not is_ccore  # wing-family
    _leftover_bath = 0
    if 'PRIVATE' in zones:
        if is_ccore:
            _priv_rooms, _leftover_bath = _subdivide_ccore_lower(
                zones['PRIVATE'], n_bed, n_bath,
                zones['_ccore_core_x'], zones['_ccore_core_w'],
                zones['_ccore_side_w'], zones['_ccore_has_dining'], rng,
                left_w=zones.get('_ccore_left_w'), right_w=zones.get('_ccore_right_w'),
                has_master_bath=has_master_bath, bath_layout=bath_layout,
                target_area=target_area, has_dressing=has_dressing)
            rooms += _priv_rooms
        elif is_vsplit:
            _priv_rooms, _leftover_bath = _subdivide_private_vsplit(
                zones['PRIVATE'], n_bed, n_bath, rng,
                has_master_bath=has_master_bath, bath_layout=bath_layout,
                target_area=target_area, has_dressing=has_dressing)
            rooms += _priv_rooms
        elif is_wing:
            _priv_rooms, _leftover_bath = _subdivide_private_wing(
                zones['PRIVATE'], n_bed, n_bath, rng, has_master_bath,
                bath_layout, target_area, has_dressing)
            rooms += _priv_rooms
        else:
            rooms += _subdivide_private_v11(zones['PRIVATE'], n_bed, n_bath, template, rng)

    # V13.1.1c — explicit horizontal CORRIDOR spine (wing family)
    if 'CORRIDOR' in zones:
        x0, y0, w, h = zones['CORRIDOR']
        rooms.append(Room('corridor', x0, y0, w, h, 'PRIVATE'))
        # V13.1.1e — en-suite mode emits a full-height tagged 'leg' corridor;
        # clear the tag to make it a normal corridor room.
        for r in rooms:
            if r.name == 'corridor' and getattr(r, 'tag', None) == 'leg':
                r.tag = None

    if 'PUBLIC'  in zones:
        # V13.1.1c/f — wing-family public zone is living ONLY. When a PUBLIC2
        # strip exists (open-plan, no dining) it joins LIVING — never a dining.
        if is_wing or is_vsplit or is_ccore:
            x0, y0, w, h = zones['PUBLIC']
            _left_edge_taken = False

            # V15.0 — guest bathroom carved out of the living room itself
            # (no extra corridor spent reaching it; reached directly from
            # the living area). Placed on the LEFT edge of the living zone,
            # which for the 'wing' variant is x=0 = the exterior wall, so
            # it gets light/air directly.
            if (is_wing or is_vsplit or is_ccore) and _leftover_bath > 0:
                # Dynamically create all leftover guest bathrooms along the left edge of public/living zone!
                n_guest = min(_leftover_bath, max(1, int(round(h, 4) // ROOM_MIN_H['bathroom'])))
                GUEST_BATH_AREA_TGT = 3.8 * n_guest
                col_w = _snap(max(ROOM_MIN_W['bathroom'] + 0.2,
                                  min(2.4, w * (0.20 + 0.05 * n_guest))), GRID_FINE)
                col_w = min(col_w, w - ROOM_MIN_W['living'])
                if col_w >= ROOM_MIN_W['bathroom']:
                    total_bath_h = _snap(np.clip(GUEST_BATH_AREA_TGT / max(col_w, 1.0),
                                                 ROOM_MIN_H['bathroom'] * n_guest, h), GRID_FINE)
                    each_h = _snap(total_bath_h / n_guest, GRID_FINE)
                    cur_y = y0
                    for g_idx in range(n_guest):
                        this_h = each_h if g_idx < n_guest - 1 else round(total_bath_h - cur_y + y0, 4)
                        tag_name = 'guest_bath_living' if n_guest == 1 else f'guest_bath_{g_idx+1}'
                        rooms.append(Room('bathroom', x0, cur_y, col_w, this_h,
                                          'PUBLIC', tag=tag_name))
                        cur_y = round(cur_y + this_h, 4)
                    leftover_h = round(h - total_bath_h, 4)
                    if leftover_h >= 1.30:
                        # Create entry foyer above guest baths
                        rooms.append(Room('foyer', x0, round(y0 + total_bath_h, 4), col_w, leftover_h, 'PUBLIC'))
                    elif leftover_h > 0:
                        # Absorb small leftover into last bathroom
                        rooms[-1].h = round(rooms[-1].h + leftover_h, 4)
                    x0 = round(x0 + col_w, 4)
                    w  = round(w - col_w, 4)
                    _left_edge_taken = True

            # V15.8 — ENTRY FOYER: a privacy transition between the main
            # door and the living room, so the apartment never opens
            # straight into living. Sized from AREA_TARGET['foyer'], but
            # NEVER skipped outright — if the tier target doesn't fit, it
            # shrinks down to the smallest workable entry zone
            # (ROOM_MIN_AREA['foyer']) instead of disappearing.
            if is_wing and not any(r.name == 'foyer' for r in rooms):
                net_est = target_area if target_area else w * h * 3.0
                foyer_tgt = _tier_target('foyer', net_est)
                if not _left_edge_taken:
                    # left exterior edge is free — foyer as a full-height
                    # column there (keeps the TOP wall free for the
                    # balcony to attach to living, undisturbed).
                    foyer_w = _snap(np.clip(foyer_tgt / max(h, 1.0),
                                            ROOM_MIN_W['foyer'],
                                            min(2.4, w * 0.30)), GRID_FINE)
                    foyer_w = min(foyer_w, w - ROOM_MIN_W['living'])
                    if foyer_w < ROOM_MIN_W['foyer']:
                        # compact entry zone — shrink to the bare minimum
                        # rather than skip it.
                        foyer_w = min(ROOM_MIN_W['foyer'], w - ROOM_MIN_W['living'])
                    if foyer_w >= ROOM_MIN_W['foyer'] * 0.9:
                        rooms.append(Room('foyer', x0, y0, foyer_w, h, 'PUBLIC'))
                        x0 = round(x0 + foyer_w, 4)
                        w  = round(w - foyer_w, 4)
                else:
                    # left edge already taken by the living-carved guest
                    # bath — fall back to a TOP band instead. (In this one
                    # layout, the balcony may end up adjacent to the foyer
                    # rather than living; balcony<->foyer is a mandatory
                    # pair specifically to cover that.)
                    foyer_h = _snap(np.clip(foyer_tgt / max(w, 1.0),
                                            ROOM_MIN_H['foyer'],
                                            min(2.0, h * 0.35)), GRID_FINE)
                    foyer_h = min(foyer_h, h - ROOM_MIN_H['living'])
                    if foyer_h < ROOM_MIN_H['foyer']:
                        foyer_h = min(ROOM_MIN_H['foyer'], h - ROOM_MIN_H['living'])
                    if foyer_h >= ROOM_MIN_H['foyer'] * 0.9:
                        rooms.append(Room('foyer', x0, y0 + h - foyer_h, w, foyer_h,
                                          'PUBLIC'))
                        h = round(h - foyer_h, 4)

            wing_pub2 = zones.get('PUBLIC2')
            if wing_pub2 is not None:
                px, py, pw, ph = wing_pub2
                if (abs(py - y0) < 0.01 and abs(ph - h) < 0.31):
                    # same baseline & height → widen living to swallow it
                    if abs(px + pw - x0) < 0.05:        # PUBLIC2 left of living
                        w = round(w + pw, 4); x0 = px
                    elif abs(x0 + w - px) < 0.05:       # PUBLIC2 right of living
                        w = round(w + pw, 4)
                    else:
                        rooms.append(Room('living', px, py, pw, ph, 'PUBLIC'))
                else:
                    # different shape → separate open-plan living rectangle
                    rooms.append(Room('living', px, py, pw, ph, 'PUBLIC'))
                zones = {k: v for k, v in zones.items() if k != 'PUBLIC2'}
            rooms.append(Room('living', x0, y0, w, h, 'PUBLIC'))
        else:
            rooms += _subdivide_public(zones['PUBLIC'], target_area)

    # V13.1.1c — explicit DINING zone
    if 'DINING' in zones:
        x0, y0, w, h = zones['DINING']
        rooms.append(Room('dining', x0, y0, w, h, 'PUBLIC'))

    # STORAGE zones suppressed — area merged upstream into kitchen/living

    if 'PUBLIC2' in zones:
        # Legacy PUBLIC2 path (only reached if not consumed above).
        existing_dining = any(r.name == 'dining' for r in rooms)
        x0, y0, w, h = zones['PUBLIC2']
        # always merge into living regardless of size
        rooms.append(Room('living', x0, y0, w, h, 'PUBLIC'))
    if 'SERVICE' in zones:
        svc = zones['SERVICE']
        overlap = any(
            min(r.x1, svc[0]+svc[2]) - max(r.x0, svc[0]) > 0.1 and
            min(r.y1, svc[1]+svc[3]) - max(r.y0, svc[1]) > 0.1
            for r in rooms)
        if not overlap:
            rooms += _subdivide_service(svc, n_kit)
    if 'OUTDOOR' in zones:
        rooms += _subdivide_outdoor_protrude(zones['OUTDOOR'], public_zone)
    return rooms


# ════════════════════════════════════════════════════════════
# STAGE 7 — GEOMETRY  (V11-FIX-#10, #12: target is NET area)
# ════════════════════════════════════════════════════════════
def stage7_geometry(rooms, BW, BH, target_area):
    """Scale BW × BH so total NET room area = target_area.

    V11-FIX-#10 — area accounting uses NET (inside-wall) area `(w-t)(h-t)` matching
                  the renderer's 0.15 m wall thickness. The user's 'I asked for 90 m² and
                  got 95 m²' bug is gone.
    V11-FIX-#12 — corridor area is no longer double-counted: it's part of the indoor net
                  sum exactly once, and the balcony (outdoor) is excluded.
    """
    indoor = [r for r in rooms if r.name != 'balcony']
    total_net = sum(r.area for r in indoor)
    if total_net < 0.1: return rooms, BW, BH
    scale = math.sqrt(target_area / total_net)
    BW_new = round(BW * scale, 3); BH_new = round(BH * scale, 3)

    scaled = []
    for r in rooms:
        if r.is_protrusion:
            # Protrusion keeps its own size, sits just outside the envelope.
            # V13.6 — respect the attachment edge: a balcony emitted BELOW the
            # envelope (y0<0, flipped wing-stack) stays below; otherwise on top.
            new_x0 = round(r.x0 * scale, 3)
            new_w  = round(r.w  * scale, 3)
            new_y0 = round(-BALCONY_PROTRUDE, 3) if r.y0 < 0 else BH_new
            scaled.append(Room(r.name, new_x0, new_y0,
                               new_w, BALCONY_PROTRUDE,
                               r.zone, is_protrusion=True,
                               tag=getattr(r, 'tag', None)))
        else:
            scaled.append(Room(r.name,
                               round(r.x0 * scale, 3), round(r.y0 * scale, 3),
                               round(r.w  * scale, 3), round(r.h  * scale, 3),
                               r.zone, tag=getattr(r, 'tag', None)))
    return scaled, BW_new, BH_new


def _resolve_remaining_overlaps(rooms, max_iters=200):
    ANCHOR = {'corridor', 'living', 'balcony'}
    for _ in range(max_iters):
        moved = False
        for i in range(len(rooms)):
            for j in range(i+1, len(rooms)):
                r1, r2 = rooms[i], rooms[j]
                if r1.is_protrusion or r2.is_protrusion: continue
                ox = min(r1.x1, r2.x1) - max(r1.x0, r2.x0)
                oy = min(r1.y1, r2.y1) - max(r1.y0, r2.y0)
                if ox > 0.05 and oy > 0.05:
                    moved = True
                    a1 = r1.name in ANCHOR; a2 = r2.name in ANCHOR
                    if ox < oy:
                        push = max(GRID, _snap(ox))
                        if a1 and not a2:
                            r2.x0 = round(r2.x0 + (push if r1.cx < r2.cx else -push), 4)
                        elif a2 and not a1:
                            r1.x0 = round(r1.x0 + (push if r2.cx < r1.cx else -push), 4)
                        else:
                            if r1.cx < r2.cx: r2.x0 = _snap(r1.x1)
                            else: r1.x0 = _snap(r2.x1)
                    else:
                        push = max(GRID, _snap(oy))
                        if a1 and not a2:
                            r2.y0 = round(r2.y0 + (push if r1.cy < r2.cy else -push), 4)
                        elif a2 and not a1:
                            r1.y0 = round(r1.y0 + (push if r2.cy < r1.cy else -push), 4)
                        else:
                            if r1.cy < r2.cy: r2.y0 = _snap(r1.y1)
                            else: r1.y0 = _snap(r2.y1)
        if not moved: break


def _tighten_adjacency(rooms, must_pairs, max_iters=50):
    for _ in range(max_iters):
        moved = False
        for (i, j) in must_pairs:
            r1, r2 = rooms[i], rooms[j]
            if r1.is_protrusion or r2.is_protrusion: continue
            if r1.shares_wall(r2): continue
            gap_x = max(r1.x0, r2.x0) - min(r1.x1, r2.x1)
            gap_y = max(r1.y0, r2.y0) - min(r1.y1, r2.y1)
            xo = min(r1.x1, r2.x1) - max(r1.x0, r2.x0)
            yo = min(r1.y1, r2.y1) - max(r1.y0, r2.y0)
            if xo > 0.25 and gap_y > 0:
                pull = _snap(gap_y + GRID); old = r2.y0
                r2.y0 = _snap(r2.y0 - pull) if r1.cy < r2.cy else _snap(r2.y0 + pull)
                if any(r2.overlap_area(rooms[k]) > 0.01 for k in range(len(rooms)) if k != j):
                    r2.y0 = old
                else: moved = True
            elif yo > 0.25 and gap_x > 0:
                pull = _snap(gap_x + GRID); old = r2.x0
                r2.x0 = _snap(r2.x0 - pull) if r1.cx < r2.cx else _snap(r2.x0 + pull)
                if any(r2.overlap_area(rooms[k]) > 0.01 for k in range(len(rooms)) if k != j):
                    r2.x0 = old
                else: moved = True
        if not moved: break


def stage7b_bfs_polish(rooms):
    # 1) snap edges so BSP tiling stays intact. V13.2.1 — snap on GRID_FINE
    #    (0.10m) instead of GRID (0.50m). The coarse 0.50 snap was collapsing
    #    the deliberate master/guest bath width difference (1.6 vs 1.2 → both
    #    landed on 1.5) and equal-ising jittered bedrooms. 0.10 keeps tiles
    #    aligned (all coords are already 0.10-multiples from GRID_FINE splits)
    #    while preserving the variety.
    for r in rooms:
        if r.is_protrusion: continue
        x0_s, x1_s = _snap(r.x0, GRID_FINE), _snap(r.x1, GRID_FINE)
        y0_s, y1_s = _snap(r.y0, GRID_FINE), _snap(r.y1, GRID_FINE)
        r.x0 = x0_s
        r.y0 = y0_s
        r.w  = max(x1_s - x0_s, GRID_FINE)
        r.h  = max(y1_s - y0_s, GRID_FINE)

    name_to_idx = {}
    for i, r in enumerate(rooms): name_to_idx.setdefault(r.name, []).append(i)
    must_pairs = []
    # V15.1 — bathrooms carrying one of these tags are INTENTIONALLY not
    # corridor-adjacent (en-suite reached only from its bedroom, or a guest
    # bath reached only from living). The blind 'bathroom'->'corridor' pull
    # below must skip them, or it warps the whole layout trying to drag a
    # bathroom toward a corridor it was deliberately placed away from.
    NO_CORRIDOR_PULL_TAGS = {'ensuite', 'master_bath', 'guest_bath', 'guest_bath_living'}
    for dep, trg, _w in ADJACENCY_RULES:
        for i in name_to_idx.get(dep, []):
            if (dep == 'bathroom' and trg == 'corridor'
                    and getattr(rooms[i], 'tag', None) in NO_CORRIDOR_PULL_TAGS):
                continue
            for j in name_to_idx.get(trg, []):
                must_pairs.append((i, j))

    for _ in range(3):
        _tighten_adjacency(rooms, must_pairs, max_iters=40)
        _resolve_remaining_overlaps(rooms, max_iters=80)
    return rooms


# ════════════════════════════════════════════════════════════
# STAGE 8 — FACADE / WINDOWS  (V11-FIX-#9 : multi-window for bedrooms)
# ════════════════════════════════════════════════════════════
WINDOW_PRIORITY = ['living', 'bedroom', 'kitchen', 'bathroom']

def stage8_windows(rooms, BW, BH):
    tol = 0.20
    for r in rooms:
        if r.is_protrusion and r.name == 'balcony':
            # Balcony: window/parapet on every exterior side
            r.windows = [
                ('top',   min(0.90, r.w * 0.90)),
                ('left',  min(0.90, r.h * 0.85)),
                ('right', min(0.90, r.h * 0.85)),
            ]
            continue

        wins, exposures = [], []
        if r.y1 >= BH - tol: exposures.append(('top',    r.w))
        if r.y0 <= tol:      exposures.append(('bottom', r.w))
        if r.x0 <= tol:      exposures.append(('left',   r.h))
        if r.x1 >= BW - tol: exposures.append(('right',  r.h))
        exposures.sort(key=lambda e: -e[1])

        # V11-FIX-#9 — bedrooms / living can have TWO windows if they have two
        # exterior walls (cross-ventilation). Kitchen/bathroom keep one.
        max_wins = 2 if r.name in ('living', 'bedroom') else 1
        for side, length in exposures[:max_wins]:
            if r.name in WINDOW_PRIORITY:
                wins.append((side, min(1.20, length * 0.55)))

        if r.name == 'living' and not wins:
            wins = [('top', min(0.90, r.w * 0.60))] if r.w >= r.h else \
                   [('right', min(0.90, r.h * 0.60))]
        r.windows = wins
    return rooms
# ════════════════════════════════════════════════════════════
# STAGE 9 — DOORS (Bulletproof Quota + Sliders + Structural Avoidance)
# ════════════════════════════════════════════════════════════
def _pair(a, b): return tuple(sorted([a, b]))

DOOR_MANDATORY = {
    _pair('corridor', 'living'), _pair('corridor', 'bedroom'),
    _pair('corridor', 'bathroom'), _pair('corridor', 'kitchen'),
    _pair('balcony',  'living'), _pair('foyer',    'living'),
    _pair('balcony',  'foyer'),
}
DOOR_OPTIONAL = {
    _pair('bedroom', 'bathroom'), _pair('foyer',   'corridor'),
    _pair('foyer',   'kitchen'), _pair('dining',  'living'),
    _pair('dining',  'kitchen'), _pair('foyer',   'dining'),
    _pair('storage', 'kitchen'), _pair('storage', 'corridor'),
    _pair('storage', 'living'), _pair('storage', 'bedroom'),
}

def _door_pair(a, b): return _pair(a, b)

def _door_status(a, b):
    p = _door_pair(a, b)
    if p in DOOR_MANDATORY: return 'mandatory'
    if p in DOOR_OPTIONAL:  return 'optional'
    return 'forbidden'

def _build_door_candidates(rooms):
    out = []
    N = len(rooms)
    for i in range(N):
        for j in range(i+1, N):
            r1, r2 = rooms[i], rooms[j]
            tagi, tagj = getattr(r1, 'tag', None), getattr(r2, 'tag', None)
            if ('guest_bath_living' in (tagi, tagj) and 'corridor' in (r1.name, r2.name)):
                continue
            st = _door_status(r1.name, r2.name)
            if st == 'forbidden':
                names = {r1.name, r2.name}
                tags  = {getattr(r1, 'tag', None), getattr(r2, 'tag', None)}
                if names == {'bathroom', 'living'} and 'guest_bath_living' in tags:
                    st = 'mandatory'
                else: continue
            seg = r1.shared_wall_segment(r2)
            if seg is None: continue
            axis, fixed, lo, hi = seg
            if hi - lo < DOOR_W_M + 0.30: continue
            out.append((i, j, axis, fixed, lo, hi, st))
    return out

def _place_door_along(seg, rooms, occupied_by_corridor):
    i, j, axis, fixed, lo, hi, st = seg
    # [التصحيح 1]: إبعاد الأبواب 65 سم عن الأركان عشان متخبطش في الأعمدة الخرسانية!
    cm = 0.65
    free_lo = lo + cm; free_hi = hi - cm - DOOR_W_M
    if free_hi <= free_lo:
        cm = 0.20 # لو الحيطة صغيرة جداً (زي حمام)، قلل المسافة للضرورة
        free_lo = lo + cm; free_hi = hi - cm - DOOR_W_M
        if free_hi <= free_lo: return None

    forbidden = []; same_wall_doors_in_corridor = []; opposite_wall_doors = []
    corridor_room = None
    if rooms[i].name == 'corridor': corridor_room = rooms[i]
    elif rooms[j].name == 'corridor': corridor_room = rooms[j]

    for ri, r in enumerate(rooms):
        for d in r.doors:
            if d.get('axis') != axis: continue
            if abs(d.get('fixed', -999) - fixed) < 0.08:
                forbidden.append((d['lo'], d['lo'] + DOOR_W_M))
                if rooms[d.get('partner', -1)].name == 'corridor' or r.name == 'corridor':
                    same_wall_doors_in_corridor.append(d['lo'] + DOOR_W_M/2)
            elif corridor_room is not None:
                if axis == 'v':
                    other_wall = corridor_room.x0 if abs(fixed - corridor_room.x1) < 0.08 else \
                                 corridor_room.x1 if abs(fixed - corridor_room.x0) < 0.08 else None
                else:
                    other_wall = corridor_room.y0 if abs(fixed - corridor_room.y1) < 0.08 else \
                                 corridor_room.y1 if abs(fixed - corridor_room.y0) < 0.08 else None
                if other_wall is not None and abs(d.get('fixed', -999) - other_wall) < 0.08:
                    opposite_wall_doors.append(d['lo'] + DOOR_W_M/2)

    candidates = []; step = 0.20; p = free_lo
    while p <= free_hi + 1e-6:
        if not any(p < fhi - 0.05 and p + DOOR_W_M > flo + 0.05 for flo, fhi in forbidden):
            candidates.append(p)
        p += step

    if not candidates: return None

    def isolation(p):
        c = p + DOOR_W_M/2
        same_dist = (min(abs(c - c2) for c2 in same_wall_doors_in_corridor) if same_wall_doors_in_corridor else 99.0)
        opp_dist  = (min(abs(c - c2) for c2 in opposite_wall_doors) if opposite_wall_doors else 99.0)
        return min(same_dist, opp_dist)

    candidates.sort(key=isolation, reverse=True)
    p = candidates[0]
    if axis == 'h': door = dict(type='h', axis='h', fixed=fixed, lo=p, x=p, y=fixed, w=DOOR_W_M, partner=j)
    else:           door = dict(type='v', axis='v', fixed=fixed, lo=p, x=fixed, y=p, w=DOOR_W_M, partner=j)
    return door

def stage9_doors_v11(rooms, has_master_bath=False):
    # V16.7 QA Pass Foyer validation & repair
    foyers = [r for r in rooms if r.name == 'foyer']
    envelope = _building_envelope(rooms)
    bal = next((r for r in rooms if r.name == 'balcony'), None)
    
    def _strip_balcony_side(liv, sides):
        clean_s = []
        for s_name, s_len, sx, sy in sides:
            touches_bal = False
            for b_room in rooms:
                if b_room.name in ('balcony', 'terrace', 'outdoor'):
                    if s_name == 'top' and abs(liv.y1 - b_room.y0) < 0.4 and max(liv.x0, b_room.x0) < min(liv.x1, b_room.x1) - 0.05:
                        touches_bal = True; break
                    elif s_name == 'bottom' and abs(liv.y0 - b_room.y1) < 0.4 and max(liv.x0, b_room.x0) < min(liv.x1, b_room.x1) - 0.05:
                        touches_bal = True; break
                    elif s_name == 'right' and abs(liv.x1 - b_room.x0) < 0.4 and max(liv.y0, b_room.y0) < min(liv.y1, b_room.y1) - 0.05:
                        touches_bal = True; break
                    elif s_name == 'left' and abs(liv.x0 - b_room.x1) < 0.4 and max(liv.y0, b_room.y0) < min(liv.y1, b_room.y1) - 0.05:
                        touches_bal = True; break
            if not touches_bal:
                clean_s.append((s_name, s_len, sx, sy))
        return clean_s

    for fr in foyers:
        unrealistic = False
        for bal_r in rooms:
            if bal_r.name in ('balcony', 'terrace', 'outdoor'):
                if fr.shares_wall(bal_r) or (max(fr.x0, bal_r.x0) < min(fr.x1, bal_r.x1) and max(fr.y0, bal_r.y0) < min(fr.y1, bal_r.y1)):
                    unrealistic = True
                    break
        if not unrealistic:
            shares_living = any(fr.shares_wall(r) for r in rooms if r.name == 'living')
            if not shares_living:
                unrealistic = True
        if not unrealistic:
            sides = _strip_balcony_side(fr, _perimeter_sides(fr, envelope))
            if not sides:
                unrealistic = True
        if unrealistic:
            fr.name = 'living'

    # Clear doors
    for r in rooms:
        r.doors = []
        
    n = len(rooms)
    
    # Identify indices
    foyer_idxs = [i for i, r in enumerate(rooms) if r.name == 'foyer']
    living_idxs = [i for i, r in enumerate(rooms) if r.name == 'living']
    corridor_idxs = [i for i, r in enumerate(rooms) if r.name == 'corridor']
    bedroom_idxs = [i for i, r in enumerate(rooms) if r.name == 'bedroom']
    bathroom_idxs = [i for i, r in enumerate(rooms) if r.name == 'bathroom']
    kitchen_idxs = [i for i, r in enumerate(rooms) if r.name == 'kitchen']
    dining_idxs = [i for i, r in enumerate(rooms) if r.name == 'dining']
    balcony_idxs = [i for i, r in enumerate(rooms) if r.name == 'balcony']
    storage_idxs = [i for i, r in enumerate(rooms) if r.name in ('storage', 'laundry')]
    
    ensuite_baths = [i for i in bathroom_idxs if getattr(rooms[i], 'tag', None) in ('ensuite', 'master_bath')] if has_master_bath else []
    master_beds = [i for i in bedroom_idxs if getattr(rooms[i], 'tag', None) == 'master']
    common_baths = [i for i in bathroom_idxs if i not in ensuite_baths]

    # Entry root
    root_idx = None
    if foyer_idxs: root_idx = foyer_idxs[0]
    elif living_idxs: root_idx = living_idxs[0]
    else: root_idx = 0

    backbone_edges = []
    backbone_visited = {root_idx}
    
    # Connect foyer & living segments
    all_pub_idxs = foyer_idxs + living_idxs
    while True:
        best_edge = None
        best_len = -1
        for u in backbone_visited:
            if u not in all_pub_idxs: continue
            for v in all_pub_idxs:
                if v in backbone_visited: continue
                seg = rooms[u].shared_wall_segment(rooms[v])
                if seg is not None:
                    L = seg[3] - seg[2]
                    if L >= 0.50 and L > best_len:
                        best_len = L
                        best_edge = (u, v, seg)
        if best_edge:
            u, v, seg = best_edge
            backbone_edges.append((u, v, seg))
            backbone_visited.add(v)
        else:
            break
            
    # Connect Corridor segments to the backbone
    if corridor_idxs:
        best_edge = None
        best_len = -1
        for u in backbone_visited:
            for v in corridor_idxs:
                seg = rooms[u].shared_wall_segment(rooms[v])
                if seg is not None:
                    L = seg[3] - seg[2]
                    if L >= 0.80 and L > best_len:
                        best_len = L
                        best_edge = (u, v, seg)
        if best_edge:
            u, v, seg = best_edge
            backbone_edges.append((u, v, seg))
            backbone_visited.add(v)
            
            while True:
                best_cor_edge = None
                best_cor_len = -1
                for u in backbone_visited:
                    if u not in corridor_idxs: continue
                    for v in corridor_idxs:
                        if v in backbone_visited: continue
                        seg = rooms[u].shared_wall_segment(rooms[v])
                        if seg is not None:
                            L = seg[3] - seg[2]
                            if L >= 0.50 and L > best_cor_len:
                                best_cor_len = L
                                best_cor_edge = (u, v, seg)
                if best_cor_edge:
                    u, v, seg = best_cor_edge
                    backbone_edges.append((u, v, seg))
                    backbone_visited.add(v)
                else:
                    break

    tree_edges = list(backbone_edges)
    
    # Helper to find the best adjacent room segment based on target room lists
    def find_best_connection(room_idx, target_idxs, min_w=0.80):
        best_seg = None
        best_parent = None
        best_len = -1
        for p_idx in target_idxs:
            seg = rooms[room_idx].shared_wall_segment(rooms[p_idx])
            if seg is not None:
                L = seg[3] - seg[2]
                if L >= min_w and L > best_len:
                    best_len = L
                    best_seg = seg
                    best_parent = p_idx
        return best_parent, best_seg

    # Connect other rooms directly to backbone
    # Bedrooms
    for r_idx in bedroom_idxs:
        # Try corridor
        parent_idx, best_seg = find_best_connection(r_idx, corridor_idxs, min_w=0.80)
        # Fallback to living
        if parent_idx is None:
            parent_idx, best_seg = find_best_connection(r_idx, living_idxs, min_w=0.80)
        # Fallback to corridor/living with reduced width
        if parent_idx is None:
            parent_idx, best_seg = find_best_connection(r_idx, corridor_idxs + living_idxs, min_w=0.60)
        if parent_idx is not None:
            tree_edges.append((parent_idx, r_idx, best_seg))
            
    # Ensuite
    for b_idx in ensuite_baths:
        parent_idx, best_seg = find_best_connection(b_idx, master_beds, min_w=0.80)
        if parent_idx is None:
            parent_idx, best_seg = find_best_connection(b_idx, master_beds, min_w=0.60)
        if parent_idx is not None:
            tree_edges.append((parent_idx, b_idx, best_seg))

    # Common bathrooms
    for b_idx in common_baths:
        parent_idx = None
        best_seg = None
        is_guest_living = getattr(rooms[b_idx], 'tag', None) in ('guest_bath_living', 'guest_bath')
        if is_guest_living:
            parent_idx, best_seg = find_best_connection(b_idx, living_idxs, min_w=0.80)
        if parent_idx is None:
            parent_idx, best_seg = find_best_connection(b_idx, corridor_idxs, min_w=0.80)
        if parent_idx is None:
            parent_idx, best_seg = find_best_connection(b_idx, living_idxs, min_w=0.80)
        if parent_idx is None:
            parent_idx, best_seg = find_best_connection(b_idx, corridor_idxs + living_idxs, min_w=0.60)
        if parent_idx is not None:
            tree_edges.append((parent_idx, b_idx, best_seg))

    # Kitchen
    for k_idx in kitchen_idxs:
        parent_idx, best_seg = find_best_connection(k_idx, living_idxs, min_w=0.80)
        if parent_idx is None:
            parent_idx, best_seg = find_best_connection(k_idx, corridor_idxs, min_w=0.80)
        if parent_idx is None:
            parent_idx, best_seg = find_best_connection(k_idx, living_idxs + corridor_idxs, min_w=0.60)
        if parent_idx is not None:
            tree_edges.append((parent_idx, k_idx, best_seg))

    # Dining
    for d_idx in dining_idxs:
        parent_idx, best_seg = find_best_connection(d_idx, living_idxs, min_w=0.80)
        if parent_idx is None:
            parent_idx, best_seg = find_best_connection(d_idx, kitchen_idxs, min_w=0.80)
        if parent_idx is None:
            parent_idx, best_seg = find_best_connection(d_idx, living_idxs + kitchen_idxs, min_w=0.60)
        if parent_idx is not None:
            tree_edges.append((parent_idx, d_idx, best_seg))

    # Balcony
    for b_idx in balcony_idxs:
        parent_idx, best_seg = find_best_connection(b_idx, living_idxs, min_w=0.80)
        if parent_idx is None:
            parent_idx, best_seg = find_best_connection(b_idx, living_idxs, min_w=0.60)
        if parent_idx is not None:
            tree_edges.append((parent_idx, b_idx, best_seg))

    # Storage/laundry
    for s_idx in storage_idxs:
        parent_idx, best_seg = find_best_connection(s_idx, corridor_idxs, min_w=0.80)
        if parent_idx is None:
            parent_idx, best_seg = find_best_connection(s_idx, kitchen_idxs, min_w=0.80)
        if parent_idx is None:
            parent_idx, best_seg = find_best_connection(s_idx, living_idxs, min_w=0.80)
        if parent_idx is None:
            parent_idx, best_seg = find_best_connection(s_idx, corridor_idxs + kitchen_idxs + living_idxs, min_w=0.60)
        if parent_idx is not None:
            tree_edges.append((parent_idx, s_idx, best_seg))

    # Safety fallback to connect isolated rooms
    connected = {root_idx}
    for u, v, _ in tree_edges:
        connected.add(u); connected.add(v)
        
    for r_idx in range(n):
        if r_idx not in connected:
            best_seg = None
            parent_idx = None
            best_len = -1
            for c_idx in connected:
                seg = rooms[r_idx].shared_wall_segment(rooms[c_idx])
                if seg is not None:
                    L = seg[3] - seg[2]
                    if L > best_len:
                        best_len = L
                        best_seg = seg
                        parent_idx = c_idx
            if parent_idx is not None:
                tree_edges.append((parent_idx, r_idx, best_seg))
                connected.add(r_idx)

    # Place doors and decide swings
    SWING_PRIORITY = {'bathroom': 0, 'storage': 0, 'bedroom': 1, 'kitchen': 2, 'corridor': 3, 'living': 4, 'foyer': 5, 'dining': 6, 'balcony': 7}
    
    for u, v, seg in tree_edges:
        axis, fixed, lo, hi = seg[0], seg[1], seg[2], seg[3]
        L = hi - lo
        d_w = min(DOOR_W_M, L - 0.05)
        if d_w < 0.60:
            d_w = L
        d_w = round(d_w, 4)
        
        mid = (lo + hi) / 2.0
        p = round(mid - d_w / 2.0, 4)
        fixed_r = round(fixed, 4)
        
        r_u, r_v = rooms[u], rooms[v]
        p_u = SWING_PRIORITY.get(r_u.name, 9)
        p_v = SWING_PRIORITY.get(r_v.name, 9)
        if p_u < p_v:
            into_idx, out_idx = u, v
        elif p_u > p_v:
            into_idx, out_idx = v, u
        else:
            into_idx = u if r_u.area < r_v.area else v
            out_idx = v if into_idx == u else u
            
        into_room = rooms[into_idx]
        
        if axis == 'h':
            dist_left = p - into_room.x0
            dist_right = into_room.x1 - (p + d_w)
            hinge_left = (dist_left <= dist_right)
            is_up = (into_room.cy > fixed)
            swing = ('NE' if hinge_left else 'NW') if is_up else ('SE' if hinge_left else 'SW')
            door = dict(type='h', axis='h', fixed=fixed_r, lo=p, x=p, y=fixed_r, w=d_w, partner=out_idx, swing=swing)
        else:
            dist_bottom = p - into_room.y0
            dist_top = into_room.y1 - (p + d_w)
            hinge_bottom = (dist_bottom <= dist_top)
            is_right = (into_room.cx > fixed)
            swing = ('NE' if hinge_bottom else 'NW') if is_right else ('SE' if hinge_bottom else 'SW')
            door = dict(type='v', axis='v', fixed=fixed_r, lo=p, x=fixed_r, y=p, w=d_w, partner=out_idx, swing=swing)
            
        pair_names = tuple(sorted([rooms[u].name, rooms[v].name]))
        if pair_names in {('corridor', 'living'), ('foyer', 'living'), ('dining', 'living'), ('foyer', 'corridor')} or rooms[u].name == rooms[v].name:
            door['open_passage'] = True
        elif 'balcony' in pair_names:
            door['is_sliding'] = True
            
        rooms[into_idx].doors.append(door)

    # Place entry door — V16.8 Bulletproof Realism Rule:
    # An apartment entrance door must NEVER be placed on a wall that touches or faces ANY balcony/terrace/outdoor space.
    def _get_clean_exterior_sides(room_obj, all_rms, env):
        if room_obj.name in ('balcony', 'terrace', 'outdoor', 'bedroom', 'bathroom'):
            return []
        p_sides = _perimeter_sides(room_obj, env)
        if not p_sides:
            return []
        clean_s = []
        for s_name, s_len, sx, sy in p_sides:
            touches_bal = False
            for b_room in all_rms:
                if b_room.name in ('balcony', 'terrace', 'outdoor'):
                    if s_name == 'top' and abs(room_obj.y1 - b_room.y0) < 0.4:
                        if max(room_obj.x0, b_room.x0) < min(room_obj.x1, b_room.x1) - 0.05:
                            touches_bal = True; break
                    elif s_name == 'bottom' and abs(room_obj.y0 - b_room.y1) < 0.4:
                        if max(room_obj.x0, b_room.x0) < min(room_obj.x1, b_room.x1) - 0.05:
                            touches_bal = True; break
                    elif s_name == 'right' and abs(room_obj.x1 - b_room.x0) < 0.4:
                        if max(room_obj.y0, b_room.y0) < min(room_obj.y1, b_room.y1) - 0.05:
                            touches_bal = True; break
                    elif s_name == 'left' and abs(room_obj.x0 - b_room.x1) < 0.4:
                        if max(room_obj.y0, b_room.y0) < min(room_obj.y1, b_room.y1) - 0.05:
                            touches_bal = True; break
            if not touches_bal:
                clean_s.append((s_name, s_len, sx, sy))
        return clean_s

    chosen_entry = None
    priority_order = ['foyer', 'living', 'corridor', 'dining', 'study', 'storage', 'hall', 'kitchen']
    for p_name in priority_order:
        for r_obj in rooms:
            if r_obj.name == p_name and not r_obj.is_protrusion:
                c_sides = _get_clean_exterior_sides(r_obj, rooms, envelope)
                if c_sides:
                    c_sides.sort(key=lambda s: -s[1])
                    chosen_entry = (r_obj, c_sides[0])
                    break
        if chosen_entry is not None:
            break

    if chosen_entry is not None:
        root_r, (side_name, length, x_coord, y_coord) = chosen_entry
        if side_name in ('bottom', 'top'):
            dw, dh = min(1.0, length * 0.8), 0.15
            dx = x_coord + (length - dw) / 2
            dy = root_r.y0 if side_name == 'bottom' else root_r.y1
            dtype = 'h'
        else:
            dw, dh = 0.15, min(1.0, length * 0.8)
            dx = root_r.x0 if side_name == 'left' else root_r.x1
            dy = y_coord + (length - dh) / 2
            dtype = 'v'
            
        entry_door = {
            'type': dtype, 'x': round(dx, 4), 'y': round(dy, 4),
            'w': round(dw, 4), 'h': round(dh, 4),
            'partner': -1, 'entry': True, 'open_passage': False,
            'swing': 'NW' if dtype == 'h' else 'NE'
        }
        root_r.doors.append(entry_door)
        
    return rooms

def _building_envelope(rooms):
    """أقصى مستطيل يحيط بكل الغرف الداخلية (بدون البروزات زي البلكونة) —
    ده المحيط الخارجي الحقيقي للمبنى."""
    interior = [r for r in rooms if not r.is_protrusion]
    x0 = min(r.x0 for r in interior); y0 = min(r.y0 for r in interior)
    x1 = max(r.x1 for r in interior); y1 = max(r.y1 for r in interior)
    return x0, y0, x1, y1

def _perimeter_sides(r, envelope, tol=0.06):
    """الأضلاع من غرفة r اللي فعلاً واقعة على محيط المبنى (مش بس 'مفيش غرفة جنبها')."""
    ex0, ey0, ex1, ey1 = envelope
    sides = []
    if abs(r.y0 - ey0) < tol: sides.append(('bottom', r.w, r.x0, r.y0))
    if abs(r.y1 - ey1) < tol: sides.append(('top',    r.w, r.x0, r.y1))
    if abs(r.x0 - ex0) < tol: sides.append(('left',   r.h, r.x0, r.y0))
    if abs(r.x1 - ex1) < tol: sides.append(('right',  r.h, r.x1, r.y0))
    return sides

def _add_entry_door(rooms):
    """V16.7: Foyer validation & Entrance door placement.
    An unrealistic foyer (connects/overlaps/touches balcony or lacks exterior wall) is converted to 'living'.
    The apartment entrance door must always connect to either Foyer (preferred) or Living room (fallback).
    It must NEVER connect to Balcony, Terrace, Outdoor space, Kitchen, Bedroom, Bathroom, Corridor, or Dining.
    """
    envelope = _building_envelope(rooms)
    bal = next((r for r in rooms if r.name == 'balcony'), None)

    def _strip_balcony_side(liv, sides):
        clean_s = []
        for s_name, s_len, sx, sy in sides:
            touches_bal = False
            for b_room in rooms:
                if b_room.name in ('balcony', 'terrace', 'outdoor'):
                    if s_name == 'top' and abs(liv.y1 - b_room.y0) < 0.4 and max(liv.x0, b_room.x0) < min(liv.x1, b_room.x1) - 0.05:
                        touches_bal = True; break
                    elif s_name == 'bottom' and abs(liv.y0 - b_room.y1) < 0.4 and max(liv.x0, b_room.x0) < min(liv.x1, b_room.x1) - 0.05:
                        touches_bal = True; break
                    elif s_name == 'right' and abs(liv.x1 - b_room.x0) < 0.4 and max(liv.y0, b_room.y0) < min(liv.y1, b_room.y1) - 0.05:
                        touches_bal = True; break
                    elif s_name == 'left' and abs(liv.x0 - b_room.x1) < 0.4 and max(liv.y0, b_room.y0) < min(liv.y1, b_room.y1) - 0.05:
                        touches_bal = True; break
            if not touches_bal:
                clean_s.append((s_name, s_len, sx, sy))
        return clean_s

    # Step 1: Validate Foyer rooms
    for fr in [r for r in rooms if r.name == 'foyer' and not r.is_protrusion]:
        unrealistic = False
        for bal_r in rooms:
            if bal_r.name in ('balcony', 'terrace', 'outdoor'):
                if fr.shares_wall(bal_r) or (max(fr.x0, bal_r.x0) < min(fr.x1, bal_r.x1) and max(fr.y0, bal_r.y0) < min(fr.y1, bal_r.y1)):
                    unrealistic = True; break
                for d in fr.doors:
                    if rooms[d['partner']].name in ('balcony', 'terrace', 'outdoor'):
                        unrealistic = True; break
        if not unrealistic:
            sides = _strip_balcony_side(fr, _perimeter_sides(fr, envelope))
            if not sides:
                unrealistic = True
        if unrealistic:
            fr.name = 'living'

    chosen = None

    # Step 2: Priority 1 - Foyer (preferred)
    for r in rooms:
        if r.name == 'foyer' and not r.is_protrusion:
            sides = _strip_balcony_side(r, _perimeter_sides(r, envelope))
            if sides:
                sides.sort(key=lambda s: -s[1])
                chosen = (r, sides[0])
                break

    # Step 3: Priority 2 - Living room (fallback)
    if chosen is None:
        for r in rooms:
            if r.name == 'living' and not r.is_protrusion:
                sides = _strip_balcony_side(r, _perimeter_sides(r, envelope))
                if sides:
                    sides.sort(key=lambda s: -s[1])
                    chosen = (r, sides[0])
                    break

    # Step 4: Priority 3 - Absolute safety fallback (any perimeter side of living or foyer without balcony stripping)
    if chosen is None:
        for r in rooms:
            if r.name in ('foyer', 'living') and not r.is_protrusion:
                sides = _perimeter_sides(r, envelope)
                if sides:
                    sides.sort(key=lambda s: -s[1])
                    chosen = (r, sides[0])
                    break

    if chosen is not None:
        r, (side_name, length, x_coord, y_coord) = chosen
        if side_name in ('bottom', 'top'):
            dw, dh = min(1.0, length * 0.8), 0.15
            dx = x_coord + (length - dw) / 2
            dy = r.y0 if side_name == 'bottom' else r.y1
            dtype = 'h'
        else:
            dw, dh = 0.15, min(1.0, length * 0.8)
            dx = r.x0 if side_name == 'left' else r.x1
            dy = y_coord + (length - dh) / 2
            dtype = 'v'
        r.doors.append({
            'type': dtype, 'x': round(dx, 4), 'y': round(dy, 4),
            'w': round(dw, 4), 'h': round(dh, 4),
            'partner': -1, 'entry': True, 'open_passage': False,
            'swing': 'NW' if dtype == 'h' else 'NE'
        })


# ════════════════════════════════════════════════════════════
# SCORE  (V11 — adds ratio-bands, kitchen-vs-bedroom check, master-bath bonus)
# ════════════════════════════════════════════════════════════
BAD_LIVING_NEIGHBORS = {'bathroom'}
REQUIRES_EXTERIOR    = {'bedroom', 'living', 'balcony', 'kitchen'}


def score_plan_v11(rooms, BW, BH, target_area):
    if not rooms: return 1e9
    N = len(rooms)
    by_t = {}
    for r in rooms: by_t.setdefault(r.name, []).append(r)
    score = 0.0

    # ── overlap (hard) ────────────────────────────────────
    for i in range(N):
        for j in range(i+1, N):
            if rooms[i].is_protrusion or rooms[j].is_protrusion: continue
            ov = rooms[i].overlap_area(rooms[j])
            if ov > 0: score += ov * 800.0

    # ── area error  (V11-FIX-#10, #12 : NET indoor area) ──
    indoor_net = sum(r.area for r in rooms if r.name != 'balcony')
    score += abs(indoor_net - target_area) / max(target_area, 1.) * 20.0

    # ── coverage ────────────────────────────────────────
    indoor_gross = sum(r.gross_area for r in rooms if not r.is_protrusion)
    coverage = indoor_gross / max(BW * BH, 0.01)
    score += max(0., 0.78 - coverage) * 35.0

    # ── circulation reachability ─────────────────────────
    reach_frac, isolated = stage4_circulation(rooms)
    score += isolated * 500.0
    score += (1.0 - reach_frac) * 35.0

    # ── adjacency rules (soft) ───────────────────────────
    for dep, trg, wt in ADJACENCY_RULES:
        if dep not in by_t or trg not in by_t: continue
        for di in by_t[dep]:
            if not any(di.shares_wall(ti) for ti in by_t[trg]):
                score += wt * 40.0 / len(ADJACENCY_RULES)

    # ── bathroom must not touch living ───────────────────
    for bi in by_t.get('bathroom', []):
        for li in by_t.get('living', []):
            if bi.shares_wall(li): score += 120.0

    # ── balcony reality check ────────────────────────────
    for r in by_t.get('balcony', []):
        # Must be a protrusion AND must share a wall with living  (V11-FIX-#13)
        if not r.is_protrusion: score += 60.0
        if not any(r.shares_wall(l) for l in by_t.get('living', [])):
            score += 100.0
        # Balcony MUST NOT share a wall with kitchen / bedroom / bathroom / corridor (V11-FIX-#2)
        for bad in ('kitchen', 'bedroom', 'bathroom', 'corridor'):
            for x in by_t.get(bad, []):
                if r.shares_wall(x): score += 120.0

    # ── daylight (exterior-facing rooms) ─────────────────
    for name in ('living', 'bedroom', 'kitchen'):
        for r in by_t.get(name, []):
            if not r.touches_outer(BW, BH): score += 18.0

    # ── PER-ROOM ASPECT-RATIO BANDS  (V11-FIX-#14) ───────
    for r in rooms:
        if r.h < 0.1: continue
        ratio = r.w / r.h
        lo, hi = RATIO_BANDS.get(r.name, (0.30, 3.50))
        if ratio < lo or ratio > hi:
            # quadratic penalty — gets worse the further you stray
            dev = max(lo - ratio, ratio - hi)
            score += 40.0 + 100.0 * dev

    # ── MIN / MAX AREAS  (V11-FIX-#7, #8) ────────────────
    for r in rooms:
        if r.name == 'balcony': continue
        a = r.area
        mn = ROOM_MIN_AREA.get(r.name)
        mx = ROOM_MAX_AREA.get(r.name)
        if mn and a < mn: score += (mn - a) * 35.0
        if mx and a > mx: score += (a - mx) * 22.0

    # ── KITCHEN must be < SMALLEST BEDROOM  (V11-FIX-#8) ─
    if by_t.get('bedroom') and by_t.get('kitchen'):
        min_bed = min(r.area for r in by_t['bedroom'])
        max_kit = max(r.area for r in by_t['kitchen'])
        if max_kit >= min_bed:
            score += (max_kit - min_bed + 0.5) * 50.0

    # ── min dims ─────────────────────────────────────────
    for r in rooms:
        if r.is_protrusion: continue
        mn_w = ROOM_MIN_W.get(r.name, 1.0)
        mn_h = ROOM_MIN_H.get(r.name, 1.0)
        if r.w < mn_w * 0.82: score += 20.0
        if r.h < mn_h * 0.82: score += 20.0

    # ── living should be largest ─────────────────────────
    if by_t.get('living'):
        liv_a = max(r.area for r in by_t['living'])
        for r in rooms:
            if r.name not in ('living', 'balcony') and r.area > liv_a + 3.0:
                score += 12.0

    # ── plumbing cluster ─────────────────────────────────
    # V14.0 — REMOVED proximity penalty. Baths are now allowed to be
    # distributed across the plan (guest bath near entry/living,
    # master bath ensuite with master bedroom).
    baths = by_t.get('bathroom', [])

    # ── MASTER-BATH BONUS ───────────────────────────────
    # V13.1.2-PATCH-5: REMOVED the old V11-FIX-#7 bonus.
    # The deleted test rewarded any bathroom that geometrically shared a wall
    # with both a bedroom AND a corridor — but that geometry describes a
    # corridor-side bathroom with an incidental bedroom-wall, NOT a master
    # suite. The correct ensuite reward lives in score_plan_v12 (-25 for a
    # bathroom sharing a wall with a bedroom while NOT touching corridor),
    # keyed on the same geometry that stage9_doors_v11 honors via tag='ensuite'.
    # Keeping both bonuses caused double-counting and confused the optimizer.

    # ── alignment bonus ──────────────────────────────────
    misalign = 0
    for i in range(N):
        for j in range(i+1, N):
            ri, rj = rooms[i], rooms[j]
            for ei in (ri.x0, ri.x1, ri.y0, ri.y1):
                for ej in (rj.x0, rj.x1, rj.y0, rj.y1):
                    if 0.01 < abs(ei - ej) < 0.30: misalign += 1
    score += min(misalign * 0.8, 16.0)

    # ── V4 hard privacy penalties (kept) ─────────────────
    bed_liv_violations = sum(
        1 for bi in by_t.get('bedroom', [])
        for li in by_t.get('living', [])
        if bi.shares_wall(li))
    score += bed_liv_violations * 300.0

    cors = by_t.get('corridor', [])
    if cors:
        for bi in by_t.get('bathroom', []):
            # V13.1.2-PATCH-4 — exempt true ensuite baths from this penalty.
            # Old behavior: +300 for any bath not touching corridor. That
            # cancelled V12's -25 ensuite reward (net +275 against the very
            # design we wanted) and biased the engine toward corridor-side
            # bathrooms even when has_master_bath=True. Now ensuite-tagged
            # baths are corridor-isolated BY DESIGN and pay no penalty.
            if getattr(bi, 'tag', None) == 'ensuite':
                continue
            if not any(bi.shares_wall(c) for c in cors):
                score += 300.0
    else:
        score += 400.0

    if cors:
        c0 = cors[0]
        links_liv = any(c0.shares_wall(l) for l in by_t.get('living',   []))
        links_bed = any(c0.shares_wall(b) for b in by_t.get('bedroom',  []))
        links_bth = any(c0.shares_wall(b) for b in by_t.get('bathroom', []))
        links_kit = any(c0.shares_wall(k) for k in by_t.get('kitchen',  []))
        if links_liv and links_bed and links_bth: score -= 45.0
        if links_kit: score -= 20.0     # V11-FIX-#6 reward

    return score


# ════════════════════════════════════════════════════════════
# V13.1.2 — REACHABILITY + DEAD-SPACE HELPERS  (PATCH-6)
# ════════════════════════════════════════════════════════════
def _reachability_check(rooms):
    """V13.1.2 — every non-balcony, non-protrusion room must be reachable
    from the apartment entry door through the door graph. Catches:
      • storage rooms emitted without an outgoing door
      • bedrooms whose only door was suppressed by ensuite filtering
      • rooms isolated by BSP / merge edge cases
    Returns None on success, else a reason string for the gate.
    """
    if not rooms: return 'no rooms'

    entry_idx = None
    for i, r in enumerate(rooms):
        for d in r.doors:
            if d.get('entry'):
                entry_idx = i; break
        if entry_idx is not None: break
    if entry_idx is None:
        return 'no entry door placed'

    n = len(rooms)
    adj = {i: set() for i in range(n)}
    for i, r in enumerate(rooms):
        for d in r.doors:
            p = d.get('partner')
            if p is None: continue
            if not isinstance(p, int): continue
            if 0 <= p < n:
                adj[i].add(p); adj[p].add(i)

    # V13.2 — 'master_ext' is a geometric extension of the master bedroom
    # (the strip absorbed under the bath band). It is the SAME logical room,
    # so it is reachable through whichever bedroom it is contiguous with.
    # Wire it into the graph by full-wall adjacency (no door needed).
    for i, r in enumerate(rooms):
        if getattr(r, 'tag', None) != 'master_ext': continue
        for j, o in enumerate(rooms):
            if i == j: continue
            if o.name != 'bedroom': continue
            # shares a vertical wall with > 0.5m overlap?
            shares_v = ((abs(o.x1 - r.x0) < 0.06 or abs(r.x1 - o.x0) < 0.06)
                        and min(o.y1, r.y1) - max(o.y0, r.y0) > 0.5)
            shares_h = ((abs(o.y1 - r.y0) < 0.06 or abs(r.y1 - o.y0) < 0.06)
                        and min(o.x1, r.x1) - max(o.x0, r.x0) > 0.5)
            if shares_v or shares_h:
                adj[i].add(j); adj[j].add(i)

    seen = {entry_idx}
    stack = [entry_idx]
    while stack:
        u = stack.pop()
        for v in adj[u]:
            if v not in seen:
                seen.add(v); stack.append(v)

    for i, r in enumerate(rooms):
        if r.name == 'balcony':       continue
        if r.is_protrusion:           continue
        if i not in seen:
            return (f'{r.name} at ({r.x0:.1f},{r.y0:.1f}) {r.w:.1f}x{r.h:.1f} '
                    f'is sealed (no door path from entry)')
    return None


def _dead_space_total(rooms):
    """V13.1.2 — sum of indoor-envelope area NOT covered by any room.
    Uses the same axis-aligned grid trick as _absorb_orphan_strips but
    returns the total cumulative dead area instead of merging it.
    """
    indoor = [r for r in rooms if not r.is_protrusion]
    if not indoor: return 0.0
    BW = max(r.x1 for r in indoor)
    BH = max(r.y1 for r in indoor)
    xs = sorted({0.0, BW} | {r.x0 for r in indoor} | {r.x1 for r in indoor})
    ys = sorted({0.0, BH} | {r.y0 for r in indoor} | {r.y1 for r in indoor})
    total = 0.0
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            x0, x1 = xs[i], xs[i+1]
            y0, y1 = ys[j], ys[j+1]
            if x1 - x0 < 0.20 or y1 - y0 < 0.20: continue
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            covered = any(r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1 for r in indoor)
            if not covered:
                total += (x1 - x0) * (y1 - y0)
    return total


def _v12_livability_gate(rooms, target_area):
    """V16.2 — HARD reject layouts where any room is unlivable.
    Relaxed limits for wide rectangular and deep L-shaped layouts:
    - Allows bathroom areas up to 16.5m² (ensuite) / 14.5m² and ratio up to 4.8 / 4.2.
    - Allows secondary bedrooms to be up to 1.35x master bedroom sleeping chamber when ensuite is present.
    - Kitchen ratio and corridor share caps scaled for shape variety.
    """
    by_t = {}
    for r in rooms: by_t.setdefault(r.name, []).append(r)
    indoor_net = sum(r.area for r in rooms if r.name != 'balcony' and not r.is_protrusion)

    bed_min = 9.0 if indoor_net <= 80 else ROOM_MIN_AREA['bedroom']
    for r in by_t.get('bedroom', []):
        if r.w < 2.40 or r.h < 2.40:
            return f'bedroom dim {r.w:.2f}×{r.h:.2f} < 2.40 (too narrow)'
        if r.area < bed_min:
            return f'bedroom area {r.area:.1f} < {bed_min}'

    bedrooms = by_t.get('bedroom', [])
    master_bed = next((r for r in bedrooms if getattr(r, 'tag', None) == 'master'), None)
    if master_bed is not None:
        for r in bedrooms:
            if r is not master_bed and r.area > master_bed.area * 1.35 + 2.5:
                return (f'secondary bedroom ({r.area:.1f}m²) is larger than the '
                        f'master bedroom ({master_bed.area:.1f}m²)')

    corridor_area = sum(r.area for r in by_t.get('corridor', []))
    if indoor_net > 0:
        corridor_pct = corridor_area / indoor_net
        if corridor_pct > 0.22:
            return f'corridor takes {corridor_pct*100:.1f}% of the net area (> 22% hard limit)'

    for r in by_t.get('bathroom', []):
        is_ensuite = getattr(r, 'tag', None) == 'ensuite'
        max_area  = 16.5 if is_ensuite else 14.5
        max_ratio = 4.8  if is_ensuite else 4.2
        if r.area < ROOM_MIN_AREA['bathroom']:
            return f'bathroom too small ({r.area:.1f})'
        if r.area > max_area:
            return f'bathroom too large ({r.area:.1f} > {max_area})'
        if r.h > 0.01:
            ratio = r.w / r.h
            if ratio > max_ratio or ratio < 0.25:
                return f'bathroom ratio {ratio:.2f} unlivable (bowling-alley shape)'

    for r in by_t.get('living', []):
        if r.h > 0.01:
            ratio = r.w / r.h
            if ratio > 12.00 or ratio < 0.12:
                return f'living ratio {ratio:.2f} unlivable (corridor-shape)'

    for r in by_t.get('kitchen', []):
        if r.h > 0.01:
            ratio = r.w / r.h
            if ratio > 12.00 or ratio < 0.12:
                return f'kitchen ratio {ratio:.2f} unlivable'

    if indoor_net < 0.5: return 'no indoor area'

    has_dining_room = bool(by_t.get('dining'))
    n_corridor_rooms = len(by_t.get('corridor', []))
    for name, cap in AREA_SHARE_CAP.items():
        if name == 'living' and not has_dining_room:
            cap = _living_cap_frac(indoor_net)
        if name == 'corridor' and n_corridor_rooms >= 2:
            cap = 0.22
        tot = sum(r.area for r in by_t.get(name, []))
        if tot > cap * indoor_net + 1.0:
            return f'{name} share {tot/indoor_net:.0%} > cap {cap:.0%}'

    if by_t.get('living'):
        liv_a = max(r.area for r in by_t['living'])
        if liv_a < ROOM_MIN_AREA['living']:
            return f'living area {liv_a:.1f} < {ROOM_MIN_AREA["living"]}'

    indoor = [r for r in rooms if not r.is_protrusion]
    if indoor:
        BW_ = max(r.x1 for r in indoor)
        BH_ = max(r.y1 for r in indoor)
        def _touches_ext(rm):
            return (rm.x0 < 0.10 or rm.y0 < 0.10 or
                    rm.x1 > BW_ - 0.10 or rm.y1 > BH_ - 0.10)
        ext_corridors = [c for c in by_t.get('corridor', []) if _touches_ext(c)]
        ext_livings = [lv for lv in by_t.get('living', []) if _touches_ext(lv)]
        for r in by_t.get('kitchen', []):
            if _touches_ext(r): continue
            lit_via_living = any(r.shares_wall(lv) for lv in ext_livings)
            lit_via_corridor = any(r.shares_wall(c) for c in ext_corridors)
            if not (lit_via_living or lit_via_corridor):
                return f'kitchen at ({r.x0:.1f},{r.y0:.1f}) has no light/air'

    if by_t.get('bedroom') and by_t.get('kitchen'):
        min_bed = min(r.area for r in by_t['bedroom'])
        max_kit = max(r.area for r in by_t['kitchen'])
        if max_kit > 6.0 * min_bed:
            return f'kitchen {max_kit:.1f} >> smallest bedroom {min_bed:.1f} (>6.0×)'

    reach_fail = _reachability_check(rooms)
    if reach_fail is not None:
        return reach_fail

    # V16.7 Hard Foyer validation rule before rendering
    for r in rooms:
        if r.name == 'foyer':
            for bal in rooms:
                if bal.name in ('balcony', 'terrace', 'outdoor'):
                    if r.shares_wall(bal) or (max(r.x0, bal.x0) < min(r.x1, bal.x1) and max(r.y0, bal.y0) < min(r.y1, bal.y1)):
                        return f'unrealistic foyer: foyer connects to or overlaps balcony'
            for d in r.doors:
                if rooms[d['partner']].name in ('balcony', 'terrace', 'outdoor'):
                    return f'unrealistic foyer: foyer door connects to balcony'

    # V16.7 Hard Apartment Entrance Door validation rule before rendering
    entry_room = next((r for r in rooms if any(d.get('entry') for d in r.doors)), None)
    if entry_room is not None:
        if entry_room.name not in ('foyer', 'living'):
            return f'invalid entry door: entrance connects directly to {entry_room.name} (must be foyer or living)'

    return None


# ════════════════════════════════════════════════════════════
# STAGE 10 — OPTIMIZATION
# ════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════
def _absorb_orphan_strips(rooms, BW, BH):
    """V12 — find empty rectangles inside [0,BW]×[0,BH] that aren't covered by any
    non-protrusion room, and merge each one into the neighbour it shares the longest
    edge with. Used after _subdivide_service to clean up surplus strips below kitchen.

    Only merges into LIVING / FOYER (not kitchen — we already capped its size).
    Won't push a room past its ROOM_MAX_AREA.
    """
    indoor = [r for r in rooms if not r.is_protrusion]
    if not indoor: return rooms

    xs = sorted({0.0, BW} | {r.x0 for r in indoor} | {r.x1 for r in indoor})
    ys = sorted({0.0, BH} | {r.y0 for r in indoor} | {r.y1 for r in indoor})

    holes = []
    for i in range(len(xs)-1):
        for j in range(len(ys)-1):
            x0, x1 = xs[i], xs[i+1]
            y0, y1 = ys[j], ys[j+1]
            if x1 - x0 < 0.20 or y1 - y0 < 0.20: continue
            cx, cy = (x0+x1)/2, (y0+y1)/2
            inside = False
            for r in indoor:
                if r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1:
                    inside = True; break
            if not inside:
                holes.append((x0, y0, x1 - x0, y1 - y0))

    absorb_priority = ('living', 'foyer', 'corridor', 'dining', 'kitchen')

    def _max_area_for(name):
        if name == 'living': return 50.0
        if name == 'foyer':  return 12.0
        return ROOM_MAX_AREA.get(name, 999.0)

    for hx, hy, hw, hh in holes:
        if hw * hh < 0.3: continue
        # V16.3 — Do not absorb exterior corner notches (L-Shape and Wing Shape setbacks)!
        if (hx < 0.1 and hy + hh > BH - 0.1) or (hx + hw > BW - 0.1 and hy + hh > BH - 0.1):
            continue
        best, best_len, best_axis = None, 0.0, None
        for r in indoor:
            if r.name not in absorb_priority: continue
            if (r.w * r.h) + hw * hh > _max_area_for(r.name): continue
            if abs(r.x1 - hx) < 0.05:
                ovl = max(0.0, min(r.y1, hy+hh) - max(r.y0, hy))
                if ovl > best_len: best, best_len, best_axis = r, ovl, ('right', hx, hy, hw, hh)
            if abs(r.x0 - (hx+hw)) < 0.05:
                ovl = max(0.0, min(r.y1, hy+hh) - max(r.y0, hy))
                if ovl > best_len: best, best_len, best_axis = r, ovl, ('left',  hx, hy, hw, hh)
            if abs(r.y1 - hy) < 0.05:
                ovl = max(0.0, min(r.x1, hx+hw) - max(r.x0, hx))
                if ovl > best_len: best, best_len, best_axis = r, ovl, ('top',   hx, hy, hw, hh)
            if abs(r.y0 - (hy+hh)) < 0.05:
                ovl = max(0.0, min(r.x1, hx+hw) - max(r.x0, hx))
                if ovl > best_len: best, best_len, best_axis = r, ovl, ('bot',   hx, hy, hw, hh)

        merged = False
        if best is not None and best_len >= 0.5:
            side, hx, hy, hw, hh = best_axis
            if side == 'right' and hy <= best.y0 + 0.05 and hy + hh >= best.y1 - 0.05:
                best.w = round(hx + hw - best.x0, 4); merged = True
            elif side == 'left' and hy <= best.y0 + 0.05 and hy + hh >= best.y1 - 0.05:
                best.w = round(best.x1 - hx, 4); best.x0 = hx; merged = True
            elif side == 'top' and hx <= best.x0 + 0.05 and hx + hw >= best.x1 - 0.05:
                best.h = round(hy + hh - best.y0, 4); merged = True
            elif side == 'bot' and hx <= best.x0 + 0.05 and hx + hw >= best.x1 - 0.05:
                best.h = round(best.y1 - hy, 4); best.y0 = hy; merged = True
    return rooms


def stage9b_dead_space(rooms, BW, BH, tol=0.25):
    rooms = _absorb_orphan_strips(rooms, BW, BH)
    for r in rooms:
        if r.is_protrusion: continue
        if 0.0 < r.x0 < tol:           r.w  = round(r.w + r.x0, 3); r.x0 = 0.0
        if 0.0 < r.y0 < tol:           r.h  = round(r.h + r.y0, 3); r.y0 = 0.0
        if BW - tol < r.x1 < BW:       r.w  = round(BW - r.x0, 3)
        if BH - tol < r.y1 < BH:       r.h  = round(BH - r.y0, 3)
    return rooms



def score_plan_v12(rooms, BW, BH, target_area, _reason_out=None):
    """V12 score = HARD livability gate then V11 score with extra terms.

    Layouts that fail the livability gate get +∞ score and are dropped by stage 10.

    V13.1.1 diagnostic: if `_reason_out` is a list, the rejection reason
    (or None) is appended to it for downstream aggregation.
    """
    if not rooms:
        if _reason_out is not None: _reason_out.append('no_rooms')
        return float('inf')
    reason = _v12_livability_gate(rooms, target_area)
    if reason is not None:
        if _reason_out is not None: _reason_out.append(reason)
        return float('inf')
    if _reason_out is not None: _reason_out.append(None)

    score = score_plan_v11(rooms, BW, BH, target_area)

    # V13.2.1 — DIVERSITY REWARD. The optimizer minimizes score and was
    # converging every template to the SAME symmetric optimum (identical
    # bedrooms, identical baths), killing the jitter. Reward genuine variety:
    #   • bedrooms with DIFFERENT areas (a master + a smaller secondary)
    #   • baths with DIFFERENT areas (master bath + guest bath)
    # The reward is bounded so it cannot override hard livability terms.
    by_t0 = {}
    for r in rooms: by_t0.setdefault(r.name, []).append(r)
    beds0 = by_t0.get('bedroom', [])
    if len(beds0) >= 2:
        areas = sorted(r.area for r in beds0)
        spread = (areas[-1] - areas[0])
        score -= min(spread * 15.0, 120.0) # reward bedroom variety

    baths = by_t0.get('bathroom', [])
    if len(baths) >= 2:
        areas = sorted(r.area for r in baths)
        spread = (areas[-1] - areas[0])
        score -= min(spread * 20.0, 100.0) # reward bath variety

    by_t = by_t0
    cors = by_t.get('corridor', [])
    guest_baths = [b for b in baths if getattr(b, 'tag', '') in ('guest_bath', 'guest', 'guest_bath_living')]
    master_baths = [b for b in baths if getattr(b, 'tag', '') in ('master_bath', 'ensuite')]
    livings = by_t.get('living', [])
    # Reward: guest bath shares wall with corridor (accessible from entry side)
    if guest_baths and cors:
        for gb in guest_baths:
            if any(gb.shares_wall(c) for c in cors):
                score -= 15.0   # strong bonus: guest bath corridor-accessible
                break
    # Reward: guest bath shares wall with living (very open/convenient for guests)
    if guest_baths and livings:
        for gb in guest_baths:
            if any(gb.shares_wall(l) for l in livings):
                score -= 8.0
                break
    # Reward: master bath shares wall with master bedroom (ensuite)
    master_beds = [b for b in by_t.get('bedroom', []) if getattr(b, 'tag', '') == 'master']
    if master_baths and master_beds:
        for mb in master_baths:
            if any(mb.shares_wall(bd) for bd in master_beds):
                score -= 20.0   # strong bonus: master bath truly ensuite
                break
    # Foyer bonus
    if by_t.get('foyer'):
        score -= 8.0

    # V13.1.1 — soft penalty for kitchen ≥ smallest bedroom (replaces V12 hard reject)
    if by_t.get('bedroom') and by_t.get('kitchen'):
        min_bed = min(r.area for r in by_t['bedroom'])
        max_kit = max(r.area for r in by_t['kitchen'])
        if max_kit >= min_bed:
            excess = max_kit - min_bed
            score += 8.0 * excess  # ~8 points per m² over

    # V13.1.1b — soft penalty for narrow bedrooms (2.40-2.79m).
    # Bedrooms below 2.40m are hard-rejected by the gate.
    for r in by_t.get('bedroom', []):
        min_dim = min(r.w, r.h)
        if min_dim < 2.80:
            shortfall = 2.80 - min_dim
            score += 25.0 * shortfall  # 25 points per cm of narrowness

    return score


score_plan_v10 = score_plan_v12



# V13.1.2-PATCH-7 — STORAGE-DOOR SAFETY NET (stage9c)
# ════════════════════════════════════════════════════════════
def stage9c_storage_doors(rooms):
    # Safety net is now a no-op as stage9_doors_v11 guarantees full tree connectivity and 1-to-1 match!
    return rooms

def _run_one_v11(n_bed, n_bath, n_kit, has_bal, target_area,
                  template, seed, hint=None, _reason_out=None,
                  has_dining=False, has_master_bath=False,
                  bath_layout=None, has_dressing=False):
    # bath_layout (when given) decides the actual subdivision strategy;
    # has_master_bath here only needs to tell stage2 whether the PRIVATE
    # zone needs the taller "suite" floor height (true for either ensuite
    # strategy, false for the classic corridor-both layout).
    _zone_master_flag = (has_master_bath if bath_layout is None
                         else bath_layout != 'corridor_both')
    rng = np.random.default_rng(seed * 41 + TEMPLATES.index(template) * 7)
    BW, BH = stage1_site(target_area, n_bed, seed, hint)
    h_ok, _ = validate_hints_v4(hint, BW)
    zones = stage2_zones_v11(BW, BH, n_bed, n_bath, n_kit, has_bal, template,
                             rng, h_ok, has_dining, _zone_master_flag, target_area)
    if zones.get('_physically_impossible_notch'):
        if _reason_out is not None: _reason_out.append('physically_impossible_notch')
        return None, BW, BH, float('inf')
    rooms = stage6_subdivide_v11(zones, n_bed, n_bath, n_kit, template, rng,
                                 target_area, has_master_bath, bath_layout, has_dressing)
    if not rooms:
        if _reason_out is not None: _reason_out.append('stage6_no_rooms')
        return None, BW, BH, float('inf')
    rooms, BW, BH = stage7_geometry(rooms, BW, BH, target_area)
    rooms         = stage7b_bfs_polish(rooms)
    rooms         = stage9b_dead_space(rooms, BW, BH)
    rooms         = stage8_windows(rooms, BW, BH)
    rooms         = stage9_doors_v11(rooms, has_master_bath=has_master_bath)
    rooms         = stage9c_storage_doors(rooms)   # V13.1.2-PATCH-7 safety net
    # V16.7 Hard architectural constraint: final layout must always contain exact requested bathroom and bedroom count
    baths = [r for r in rooms if r.name == 'bathroom']
    beds = [r for r in rooms if r.name == 'bedroom']
    if len(baths) != max(n_bath, 1):
        if _reason_out is not None: _reason_out.append(f'hard constraint: generated baths ({len(baths)}) != requested ({n_bath})')
        return None, BW, BH, float('inf')
    if len(beds) != max(n_bed, 1):
        if _reason_out is not None: _reason_out.append(f'hard constraint: generated beds ({len(beds)}) != requested ({n_bed})')
        return None, BW, BH, float('inf')
    return rooms, BW, BH, score_plan_v12(rooms, BW, BH, target_area, _reason_out)


def generate_arch_plans_v11(n_bed, n_bath, n_kit, has_bal, target_area,
                             n_options=4, n_attempts=14, use_gan_hint=False,
                             has_dining=False, has_master_bath=False,
                             seed=0):
    """V12 — always sweeps ALL templates (classic / split / corridor / wing) so the
    hard-livability gate can elect the winner. Single-seed-per-template runs are
    typically rejected by the gate at smaller areas, so n_attempts ≥ 14 is
    recommended.

    V13.1.1e new flags:
      has_dining      — if True a separate dining room is created; if False
                        (default) the dining area is folded into the living
                        room (open-plan reception).
      has_master_bath — if True one bathroom becomes an en-suite opening only
                        from the master bedroom; the other stays a guest bath
                        on the corridor. If False both baths are on the corridor.
    """
    # NOTE: this deployment is deterministic/procedural only — the trained
    # GAN checkpoint is intentionally NOT loaded here, so use_gan_hint is
    # always treated as False regardless of the argument passed in. (This
    # function is unused by generate_one/generate_options — kept only for
    # completeness/compatibility.)
    hint = None
    if use_gan_hint:
        print('  [GAN hint] disabled in this deployment → V4 filter only')

    print(f'  [options] has_dining={has_dining}  has_master_bath={has_master_bath}')

    guided_n = n_attempts // 2
    random_n = n_attempts - guided_n
    results  = []
    # V15.9 — TOPOLOGY is now chosen by the area band FIRST, not swept
    # across all templates and left to the score/gate to "fix" by scaling
    # whatever wins. Different area bands genuinely try different shapes.
    allowed_templates =_templates_for_program(target_area, n_bed, n_bath)
    n_options = max(n_options, len(allowed_templates))
    print(f'  [area-band] target_area={target_area}  allowed templates: '
          f'{allowed_templates}')
    # V13.7 — the user `seed` now actually changes the output. It offsets the
    # internal attempt indices, so different seeds explore a DIFFERENT band of
    # the BSP jitter space and return genuinely different layouts. Previously
    # the attempt indices were a fixed 0..n_attempts range and the engine was
    # fully deterministic — changing seed did nothing (diversity-across-seeds=0).
    seed_off = int(seed) * 1009   # large stride so seed bands don't overlap

    for tmpl in allowed_templates[:n_options]:
        best = (None, 0, 0, float('inf'))
        rejected = 0
        reasons = []   # V13.1.1 diagnostic — collect rejection reasons
        for attempt in range(guided_n):
            rooms, BW, BH, sc = _run_one_v11(n_bed, n_bath, n_kit, has_bal,
                                              target_area, tmpl, seed_off + attempt, hint, reasons,
                                              has_dining, has_master_bath)
            if sc == float('inf'): rejected += 1; continue
            if rooms and sc < best[3]: best = (rooms, BW, BH, sc)
        for attempt in range(guided_n, guided_n + random_n):
            rooms, BW, BH, sc = _run_one_v11(n_bed, n_bath, n_kit, has_bal,
                                              target_area, tmpl, seed_off + attempt, None, reasons,
                                              has_dining, has_master_bath)
            if sc == float('inf'): rejected += 1; continue
            if rooms and sc < best[3]: best = (rooms, BW, BH, sc)
        marker = '✓' if best[0] is not None else '✗'
        print(f'  [template {tmpl:8s}] {marker}  best={best[3] if best[3]<1e8 else "rejected"}'
              f'  livability-rejects={rejected}/{n_attempts}')

        # V13.1.1 — print top rejection reasons for failed/marginal templates
        if rejected >= n_attempts // 2:
            # Truncate detailed numeric values for clean grouping
            cleaned = []
            for r in reasons:
                if r is None: continue
                # Strip numeric values to group by reason type
                cleaned.append(' '.join(
                    'N' if any(c.isdigit() for c in tok) and '.' in tok else tok
                    for tok in r.split()
                ))
            from collections import Counter
            top = Counter(cleaned).most_common(3)
            for reason, cnt in top:
                print(f'      reject ×{cnt:>2}: {reason}')

        if best[0] is not None: results.append((*best, tmpl))

    results.sort(key=lambda x: x[3])
    return results


# Back-compat aliases so cells 8/9 keep working with V11 naming.
stage2_zones_v10        = stage2_zones_v11
stage6_subdivide_v10    = stage6_subdivide_v11
stage9_doors_v10        = stage9_doors_v11
generate_arch_plans_v10 = generate_arch_plans_v11
# V12 entry-point aliases
generate_arch_plans_v12 = generate_arch_plans_v11
score_plan              = score_plan_v12


print('═' * 64)
print('  V13.6 ARCHITECTURAL ENGINE — DESIGN/GATE CONSISTENCY + RIGOROUS BATH GATE — loaded ✓')
print('═' * 64)
print('  V13.1.2.1 patches over V13.1.2:')
print('    PATCH-2.1  storage edge threshold 0.85m → 1.15m (matches DOOR_W_M+margin)')
print('    PATCH-6b.1 dead-space gate 2.0m² → 3.0m² (allows small tile strips)')
print('    PATCH-7    stage9c_storage_doors — safety net door-emission for storage')
print('  Net effect: storage rooms ALWAYS get a door, no more "sealed" rejections.')
print('')
print('  V13.1.2 patches (still active):')
print('    PATCH-1  Hierarchical grid (GRID_FINE=0.10m) — jitter survives snap')
print('    PATCH-2  Storage emission tightened: min_dim≥1.20m + door-edge required')
print('    PATCH-3  Merge priority broadened (+corridor/kitchen/dining)')
print('    PATCH-4  +300 bath-corridor penalty NOW exempts ensuite-tagged baths')
print('    PATCH-5  Removed fake V11-FIX-#7 master-bath bonus (V12 has correct one)')
print('    PATCH-6  HARD reachability gate (BFS from entry door)')
print('    PATCH-6b HARD dead-space gate')
print('')
print('  V13.1.1g templates retained:')
print('    • wing       — kitchen column on the RIGHT, living on the left')
print('    • wing-split — kitchen left, living middle, study/store right')
print('    • wing-stack — kitchen + storage stacked in a right column')
print('  Entry : generate_arch_plans_v12(n_bed, n_bath, n_kit, has_bal, area,')
print('                                  has_dining=False, has_master_bath=False)')
