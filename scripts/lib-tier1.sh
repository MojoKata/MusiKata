# Sourced: tier1_setup HERE -- the container tier 1 runs in (an Ubuntu 24.04 image, musikata-tier1),
# and the release's Python, PySide6 and the packages MusiKata carries, for it
# (packaging/versions.env), made once. Sets IMG, SITE (PySide6 and the rest, for PYTHONPATH) and PYT (the Python, a path under
# HERE).
tier1_setup() {
    . "$1/packaging/versions.env"
    PYT=$(sh "$1/scripts/python-standalone.sh")
    # What Qt's offscreen platform, Qt Multimedia and the tests need from a desktop system (Ubuntu
    # 24.04's glibc 2.39); Noto Sans as the sans-serif font, the mockups' (R6.2); PulseAudio, whose
    # null sink is the sound device the playback tests play into, as there is no sound card and Qt
    # has no null output of its own (scripts/test-tier1.sh starts it); D-Bus's daemon and its
    # clients, for the MPRIS tests' own session bus (tests/test_app_mpris.py, A4.5); libfaketime,
    # for the suite run at a set time (MUSIKATA_CLOCK, scripts/test-clock.sh). /etc/passwd is left
    # writable so a run adds its own user (scripts/test-tier1.sh): the container runs as the
    # caller's uid, which the image may not name (CI's runner is 1001), and dbus-daemon won't start
    # for a uid it can't look up. The image's tag follows this recipe, so a change makes a new
    # image.
    _df="FROM $NOBLE_IMAGE"'
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git libgl1 libegl1 libxkbcommon0 libfontconfig1 libdbus-1-3 dbus libglib2.0-0t64 libpulse0 libasound2t64 pulseaudio fonts-noto-core fontconfig python3 ca-certificates gnupg libfaketime >/dev/null
RUN printf "<?xml version=\"1.0\"?><!DOCTYPE fontconfig SYSTEM \"fonts.dtd\"><fontconfig><alias><family>sans-serif</family><prefer><family>Noto Sans</family></prefer></alias></fontconfig>\n" > /etc/fonts/local.conf && fc-match sans-serif | grep -q "Noto Sans"
RUN chmod 666 /etc/passwd'
    IMG=musikata-tier1:$(printf '%s' "$_df" | sha256sum | cut -c1-12)
    # The build is quiet but bounded: a build takes a minute at most, so ten fail it (apt-get can
    # stall on a runner and leave a job silent until its own limit), and a failure shows the
    # build's own output (which mirror, which package).
    if ! docker image inspect "$IMG" >/dev/null 2>&1; then
        _log=$(mktemp)
        if ! printf '%s\n' "$_df" | timeout 600 docker build --progress=plain -t "$IMG" - >"$_log" 2>&1; then
            echo "tier1: building $IMG failed or took over 10 minutes; docker build said:" >&2
            cat "$_log" >&2
            rm -f "$_log"
            return 1
        fi
        rm -f "$_log"
    fi
    # PySide6 (Essentials and Addons: Qt Multimedia is in Addons, A6.2) and what MusiKata carries
    # (RUNTIME: Mutagen, NumPy, PyAV, truststore), for the release's Python; the folder's name
    # follows the pins, so a pin moved makes a new one.
    SITE="$1/build/site-packages-$(printf '%s %s %s' "$PY_SERIES" "$PYSIDE" "$RUNTIME" | sha256sum | cut -c1-12)"
    if [ ! -d "$SITE/PySide6" ]; then
        echo "== PySide6 $PYSIDE and $RUNTIME for Python $PY_SERIES" >&2
        rm -rf "$SITE.part" && mkdir -p "$SITE.part"
        # shellcheck disable=SC2086 # RUNTIME is a list of pip specs
        docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$1:$1:ro" -v "$SITE.part:/site" "$IMG" \
            "$PYT" -m pip install -q --no-deps --disable-pip-version-check --target /site \
            "PySide6-Essentials==$PYSIDE" "PySide6-Addons==$PYSIDE" "shiboken6==$PYSIDE" $RUNTIME
        rm -rf "$SITE" && mv "$SITE.part" "$SITE"
    fi
}
