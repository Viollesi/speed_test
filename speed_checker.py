import argparse
import http.client
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence


REQUEST_COUNT = 10
TIMEOUT_SECONDS = 30
CHUNK_SIZE = 64 * 1024
USER_AGENT = "SpeedChecker/1.0"


def validate_url(url: str) -> None:
    try:
        parsed_url = urllib.parse.urlparse(url)
        hostname = parsed_url.hostname
    except ValueError as error:
        raise ValueError(f"некорректный URL: {error}") from error

    if parsed_url.scheme not in {"http", "https"}:
        raise ValueError("URL должен использовать схему http или https")
    if not hostname:
        raise ValueError("URL должен содержать домен")


def download_once(url: str) -> tuple[int, float]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )
    started_at = time.perf_counter()
    downloaded_bytes = 0

    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        while chunk := response.read(CHUNK_SIZE):
            downloaded_bytes += len(chunk)

    elapsed_seconds = time.perf_counter() - started_at
    return downloaded_bytes, elapsed_seconds


def run_measurements(
    url: str,
    request_count: int = REQUEST_COUNT,
) -> tuple[int, float]:
    
    total_bytes = 0
    total_time_seconds = 0.0

    for _ in range(request_count):
        downloaded_bytes, elapsed_seconds = download_once(url)
        total_bytes += downloaded_bytes
        total_time_seconds += elapsed_seconds

    return total_bytes, total_time_seconds


def calculate_statistics(
    total_bytes: int,
    total_time_seconds: float,
    request_count: int = REQUEST_COUNT,
) -> tuple[float, float, float]:
    
    if total_time_seconds <= 0:
        raise ValueError("общее время измерения должно быть больше нуля")
    if request_count <= 0:
        raise ValueError("количество запросов должно быть больше нуля")

    average_time_seconds = total_time_seconds / request_count
    total_megabytes = total_bytes / 1_000_000
    speed_mbps = total_bytes * 8 / total_time_seconds / 1_000_000
    return average_time_seconds, total_megabytes, speed_mbps


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Измерение прикладной скорости скачивания по заданному URL.",
    )
    parser.add_argument("url", help="URL ресурса для скачивания")
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = parse_arguments(arguments)

    try:
        validate_url(args.url)
        total_bytes, total_time_seconds = run_measurements(args.url)
        average_time, total_megabytes, speed_mbps = calculate_statistics(
            total_bytes,
            total_time_seconds,
        )
    except urllib.error.HTTPError as error:
        print(
            f"Ошибка: HTTP-ошибка {error.code}: {error.reason}",
            file=sys.stderr,
        )
        return 1
    except urllib.error.URLError as error:
        print(f"Ошибка сети: {error.reason}", file=sys.stderr)
        return 1
    except TimeoutError as error:
        details = f": {error}" if str(error) else ""
        print(f"Ошибка: превышено время ожидания{details}", file=sys.stderr)
        return 1
    except (OSError, http.client.HTTPException) as error:
        print(f"Ошибка чтения ответа: {error}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1

    print(f"Выполнено запросов: {REQUEST_COUNT}")
    print(f"Среднее время запроса: {average_time:.2f} с")
    print(f"Скачано данных: {total_megabytes:.2f} МБ")
    print(f"Средняя скорость: {speed_mbps:.2f} Мбит/с")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
