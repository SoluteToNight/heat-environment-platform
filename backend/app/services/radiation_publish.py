import json
import math
import os
import shutil
import uuid
from pathlib import Path

import numpy as np

from app.config import settings
from app.services import spatial_service as spatial


def publish_radiation(source):
    source = Path(source)
    original = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    if original.get('status') != 'completed':
        raise ValueError('Only completed radiation outputs can be published.')
    kind = 'tile' if original.get('quantity') == 'net_shortwave' else 'geometry'
    filename = 'net_shortwave.npy' if kind == 'tile' else 'receivers.geojson'
    expected_hash = original['array_sha256' if kind == 'tile' else 'output_sha256']
    if spatial.sha256(source / filename) != expected_hash:
        raise ValueError('Radiation output differs from its manifest hash.')
    root = settings.SPATIAL_STORAGE_DIR
    root.mkdir(parents=True, exist_ok=True)
    run_id = 'spatial_' + kind + '_' + uuid.uuid4().hex
    output = root / run_id
    output.mkdir()
    shutil.copy2(source / 'manifest.json', output / 'input_manifest.json')
    shutil.copy2(source / filename, output / filename)
    shutil.copy2(spatial.boundary_path(), output / 'boundary.geojson')
    manifest = {**original, 'run_id': run_id, 'kind': kind, 'status': 'running', 'created_at': spatial.utc_text(spatial.utc_now()), 'input_path': str(source), 'input_manifest_sha256': spatial.sha256(source / 'manifest.json'), 'boundary_sha256': spatial.sha256(output / 'boundary.geojson'), 'code_sha256': spatial.sha256(__file__), 'attributions': ['QWeather', '建筑来源与高度口径见输入清单']}
    try:
        if kind == 'tile':
            profile = original['profile']
            if profile.get('verified') is not True or not profile.get('evidence'):
                raise ValueError('Verified tile metadata required.')
            count = 2 ** profile['z']
            west = profile['x'] / count * 360 - 180
            east = (profile['x'] + 1) / count * 360 - 180
            north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * profile['y'] / count))))
            south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (profile['y'] + 1) / count))))
            city = spatial.load_boundary().bounds
            bbox = [max(west, city[0]), max(south, city[1]), min(east, city[2]), min(north, city[3])]
            if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
                raise ValueError('Tile does not intersect Shanghai.')
            manifest.update(times=[profile['valid_time']], bbox=bbox, display_variables=['net_shortwave_background'], source='QWeather 公开太阳净辐照图；时间统计口径待核验' if profile['temporal_support'] == 'unknown' else 'QWeather 辐射瓦片', method='Web Mercator 原网格配准双线性取样；仅背景净短波', spatial_support='上海附近网格节点间距约 8.4 km；时间统计口径见图层详情，显示插值不提高气象信息分辨率。', quality=original.get('quality', []) + ['Net shortwave is not GHI; no local W/m² downscaling from this field.'])
        else:
            collection = json.loads((source / filename).read_text(encoding='utf-8'))
            features = collection['features']
            if not features:
                raise ValueError('No geometry receivers.')
            coordinates = np.asarray([feature['geometry']['coordinates'] for feature in features])
            east, north = spatial.PROJECT.transform(coordinates[:, 0], coordinates[:, 1])
            variables = ['sun_visibility', 'sky_factor']
            if original.get('components'):
                variables.append('local_downwelling_shortwave')
            values = {variable: np.asarray([feature['properties'].get(variable) for feature in features], dtype=float) for variable in variables}
            np.savez_compressed(output / 'receivers.npz', projected=np.column_stack([east, north]), **values)
            manifest.update(times=[original['valid_time']], display_variables=variables, source='建筑遮挡情景；' + original.get('components', {}).get('source', '未输入辐射分量'), method='建筑射线遮挡、余弦加权天空因子；接收网格逐格取值，不平滑阴影边界', spatial_support=f"{original['grid_m']} m 接收网格，平坦地形情景；未知高度及建筑内部为空。", receiver_height=f"{original['receiver_height_m']} m 水平接收面", array_sha256=spatial.sha256(output / 'receivers.npz'))
        manifest['status'] = 'completed'
        spatial.write_json(output / 'manifest.json', manifest)
        temporary = root / (run_id + '.tmp')
        spatial.write_json(temporary, {'run_id': run_id})
        os.replace(temporary, root / f'latest_{kind}.json')
        return manifest
    except Exception:
        manifest['status'] = 'failed'
        spatial.write_json(output / 'manifest.json', manifest)
        raise
