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
import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from musikata_core.audio import decode

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

TONE = 440


def write(path, fmt, codec, sample_fmt, rate, layout, seconds=0.5, level=0.5):
    """A sine of TONE Hz at `level` in every channel, `seconds` long, written by FFmpeg as
    `codec` in `sample_fmt` (packed, or planar with a "p"), at `rate`, in `layout`."""
    n = int(rate * seconds)
    channels = av.AudioLayout(layout).nb_channels
    x = level * np.sin(2 * np.pi * TONE * np.arange(n) / rate)
    with av.open(path, "w", format=fmt) as out:
        s = out.add_stream(codec, rate=rate, layout=layout)
        s.codec_context.format = sample_fmt
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
    with decode.Decoder(path, rate, channels) as d:
        blocks = list(d.blocks(block))
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
    assert d.skipped == 0 and d.decoded == len(samples)


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
        decode.Decoder(path, 48000, 2)


def test_a_missing_file_an_empty_one_and_one_of_noise_cant_be_played(tmp_path):
    with pytest.raises(decode.DecodeError, match="couldn't open"):
        decode.Decoder(str(tmp_path / "gone.flac"), 48000, 2)
    noise = tmp_path / "noise.mp3"
    noise.write_bytes(np.random.default_rng(1).bytes(5000))
    with pytest.raises(decode.DecodeError, match="couldn't open"):
        decode.Decoder(str(noise), 48000, 2)
    empty = tmp_path / "empty.flac"
    empty.write_bytes(b"")
    with (
        decode.Decoder(str(empty), 48000, 2) as d,  # FFmpeg opens it, and finds nothing in it
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
        decode.Decoder(path, 48000, 2)
