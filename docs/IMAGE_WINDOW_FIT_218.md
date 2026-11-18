# 2.1.8: Whole-image window fit

Custom images now retain their complete composition and aspect ratio. The previous
center-crop setting is retained in saved data for compatibility, but its UI label
is now 중앙 맞춤 and it no longer cuts off artwork. Existing sets and image files
are not rewritten or removed. Model selections remain GPT-6.2 Sol/Astra.

Both settings previews and the timer use the same whole-image resize transform.
A timer-specific viewport is measured after window/work-area clamping; character
size and placement use that final client area. Settings-window dimensions never
become the timer's layout dimensions. Role changes and shuffled artwork refresh
the retained pre-clamp image. No source PNG is modified.

Root causes addressed:
- ImageOps.fit filled a frame by enlarging/cropping tall art.
- Preview and timer frames had different aspect ratios.
- Clamping window dimensions did not correspondingly resize/reposition artwork.

Regression coverage includes tall/wide/square/small images, legacy crop preference,
roles, 80–200% scale, small work areas, retained-source resizing and reentrant
layout notifications. Exact cause of the reported screenshot's scale cannot be
proven without the user's runtime profile; the identified defective paths are
covered independently rather than claiming that unknown configuration was reproduced.
