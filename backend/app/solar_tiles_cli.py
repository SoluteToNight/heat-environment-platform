import argparse
import datetime
import hashlib
import io
import json
import re
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

from app.services.radiation_service import decode_tile
from app.services.radiation_publish import publish_radiation
from app.services.spatial_service import write_json, sha256, utc_now, utc_text


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'ShanghaiHeatResearch/1.0'})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read()


def capture(output, moment, publish=False):
    if moment.tzinfo is None or moment.minute or moment.second:
        raise ValueError('Specify a timezone-aware exact hour.')
    moment = moment.astimezone(datetime.timezone.utc)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'status': 'running', 'created_at': utc_text(utc_now()), 'algorithm': 'qweather-public-map-reviewed-decoder-v1'}
    try:
        page = download('https://map.qweather.com/').decode('utf-8')
        match = re.search(r"fileHash\s*=\s*'([a-f0-9]+)'", page)
        if not match:
            raise ValueError('Map bundle reference changed; decoder review required.')
        script_url = f'https://map.qweather.com/index.{match[1]}.js'
        script = download(script_url)
        (output / 'map_decoder_source.js').write_bytes(script)
        text = script.decode('utf-8')
        for expression in ('4*t*4+16', 'i+=32', '2056+o+((n<<8)+n)<<2', 'decodeR', '太阳净辐照', 'renderFrom:"R"'):
            if expression not in text:
                raise ValueError('Public decoder has changed; review its data layout before importing.')
        metadata_url = 'https://tiles.qweather.com/data/i/2.1/common.json'
        metadata_bytes = download(metadata_url)
        (output / 'common.json').write_bytes(metadata_bytes)
        metadata = json.loads(metadata_bytes)
        update = metadata['update']
        if not re.fullmatch(r'\d{10}', update):
            raise ValueError('Invalid model cycle.')
        url = f'https://tiles.qweather.com/data/i/2.1/{update}/{moment:%Y/%m/%d/%H}/4/13/6/asob-surface.jpg'
        content = download(url)
        (output / 'source.jpg').write_bytes(content)
        image = Image.open(io.BytesIO(content))
        profile = {'verified': True, 'verification_scope': 'public map encoding and displayed variable only; time averaging and physical model metadata unverified', 'evidence': {'script_url': script_url, 'script_sha256': hashlib.sha256(script).hexdigest(), 'header': '4*257*4+16 bytes, stride32, 28 encoded bytes', 'data': '(2056+column+row*257)*4; 2056/257=8', 'nodata': 'asob layer has no jpgTransparency/pngTransparency flag in reviewed bundle; follow renderer, independent missing-code semantics unverified'}, 'width': 257, 'height': 265, 'header_offset': 4128, 'header_stride': 32, 'data_x': 0, 'data_y': 8, 'data_width': 257, 'data_height': 257, 'registration': 'grid_nodes_with_border', 'nodata_codes': [], 'quantity': 'net_shortwave', 'unit': 'W/m²', 'valid_time': utc_text(moment), 'temporal_support': 'unknown', 'z': 4, 'x': 13, 'y': 6, 'source_url': url, 'model_cycle': update}
        if image.size != (257, 265):
            raise ValueError('Unexpected public tile dimensions.')
        values, decoded = decode_tile(content, profile)
        np.save(output / 'net_shortwave.npy', values)
        write_json(output / 'profile.json', profile)
        manifest.update(decoded, quantity='net_shortwave', unit='W/m²', array_sha256=sha256(output / 'net_shortwave.npy'), profile_sha256=sha256(output / 'profile.json'), metadata_sha256=sha256(output / 'common.json'), source_url=url, status='completed', quality=['Public map diagnostic background, not a validated research observation.', 'Instant/interval-mean semantics remain unverified; cannot enter radiation downscaling.', 'Signed decoded values are retained; the public popup may display absolute magnitude.', 'JPEG quantization and original model effective resolution remain unvalidated.'])
    except Exception as error:
        manifest.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        write_json(output / 'manifest.json', manifest)
    if publish:
        return publish_radiation(output)
    return manifest


def main():
    parser = argparse.ArgumentParser(description='Archive and decode the reviewed QWeather public solar map tile; not the JWT solar API.')
    parser.add_argument('--time', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    result = capture(args.output, datetime.datetime.fromisoformat(args.time.replace('Z', '+00:00')), args.publish)
    print(json.dumps({'status': result['status'], 'run_id': result.get('run_id'), 'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
