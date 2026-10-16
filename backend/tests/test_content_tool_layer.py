from contextlib import redirect_stdout
import io
import json
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch

from application.tool_contracts import TOOL_SPECS
from application.tool_execution import ToolExecutor, remaining_timeout
from life_prototype.douban import Douban, DoubanUnavailable, add_candidate
from life_prototype.quote_sources import Sources


def receipts(output):
    return [json.loads(line.removeprefix('[tool_execution] ')) for line in output.getvalue().splitlines()
            if line.startswith('[tool_execution] ')]


class ContentToolLayerTests(unittest.TestCase):
    def test_movie_calls_use_canonical_contract_even_on_domain_cache_hits(self):
        cog = Mock()
        client = Douban(cog)
        output = io.StringIO()
        with redirect_stdout(output), patch.object(client,'_call',return_value=[]) as adapter:
            self.assertEqual(client.call('search',q='private-query',count=2),[])
            adapter.assert_called_once_with('search',q='private-query',count=2)
            for args in ({'q':'q','count':True},{'q':'q','count':9},{'q':'q','count':2,'extra':'x'}):
                with self.assertRaises(ValueError): client.call('search',**args)
            self.assertEqual(adapter.call_count,1)
        logs = receipts(output)
        self.assertEqual([r['status'] for r in logs],['completed','failed','failed','failed'])
        self.assertTrue(all(r['tool']=='movies.search' for r in logs))
        self.assertNotIn('private-query',output.getvalue())

    def test_book_transport_is_inside_shared_execution_layer(self):
        output = io.StringIO()
        with redirect_stdout(output), patch.object(Douban,'_run',return_value=[]) as raw:
            Douban.book_call('search',query='book',count=3)
            raw.assert_called_once_with('search-book',{'q':'book','count':3})
            with self.assertRaises(ValueError): Douban.book_call('detail',douban_id='not-an-id')
            self.assertEqual(raw.call_count,1)
        self.assertEqual([r['tool'] for r in receipts(output)],['books.search','books.detail'])

    def test_quote_source_fallback_has_individual_failure_receipts(self):
        sources = Sources(getter=Mock(side_effect=OSError('private-cookie-must-not-log')))
        output = io.StringIO()
        with redirect_stdout(output):
            result = sources.collect({'kind':'reading','title':'book','author':'author',
                                      'original_title':'Book','douban_book_id':'123'})
        self.assertEqual(result,[])
        logs = receipts(output)
        self.assertEqual(logs[-1]['tool'],'quotes.collect')
        self.assertEqual(logs[-1]['status'],'completed')
        self.assertEqual(len([r for r in logs if r['tool']=='quotes.fetch' and r['status']=='failed']),3)
        self.assertNotIn('private-cookie-must-not-log',output.getvalue())
        with redirect_stdout(io.StringIO()), self.assertRaises(ValueError): sources.wiki({'kind':'reading','title':'book'},'evil')

    def test_nested_timeouts_are_classified_without_leaking_remote_errors(self):
        def adapter(**kwargs):
            try: raise subprocess.TimeoutExpired('sensitive-command',1)
            except subprocess.TimeoutExpired as exc: raise DoubanUnavailable('sensitive-cookie') from exc
        output = io.StringIO()
        with redirect_stdout(output):
            result = ToolExecutor({'movie_detail':adapter},source='test').call('movies.detail',douban_id='123')
        self.assertEqual(result.status,'timeout')
        self.assertEqual(result.error['code'],'timeout')
        self.assertNotIn('sensitive',output.getvalue())

    def test_read_deadline_is_inherited_and_write_stays_on_caller_thread(self):
        caller = threading.get_ident()
        seen = {}
        def write(douban_id,runtime_index):
            seen['write_thread'] = threading.get_ident()
            nested = ToolExecutor({'movie_detail':lambda douban_id:{'remaining':remaining_timeout(20)}},source='test')
            seen['remaining'] = nested.call('movies.detail',douban_id=douban_id).unwrap()['remaining']
            return {'added':True}
        with redirect_stdout(io.StringIO()):
            result = ToolExecutor({'add_movie_candidate':write},source='test',timeouts={'movies.add':1}).call(
                'movies.add',douban_id='123',runtime_index=0)
        self.assertTrue(result.ok)
        self.assertEqual(seen['write_thread'],caller)
        self.assertLessEqual(seen['remaining'],1)

    def test_candidate_write_uses_common_receipt(self):
        output = io.StringIO()
        with redirect_stdout(output), patch('life_prototype.douban._add_candidate',return_value={'added':True}):
            self.assertEqual(add_candidate(Mock(),'123',0),{'added':True})
        log = receipts(output)[0]
        self.assertEqual(log['tool'],'movies.add')
        self.assertTrue(log['write'])

    def test_existing_chat_tool_contracts_and_result_checks_are_preserved(self):
        with redirect_stdout(io.StringIO()):
            executor = ToolExecutor({'_query_weather_agent':lambda:({},None)},source='chat')
            self.assertTrue(executor.call('weather.current').ok)
            executor.services['_query_weather_agent'] = lambda:('invalid',None)
            self.assertEqual(executor.call('weather.current').error['code'],'invalid_result')
            self.assertEqual(executor.call('weather.current',unexpected=True).error['code'],'invalid_arguments')
        for name,spec in TOOL_SPECS.items():
            # Building every signature catches required-after-optional regressions.
            try: spec.bind((),{})
            except ValueError as exc: self.assertEqual(str(exc),'invalid_tool_arguments',name)


if __name__=='__main__': unittest.main()
