# Native process-loopback helper

The desktop process launches `bin/tawil-audio-capture.exe`. The helper must use
`ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, ...)` with
`AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK` and
`PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE`.

Stdout is binary-only. Each PCM16 mono frame has this little-endian header:

```text
4 bytes magic "TWPC"
uint32 payload byte length
uint16 channel count
uint16 sample rate
payload bytes
```

Diagnostics go to stderr. The executable accepts:

```text
tawil-audio-capture.exe --pid 1234 --include-tree --frame-ms 20
```

This contract keeps COM/WASAPI out of Python and lets capture run at native
priority without blocking Qt or asyncio. The implementation targets Windows
10 build 20348 or later and follows Microsoft's ApplicationLoopback sample. It
requests PCM16 mono at 16 kHz and emits fixed-duration frames.
