import sys,unittest,time
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voice_audio import VoiceAudio


def pcm(samples):return np.rint(samples*32767).astype('<i2').tobytes()
def decode(data):return np.frombuffer(data,dtype='<i2').astype(float)/32767
def render(data,processor,chunks=777):
    return b''.join(processor.feed(data[i:i+chunks]) for i in range(0,len(data),chunks))+processor.finish()


class AudioTests(unittest.TestCase):
    def test_neutral_processing_reconstructs_impulse_and_retains_exact_length(self):
        samples=np.zeros(5021);samples[[0,256,5000]]=.01
        data=pcm(samples)
        result=render(data,VoiceAudio(formant_semitones=0,air_db=0))
        self.assertEqual(len(result),len(data))
        self.assertLess(np.max(np.abs(decode(result)-decode(data))),1/32767+.000001)

    def test_arbitrary_odd_byte_chunks_have_identical_output_and_silence_is_silent(self):
        rng=np.random.default_rng(1);data=pcm(rng.normal(0,.01,45000))
        self.assertEqual(render(data,VoiceAudio(),777),render(data,VoiceAudio(),6000))
        self.assertEqual(render(bytes(10000),VoiceAudio()),bytes(10000))

    def test_pitch_and_duration_are_preserved_with_formant_processing(self):
        t=np.arange(44100)/44100
        data=pcm(.04*np.sin(2*np.pi*220*t))
        result=decode(render(data,VoiceAudio()))
        self.assertEqual(len(result),len(t))
        spectrum=np.abs(np.fft.rfft(result[4096:-4096]))
        peak=np.fft.rfftfreq(len(result[4096:-4096]),1/44100)[np.argmax(spectrum)]
        self.assertLess(abs(peak-220),2)

    def test_air_shelf_enhances_upper_frequencies_more_than_bass(self):
        t=np.arange(22050)/44100
        gains=[]
        for frequency in (500,12000):
            data=pcm(.03*np.sin(2*np.pi*frequency*t))
            result=decode(render(data,VoiceAudio(formant_semitones=0)))[2048:-2048]
            gains.append(float(np.sqrt(np.mean(result**2))))
        self.assertGreater(gains[1]/gains[0],1.2)

    def test_brat_presence_boost_targets_mid_high_voice_band(self):
        t=np.arange(22050)/44100;gains=[]
        for frequency in (500,3250,12000):
            data=pcm(.015*np.sin(2*np.pi*frequency*t))
            plain=decode(render(data,VoiceAudio(formant_semitones=0,air_db=0)))[2048:-2048]
            boosted=decode(render(data,VoiceAudio(formant_semitones=0,air_db=0,presence_db=2.5)))[2048:-2048]
            gains.append(float(np.sqrt(np.mean(boosted**2)/np.mean(plain**2))))
        self.assertGreater(gains[1],1.25)
        self.assertLess(gains[0],1.02);self.assertLess(gains[2],1.02)

    def test_formant_envelope_moves_up_without_moving_harmonic_bins(self):
        t=np.arange(44100)/44100;frequencies=np.arange(100,5000,100)
        envelope=np.exp(-.5*((frequencies-1200)/220)**2)+.6*np.exp(-.5*((frequencies-2700)/320)**2)
        samples=np.sum((envelope/frequencies)[:,None]*np.sin(2*np.pi*frequencies[:,None]*t),axis=0)
        samples=samples/np.max(np.abs(samples))*.05
        shifted=decode(render(pcm(samples),VoiceAudio(air_db=0),4096))
        bins=np.fft.rfftfreq(22050,1/44100)
        before=np.abs(np.fft.rfft(samples[11025:33075]))
        after=np.abs(np.fft.rfft(shifted[11025:33075]))
        mask=(bins>=800)&(bins<=1700)
        center=lambda spectrum:float(np.sum(bins[mask]*spectrum[mask])/np.sum(spectrum[mask]))
        self.assertGreater(center(after)-center(before),35)
        # The most prominent harmonics remain at the original 100 Hz multiples.
        strongest=bins[np.argpartition(after,-5)[-5:]]
        self.assertTrue(np.all(np.abs(strongest/100-np.rint(strongest/100))<.025))

    def test_compression_reduces_loud_peaks_and_reset_drops_previous_audio(self):
        t=np.arange(22050)/44100
        data=pcm(.9*np.sin(2*np.pi*400*t))
        processed=decode(render(data,VoiceAudio(formant_semitones=0,air_db=0)))
        self.assertLess(np.max(np.abs(processed[2048:])),.5)
        processor=VoiceAudio();processor.feed(data[:301]);processor.reset()
        self.assertEqual(render(bytes(2000),processor),bytes(2000))

    def test_partial_pcm_sample_is_reported_instead_of_silently_truncated(self):
        processor=VoiceAudio();processor.feed(b'\x01')
        with self.assertRaises(ValueError):processor.finish()

    def test_processing_cost_is_small_relative_to_audio_duration(self):
        t=np.arange(88200)/44100;data=pcm(.03*np.sin(2*np.pi*220*t))
        started=time.perf_counter();render(data,VoiceAudio(),4096)
        self.assertLess(time.perf_counter()-started,.4)


if __name__=='__main__':unittest.main()
