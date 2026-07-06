# CELL 7: PROFESSIONAL ARCHITECTURAL RENDERER + FLUSH EGYPTIAN COLUMNS
# ═══════════════════════════════════════════════════════════════════════
import math
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle, Arc, Polygon as MplPolygon, Circle, FancyBboxPatch
from matplotlib.lines import Line2D

WALL_T = 0.15

WALL_COLOR, INNER_COLOR, FURN_COLOR, FURN_FILL = '#1A1A1A', '#2C2C2C', '#555555', '#FFFFFF'
DIM_COLOR, WIN_FILL, WIN_LINE = '#9B2A1F', '#AED6F1', '#2471A3'
DOOR_COLOR, DOOR_ARC, ENTRY_COLOR, ENTRY_ARC = '#2E7D32', '#2E7D32', '#B7791F', '#B7791F'
TAG_TEXT, TAG_SUBTEXT, TAG_RULE, CORRIDOR_HATCH_COLOR = '#1A1A1A', '#666666', '#999999', '#7E57C2'

OUTER_WALL_LW, INNER_WALL_LW, FURNITURE_LW, SWING_LW, DIM_LW, WIN_LW, WIN_DEPTH = 5.5, 2.0, 0.7, 0.6, 0.5, 2.2, 0.06

ROOM_HATCH = {
    'bathroom': ('....', 0.30, '#5C8A88'), 'foyer'   : ('||',   0.18, '#B7791F'),
    'corridor': ('///',  0.30, '#7E57C2'), 'balcony' : ('++',   0.20, '#9B8B2C'),
}

def _door_geometry(d):
    w, swing = d['w'], d.get('swing', 'NE')
    if d['type'] == 'h':
        x, y = d['x'], d['y']
        if swing == 'NE':   return (x,y), (x,y+w), (x,y), 2*w, 2*w, 0, 90
        elif swing == 'NW': return (x+w,y), (x+w,y+w), (x+w,y), 2*w, 2*w, 90, 180
        elif swing == 'SE': return (x,y), (x,y-w), (x,y), 2*w, 2*w, 270, 360
        else:               return (x+w,y), (x+w,y-w), (x+w,y), 2*w, 2*w, 180, 270
    else:
        x, y = d['x'], d['y']
        if swing == 'NE':   return (x,y), (x+w,y), (x,y), 2*w, 2*w, 0, 90
        elif swing == 'NW': return (x,y+w), (x+w,y+w), (x,y+w), 2*w, 2*w, 270, 360
        elif swing == 'SE': return (x,y), (x-w,y), (x,y), 2*w, 2*w, 90, 180
        else:               return (x,y+w), (x-w,y+w), (x,y+w), 2*w, 2*w, 180, 270

def _interior_box(r, pad=0.10):
    inset = WALL_T * 0.5 + pad
    return (r.x0 + inset, r.y0 + inset, r.x1 - inset, r.y1 - inset)

def _furn_rect(ax, x, y, w, h, fc=None, lw=None, zorder=6, ls='-'):
    ax.add_patch(Rectangle((x, y), w, h, fc=fc or FURN_FILL, ec=FURN_COLOR, lw=lw or FURNITURE_LW, ls=ls, zorder=zorder))

def _furn_circle(ax, cx, cy, rad, fc=None, lw=None, zorder=6):
    ax.add_patch(Circle((cx, cy), rad, fc=fc or FURN_FILL, ec=FURN_COLOR, lw=lw or FURNITURE_LW, zorder=zorder))

def _furn_bed(ax, r, is_master=False):
    ix0, iy0, ix1, iy1 = _interior_box(r, pad=0.12)
    iw, ih = ix1 - ix0, iy1 - iy0
    if iw < 1.50 or ih < 1.50: return
    BED_W, BED_L, NS = 1.60 if is_master else 1.20, 2.00, 0.45
    if ih >= iw:
        bw, bl = min(BED_W, iw - 0.30), min(BED_L, ih - 0.50)
        bx, by = ix0 + (iw - bw) / 2, iy1 - bl - 0.20
        _furn_rect(ax, bx, by, bw, bl)
        ax.plot([bx + 0.12, bx + bw - 0.12], [by + bl - 0.30] * 2, color=FURN_COLOR, lw=FURNITURE_LW, zorder=7)
        ax.plot([bx + 0.12, bx + bw - 0.12], [by + 0.55] * 2, color=FURN_COLOR, lw=FURNITURE_LW * 0.7, zorder=7, ls=(0,(3,2)))
    else:
        bw, bl = min(BED_L, iw - 0.50), min(BED_W, ih - 0.30)
        bx, by = ix1 - bw - 0.20, iy0 + (ih - bl) / 2
        _furn_rect(ax, bx, by, bw, bl)
        ax.plot([bx + bw - 0.30] * 2, [by + 0.12, by + bl - 0.12], color=FURN_COLOR, lw=FURNITURE_LW, zorder=7)
        ax.plot([bx + 0.55] * 2, [by + 0.12, by + bl - 0.12], color=FURN_COLOR, lw=FURNITURE_LW * 0.7, zorder=7, ls=(0,(3,2)))

def _furn_living(ax, r):
    ix0, iy0, ix1, iy1 = _interior_box(r, pad=0.15)
    iw, ih = ix1 - ix0, iy1 - iy0
    if iw < 2.20 or ih < 2.20: return
    if iw >= ih:
        sofa_w, sofa_d = min(2.40, iw - 0.80), 0.85
        sx, sy = ix0 + (iw - sofa_w) / 2, iy0 + 0.05
        _furn_rect(ax, sx, sy, sofa_w, sofa_d)
    else:
        sofa_w, sofa_l = 0.85, min(2.40, ih - 0.80)
        sx, sy = ix0 + 0.05, iy0 + (ih - sofa_l) / 2
        _furn_rect(ax, sx, sy, sofa_w, sofa_l)

def _furn_kitchen(ax, r):
    ix0, iy0, ix1, iy1 = _interior_box(r, pad=0.05)
    if ix1 - ix0 < 1.80 or iy1 - iy0 < 1.80: return
    _furn_rect(ax, ix0, iy0, ix1 - ix0, 0.60, fc='#F0EBE0')
    _furn_rect(ax, ix0, iy0, 0.60, iy1 - iy0, fc='#F0EBE0')

def _furn_bathroom(ax, r):
    ix0, iy0, ix1, iy1 = _interior_box(r, pad=0.08)
    if ix1 - ix0 < 1.20 or iy1 - iy0 < 1.20: return
    _furn_rect(ax, ix0, iy1 - 0.42, 0.55, 0.42, fc='#E8EEF2')

def _draw_furniture(ax, r):
    if r.is_protrusion or r.area < 2.0: return
    if r.name == 'bedroom': _furn_bed(ax, r, is_master=(getattr(r, 'tag', None) == 'master'))
    elif r.name == 'living': _furn_living(ax, r)
    elif r.name == 'kitchen': _furn_kitchen(ax, r)
    elif r.name == 'bathroom': _furn_bathroom(ax, r)

def _draw_window(ax, side, r, zorder=7):
    if not r.windows: return
    for s, wlen in r.windows:
        if s != side: continue
        if s in ('bottom', 'top'):
            x, y = r.cx - wlen / 2, r.y0 if s == 'bottom' else r.y1
            ax.plot([x, x + wlen], [y] * 2, color=WIN_LINE, lw=WIN_LW, solid_capstyle='butt', zorder=zorder)
        else:
            y, x = r.cy - wlen / 2, r.x0 if s == 'left' else r.x1
            ax.plot([x] * 2, [y, y + wlen], color=WIN_LINE, lw=WIN_LW, solid_capstyle='butt', zorder=zorder)

def _draw_door(ax, d, zorder=8):
    if d['type'] == 'h':
        ax.plot([d['x'], d['x'] + d['w']], [d['y'], d['y']], color='white', lw=3, solid_capstyle='butt', zorder=zorder - 1)
    else:
        ax.plot([d['x'], d['x']], [d['y'], d['y'] + d['w']], color='white', lw=3, solid_capstyle='butt', zorder=zorder - 1)

    if d.get('open_passage'):
        if d['type'] == 'h': ax.plot([d['x'], d['x'] + d['w']], [d['y'], d['y']], color=INNER_COLOR, lw=0.8, ls='--', zorder=zorder)
        else: ax.plot([d['x'], d['x']], [d['y'], d['y'] + d['w']], color=INNER_COLOR, lw=0.8, ls='--', zorder=zorder)
        return
    if d.get('is_sliding'):
        sw = d['w'] / 2
        if d['type'] == 'h':
            ax.plot([d['x'], d['x'] + sw], [d['y'], d['y']], color=WIN_LINE, lw=1.5, zorder=zorder)
            ax.plot([d['x'] + sw, d['x'] + d['w']], [d['y'], d['y']], color=WIN_LINE, lw=1.5, zorder=zorder)
        else:
            ax.plot([d['x'], d['x']], [d['y'], d['y'] + sw], color=WIN_LINE, lw=1.5, zorder=zorder)
            ax.plot([d['x'], d['x']], [d['y'] + sw, d['y'] + d['w']], color=WIN_LINE, lw=1.5, zorder=zorder)
        return

    hinge, leaf_end, arc_centre, arc_w, arc_h, theta1, theta2 = _door_geometry(d)
    is_entry = d.get('entry', False)
    ax.plot([hinge[0], leaf_end[0]], [hinge[1], leaf_end[1]], color=ENTRY_COLOR if is_entry else DOOR_COLOR, lw=2.0 if is_entry else 1.4, zorder=zorder)
    ax.add_patch(Arc(arc_centre, arc_w, arc_h, angle=0, theta1=theta1, theta2=theta2, color=ENTRY_ARC if is_entry else DOOR_ARC, lw=SWING_LW, linestyle='--', zorder=zorder))
    if is_entry:
        cx = (d['x'] + d['x'] + d['w']) / 2 if d['type'] == 'h' else d['x']
        cy = d['y'] if d['type'] == 'h' else (d['y'] + d['y'] + d['w']) / 2
        ax.plot(cx, cy, marker='v' if d['type'] == 'h' else '<', ms=6, color=ENTRY_COLOR, zorder=zorder + 1)

def _draw_room_tag(ax, r, n_baths=2, zorder=10):
    import matplotlib.patheffects as pe
    halo = [pe.withStroke(linewidth=3.5, foreground='white', alpha=0.95)]
    tag = r.name.upper()
    rtag = getattr(r, 'tag', None)
    if r.name == 'living':
        if hasattr(ax, '_rooms_list'):
            max_liv = max([rm for rm in ax._rooms_list if rm.name == 'living'], key=lambda x: x.area)
            if r is not max_liv: return

    if r.name == 'bedroom' and rtag == 'master': tag = 'MASTER\nBEDROOM'
    elif r.name == 'bathroom' and rtag == 'ensuite': tag = 'EN-SUITE\nBATH'
    elif r.name == 'bathroom' and rtag in ('guest_bath', 'guest_bath_living'):
        tag = 'BATH' if n_baths == 1 else 'GUEST\nBATH'
    elif r.name == 'storage' and rtag == 'dressing': tag = 'DRESSING\nROOM'

    fs_name, fs_area, rule_half = 7.5, 6.0, 0.40
    ax.text(r.cx, r.cy + 0.25, tag, ha='center', va='center', fontsize=fs_name, fontweight='bold', color=TAG_TEXT, zorder=zorder, path_effects=halo)
    ax.plot([r.cx - rule_half, r.cx + rule_half], [r.cy - 0.04] * 2, color=TAG_RULE, lw=0.5, zorder=zorder)
    ax.text(r.cx, r.cy - 0.22, f'{r.area:.1f} m²', ha='center', va='center', fontsize=fs_area, color=TAG_SUBTEXT, zorder=zorder, style='italic', path_effects=halo)
    ax.text(r.cx, r.cy - 0.45, f'{r.w:.2f} × {r.h:.2f} m', ha='center', va='center', fontsize=fs_area*0.85, color=TAG_SUBTEXT, zorder=zorder, path_effects=halo)

def _envelope_outline(rooms):
    """V16.3 — Returns the TRUE outer boundary polygon of the building envelope
    using Shapely union and mitre buffering. Respects L-Shape and Wing setbacks."""
    try:
        from shapely.geometry import box
        from shapely.ops import unary_union
        interior = [r for r in rooms if not r.is_protrusion]
        if not interior: return None
        boxes = [box(r.x0, r.y0, r.x1, r.y1) for r in interior]
        u = unary_union(boxes)
        # Buffer outward by WALL_T with mitre join (join_style=2) for architectural corners
        buf = u.buffer(WALL_T, join_style=2)
        if buf.geom_type == 'Polygon':
            return list(buf.exterior.coords)
        elif buf.geom_type == 'MultiPolygon':
            return list(buf.geoms[0].exterior.coords)
    except Exception:
        pass
    interior = [r for r in rooms if not r.is_protrusion]
    if not interior: return None
    x0, y0 = min(r.x0 for r in interior), min(r.y0 for r in interior)
    x1, y1 = max(r.x1 for r in interior), max(r.y1 for r in interior)
    return [(x0 - WALL_T, y0 - WALL_T), (x1 + WALL_T, y0 - WALL_T), (x1 + WALL_T, y1 + WALL_T), (x0 - WALL_T, y1 + WALL_T)]

# ─── دالة الأعمدة المدفونة الذكية (Flush Columns) ───────────────────────────
def _draw_egyptian_columns(ax, rooms):
    """رسم أعمدة متوافقة مع الحائط ولا تبرز خارج المخطط"""
    intersections = []
    for r in rooms:
        if r.is_protrusion: continue
        intersections.extend([(r.x0, r.y0), (r.x1, r.y0), (r.x0, r.y1), (r.x1, r.y1)])

    unique_corners = []
    for c in intersections:
        if not any(math.hypot(c[0]-u[0], c[1]-u[1]) < 0.2 for u in unique_corners):
            unique_corners.append(c)

    BW = max((r.x1 for r in rooms if not r.is_protrusion), default=10)
    BH = max((r.y1 for r in rooms if not r.is_protrusion), default=10)

    for cx, cy in unique_corners:
        hit_opening = False
        for r in rooms:
            for d in r.doors:
                if d['type'] == 'h' and abs(cy - d['y']) < 0.3 and d['x']-0.2 < cx < d['x']+d['w']+0.2: hit_opening = True
                if d['type'] == 'v' and abs(cx - d['x']) < 0.3 and d['y']-0.2 < cy < d['y']+d['w']+0.2: hit_opening = True
            for side, wlen in r.windows:
                if side in ('bottom', 'top') and abs(cy - (r.y0 if side=='bottom' else r.y1)) < 0.3 and r.cx-wlen/2-0.2 < cx < r.cx+wlen/2+0.2: hit_opening = True
                if side in ('left', 'right') and abs(cx - (r.x0 if side=='left' else r.x1)) < 0.3 and r.cy-wlen/2-0.2 < cy < r.cy+wlen/2+0.2: hit_opening = True
        if hit_opening: continue

        is_edge_y = (cy < 0.1 or cy > BH - 0.1)
        is_edge_x = (cx < 0.1 or cx > BW - 0.1)

        if is_edge_y and not is_edge_x: orient_h = True
        elif is_edge_x and not is_edge_y: orient_h = False
        else: orient_h = (int(cx * 100 + cy * 10) % 2 == 0)

        # سمك العمود = 0.15 ليكون موازي للحائط تماماً
        cw, ch = (0.50, 0.15) if orient_h else (0.15, 0.50)

        rx, ry = cx - cw/2, cy - ch/2

        # إزاحة العمدان عشان متطلعش بره حدود الشقة
        if orient_h:
            if cx < 0.1: rx = cx - 0.075
            elif cx > BW - 0.1: rx = cx - cw + 0.075
        else:
            if cy < 0.1: ry = cy - 0.075
            elif cy > BH - 0.1: ry = cy - ch + 0.075

        ax.add_patch(Rectangle((rx, ry), cw, ch, fc=WALL_COLOR, ec='none', zorder=9))

ROOM_COLORS = {'living':'#FFFDE7', 'bedroom':'#DDEEFF', 'kitchen':'#E8F5E9', 'bathroom':'#E0F2F1', 'balcony':'#FFF9C4', 'corridor':'#EDE7F6', 'foyer':'#FFF3E0', 'dining':'#FFF8E1'}

def render_plan_v11(rooms, BW, BH, net_area=None, title='', save_path=None):
    if not rooms: return None
    ext_x0, ext_y0 = min(r.x0 for r in rooms), min(r.y0 for r in rooms)
    ext_x1, ext_y1 = max(r.x1 for r in rooms), max(r.y1 for r in rooms)
    margin = max(1.2, min(ext_x1 - ext_x0, ext_y1 - ext_y0) * 0.15)
    fig_w, fig_h = max(10, (ext_x1 - ext_x0) + 2 * margin + 1.5), max(8,  (ext_y1 - ext_y0) + 2 * margin + 1.5)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=150)
    ax.set_facecolor('#FAFAFA'); fig.patch.set_facecolor('white')
    ax.set_aspect('equal')

    n_baths = sum(1 for rm in rooms if rm.name == 'bathroom')

    for r in rooms:
        fc = ROOM_COLORS.get(r.name, '#F5F5F5')
        ax.add_patch(Rectangle((r.x0 + WALL_T / 2, r.y0 + WALL_T / 2), max(0.1, r.w - WALL_T), max(0.1, r.h - WALL_T), fc=fc, ec='none', zorder=1))

    for r in rooms: ax.add_patch(Rectangle((r.x0, r.y0), r.w, r.h, fc='none', ec=INNER_COLOR, lw=INNER_WALL_LW, zorder=3))

    _draw_egyptian_columns(ax, rooms)

    for r in rooms: _draw_furniture(ax, r)
    ax._rooms_list = rooms
    for r in rooms: _draw_room_tag(ax, r, n_baths=n_baths, zorder=10)

    for r in rooms:
        for s, _ in r.windows: _draw_window(ax, s, r, zorder=7)
        for d in r.doors: _draw_door(ax, d, zorder=8)

    pts = _envelope_outline(rooms)
    if pts: ax.add_patch(MplPolygon(pts, closed=True, fill=False, ec=WALL_COLOR, lw=OUTER_WALL_LW, zorder=5, joinstyle='miter'))

    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values(): sp.set_visible(False)

    indoor = [r for r in rooms if r.name != 'balcony']
    net_m2 = sum(r.area for r in indoor)
    ax.set_title(f'{title} | NET {net_m2:.1f}m²', fontsize=10, fontweight='bold', pad=14)
    ax.set_xlim(ext_x0 - margin, ext_x1 + margin)
    ax.set_ylim(ext_y0 - margin, ext_y1 + margin)
    plt.tight_layout()

    if save_path: fig.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.show()
    return fig

render_plan_v10 = render_plan_v11
