"""Bounded streaming spectral-envelope shift, air EQ and gentle peak compression.

Frequency bins and phase are preserved: this changes the spectral envelope,
not pitch or sample rate. A 1024-sample window adds under 24 ms of buffering.
"""
import math
import numpy as np


class VoiceAudio:
    def __init__(self, sample_rate=44100, formant_semitones=1.0, air_db=2.5, ratio=3.0, presence_db=0.0):
        self.rate = sample_rate
        self.size = 1024
        self.hop = 256
        self.window = np.sqrt(np.hanning(self.size + 1)[:-1])
        self.shift = 2 ** (formant_semitones / 12)
        bins = np.arange(self.size // 2 + 1)
        # Smooth high shelf centered at 8 kHz, capped at +2.5 dB.
        frequency = bins * sample_rate / self.size
        self.air = 10 ** ((air_db * frequency**4 / (frequency**4 + 8000**4)) / 20)
        # Broad presence bump over 2.5–4 kHz; preserve bass and original pitch.
        presence = presence_db * np.exp(-.5 * ((frequency - 3250) / 650)**2)
        self.air *= 10 ** (presence / 20)
        self.bins = bins
        self.ratio = ratio
        self.reset()

    def reset(self):
        self.input = np.zeros(self.size - self.hop)
        self.overlap = np.zeros(self.size)
        self.weight = np.zeros(self.size)
        self.byte_tail = b''
        self.skip = self.size - self.hop
        self.received = self.emitted = 0
        self.gain = 1.0

    def feed(self, data):
        data = self.byte_tail + data
        even = len(data) // 2 * 2
        self.byte_tail = data[even:]
        samples = np.frombuffer(data[:even], dtype='<i2').astype(np.float64) / 32768
        self.received += len(samples)
        self.input = np.concatenate((self.input, samples))
        return self.process()

    def process(self):
        output = []
        while len(self.input) >= self.size:
            spectrum = np.fft.rfft(self.input[:self.size] * self.window)
            if self.shift != 1:
                log_magnitude = np.log(np.maximum(np.abs(spectrum), 1e-7))
                cepstrum = np.fft.irfft(log_magnitude, n=self.size)
                # Low-quefrency liftering estimates the broad vocal tract envelope.
                cepstrum[40:-39] = 0
                envelope = np.fft.rfft(cepstrum).real
                shifted = np.interp(self.bins / self.shift, self.bins, envelope)
                adjustment = np.clip(shifted - envelope, -math.log(2), math.log(2))
                # Preserve bass and unvoiced upper-frequency texture.
                blend = np.clip((self.bins * self.rate / self.size - 200) / 400, 0, 1)
                blend *= np.clip((9000 - self.bins * self.rate / self.size) / 2000, 0, 1)
                spectrum *= np.exp(adjustment * blend)
            frame = np.fft.irfft(spectrum * self.air, n=self.size) * self.window
            self.overlap += frame
            self.weight += self.window**2
            block = self.overlap[:self.hop] / np.maximum(self.weight[:self.hop], 1e-9)
            if self.skip:
                self.skip -= self.hop
            else:
                remaining = self.received - self.emitted
                block = block[:min(len(block), remaining)]
                if len(block):
                    output.append(self.compress(block)); self.emitted += len(block)
            self.overlap[:-self.hop] = self.overlap[self.hop:]; self.overlap[-self.hop:] = 0
            self.weight[:-self.hop] = self.weight[self.hop:]; self.weight[-self.hop:] = 0
            self.input = self.input[self.hop:]
        if not output: return b''
        samples = np.concatenate(output)
        return np.rint(np.clip(samples, -.98, .98) * 32767).astype('<i2').tobytes()

    def compress(self, block):
        peak = float(np.max(np.abs(block)))
        threshold = 10 ** (-18 / 20)
        target = (threshold / peak) ** (1 - 1 / self.ratio) if peak > threshold else 1.0
        # Fast attack, 120 ms release; no makeup gain or noise-floor pumping.
        coefficient = math.exp(-1 / (self.rate * (.004 if target < self.gain else .12)))
        gains = target + (self.gain - target) * coefficient ** np.arange(1, len(block) + 1)
        self.gain = float(gains[-1])
        return block * gains

    def finish(self):
        if self.byte_tail: raise ValueError('Incomplete PCM sample')
        self.input = np.concatenate((self.input, np.zeros(self.size)))
        return self.process()
