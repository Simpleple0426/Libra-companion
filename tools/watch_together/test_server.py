import unittest
from unittest.mock import MagicMock, patch
from server import Handler, valid_backend


class AddressTests(unittest.TestCase):
    def test_accepts_tailnet_and_loopback(self):
        self.assertEqual(valid_backend('http://100.64.0.10:8000/'), 'http://100.64.0.10:8000')
        self.assertEqual(valid_backend('http://127.0.0.1:8000'), 'http://127.0.0.1:8000')

    def test_accepts_https_domain_and_private_prefix(self):
        key = 'a' * 64
        self.assertEqual(valid_backend('https://companion.example.com/connect/' + key + '/'),
                         'https://companion.example.com/connect/' + key)
        self.assertEqual(valid_backend('https://example.com'), 'https://example.com')

    def test_rejects_insecure_public_hosts_credentials_and_wrong_paths(self):
        for value in ['http://example.com', 'http://8.8.8.8', 'file:///x',
                      'http://user:password@127.0.0.1:8000', 'http://127.0.0.1:8000/other',
                      'http://127.0.0.1:8000/connect/' + 'a' * 64,
                      'https://example.com/connect/short', 'https://example.com/chat',
                      'https://user:password@example.com', 'https://example.com?key=secret']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                valid_backend(value)

    def test_https_request_preserves_private_prefix_and_watch_token(self):
        key = 'a' * 64
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"ready":true}'
        with patch('server.urllib.request.build_opener', return_value=opener) as factory:
            result = Handler.upstream('/status', None, {
                'backend': 'https://example.com/connect/' + key,
                'token': 'watch-token',
            })
        factory.assert_called_once_with()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://example.com/connect/' + key + '/watch-together/status')
        self.assertEqual(request.get_header('Authorization'), 'Bearer watch-token')
        self.assertEqual(result, {'ready': True})
