# app.py — Flask API for the ResPlan procedural floor-plan generator (V16.2).
#
# This server NEVER loads the trained GAN/GNN checkpoint. Every layout is
# produced by the deterministic rule-based engine extracted from the
# notebook (planning_engine.py + renderer.py), wrapped by generator.py's
# generate_options() (V16.2 SHAPE VARIETY & ENTRY DOORS).
#
# IMAGE DELIVERY: real PNG files served at their own URL — NOT base64.
# /generate renders each option, saves its PNG to a short-lived disk cache,
# and returns JSON metadata where each option has an "image_url" you open
# directly (in a browser, an <img> tag, or Swagger's response viewer) to
# see the actual image bytes.
#
# Endpoints
# ─────────
# GET  /health
#       -> {"status": "ok"}
#
# GET|POST /generate
#       GET  : params as query string
#       POST : params as a JSON request body (use this in Swagger's
#              "Request body" box)
#
#       Params: n_bed, n_bath, n_kit, has_bal, area, has_master_bath,
#               has_dining, has_dressing, n_options (1-3), n_attempts, seed
#               (same meaning as before)
#
#       -> JSON: {"request_id": "...", "options": [
#            {"ok": true, "image_url": "/image/<request_id>/1.png",
#             "shape": "square", "template": "wing-split", ...plan data},
#            ...
#          ]}
#          (no image bytes/base64 in this response — fetch image_url
#          separately to get the actual PNG)
#
# GET /image/<request_id>/<filename>
#       -> raw image/png bytes for one option from a previous /generate call
# ──────────────────────────────────────────────────────────────────────────

import os
import time
import uuid
from pathlib import Path

from flask import Flask, request, jsonify, send_file, abort
from flasgger import Swagger

from generator import generate_options

app = Flask(__name__)

CACHE_DIR = Path('/tmp/resplan_cache')
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_SECONDS = 30 * 60  # purge anything older than 30 minutes

app.config['SWAGGER'] = {
    'title': 'ResPlan Floor Plan API',
    'uiversion': 3,
    'specs_route': '/apidocs/',
}

_BODY_SCHEMA = {
    'type': 'object',
    'properties': {
        'n_bed':           {'type': 'integer', 'example': 2, 'description': 'Number of bedrooms (1-4)'},
        'n_bath':          {'type': 'integer', 'example': 2, 'description': 'Number of bathrooms (1-3)'},
        'n_kit':           {'type': 'integer', 'example': 1, 'description': 'Number of kitchens (0-1)'},
        'has_bal':         {'type': 'boolean', 'example': True, 'description': 'Include a protruding balcony'},
        'area':            {'type': 'number',  'example': 100, 'description': 'Target NET interior area in m²'},
        'has_master_bath': {'type': 'boolean', 'example': False, 'description': 'En-suite bath for the master bedroom'},
        'has_dining':      {'type': 'boolean', 'example': True, 'description': 'Include a separate dining room'},
        'has_dressing':    {'type': 'boolean', 'example': False, 'description': 'Include a dressing area in the master suite'},
        'n_options':       {'type': 'integer', 'example': 3, 'description': '1-3 distinct layouts (one per shape where possible)'},
        'n_attempts':      {'type': 'integer', 'example': 25, 'description': 'Attempts per template x bath-strategy x shape combo (max 60)'},
        'seed':            {'type': 'integer', 'example': 0, 'description': 'Optional — omit for a random valid layout each call'},
    },
}

swagger_template = {
    'swagger': '2.0',
    'info': {
        'title': 'ResPlan Floor Plan API',
        'description': 'Procedural (non-GAN) floor-plan generator with input '
                        'validation. /generate first checks whether the '
                        'requested program can physically fit the requested '
                        'area (HTTP 400 if not, with a suggested area range); '
                        'otherwise it returns JSON with an image_url per '
                        'option — open that URL to get the real PNG file '
                        '(no base64).',
        'version': '5.0.0',
    },
    'paths': {
        '/health': {
            'get': {'summary': 'Health check', 'responses': {'200': {'description': 'OK'}}}
        },
        '/generate': {
            'get': {
                'summary': 'Generate floor plan options (query params) — returns image_url per option',
                'parameters': [
                    {'name': 'n_bed', 'in': 'query', 'type': 'integer', 'default': 2},
                    {'name': 'n_bath', 'in': 'query', 'type': 'integer', 'default': 1},
                    {'name': 'n_kit', 'in': 'query', 'type': 'integer', 'default': 1},
                    {'name': 'has_bal', 'in': 'query', 'type': 'boolean', 'default': True},
                    {'name': 'area', 'in': 'query', 'type': 'number', 'default': 75.0},
                    {'name': 'has_master_bath', 'in': 'query', 'type': 'boolean', 'default': False},
                    {'name': 'has_dining', 'in': 'query', 'type': 'boolean', 'default': False},
                    {'name': 'has_dressing', 'in': 'query', 'type': 'boolean', 'default': False},
                    {'name': 'n_options', 'in': 'query', 'type': 'integer', 'default': 3},
                    {'name': 'n_attempts', 'in': 'query', 'type': 'integer', 'default': 25},
                    {'name': 'seed', 'in': 'query', 'type': 'integer'},
                ],
                'produces': ['application/json'],
                'responses': {
                    '200': {'description': 'JSON with image_url + data per option'},
                    '400': {'description': 'Input validation failed (program cannot physically fit the area)'},
                    '422': {'description': 'Validation passed but no valid layout was found'},
                },
            },
            'post': {
                'summary': 'Generate floor plan options (JSON request body) — returns image_url per option',
                'consumes': ['application/json'],
                'parameters': [
                    {'name': 'body', 'in': 'body', 'required': True, 'schema': _BODY_SCHEMA},
                ],
                'produces': ['application/json'],
                'responses': {
                    '200': {'description': 'JSON with image_url + data per option'},
                    '400': {'description': 'Input validation failed (program cannot physically fit the area)'},
                    '422': {'description': 'Validation passed but no valid layout was found'},
                },
            },
        },
        '/image/{request_id}/{filename}': {
            'get': {
                'summary': 'Fetch the real PNG image for one option from a previous /generate call',
                'parameters': [
                    {'name': 'request_id', 'in': 'path', 'type': 'string', 'required': True},
                    {'name': 'filename', 'in': 'path', 'type': 'string', 'required': True,
                     'description': "e.g. '1.png'"},
                ],
                'produces': ['image/png'],
                'responses': {
                    '200': {'description': 'PNG image'},
                    '404': {'description': 'Not found or expired'},
                },
            }
        },
    },
}

Swagger(app, template=swagger_template)


def _parse_bool(v, default):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ('1', 'true', 'yes', 'on')


def _params_from_request():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    def get(key, default, cast=str):
        v = data.get(key, default)
        if v is None:
            return default
        if cast is bool:
            return _parse_bool(v, default)
        try:
            return cast(v)
        except (TypeError, ValueError):
            return default

    seed_raw = data.get('seed', None)
    seed = None
    if seed_raw is not None and str(seed_raw) != '':
        try:
            seed = int(seed_raw)
        except (TypeError, ValueError):
            seed = None

    return dict(
        n_bed=get('n_bed', 2, int),
        n_bath=get('n_bath', 1, int),
        n_kit=get('n_kit', 1, int),
        has_bal=get('has_bal', True, bool),
        area=get('area', 75.0, float),
        has_master_bath=get('has_master_bath', False, bool),
        has_dining=get('has_dining', False, bool),
        has_dressing=get('has_dressing', False, bool),
        n_options=min(max(get('n_options', 3, int), 1), 3),
        n_attempts=min(max(get('n_attempts', 25, int), 1), 60),
        seed=seed,
    )


def _purge_old_cache():
    cutoff = time.time() - CACHE_TTL_SECONDS
    try:
        for entry in CACHE_DIR.iterdir():
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                for f in entry.glob('*'):
                    f.unlink(missing_ok=True)
                entry.rmdir()
    except OSError:
        pass  # best-effort cleanup; never fail a request over this


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


@app.route('/generate', methods=['GET', 'POST'])
def generate_endpoint():
    _purge_old_cache()
    params = _params_from_request()
    results = generate_options(**params)

    request_id = uuid.uuid4().hex[:12]
    req_dir = CACHE_DIR / request_id
    req_dir.mkdir(parents=True, exist_ok=True)

    out = []
    any_ok = False
    for r in results:
        entry = {k: v for k, v in r.items() if k != 'png_bytes'}
        if r.get('ok') and 'png_bytes' in r:
            filename = f"{r['option']}.png"
            (req_dir / filename).write_bytes(r['png_bytes'])
            entry['image_url'] = f'/image/{request_id}/{filename}'
            any_ok = True
        out.append(entry)

    if any_ok:
        status = 200
    elif results and results[0].get('validation_failed'):
        status = 400  # the request itself is infeasible — not a server-side generation miss
    else:
        status = 422  # validation passed but no valid design was found
    return jsonify({'request_id': request_id, 'options': out}), status


@app.route('/image/<request_id>/<filename>', methods=['GET'])
def get_image(request_id, filename):
    # basic path-safety: only allow the exact "<digit>.png" pattern we wrote
    if not filename.endswith('.png') or '/' in request_id or '/' in filename:
        abort(404)
    path = CACHE_DIR / request_id / filename
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype='image/png')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
