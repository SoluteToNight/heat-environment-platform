import argparse
import datetime
import json
from pathlib import Path

import numpy as np

from app.services.radiation_service import decode_tile, compute_geometry, downscale_components
from app.services.spatial_service import write_json, sha256, utc_text, utc_now
from app.services.radiation_publish import publish_radiation


def main():
    parser = argparse.ArgumentParser(description='Verified tile import and pilot radiation geometry computation.')
    commands = parser.add_subparsers(dest='action', required=True)
    decoder = commands.add_parser('decode')
    decoder.add_argument('--tile', type=Path, required=True)
    decoder.add_argument('--profile', type=Path, required=True)
    geometry = commands.add_parser('geometry')
    geometry.add_argument('--buildings', type=Path, required=True)
    geometry.add_argument('--bbox', type=float, nargs=4, required=True)
    geometry.add_argument('--time', required=True)
    geometry.add_argument('--grid-m', type=float, default=30)
    geometry.add_argument('--radius', type=float, default=500)
    geometry.add_argument('--receiver-height', type=float, default=1.1)
    geometry.add_argument('--components', type=Path)
    for command in (decoder, geometry):
        command.add_argument('--output', type=Path, required=True)
        command.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {'status': 'running', 'created_at': utc_text(utc_now()), 'algorithm': 'radiation-pilot-v1'}
    try:
        if args.action == 'decode':
            profile = json.loads(args.profile.read_text(encoding='utf-8-sig'))
            values, metadata = decode_tile(args.tile.read_bytes(), profile)
            np.save(args.output / 'net_shortwave.npy', values)
            manifest.update(metadata, quantity='net_shortwave', unit='W/m²', array_sha256=sha256(args.output / 'net_shortwave.npy'), profile_sha256=sha256(args.profile))
        else:
            moment = datetime.datetime.fromisoformat(args.time.replace('Z', '+00:00'))
            receivers = compute_geometry(args.bbox, args.buildings, moment, args.grid_m, args.receiver_height, args.radius)
            if args.components:
                components = json.loads(args.components.read_text(encoding='utf-8-sig'))
                if components.get('verified') is not True or components.get('unit') != 'W/m²' or not components.get('source'):
                    raise ValueError('Verified, attributed W/m² components required.')
                valid_time = datetime.datetime.fromisoformat(components['valid_time'].replace('Z', '+00:00'))
                if valid_time != moment:
                    raise ValueError('Radiation and geometry times must match.')
                receivers = downscale_components(receivers, components['dni'], components['dhi'], components['quantity'], components['temporal_support'])
                manifest['components_sha256'] = sha256(args.components)
                manifest['components'] = components
            features = [{'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [receiver['longitude'], receiver['latitude']]}, 'properties': receiver} for receiver in receivers]
            write_json(args.output / 'receivers.geojson', {'type': 'FeatureCollection', 'features': features})
            manifest.update({'valid_time': utc_text(moment), 'geometry_sha256': sha256(args.buildings), 'bbox': args.bbox, 'receiver_count': len(receivers), 'grid_m': args.grid_m, 'receiver_height_m': args.receiver_height, 'ray_radius_m': args.radius, 'crs': 'EPSG:32651', 'output_crs': 'EPSG:4326', 'sky_sampling': '24 azimuth x 8 equal sin(elevation)^2 strata; cosine weighted', 'output_sha256': sha256(args.output / 'receivers.geojson'), 'quality': ['Flat terrain scenario; DEM and canopy omitted.', 'Finite radius; geometry completeness and distant obstructions unverified.', 'Unknown intersecting building height produces null.', 'Surrounding reflected radiation omitted.', 'No independent observational validation; not UTCI.']})
        manifest['status'] = 'completed'
    except Exception as error:
        manifest.update(status='failed', error=str(error))
        raise
    finally:
        write_json(args.output / 'manifest.json', manifest)
    if args.publish:
        published = publish_radiation(args.output)
        print(json.dumps({'run_id': published['run_id'], 'variables': published['display_variables']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
