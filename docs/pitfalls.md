# Pitfalls worth knowing

Things that broke while building and running the pipeline, kept here so they
don't have to be rediscovered. Back to the [README](../README.md).

- **Whisper word timings jitter backwards.** Captions stack on the same frames
  and flicker unless normalised. Both `render.py` and `assemble.py` handle it.
- **Filtergraph chains must be joined with `;`.** Concatenating them with an
  empty string makes ffmpeg read the next input pad as a second input to the
  previous filter, and it fails with a bare `Invalid argument`.
- **ffmpeg expressions inside filter args need their commas escaped.** A
  `max(0,min(...))` in a `crop` x-position will otherwise be read as two
  arguments. `_focus_expr` escapes them.
- **`ass=` needs a path that doesn't require escaping.** Write the `.ass` into a
  scratch directory and run ffmpeg with that as its cwd.
- **`WrapStyle: 2` disables word wrapping — long text gets CLIPPED, not
  wrapped.** Short labels fit, so it hides until someone adds a long one. Both
  renderers now use `WrapStyle: 0`. Check every new string at the frame edges.
- **Heavy CPU work starves GPU transcription.** Rendering while mlx-whisper runs
  dropped it from ~250 to ~77 mel-frames/s. Transcribe first, render after.
- **A campaign may pay nothing below a minimum-payout threshold.** Read
  `minPayoutCents`, not just the headline CPM — see
  [whop-content-rewards.md](whop-content-rewards.md).
- **Rank campaigns by the view gate, not the CPM.** `minPayout ÷ rate × 1000` is
  the views one clip needs before it earns a cent. A high CPM with a high gate
  pays worse than a lower CPM you can actually clear. The *cap* matters too: it
  decides the views at which a hit stops earning.
