"""Decoding a song's file (src/musikata_core/audio/decode.py; A4.1): every kind of R2.2, and the
shapes the files take (docs/process/testing.md, "Shapes": `audio`), decoded to the device's rate
and channels as float32 blocks of a set size; and the files that can't be played.

Why: the device is fed only what this hands on. A rate taken wrong plays the song at the wrong
pitch; a mono song folded the way FFmpeg folds it plays 3 dB quieter than the stereo one before
it, and a 5.1 one folded without care clips; a block of the wrong size or a frame lost between
two is a click. And a damaged file must stop with its reason, never stop the thread playing it."""

import fractions
import logging
import os
import sys
from pathlib import Path

import av
import mutagen.mp4
import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from musikata_core.audio import decode

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

TONE = 440


def write(path, fmt, codec, sample_fmt, rate, layout, seconds=0.5, level=0.5, frames=None,
          options=None, vbr=False, silence=0):  # fmt: skip
    """A sine of TONE Hz at `level` in every channel, `seconds` long (or `frames` samples), then
    `silence` samples of nothing, written by FFmpeg as `codec` in `sample_fmt` (packed, or planar
    with a "p"), at `rate`, in `layout`; `options` are the container's (the muxer's), and `vbr`
    asks the encoder for a variable rate (LAME's -V 4)."""
    n = frames if frames is not None else int(rate * seconds)
    channels = av.AudioLayout(layout).nb_channels
    x = level * np.sin(2 * np.pi * TONE * np.arange(n) / rate)
    x = np.concatenate([x, np.zeros(silence)])
    n += silence
    with av.open(path, "w", format=fmt, options=options or {}) as out:
        s = out.add_stream(codec, rate=rate, layout=layout)
        s.codec_context.format = sample_fmt
        if vbr:
            s.codec_context.flags |= av.codec.context.Flags.qscale
            s.codec_context.global_quality = 4 * 118  # FFmpeg's FF_QP2LAMBDA
        step = s.codec_context.frame_size or 1024
        for i in range(0, n, step):
            chunk = np.tile(x[i : i + step], (channels, 1))
            kind = sample_fmt.rstrip("p")
            if kind == "s16":
                chunk = (chunk * 32767).astype(np.int16)
            elif kind == "s32":
                chunk = (chunk * 2147483647).astype(np.int32)
            elif kind == "u8":
                chunk = (chunk * 127 + 128).astype(np.uint8)
            elif kind == "flt":
                chunk = chunk.astype(np.float32)
            arr = chunk if sample_fmt.endswith("p") else chunk.T.reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(
                np.ascontiguousarray(arr), format=sample_fmt, layout=layout
            )
            frame.sample_rate, frame.pts, frame.time_base = rate, i, fractions.Fraction(1, rate)
            for packet in s.encode(frame):
                out.mux(packet)
        for packet in s.encode(None):
            out.mux(packet)
    return path


def decoded(path, rate=48000, channels=2, block=960):
    """The file played alone at the device's `rate` and `channels`, checked as blocks of `block`
    frames, and its decoder."""
    with decode.Decoder(path, channels) as d:
        blocks = list(decode.played(d, rate, block))
    assert all(len(b) == block for b in blocks[:-1]) and 0 < len(blocks[-1]) <= block
    assert all(b.dtype == np.float32 and b.shape[1] == channels for b in blocks)
    return d, np.concatenate(blocks)


def pitch(samples, rate):
    """The strongest frequency in a channel, in Hz."""
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return np.argmax(spectrum) * rate / len(samples)


# ---------- folding channels: plain arithmetic ----------


def test_mono_goes_whole_to_both_sides_and_stereo_stays_as_it_is():
    assert np.array_equal(decode.mix_matrix(["FC"], 2), [[1, 1]])
    assert np.array_equal(decode.mix_matrix(["FL", "FR"], 2), np.eye(2))
    assert np.array_equal(decode.mix_matrix(["NONE"], 1), [[1]])
    block = np.array([[0.5, -0.25]], np.float32)
    assert decode.mix(block, decode.mix_matrix(["FL", "FR"], 2)) is block


def test_to_a_mono_device_every_channel_but_the_lfe_is_averaged():
    assert np.allclose(decode.mix_matrix(["FL", "FR"], 1), [[0.5], [0.5]])
    six = decode.mix_matrix(["FL", "FR", "FC", "LFE", "BL", "BR"], 1)
    assert np.allclose(six[:, 0], [0.2, 0.2, 0.2, 0, 0.2, 0.2])
    assert np.allclose(decode.mix_matrix(["LFE", "LFE2"], 1), [[0.5], [0.5]])  # nothing else


def test_surround_folds_to_its_sides_with_the_centre_in_both_and_never_past_full_scale():
    names = ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"]
    m = decode.mix_matrix(names, 2)
    assert m[3].tolist() == [0, 0] and m[2, 0] == m[2, 1] > 0
    assert m[0, 1] == m[1, 0] == m[4, 1] == m[6, 1] == 0
    assert np.allclose(m.sum(axis=0), 1.0)  # every channel at full scale at once: just full scale
    loud = np.ones((4, 8), np.float32)
    assert np.abs(decode.mix(loud, m)).max() <= 1.0 + 1e-6


def test_channels_of_no_known_name_go_left_and_right_by_their_place():
    m = decode.mix_matrix(["NONE", "NONE", "NONE", "NONE"], 2)
    assert np.allclose(m, [[0.5, 0], [0, 0.5], [0.5, 0], [0, 0.5]])
    quad = decode.mix_matrix(["FL", "FR", "BL", "BR"], 2)
    assert quad[2, 0] > 0 and quad[3, 1] > 0 and quad[2, 1] == 0


def test_a_device_of_more_than_two_channels_isnt_folded_for():
    with pytest.raises(ValueError, match="1 or 2 only"):
        decode.mix_matrix(["FL", "FR"], 6)


def test_blocks_come_out_at_the_size_asked_whatever_sizes_went_in():
    chunks = [np.full((n, 1), i, np.float32) for i, n in enumerate((3, 0, 5, 1, 9))]
    out = list(decode.reblock(chunks, 4))
    assert [len(b) for b in out] == [4, 4, 4, 4, 2]
    assert np.concatenate(out)[:, 0].tolist() == [0, 0, 0, 2, 2, 2, 2, 2, 3] + [4] * 9
    assert list(decode.reblock([], 4)) == []


@given(st.lists(st.integers(0, 30), max_size=10), st.integers(1, 20))
def test_reblocking_keeps_every_frame_in_order(sizes, size):
    start = np.cumsum([0, *sizes])
    chunks = [
        np.arange(a, a + n, dtype=np.float32)[:, None] for a, n in zip(start, sizes, strict=False)
    ]
    out = list(decode.reblock(chunks, size))
    assert all(len(b) == size for b in out[:-1])
    joined = np.concatenate(out)[:, 0] if out else np.zeros(0)
    assert joined.tolist() == list(range(sum(sizes)))


# ---------- files, in their shapes ----------


@pytest.fixture(scope="module")
def kinds(tmp_path_factory):
    """One second of a tone in each kind of R2.2, as the demo library writes it: {kind: path}."""
    d = tmp_path_factory.mktemp("kinds")
    out = {}
    for kind, (ext, *_rest) in demo.KINDS.items():
        out[kind] = str(d / f"{kind}.{ext}")
        demo.encode(out[kind], kind, 1.0, TONE)
    return out


@pytest.mark.parametrize("kind", list(demo.KINDS))
def test_each_kind_decodes_to_its_length_and_pitch_at_the_devices_rate(kinds, kind):
    d, samples = decoded(kinds[kind])
    assert d.info.rate == demo.KINDS[kind][4] and d.info.channels == 2
    assert d.info.seconds == pytest.approx(1.0, abs=0.01)
    assert len(samples) == pytest.approx(48000, abs=48000 * 0.01)  # the encoders' padding trimmed
    assert pitch(samples[:, 0], 48000) == pytest.approx(TONE, abs=2)
    assert 0.25 < np.abs(samples).max() < 0.4  # the demo's level, 0.3 and a little noise
    assert d.skipped == 0 and d.decoded == pytest.approx(d.info.rate, abs=d.info.rate * 0.01)
    assert len(samples) == -(-d.decoded * 48000 // d.info.rate)  # resampled with nothing lost


@pytest.mark.parametrize(
    ("codec", "sample_fmt"),
    [("pcm_u8", "u8"), ("pcm_s16le", "s16"), ("pcm_s24le", "s32"), ("pcm_s32le", "s32"),
     ("pcm_f32le", "flt"), ("pcm_f64le", "dbl")],
)  # fmt: skip
def test_every_sample_format_comes_out_as_floats_at_the_level_it_went_in(
    tmp_path, codec, sample_fmt
):
    path = write(str(tmp_path / "a.wav"), "wav", codec, sample_fmt, 48000, "stereo")
    _, samples = decoded(path)
    assert samples.dtype == np.float32
    assert np.abs(samples).max() == pytest.approx(0.5, abs=0.01)


@pytest.mark.parametrize("sample_fmt", ["s16", "s32"])  # 16 and 24 bits
def test_flac_of_16_and_24_bits_decode_alike(tmp_path, sample_fmt):
    path = write(str(tmp_path / "a.flac"), "flac", "flac", sample_fmt, 44100, "stereo")
    _, samples = decoded(path, 44100)
    assert len(samples) == 22050 and np.abs(samples).max() == pytest.approx(0.5, abs=0.001)


@pytest.mark.parametrize("rate", [8000, 22050, 44100, 48000, 96000, 192000])
def test_every_rate_is_resampled_to_the_devices_keeping_length_and_pitch(tmp_path, rate):
    path = write(str(tmp_path / "a.flac"), "flac", "flac", "s16", rate, "stereo")
    d, samples = decoded(path, 48000)
    assert d.info.rate == rate
    assert len(samples) == pytest.approx(24000, abs=2)
    assert pitch(samples[:, 0], 48000) == pytest.approx(TONE, abs=2)


def test_mono_plays_at_the_same_level_in_both_sides(tmp_path):
    path = write(str(tmp_path / "a.flac"), "flac", "flac", "s16", 44100, "mono")
    d, samples = decoded(path)
    assert d.info.channels == 1
    assert np.array_equal(samples[:, 0], samples[:, 1])
    assert np.abs(samples).max() == pytest.approx(0.5, abs=0.01)  # not FFmpeg's -3 dB


@pytest.mark.parametrize(
    ("fmt", "codec", "ext", "layout"),
    [("wav", "pcm_s16le", "wav", "quad"), ("wav", "pcm_f32le", "wav", "5.1"),
     ("flac", "flac", "flac", "7.1")],
)  # fmt: skip
def test_more_channels_fold_to_stereo_without_clipping(tmp_path, fmt, codec, ext, layout):
    sample_fmt = "flt" if codec == "pcm_f32le" else "s16"
    path = write(str(tmp_path / f"a.{ext}"), fmt, codec, sample_fmt, 48000, layout, level=0.9)
    d, samples = decoded(path)
    assert d.info.channels == av.AudioLayout(layout).nb_channels
    assert np.array_equal(samples[:, 0], samples[:, 1]) and np.abs(samples).max() <= 0.9 + 1e-3


def test_a_wav_without_a_channel_mask_and_a_mono_device(tmp_path):
    # a plain WAVE_FORMAT_PCM header names no channels: FFmpeg calls them NONE
    path = write(str(tmp_path / "a.wav"), "wav", "pcm_s16le", "s16", 22050, "stereo")
    with av.open(path) as f:
        assert [c.name for c in f.streams.audio[0].layout.channels] == ["NONE", "NONE"]
    _, samples = decoded(path, 22050, channels=1, block=441)
    assert samples.shape == (11025, 1) and np.abs(samples).max() == pytest.approx(0.5, abs=0.01)


def test_a_cover_in_the_file_is_passed_over_for_the_audio(kinds, tmp_path):
    # FFmpeg sees an embedded cover as a video stream, which may come first
    path = str(tmp_path / "a.mp3")
    with open(kinds["mp3"], "rb") as src, open(path, "wb") as dst:
        dst.write(src.read())
    demo.tag(path, demo.Song(path, "mp3", {"title": "Signal Fires"}, cover=(11, 32)))
    with av.open(path) as f:
        assert f.streams.video  # the cover
    _, samples = decoded(path)
    assert len(samples) == pytest.approx(48000, abs=480)


def damaged(source, path, at=1 / 3):
    """A copy of `source` with 400 bytes a third of the way in scrambled."""
    data = bytearray(Path(source).read_bytes())
    start = int(len(data) * at)
    data[start : start + 400] = bytes((b * 7 + 13) % 256 for b in data[start : start + 400])
    Path(path).write_bytes(bytes(data))
    return path


@pytest.mark.parametrize("kind", ["mp3", "aac", "alac"])
def test_a_damaged_file_plays_on_past_what_doesnt_decode_and_says_so(kinds, tmp_path, kind, caplog):
    path = damaged(kinds[kind], str(tmp_path / ("bad" + os.path.splitext(kinds[kind])[1])))
    caplog.set_level(logging.WARNING)
    d, samples = decoded(path)
    assert len(samples) > 48000 * 0.5  # most of it, the damaged part aside
    assert d.skipped and f"skipped {d.skipped} damaged packets of {path}" in caplog.text


def test_damage_flacs_decoder_hides_plays_through_without_a_skip(kinds, tmp_path):
    # FLAC's decoder finds the damaged frame by its checksum and hands on what it could make of it
    d, samples = decoded(damaged(kinds["flac"], str(tmp_path / "bad.flac")))
    assert d.skipped == 0 and len(samples) > 48000 * 0.5


def cut(source, path):
    """A copy of the first half of `source`, as a copy or download stopped halfway leaves it."""
    data = Path(source).read_bytes()
    Path(path).write_bytes(data[: len(data) // 2])
    return path


@pytest.mark.parametrize("kind", ["flac", "mp3", "wav", "aiff"])
def test_a_file_that_ends_early_plays_up_to_where_it_ends(kinds, tmp_path, kind):
    path = cut(kinds[kind], str(tmp_path / ("cut" + os.path.splitext(kinds[kind])[1])))
    d, samples = decoded(path)
    assert d.info.seconds == pytest.approx(1.0, abs=0.6)  # what the header promised, or less
    assert 48000 * 0.3 < len(samples) < 48000 * 0.6


@pytest.mark.parametrize("kind", ["aac", "alac", "opus"])
def test_a_file_cut_before_what_it_needs_to_open_cant_be_played(kinds, tmp_path, kind):
    # an MP4's index (moov) is at its end; Ogg's length is read from its last page
    path = cut(kinds[kind], str(tmp_path / ("cut" + os.path.splitext(kinds[kind])[1])))
    with pytest.raises(decode.DecodeError, match="couldn't open"):
        decode.Decoder(path, 2)


def test_a_missing_file_an_empty_one_and_one_of_noise_cant_be_played(tmp_path):
    with pytest.raises(decode.DecodeError, match="couldn't open"):
        decode.Decoder(str(tmp_path / "gone.flac"), 2)
    noise = tmp_path / "noise.mp3"
    noise.write_bytes(np.random.default_rng(1).bytes(5000))
    with pytest.raises(decode.DecodeError, match="couldn't open"):
        decode.Decoder(str(noise), 2)
    empty = tmp_path / "empty.flac"
    empty.write_bytes(b"")
    with (
        decode.Decoder(str(empty), 2) as d,  # FFmpeg opens it, and finds nothing in it
        pytest.raises(decode.DecodeError, match="nothing in .* decodes"),
    ):
        list(d.blocks(960))


def test_a_file_with_no_audio_in_it_cant_be_played(tmp_path):
    path = str(tmp_path / "cover.mkv")
    with av.open(path, "w", format="matroska") as out:
        s = out.add_stream("mjpeg", rate=1)
        s.width = s.height = 16
        s.pix_fmt = "yuvj420p"
        frame = av.VideoFrame.from_ndarray(np.zeros((16, 16, 3), np.uint8), format="rgb24")
        frame.pts = 0
        for packet in s.encode(frame.reformat(format="yuvj420p")):
            out.mux(packet)
        for packet in s.encode(None):
            out.mux(packet)
    with pytest.raises(decode.DecodeError, match="no audio in"):
        decode.Decoder(path, 2)


# ---------- the silence encoders add (A4.2, R7.6) ----------
#
# FFmpeg trims each of these itself, so MusiKata trims none of them again: the files are made with
# a known number of samples, and decoding one gives that many, from the tone's first.

N = 12_345  # samples of tone in each file: no whole number of any encoder's frames


def samples_of(path):
    """The file decoded at its own rate, in stereo: (rate, samples)."""
    with decode.Decoder(path, 2) as d:
        return d.rate, np.concatenate(list(d.blocks(4096)))


def starts_on_the_tone(samples, rate, level=0.5):
    """Whether the samples are the tone from its first sample: no silence before it, and in
    step with it (a lossy encoder's own error aside)."""
    ideal = level * np.sin(2 * np.pi * TONE * np.arange(2000) / rate)
    return np.abs(samples[100:2000, 0] - ideal[100:2000]).max() < 0.05


@pytest.mark.parametrize("vbr", [False, True])
def test_an_mp3s_start_delay_and_end_padding_from_its_lame_header_are_left_out(tmp_path, vbr):
    path = write(str(tmp_path / "a.mp3"), "mp3", "libmp3lame", "fltp", 44100, "stereo",
                 frames=N, vbr=vbr)  # fmt: skip
    rate, samples = samples_of(path)
    assert len(samples) == N and starts_on_the_tone(samples, rate)


def test_an_mp3_tagged_in_front_keeps_its_lame_header(tmp_path, kinds):
    # an ID3v2 tag with a cover before the first frame: the header is still found after it
    path = write(str(tmp_path / "a.mp3"), "mp3", "libmp3lame", "fltp", 44100, "stereo", frames=N)
    demo.tag(path, demo.Song(path, "mp3", {"title": "Signal Fires"}, cover=(11, 64)))
    rate, samples = samples_of(path)
    assert len(samples) == N and starts_on_the_tone(samples, rate)


def test_an_mp3_with_no_lame_header_has_nothing_to_say_its_silence(tmp_path):
    # no Xing or LAME frame (an old encoder's): the encoder's delay and its last frame's padding
    # play, as nothing in the file says how long they are
    path = write(str(tmp_path / "a.mp3"), "mp3", "libmp3lame", "fltp", 44100, "stereo", frames=N,
                 options={"write_xing": "0"})  # fmt: skip
    _, samples = samples_of(path)
    assert len(samples) == 12 * 1152 and np.abs(samples[:1000]).max() < 0.01


def mp4_aac(path, edit_list, silence=0):
    return write(path, "ipod", "aac", "fltp", 44100, "stereo", frames=N, silence=silence,
                 options={} if edit_list else {"use_editlist": "0"})  # fmt: skip


def itunsmpb(path, priming, padding, samples):
    """The `iTunSMPB` tag iTunes writes: its priming, its padding and the song's samples, in
    hexadecimal among fields of zeros."""
    f = mutagen.mp4.MP4(path)
    value = f" 00000000 {priming:08X} {padding:08X} {samples:016X}" + " 00000000" * 8
    f["----:com.apple.iTunes:iTunSMPB"] = [mutagen.mp4.MP4FreeForm(value.encode())]
    f.save()
    return path


def test_an_aac_files_priming_and_padding_from_its_edit_list_are_left_out(tmp_path):
    rate, samples = samples_of(mp4_aac(str(tmp_path / "a.m4a"), edit_list=True))
    assert len(samples) == N and starts_on_the_tone(samples, rate)


def test_an_aac_files_priming_and_padding_from_its_itunsmpb_tag_are_left_out(tmp_path):
    # no edit list, only the tag: FFmpeg's encoder primes 1024 samples, and 700 samples of
    # silence after the tone stand for an encoder's padding, which the tag says to leave out
    path = mp4_aac(str(tmp_path / "a.m4a"), edit_list=False, silence=700)
    rate, untagged = samples_of(path)
    assert len(untagged) == 1024 + N + 700  # nothing says what to leave out
    rate, samples = samples_of(itunsmpb(path, 1024, 700, N))
    assert len(samples) == N and starts_on_the_tone(samples, rate)


def test_an_aac_file_with_both_as_itunes_writes_them_is_trimmed_once(tmp_path):
    path = itunsmpb(mp4_aac(str(tmp_path / "a.m4a"), edit_list=True), 1024, 0, N)
    rate, samples = samples_of(path)
    assert len(samples) == N and starts_on_the_tone(samples, rate)


def test_an_opus_files_pre_skip_and_end_are_left_out(tmp_path):
    path = write(str(tmp_path / "a.opus"), "ogg", "libopus", "s16", 48000, "stereo", frames=N)
    with av.open(path) as f:
        assert f.streams.audio[0].codec_context.delay == 312  # the pre-skip its header gives
    rate, samples = samples_of(path)
    assert len(samples) == N and starts_on_the_tone(samples, rate)


# ---------- seeking (A4.6, R7.4) ----------


def test_a_seek_starts_resampling_where_the_files_samples_and_the_devices_frames_meet():
    assert decode.seek_plan(1000, 48000, 48000) == (1000, 0)  # the device's rate: the sample
    sample, drop = decode.seek_plan(10_000, 44100, 48000)
    assert sample % 147 == 0 and (10_000 - drop) * 147 == sample * 160  # an instant both fall on
    assert decode.LEAD <= drop < decode.LEAD + 160
    assert decode.seek_plan(10, 44100, 48000) == (0, 10)  # too near the start: from it
    kept = list(decode.dropped([np.zeros((3, 1)), np.ones((4, 1))], 5))
    assert len(kept) == 1 and kept[0].tolist() == [[1.0], [1.0]]


@given(st.integers(0, 10**7), st.sampled_from([8000, 22050, 44100, 48000, 88200, 96000, 192000]))
def test_a_seeks_plan_always_lands_on_the_frame_asked_for(frame, rate):
    sample, drop = decode.seek_plan(frame, rate, 48000)
    assert sample >= 0 and drop >= 0
    assert sample * 48000 / rate + drop == frame  # resampled from there, the frame is the one


SOUGHT = {  # frames to seek to in a 3 s file: the start, within the preroll, and on
    "start": 0, "near": 500, "on": 61_234, "late": 3 * 48000 - 2000, "past": 3 * 48000 + 10,
}  # fmt: skip


@pytest.fixture(scope="module")
def three_seconds(tmp_path_factory):
    """Three seconds of each kind of R2.2; AAC as a plain tone, whose decoding is the same
    after a seek (the demo's noise is coded as noise the decoder makes afresh each time)."""
    d = tmp_path_factory.mktemp("three")
    out = {}
    for kind, (ext, *_rest) in demo.KINDS.items():
        out[kind] = str(d / f"{kind}.{ext}")
        if kind == "aac":
            write(out[kind], "ipod", "aac", "fltp", 44100, "stereo", seconds=3.0)
        else:
            demo.encode(out[kind], kind, 3.0, TONE)
    return out


# how near a seek's samples come to the song's decoded through: the same, but where a decoder
# carries state from frame to frame that a seek starts afresh (Opus's, and AAC's last frame);
# a sample out of place would be off by some 0.02
NEAR = {"aac": 2e-4, "opus": 2e-4}


@pytest.mark.slow
@pytest.mark.parametrize("kind", list(demo.KINDS))
@pytest.mark.parametrize("device", [48000, 44100])
def test_a_seek_lands_on_the_exact_sample(three_seconds, kind, device):
    # what follows a seek is what the song decoded through has there, frame for frame, at the
    # file's rate and resampled to the device's, to its end
    with decode.Decoder(three_seconds[kind], 2) as d:
        through = np.concatenate(list(decode.played(d, device, 960)))
        for where, frame in SOUGHT.items():
            got = list(decode.played(d, device, 960, start=frame))
            got = np.concatenate(got) if got else np.zeros((0, 2), np.float32)
            assert len(got) == len(through[frame:]), where
            if len(got):
                assert np.abs(got - through[frame:]).max() < NEAR.get(kind, 1e-6), where


@pytest.mark.slow
def test_a_seek_ffmpeg_cant_make_or_that_lands_past_the_sample_decodes_from_the_start(tmp_path):
    path = write(str(tmp_path / "a.flac"), "flac", "flac", "s16", 48000, "stereo", seconds=1.0)
    with decode.Decoder(path, 2) as d:
        through = np.concatenate(list(d.blocks(960)))
        d._seek = lambda seconds: False
        d.seek(30_000)
        assert np.array_equal(np.concatenate(list(d.blocks(960))), through[30_000:])
    with decode.Decoder(path, 2) as d:
        frames = d._frames
        d._frames = lambda: (setattr(f, "pts", None) or f for f in frames())  # no times
        d.seek(30_000)
        assert np.array_equal(np.concatenate(list(d.blocks(960))), through[30_000:])
    with decode.Decoder(path, 2) as d:
        frames, calls = d._frames, []

        def past():  # the first time after a seek, from a frame past the sample
            calls.append(1)
            return (f for f in frames() if len(calls) > 1 or f.pts > 31_000)

        d._frames = past
        d.seek(30_000)
        assert np.array_equal(np.concatenate(list(d.blocks(960))), through[30_000:])
        assert len(calls) == 2
