"""Deterministic regression tests; none measure perceptual alignment accuracy."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import lrc_tool as tool


def fixture():
    return {'schema_version': 1, 'title': '测试歌曲', 'artist': '示例', 'duration': 12.0,
            'metadata': {}, 'entries': [
                {'time': 1.0, 'text': '第一句', 'verified': False},
                {'time': 4.0, 'text': '第二句', 'verified': False},
                {'time': 7.0, 'text': '第一句', 'verified': False},
                {'time': 8.0, 'text': '', 'verified': False}]}


class CoreTests(unittest.TestCase):
    def test_format_zero(self): self.assertEqual(tool.fmt(0), '00:00.00')
    def test_format_carry(self): self.assertEqual(tool.fmt(59.995), '01:00.00')
    def test_format_long(self): self.assertEqual(tool.fmt(6000), '100:00.00')
    def test_reject_negative_format(self):
        with self.assertRaises(ValueError): tool.fmt(-.1)
    def test_reject_nan_format(self):
        with self.assertRaises(ValueError): tool.fmt(float('nan'))
    def test_boolean_not_time(self): self.assertFalse(tool.finite(True))
    def test_valid_timeline(self): self.assertTrue(tool.validate(fixture())['ok'])
    def test_coverage_and_duplicates(self):
        r = tool.validate(fixture(), ['第一句', '第二句', '第一句'])
        self.assertTrue(r['ok']); self.assertEqual(r['lyric_lines'], 3)
    def test_coverage_missing(self): self.assertFalse(tool.validate(fixture(), ['第一句'])['ok'])
    def test_coverage_text_change(self): self.assertFalse(tool.validate(fixture(), ['改字', '第二句', '第一句'])['ok'])
    def test_unknown_time(self):
        p=fixture(); p['entries'][1]['time']=None
        self.assertFalse(tool.validate(p)['ok'])
    def test_negative(self):
        p=fixture(); p['entries'][0]['time']=-1
        self.assertFalse(tool.validate(p)['ok'])
    def test_out_of_bounds(self):
        p=fixture(); p['entries'][-1]['time']=13
        self.assertFalse(tool.validate(p)['ok'])
    def test_start_at_end(self):
        p=fixture(); p['entries'][-1].update(time=12, text='太晚')
        self.assertFalse(tool.validate(p)['ok'])
    def test_duplicate(self):
        p=fixture(); p['entries'][1]['time']=1
        self.assertFalse(tool.validate(p)['ok'])
    def test_rounded_collision(self):
        p=fixture(); p['entries'][1]['time']=1.001
        self.assertFalse(tool.validate(p)['ok'])
    def test_reverse(self):
        p=fixture(); p['entries'][1]['time']=.5
        self.assertFalse(tool.validate(p)['ok'])
    def test_short_display_warning(self):
        p=fixture(); p['entries'][1]['time']=1.2
        self.assertTrue(any('挤压' in s for s in tool.validate(p)['warnings']))
    def test_long_display_warning(self):
        p=fixture(); p['duration']=60; p['entries'][-1]['time']=40
        self.assertTrue(any('18 秒' in s for s in tool.validate(p)['warnings']))
    def test_tail_warning(self):
        p=fixture(); p['entries'].pop()
        self.assertTrue(any('尾奏' in s for s in tool.validate(p)['warnings']))
    def test_export_offset_zero(self): self.assertIn('[offset:0]', tool.export_lrc(fixture()))
    def test_export_verification_gate(self):
        with self.assertRaises(ValueError): tool.export_lrc(fixture(), True)
    def test_export_verified(self):
        p=fixture()
        for r in p['entries']: r['verified']=True
        self.assertIn('[00:07.00]第一句', tool.export_lrc(p, True))
    def test_round_trip(self):
        p=fixture(); q=tool.parse_lrc(tool.export_lrc(p),12)
        self.assertEqual([(r['time'],r['text']) for r in q['entries']],[(r['time'],r['text']) for r in p['entries']])
    def test_multi_tags(self):
        p=tool.parse_lrc('[00:01.00][00:07.00]重复\n[00:04.00]中间',12)
        self.assertEqual([r['text'] for r in p['entries']],['重复','中间','重复'])
    def test_time_precisions(self):
        p=tool.parse_lrc('[00:01]一\n[00:02.3]二\n[00:04.125]三',12)
        self.assertEqual([r['time'] for r in p['entries']],[1,2.3,4.125])
    def test_parse_bom(self): self.assertEqual(tool.parse_lrc('\ufeff[00:01.00]一',12)['entries'][0]['text'],'一')
    def test_bad_second(self):
        with self.assertRaises(ValueError): tool.parse_lrc('[00:60.00]错误',12)
    def test_corrupt_second_tag(self):
        with self.assertRaises(ValueError): tool.parse_lrc('[00:01.00][00:99]错误',12)
    def test_duplicate_metadata(self):
        with self.assertRaises(ValueError): tool.parse_lrc('[ti:一]\n[ti:二]\n[00:01]一',12)
    def test_empty_lrc(self):
        with self.assertRaises(ValueError): tool.parse_lrc('[ti:标题]',12)
    def test_nonzero_offset_requires_mode(self):
        with self.assertRaises(ValueError): tool.parse_lrc('[offset:100]\n[00:01]一',12)
    def test_positive_earlier(self):
        self.assertAlmostEqual(tool.parse_lrc('[offset:100]\n[00:01]一',12,'positive-earlier')['entries'][0]['time'],.9)
    def test_positive_later(self):
        self.assertAlmostEqual(tool.parse_lrc('[offset:100]\n[00:01]一',12,'positive-later')['entries'][0]['time'],1.1)
    def test_bad_offset(self):
        with self.assertRaises(ValueError): tool.parse_lrc('[offset:abc]\n[00:01]一',12)
    def test_import_not_verified(self):
        self.assertFalse(tool.parse_lrc('[00:01]一',12)['entries'][0]['verified'])
    def test_shift_not_mutate(self):
        p=fixture(); q=tool.shift(p,.1)
        self.assertEqual(p['entries'][0]['time'],1); self.assertEqual(q['entries'][0]['time'],1.1)
    def test_shift_segment(self):
        q=tool.shift(fixture(),.2,2,2)
        self.assertEqual([r['time'] for r in q['entries']],[1,4.2,7,8])
    def test_shift_reject_negative(self):
        with self.assertRaises(ValueError): tool.shift(fixture(),-2)
    def test_shift_reject_collision(self):
        with self.assertRaises(ValueError): tool.shift(fixture(),3,1,1)
    def test_shift_resets_review(self):
        p=fixture(); p['entries'][0]['verified']=True
        self.assertFalse(tool.shift(p,.1)['entries'][0]['verified'])
    def test_init_no_fabrication(self):
        p=tool.new_project('一\n\n二\n一',{'duration':12,'sha256':'abc','name':'a.wav'},'标题','作者','版本')
        self.assertEqual([r['time'] for r in p['entries']],[None]*3)
    def test_init_empty(self):
        with self.assertRaises(ValueError): tool.new_project(' ',{},'','','')
    def test_html_injection(self):
        p=fixture(); p['entries'][0]['text']='</script><script>alert(1)</script>'
        page=tool.make_player(p)
        self.assertNotIn('</script><script>alert',page); self.assertIn('\\u003c/script',page)
    def test_html_placeholder_in_title(self):
        p=fixture(); p['title']='@@PROJECT@@'
        self.assertIn('@@PROJECT@@ · LRC',tool.make_player(p))
    def test_html_offline(self):
        page=tool.make_player(fixture())
        self.assertIn("connect-src 'none'",page); self.assertNotIn('src="https://',page)
    def test_html_no_audio_by_default(self):
        self.assertNotIn('data:audio/',tool.make_player(fixture()))
    def test_embed_needs_audio(self):
        with self.assertRaises(ValueError): tool.make_player(fixture(),embed=True)
    def test_write_bom_and_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'中文 目录'/'歌词.lrc'; tool.write_text(p,'内容',bom=True)
            self.assertTrue(p.read_bytes().startswith(b'\xef\xbb\xbf'))
            with self.assertRaises(ValueError): tool.write_text(p,'替换')
    def test_wrong_audio_duration(self):
        with tempfile.NamedTemporaryFile(suffix='.wav') as f:
            with patch.object(tool,'probe_audio',return_value={'duration':99,'sha256':'abc'}):
                with self.assertRaises(ValueError): tool.make_player(fixture(),Path(f.name))
    def test_wrong_audio_hash(self):
        p=fixture(); p['audio_sha256']='old'
        with tempfile.NamedTemporaryFile(suffix='.wav') as f:
            with patch.object(tool,'probe_audio',return_value={'duration':12,'sha256':'new'}):
                with self.assertRaises(ValueError): tool.make_player(p,Path(f.name))


if __name__ == '__main__':
    unittest.main()
