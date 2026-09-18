import argparse
import json

from app.config import settings
from app.services.spatial_service import sampling_plan, publish_weather


def main():
    parser = argparse.ArgumentParser(description='Plan or publish a bounded QWeather spatial forecast snapshot.')
    parser.add_argument('action', choices=['plan', 'publish'])
    parser.add_argument('--longitude', type=float, default=settings.SHANGHAI_CENTER_LON)
    parser.add_argument('--latitude', type=float, default=settings.SHANGHAI_CENTER_LAT)
    parser.add_argument('--spacing', type=float, default=1000)
    parser.add_argument('--side', type=int, default=3)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    plan = sampling_plan(args.longitude, args.latitude, args.spacing, args.side)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if args.action == 'publish':
        result = publish_weather(plan, args.force)
        print(json.dumps({'run_id': result['run_id'], 'actual_calls': result['actual_calls'], 'frames': len(result['times'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
