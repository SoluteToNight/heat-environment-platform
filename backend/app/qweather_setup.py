import argparse
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.config import settings
from app.services.qweather_service import QWeatherError, qweather_client


def generate_keys(directory: Path):
    private_path = directory / 'qweather-private.pem'
    public_path = directory / 'qweather-public.pem'
    if private_path.exists() or public_path.exists():
        raise QWeatherError('Key files already exist. Keep the current pair or explicitly choose another directory.')
    directory.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    with private_path.open('xb') as private_file:
        private_file.write(private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with public_path.open('xb') as public_file:
        public_file.write(private_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    print(f'Upload PUBLIC key only: {public_path}')
    print(f'Keep PRIVATE key locally: {private_path}')


def main():
    parser = argparse.ArgumentParser(description='Configure and verify QWeather JWT integration.')
    parser.add_argument('action', choices=['generate-key', 'check', 'sync'])
    parser.add_argument('--directory', type=Path, default=settings.BASE_DIR / 'secrets')
    args = parser.parse_args()
    try:
        if args.action == 'generate-key':
            generate_keys(args.directory.resolve())
        elif args.action == 'check':
            result = qweather_client.fetch_hourly()
            print(f"QWeather JWT request passed: {len(result['hourly']['time'])} forecast hours.")
            print(f"UTC range: {result['hourly']['time'][0]} to {result['hourly']['time'][-1]}")
            print('No database writes. No token or private key printed.')
        else:
            from app.db.session import SessionLocal
            from app.services.weather_service import sync_weather_release
            with SessionLocal() as database:
                release = sync_weather_release(database, product_id='qweather', force=True)
                print(f'Published QWeather release: {release.id}')
    except QWeatherError as error:
        print(f'QWeather setup failed: {error}')
        if error.retry_after:
            print(f'Retry-After: {error.retry_after}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
