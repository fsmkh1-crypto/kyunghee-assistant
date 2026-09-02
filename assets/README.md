# Character asset set

The application uses one consistent Kyunghee character identity across all states.

Finalized asset roles:

| File | Role |
|---|---|
| `default_full.png` | Main page / playful default pose |
| `cheer_full.png` | Daily stats page / fighting-cheer pose |
| `cute_cheer.png` | Short encouragement and positive popup |
| `nag.png` | Repeated snooze / pouting nag |
| `worry.png` | Long-use warning / concern |
| `praise.png` | Good return, completed break, positive summary |
| `master_face.png` | Tray icon and small neutral notification |
| `playful.png` | Compact playful notification |
| `cheer.png` | Compact cheer notification |

Visual lock:

- same face across every state
- long wavy hair
- soft realistic/semi-matte skin
- light pink top
- soft ivory-white skirt
- playful rather than stern default personality
- nagging should look sulky/pouting, not angry

Workday mood mapping:

- normal work: default/playful
- approaching break: cheer
- good return: cute-cheer/praise
- first snooze: worry
- repeated snooze: nag
- 17:30+ leaving-work mode: praise/worry, no productivity cheerleading
- 18:30+ late work: nag/worry
- 9 hours actual active use: hard-stop mood

The binary PNG files are generated project assets and should be committed under this directory before the Windows real-world test gate.
