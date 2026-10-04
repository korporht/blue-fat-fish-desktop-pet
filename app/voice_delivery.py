"""Local, incremental delivery cues; the visible reply and memory stay untouched."""
import re
from dataclasses import dataclass

BASE_SPEED = .98
TEMPERATURE = .85
TOP_P = .9

@dataclass(frozen=True)
class VoicePreset:
    label: str
    speed: float
    temperature: float
    top_p: float
    formant: float
    presence_db: float = 0.0

PRESETS = {
    'maid': VoicePreset('呆萌女仆', BASE_SPEED, TEMPERATURE, TOP_P, 1.0),
    'brat': VoicePreset('雌小鬼', 1.0, .9, .9, 1.5, 2.5),
}

def preset_name(value):
    return value if isinstance(value, str) and value in PRESETS else 'maid'

def speech_emotion(text, emotion='none', preset='maid', event='user'):
    if event != 'user': return 'report'
    if emotion in ('sad','cry'): return emotion
    if preset == 'brat' and re.search(r'抓到.{0,8}偷吃|抓住|认输|吃瘪|破防|制裁|挠痒|捏脸',text):
        return 'flustered'
    return emotion

STYLES = {
    'soft': '[soft tone, gentle]',
    'teased': '[playfully annoyed, quick speech]',
    'shy': '[embarrassed, shy]',
    'proud': '[proud, playful tone]',
    'happy': '[happy, light and warm]',
    'curious': '[curious, gentle tone]',
    'surprised': '[surprised]',
}
BRAT_STYLES = {
    'soft': '[soft tone, sincere and gentle]',
    # Describe the spoken tone, rather than asking for standalone vocal effects.
    'smug': '[smug, teasing tone]',
    'teased': '[flustered, quick speech]',
    'shy': '[shy, hesitant tone]',
    'proud': '[proud, playful tone]',
    'happy': '[happy, smiling tone]',
    'curious': '[playful, questioning tone]',
    'surprised': '[surprised]',
    'pity': '[mock concern, gentle teasing]',
    'flustered': '[flustered, quick speech]',
    'whisper': '[soft, teasing tone]',
}


def reply_style(text, fallback='soft', preset='maid'):
    # Classify her own wording, never make the user's distress sound like anger.
    text = re.split(r'[。！？!?\n]', text, maxsplit=1)[0]
    if preset == 'brat':
        if re.search(r'等一下|等等|对不起|我(?:道歉|错了)|认输|饶了|别(?:捏|戳|挠)',text): return 'flustered'
        if re.search(r'放心不下|可怜|让人担心|真拿你没办法',text): return 'pity'
        if re.search(r'悄悄|小声|靠近一点',text): return 'whisper'
        if re.search(r'杂鱼|好逊|太逊|就这|不会吧|大叔|噗|嘻嘻|呵[～~]',text): return 'smug'
    if re.search(r'才[、，—-]?才?(?:没有|不是|不)|谁[、，]?谁(?:让|要)|不理你|笨蛋主人', text):
        return 'teased'
    if re.search(r'害羞|脸红|别(?:这么|这样)夸|靠这么近', text): return 'shy'
    if re.search(r'快(?:点)?夸我|本女仆|厉害吧|当然啦', text): return 'proud'
    if re.match(r'(?:诶|欸|咦|那个|唔)[？?…，、]', text): return 'curious'
    return fallback


class SpeechText:
    """Never buffer prose; normalize only punctuation runs split across chunks."""
    def __init__(self, emotion='none', preset='maid'):
        self.preset = preset_name(preset)
        self.styles = BRAT_STYLES if self.preset == 'brat' else STYLES
        default = 'smug' if self.preset == 'brat' else 'soft'
        if emotion in ('sad','cry','report','comfort'): default = 'soft'
        self.style = emotion if emotion in self.styles else default
        self.max_tags = 3
        self.started = False
        self.at_sentence_start = True
        self.pending_punctuation = ''
        self.tags = 0
        self.dash_run = False
        self.vocal_char = ''
        self.vocal_count = 0

    def feed(self, text, final=False):
        out = []
        for index, char in enumerate(text):
            if char in '啊呜哼唔嗯诶欸噗嘻哈':
                self.vocal_count = self.vocal_count+1 if char == self.vocal_char else 1
                self.vocal_char = char
                if self.vocal_count > (2 if char in '嘻哈' else 1): continue
            else:
                self.vocal_char = ''; self.vocal_count = 0
            if char in '—–':
                if self.pending_punctuation: out.append(self.flush_punctuation())
                # A prolonged "诶——" invites sustained vocalisation. Keep only a
                # short pause in the speech copy, even across network fragments.
                if not self.dash_run: out.append('，')
                self.dash_run = True
                continue
            self.dash_run = False
            if char in '.…!！~～':
                self.pending_punctuation += char
                continue
            if self.pending_punctuation:
                out.append(self.flush_punctuation())
            if not self.started and not char.isspace():
                self.style = reply_style(text[index:], self.style, self.preset)
                out.append(self.styles[self.style]); self.started = True; self.tags += 1
            elif self.at_sentence_start and not char.isspace() and self.started and self.tags < self.max_tags:
                fallback = 'soft' if self.style == 'soft' else 'smug' if self.preset == 'brat' else 'soft'
                style = reply_style(text[index:], fallback, self.preset)
                if style != self.style:
                    out.append(self.styles[style]); self.style = style; self.tags += 1
            out.append(char)
            if not char.isspace(): self.at_sentence_start = char in '。！？!?\n'
        if final and self.pending_punctuation: out.append(self.flush_punctuation())
        return ''.join(out)

    def flush_punctuation(self):
        value, self.pending_punctuation = self.pending_punctuation, ''
        value = re.sub(r'(?:\.{3,}|…+)', '……', value)
        sharp = self.style == 'teased' or (self.preset == 'brat' and self.style in ('flustered','shy'))
        value = re.sub(r'[!！]+', '！！' if sharp else '！', value)
        value = re.sub(r'[~～]+', '～', value)
        if value.endswith('！'): self.at_sentence_start = True
        return value
