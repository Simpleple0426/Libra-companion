import json
import unittest
from unittest.mock import patch,Mock
import test_meal_skill as fixture
from life_prototype import media_recommendations as media
from life_prototype.config import canonical


class MediaTests(unittest.TestCase):
    setUp=fixture.MealSkillTests.setUp

    def test_real_message_delivery_enqueues_once(self):
        self.chat.receive('app:media-test','推荐你看电影《测试电影》',source='local_app_message')
        self.chat.receive('app:media-test','推荐你看电影《测试电影》',source='local_app_message')
        with self.p.store.connect() as db:
            self.assertEqual(db.execute('SELECT id,status FROM life_media_messages').fetchall(),[('app:media-test','pending')])

    def add(self,ident='m1',priority='mention',title='测试电影',kind='movie',author='',year=''):
        content='请看'+title+author+year
        item=dict(kind=kind,title=title,author=author,year=year,priority=priority,evidence_quote=content)
        with self.p.store.connect() as db:
            media.enqueue(db,ident)
            media.save(db,ident,content,[],{'items':[item]},self.clock.now().isoformat())
        return item

    def test_repeat_merges_sources_and_upgrades_without_progress(self):
        before=self.p.snapshot()
        self.add();self.add();self.add('m2','request')
        rows=media.view(self.cog)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['priority'],'request')
        self.assertEqual(len(rows[0]['sources']),2)
        self.assertEqual(self.p.snapshot(),before)

    def test_extract_message_to_existing_movie_without_network(self):
        content='请看测试电影'
        with self.p.store.connect() as db:
            media.enqueue(db,'m1')
            db.execute('INSERT INTO life_received_messages VALUES(?,?,?)',('m1',canonical({'content':content}),canonical({})))
        item=dict(kind='movie',title='测试电影',author='',year='',priority='request',evidence_quote=content)
        self.cog.calls.ask=Mock(return_value={'items':[item]})
        self.p.config.setdefault('movies',{})['existing']={'title':'测试电影','available':True}
        self.assertTrue(media.process_one(self.cog))
        self.assertTrue(media.process_one(self.cog))
        row=media.view(self.cog)[0]
        self.assertEqual(row['status'],'ready');self.assertEqual(row['resource_id'],'existing')
        self.assertEqual(media.annotations(self.cog)['existing']['priority'],'request')

    def test_rejects_invented_title_and_no_partial_write(self):
        with self.p.store.connect() as db:
            media.enqueue(db,'bad')
            with self.assertRaises(ValueError):
                media.save(db,'bad','你好',[],{'items':[dict(kind='book',title='不存在',author='',year='',priority='mention',evidence_quote='你好')]},self.clock.now().isoformat())
        self.assertEqual(media.view(self.cog),[])

    def test_ambiguous_movie_does_not_guess(self):
        self.add()
        with self.p.store.connect() as db:db.execute("UPDATE life_media_messages SET status='done'")
        with patch('life_prototype.douban.Douban') as client:
            client.return_value.call.return_value=[{'id':'1','title':'测试电影','year':'2000'},{'id':'2','title':'测试电影','year':'2020'}]
            media.process_one(self.cog)
        self.assertEqual(media.view(self.cog)[0]['status'],'needs_clarification')

    def test_book_structure_enters_reading_resources_not_purchases(self):
        self.add(kind='book',title='测试书籍')
        from life_prototype.weread_library import resources
        book={'weread_id':'abc','title':'测试书籍','author':'作者','url':'weread_book:abc'}
        with patch('life_prototype.weread.search',return_value=[book]),patch('life_prototype.weread.info',return_value=book),patch('life_prototype.weread.chapters',return_value={'bookId':'abc','chapters':[{'chapterUid':'1','title':'第一章','wordCount':1000}]}):
            media.process_one(self.cog)
        row=media.view(self.cog)[0];self.assertEqual(row['status'],'ready')
        fresh={'books':{},'objects':{}}
        with self.p.store.connect() as db:
            resources(db,fresh)
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='life_owned_books'").fetchone())
        self.assertIn(row['resource_id'],fresh['books'])
        self.assertEqual(fresh['books'][row['resource_id']]['total_chars'],1000)

    def test_failed_lookup_retains_recommendation_for_retry(self):
        self.add()
        with patch('life_prototype.media_recommendations.resolve',side_effect=TimeoutError):media.process_one(self.cog)
        row=media.view(self.cog)[0]
        self.assertEqual(row['status'],'retry');self.assertEqual(row['title'],'测试电影')

    def test_verified_new_movie_has_runtime_and_no_watch_progress(self):
        self.add(priority='request')
        before=self.p.snapshot()
        detail={'id':'12','title':'测试电影','year':'2020','url':'https://movie.douban.com/subject/12/',
                'duration_options':[{'duration_seconds':6000,'label':'100分钟'}],'summary':'简介','genres':[]}
        with patch('life_prototype.douban.Douban') as client:
            client.return_value.call.side_effect=[[detail],detail]
            media.process_one(self.cog)
        row=media.view(self.cog)[0]
        self.assertEqual(row['status'],'ready')
        with self.p.store.connect() as db:
            movie=json.loads(db.execute("SELECT body FROM life_evidence WHERE category='discovered_movie'").fetchone()[0])
        self.assertEqual(movie['duration_seconds'],6000)
        self.assertEqual(self.p.snapshot(),before)

    def test_none_extraction_marks_message_done_without_candidates(self):
        with self.p.store.connect() as db:
            media.enqueue(db,'none')
            media.save(db,'none','不要看那部电影',[],{'items':[]},self.clock.now().isoformat())
            self.assertEqual(db.execute('SELECT status FROM life_media_messages').fetchone()[0],'done')
        self.assertEqual(media.view(self.cog),[])


if __name__=='__main__':unittest.main()
