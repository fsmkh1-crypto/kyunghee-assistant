# Donor Crawler Selection Criteria

The crawler uses broad pose/reference queries, then ranks candidates for usefulness before upload.

## Ranking priorities

1. Seated or floor-level pose relevance.
2. Full-body or clearly readable lower-body structure.
3. Front, three-quarter, or low-view camera angle relevance.
4. Bent-knee / knees-up geometry when present.
5. Clear hip-thigh-knee relationships with limited occlusion.
6. High-resolution source image; prefer at least 1000 px on the shorter side when available.
7. Plain or studio background that makes body contours easier to inspect.
8. Multi-angle / turnaround / figure-reference material receives a bonus.
9. Strong compression, watermarks, thumbnails, collages, and heavy overlays are penalized.
10. Rights status is recorded separately: permissive sources rank highest for reuse, unknown-license images remain reference_only, and explicit reuse/AI/derivative prohibitions are skipped.

## Upload behavior

- Search broadly first; do not stop at the first ten discoveries.
- Deduplicate by SHA-256.
- Rank the candidate pool.
- Upload only the highest-ranked 10 successful files to the configured Google Drive folder.
- Stop immediately after 10 successful uploads.
- Preserve source URL, source domain, rights label, dimensions, digest, and score in the manifest.
