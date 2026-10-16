from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from unittest.mock import MagicMock as Mock,patch
import unittest
import test_meal_skill as fixture
from life_prototype import weread, weread_library as library, outing_content, skill_reading as reading_skill
from life_prototype.config import canonical


BOOK={'weread_id':'123','title':'目录测试书','author':'测试作者','authors':['测试作者'],'isbn':'9781234567890',
      'summary':'这本书讨论选择、判断与责任。','url':'https://weread.qq.com/fixture','word_count':10000}
CHAPTERS={'bookId':'123','chapters':[{'chapterUid':1,'chapterIdx':1,'title':'第一章','wordCount':6000,'level':1},
                                  {'chapterUid':2,'chapterIdx':2,'title':'第二章','wordCount':None,'level':1}]}


class WeReadTests(unittest.TestCase):
    setUp=fixture.MealSkillTests.setUp
    command=fixture.MealSkillTests.command

    def own(self,book=None):
        book=deepcopy(book or BOOK)
        with self.p.store.connect() as db:
            outing_content.initialize(db)
            db.execute('INSERT INTO life_owned_books VALUES(?,?,?,?,?)',('owned-test','visit-test','test-work',self.clock.now().isoformat(),canonical(book)))

    def catalog(self):
        folder=self.root/'libra/reading_knowledge';folder.mkdir(parents=True)
        (folder/'catalog.json').write_text(canonical({'books':[{'book_id':'preferred',
            'title':BOOK['title'],'author':BOOK['author'],'reading_status':'read'}],
            'excluded':[{'book_id':'excluded','title':'Excluded'}]}),encoding='utf8')

    def test_preference_catalog_becomes_readable_without_purchase(self):
        self.catalog()
        with patch.object(weread,'status',return_value={'configured':True}),patch.object(weread,'search',return_value=[BOOK]),patch.object(weread,'info',return_value=BOOK),patch.object(weread,'chapters',return_value=CHAPTERS):
            self.assertTrue(library.process_one(self.cog))
            self.assertFalse(library.process_one(self.cog))
        from life_prototype.resource_library import sync
        sync(self.cog,self.root)
        key=library.structure(BOOK,CHAPTERS)[0]
        self.assertTrue(self.p.config['books'][key]['available'])
        with self.p.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM life_weread_library').fetchone()[0],1)
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='life_owned_books'").fetchone()
            self.assertFalse(exists and db.execute('SELECT count(*) FROM life_owned_books').fetchone()[0])
        row=library.view(self.cog)['books'][0]
        self.assertEqual(row['source'],'reading_catalog')
        self.assertEqual(row['title'],BOOK['title'])

    def test_catalog_and_purchase_merge_into_one_reading_candidate(self):
        self.catalog();self.own()
        with patch.object(weread,'status',return_value={'configured':True}),patch.object(weread,'search',return_value=[BOOK]),patch.object(weread,'info',return_value=BOOK),patch.object(weread,'chapters',return_value=CHAPTERS):
            self.assertTrue(library.process_one(self.cog));self.assertTrue(library.process_one(self.cog))
            self.assertFalse(library.process_one(self.cog))
        from life_prototype.resource_library import sync
        sync(self.cog,self.root)
        self.assertEqual(sum(b.get('available',True) and b['title']==BOOK['title'] for b in self.p.config['books'].values()),1)
        self.assertTrue(outing_content.saved(self.cog)['owned_books'][0]['reading_available'])

    def test_catalog_can_choose_verified_edition_but_purchase_stays_strict(self):
        desired={'title':BOOK['title'],'author':BOOK['author']}
        editions=[BOOK,{**BOOK,'weread_id':'456'}]
        self.assertIsNone(library.match(desired,editions))
        self.assertEqual(library.match(desired,editions,choose_edition=True),BOOK)
        self.assertIsNone(library.match({**desired,'author':'Other'},editions,choose_edition=True))

    def test_catalog_prevents_repeat_purchase_before_structure_ready(self):
        self.catalog()
        self.assertTrue(outing_content.duplicate(BOOK,outing_content.owned_books(self.cog)))

    def test_gateway_uses_flat_read_only_request_and_redacts_key(self):
        response=Mock();response.read.return_value=json.dumps({'bookId':'123','title':'Test','author':'Author'}).encode()
        opener=Mock();opener.open.return_value.__enter__.return_value=response
        output=io.StringIO()
        with patch.object(weread,'api_key',return_value='wrk-private-test-key'),patch.object(weread,'build_opener',return_value=opener),redirect_stdout(output):
            result=weread.info('123')
        self.assertEqual(result['weread_id'],'123')
        payload=json.loads(opener.open.call_args.args[0].data)
        self.assertEqual(payload,{'api_name':'/book/info','skill_version':'1.0.4','bookId':'123'})
        self.assertNotIn('private-test-key',output.getvalue())
        with self.assertRaises(ValueError):weread._request('/book/getprogress',bookId='123')

    def test_search_supports_scope17_groups_without_reading_prose(self):
        response={'results':[{'scope':17,'books':[{'bookInfo':{'bookId':'123','title':'Test','author':'Author'}},
                                                {'bookInfo':{'bookId':'124','title':'Unavailable','soldout':1}}]}]}
        with patch.object(weread,'_request',return_value=response) as request:
            self.assertEqual(len(weread.search('query',5)),1)
        request.assert_called_once_with('/store/search',keyword='query',scope=10,count=5,maxIdx=0)

    def test_offline_missing_key_has_no_network_and_preserves_queue(self):
        self.own()
        with patch.object(weread,'api_key',return_value=''),patch.object(weread,'build_opener') as opener:
            self.assertFalse(library.process_one(self.cog))
            with self.assertRaises(weread.WeReadUnavailable):weread.info('123')
            opener.assert_not_called()
        self.assertEqual(library.view(self.cog)['books'][0]['status'],'pending')

    def test_upgrade_notice_stops_instead_of_using_stale_data(self):
        response=Mock();response.read.return_value=b'{"upgrade_info":{"message":"update"},"bookId":"123"}'
        opener=Mock();opener.open.return_value.__enter__.return_value=response
        with patch.object(weread,'api_key',return_value='wrk-test'),patch.object(weread,'build_opener',return_value=opener):
            with self.assertRaisesRegex(weread.WeReadUnavailable,'upgrade_required'):weread.info('123')

    def test_structure_estimates_and_rejects_bad_or_empty_maps(self):
        key,book=library.structure(BOOK,CHAPTERS)
        self.assertEqual(book['total_chars'],10000);self.assertTrue(book['contains_estimated_lengths'])
        self.assertEqual(book['structure'][0]['length_basis'],'reported_word_count')
        self.assertNotIn('text',book)
        for bad in ({'bookId':'123','chapters':[]},{'bookId':'456','chapters':CHAPTERS['chapters']},
                    {'bookId':'123','chapters':[CHAPTERS['chapters'][0]]*2}):
            with self.assertRaises(ValueError):library.structure(BOOK,bad)

    def test_owned_book_becomes_readable_without_files_and_keeps_progress(self):
        self.own()
        with patch.object(weread,'status',return_value={'configured':True}),patch.object(weread,'info',return_value=BOOK),patch.object(weread,'chapters',return_value=CHAPTERS):
            self.assertTrue(library.process_one(self.cog));self.assertFalse(library.process_one(self.cog))
        from life_prototype.resource_library import sync
        self.assertTrue(sync(self.cog,self.root))
        key=library.structure(BOOK,CHAPTERS)[0]
        self.assertTrue(self.p.config['books'][key]['available'])
        with self.p.store.connect() as db:
            state=self.p.store.read(db);state['place']='home.f2.study'
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
        self.command('read-online','start',activity_id='online',kind='reading',target=key)
        self.clock.advance(60);reading_skill.heartbeat(self.cog)
        self.assertEqual(self.p.snapshot()['activities']['online']['progress'],400)
        sync(self.cog,self.root)
        self.assertTrue(self.p.config['books'][key]['available'])
        self.assertEqual(self.p.snapshot()['activities']['online']['progress'],400)
        self.assertTrue(outing_content.saved(self.cog)['owned_books'][0]['reading_available'])
        self.assertEqual(self.model.calls,[])

    def test_douban_matching_requires_unambiguous_identity(self):
        owned={'title':BOOK['title'],'authors':['测试作者']}
        self.assertEqual(library.match(owned,[BOOK]),BOOK)
        self.assertIsNone(library.match(owned,[BOOK,{**BOOK,'weread_id':'456'}]))
        self.assertIsNone(library.match({'title':BOOK['title'],'authors':['不同作者']},[BOOK]))
        self.assertEqual(library.match({'title':'不同译名','isbn':BOOK['isbn']},[BOOK]),BOOK)

    def test_catalog_fetch_failure_retains_owned_and_retryable_state(self):
        self.own()
        with patch.object(weread,'status',return_value={'configured':True}),patch.object(weread,'info',side_effect=weread.WeReadUnavailable('weread_http_401')):
            self.assertTrue(library.process_one(self.cog))
        with self.p.store.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM life_weread_library').fetchone()[0],'retry')
            self.assertEqual(db.execute('SELECT count(*) FROM life_owned_books').fetchone()[0],1)

    def test_bookstore_searches_weread_and_queues_structure_without_douban(self):
        import test_outing_skill as outing_fixture
        outing_fixture.OutingTests.setup_outing(self)
        with patch.object(weread,'status',return_value={'configured':True}),patch.object(weread,'search',return_value=[BOOK]),patch.object(weread,'info',return_value=BOOK),patch.object(outing_content.Douban,'book_call',side_effect=AssertionError('unexpected douban')):
            outing_content.process_one(self.cog)
        saved=outing_content.saved(self.cog)
        self.assertEqual(saved['owned_books'][0]['weread_id'],'123')
        self.assertEqual(saved['owned_books'][0]['structure_status'],'pending')
        self.assertEqual(saved['drafts'][0]['kind'],'book_introduction')


if __name__=='__main__':unittest.main()
