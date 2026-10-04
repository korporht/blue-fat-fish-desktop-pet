import sys,unittest,re
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voice_delivery import SpeechText,reply_style,PRESETS,preset_name,speech_emotion


class DeliveryTests(unittest.TestCase):
    def spoken(self,parts,emotion='none'):
        delivery=SpeechText(emotion)
        return ''.join(delivery.feed(part) for part in parts)+delivery.feed('',final=True)

    def test_prose_streams_immediately_and_neutral_delivery_stays_soft(self):
        delivery=SpeechText()
        first=delivery.feed('主人，')
        self.assertTrue(first.endswith('主人，'))
        self.assertIn('[soft tone',first)
        self.assertEqual(delivery.feed('我在这里。'),'我在这里。')

    def test_punctuation_crosses_arbitrary_network_boundaries_without_repeat(self):
        parts=['那个','.','.','.','主人…','…','我在哦~','~','！','!']
        spoken=self.spoken(parts)
        self.assertEqual(re.sub(r'\[[^\]]*\]','',spoken),'那个……主人……我在哦～！')

    def test_teasing_and_praise_have_different_delivery_without_forced_catchphrases(self):
        teased=self.spoken(['才、才没有！','不要乱猜！'],'teased')
        shy=self.spoken(['主人，别这样夸我啦。'],'shy')
        self.assertIn('[playfully annoyed',teased)
        self.assertIn('[embarrassed',shy)
        self.assertIn('！！',teased)
        self.assertNotIn('哼',teased)

    def test_user_sadness_and_task_status_do_not_sound_like_angry_or_crying_fish(self):
        self.assertIn('[soft tone',self.spoken(['我陪着你。'],'sad'))
        self.assertEqual(reply_style('工作在等待确认。'),'soft')
        self.assertEqual(reply_style('主人，我在呢。才没有想你！'),'soft')

    def test_soft_to_flustered_to_soft_transition_is_sparse(self):
        spoken=self.spoken(['主人，红茶来啦。','才、才不是特意给你泡的！','小心烫哦。'])
        self.assertIn('[playfully annoyed',spoken)
        self.assertEqual(spoken.count('['),3)
        self.assertTrue(spoken.endswith('小心烫哦。'))

    def test_brat_streams_prose_with_smug_then_flustered_delivery(self):
        delivery=SpeechText(preset='brat')
        first=delivery.feed('噗～杂鱼主人，就这？～')
        self.assertIn('[smug',first)
        self.assertIn('杂鱼主人，就这？',first)
        tail=delivery.feed('等等！我道歉还不行嘛！')+delivery.feed('',final=True)
        self.assertIn('[flustered',tail)
        self.assertIn('！！',tail)
        self.assertNotIn('soft tone, slightly dreamy',first+tail)

    def test_brat_support_keeps_sincere_delivery_and_unknown_presets_fall_back(self):
        delivery=SpeechText('sad','brat')
        self.assertIn('[soft tone, sincere',delivery.feed('我在这里陪你。'))
        self.assertEqual(preset_name(['brat']),'maid')
        self.assertEqual(preset_name('something else'),'maid')
        self.assertEqual(SpeechText(preset='unknown').preset,'maid')
        self.assertEqual((PRESETS['brat'].temperature,PRESETS['brat'].formant,PRESETS['brat'].presence_db),(.9,1.5,2.5))
        self.assertEqual(speech_emotion('被我抓到偷吃了吧','none','brat'),'flustered')
        self.assertEqual(speech_emotion('被我抓到偷吃了吧','none','maid'),'none')
        self.assertEqual(speech_emotion('任务破防了吗','none','brat',event='report'),'report')

    def test_long_interjection_dash_is_a_single_short_pause_across_fragments(self):
        spoken=self.spoken(['诶','—','—','测试什么呀？','\n\n……好啦。'])
        self.assertEqual(re.sub(r'\[[^\]]*\]','',spoken),'诶，测试什么呀？\n\n……好啦。')

    def test_brat_tone_cues_never_request_standalone_cries_or_laughter(self):
        delivery=SpeechText(preset='brat')
        spoken=''.join(delivery.feed(part) for part in
            ['噗～就这？','等等！我错了。','本女仆厉害吧。','唔？','放心不下呢。'])+delivery.feed('',final=True)
        cues=re.findall(r'\[[^\]]*\]',spoken)
        self.assertLessEqual(len(cues),3)
        self.assertFalse(re.search(r'snicker|giggle|chuckl|sigh|whimper|drawn-out', ''.join(cues)))

    def test_repeated_vocalisations_are_shortened_across_chunks_without_changing_words(self):
        spoken=self.spoken(['刚才还呜','呜','呜，现在又酷','酷酷，','嘻','嘻','嘻，','啊啊。'])
        self.assertEqual(re.sub(r'\[[^\]]*\]','',spoken),'刚才还呜，现在又酷酷酷，嘻嘻，啊。')


if __name__=='__main__':unittest.main()
