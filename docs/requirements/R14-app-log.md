# R14. App log

R14.1. MusiKata keeps a log of what it does that a user or a developer may need afterwards:
start and stop with the version and platform, scans and their counts and times, every file
written and why, errors reading or writing a file (with the path and the library's message),
playback errors, and settings that were refused.

R14.2. It never logs tag values beyond a file's path, nor anything about the user beyond what the
paths say.

R14.3. The log is two text files of at most 2 MB each, `musikata.log` and `musikata.log.1`, in
the log folder of R1.5; when the first is full it replaces the second.

R14.4. ⋮ › **Show app log** opens the log folder in the system's file manager, with the current
file selected where the platform allows it.

R14.5. Each line starts with the local time to the millisecond and a level (`INFO`, `WARN`,
`ERROR`); `MUSIKATA_DEBUG=1` adds `DEBUG` lines.
