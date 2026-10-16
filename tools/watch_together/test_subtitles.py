import unittest
from subtitles import parse_subtitles


class SubtitleTests(unittest.TestCase):
    def test_srt_bom_crlf_and_markup(self):
        cues = parse_subtitles('\ufeff1\r\n00:00:01,000 --> 00:00:03,500\r\n<i>你好</i>\r\n第二行\r\n')
        self.assertEqual(cues, [{'start': 1, 'end': 3.5, 'text': '你好\n第二行'}])

    def test_webvtt_settings_and_notes(self):
        cues = parse_subtitles('WEBVTT\n\nNOTE ignore\nsecret\n\nscene\n00:01.000 --> 00:03.000 align:start\n<v Alice>Hello &amp; bye</v>')
        self.assertEqual(cues[0]['text'], 'Hello & bye')

    def test_invalid_file_and_range(self):
        for text in ['not subtitles', '00:70:00,000 --> 00:71:00,000\nx',
                     '00:00:03,000 --> 00:00:01,000\nx']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_subtitles(text)
