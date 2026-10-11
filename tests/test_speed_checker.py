import io
import http.client
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, call, patch

import speed_checker


class ValidateUrlTests(unittest.TestCase):
    def test_accepts_http_url(self) -> None:
        speed_checker.validate_url("http://example.com/file.bin")

    def test_accepts_https_url(self) -> None:
        speed_checker.validate_url("https://example.com/file.bin")

    def test_rejects_url_without_scheme(self) -> None:
        with self.assertRaisesRegex(ValueError, "схему http или https"):
            speed_checker.validate_url("example.com/file.bin")

    def test_rejects_unsupported_scheme(self) -> None:
        with self.assertRaisesRegex(ValueError, "схему http или https"):
            speed_checker.validate_url("ftp://example.com/file.bin")

    def test_rejects_url_without_domain(self) -> None:
        with self.assertRaisesRegex(ValueError, "содержать домен"):
            speed_checker.validate_url("https:///file.bin")


class DownloadOnceTests(unittest.TestCase):
    @patch("speed_checker.time.perf_counter", side_effect=[10.0, 12.5])
    @patch("speed_checker.urllib.request.urlopen")
    def test_reads_body_in_chunks_and_counts_actual_bytes(
        self,
        urlopen_mock: MagicMock,
        perf_counter_mock: MagicMock,
    ) -> None:
        response = MagicMock()
        response.read.side_effect = [b"abc", b"defgh", b""]
        urlopen_mock.return_value.__enter__.return_value = response

        downloaded_bytes, elapsed_seconds = speed_checker.download_once(
            "https://example.com/file.bin",
        )

        self.assertEqual(downloaded_bytes, 8)
        self.assertEqual(elapsed_seconds, 2.5)
        self.assertEqual(
            response.read.call_args_list,
            [
                call(speed_checker.CHUNK_SIZE),
                call(speed_checker.CHUNK_SIZE),
                call(speed_checker.CHUNK_SIZE),
            ],
        )
        perf_counter_mock.assert_called()


class RunMeasurementsTests(unittest.TestCase):
    @patch("speed_checker.download_once", return_value=(100, 0.5))
    def test_runs_exactly_ten_sequential_downloads(
        self,
        download_once_mock: MagicMock,
    ) -> None:
        result = speed_checker.run_measurements("https://example.com/file.bin")

        self.assertEqual(result, (1_000, 5.0))
        self.assertEqual(download_once_mock.call_count, 10)
        download_once_mock.assert_has_calls(
            [call("https://example.com/file.bin")] * 10,
        )

    @patch("speed_checker.download_once")
    def test_stops_after_network_error(
        self,
        download_once_mock: MagicMock,
    ) -> None:
        download_once_mock.side_effect = [
            (100, 0.5),
            urllib.error.URLError("нет соединения"),
        ]

        with self.assertRaises(urllib.error.URLError):
            speed_checker.run_measurements("https://example.com/file.bin")

        self.assertEqual(download_once_mock.call_count, 2)


class CalculateStatisticsTests(unittest.TestCase):
    def test_calculates_average_time_volume_and_speed(self) -> None:
        average_time, total_megabytes, speed_mbps = (
            speed_checker.calculate_statistics(
                total_bytes=25_000_000,
                total_time_seconds=5.0,
                request_count=10,
            )
        )

        self.assertEqual(average_time, 0.5)
        self.assertEqual(total_megabytes, 25.0)
        self.assertEqual(speed_mbps, 40.0)

    def test_rejects_zero_total_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "больше нуля"):
            speed_checker.calculate_statistics(100, 0.0)


class MainTests(unittest.TestCase):
    def run_main(self) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = speed_checker.main(["https://example.com/file.bin"])
        return exit_code, stdout.getvalue(), stderr.getvalue()

    @patch("speed_checker.run_measurements", return_value=(20_000_000, 4.0))
    def test_returns_zero_and_prints_result(
        self,
        run_measurements_mock: MagicMock,
    ) -> None:
        exit_code, stdout, stderr = self.run_main()

        self.assertEqual(exit_code, 0)
        self.assertIn("Выполнено запросов: 10", stdout)
        self.assertIn("Среднее время запроса: 0.40 с", stdout)
        self.assertIn("Скачано данных: 20.00 МБ", stdout)
        self.assertIn("Средняя скорость: 40.00 Мбит/с", stdout)
        self.assertEqual(stderr, "")
        run_measurements_mock.assert_called_once()

    @patch("speed_checker.run_measurements")
    def test_handles_http_error(self, run_measurements_mock: MagicMock) -> None:
        run_measurements_mock.side_effect = urllib.error.HTTPError(
            "https://example.com/file.bin",
            404,
            "Not Found",
            {},
            None,
        )

        exit_code, stdout, stderr = self.run_main()

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("HTTP-ошибка 404", stderr)

    @patch("speed_checker.run_measurements")
    def test_handles_url_error(self, run_measurements_mock: MagicMock) -> None:
        run_measurements_mock.side_effect = urllib.error.URLError(
            "нет соединения",
        )

        exit_code, stdout, stderr = self.run_main()

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("нет соединения", stderr)

    @patch("speed_checker.run_measurements")
    def test_handles_timeout_error(self, run_measurements_mock: MagicMock) -> None:
        run_measurements_mock.side_effect = TimeoutError("тайм-аут")

        exit_code, stdout, stderr = self.run_main()

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("превышено время ожидания", stderr)

    @patch("speed_checker.run_measurements")
    def test_handles_response_read_error(
        self,
        run_measurements_mock: MagicMock,
    ) -> None:
        run_measurements_mock.side_effect = http.client.IncompleteRead(
            b"partial",
            100,
        )

        exit_code, stdout, stderr = self.run_main()

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("Ошибка чтения ответа", stderr)

    @patch("speed_checker.urllib.request.urlopen")
    def test_invalid_url_does_not_make_request(
        self,
        urlopen_mock: MagicMock,
    ) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = speed_checker.main(["example.com/file.bin"])

        self.assertNotEqual(exit_code, 0)
        self.assertIn("схему http или https", stderr.getvalue())
        urlopen_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
