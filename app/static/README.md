# Static assets

Served by Flask's default static handler at `/static/...`.
Reference in templates with `{{ url_for('static', filename='img/logos/mc-college.svg') }}`.

Drop the real asset files into the folders below using these **exact names** so the
templates find them. Placeholders (`.gitkeep`) can be deleted once real files land.

## img/logos/  (highest priority — used in 4 places)
Use SVG, or transparent-background high-res PNG. **Never JPEG** (logos must stay sharp).

| File | What it is |
|------|------------|
| `mc-college.svg` (or `.png`) | MC College circular logo — blue #353B8C / green #2E663F, white bg |
| `jsmu.svg` (or `.png`)       | JSMU crest logo — green #396440 / gold #EDDF4B, white bg |
| `mc-college@2x.png`          | Retina PNG (only if using PNG, not SVG) |
| `jsmu@2x.png`                | Retina PNG (only if using PNG, not SVG) |

## video/  (Section 7 — Principal's video)
Skip these if hosting on YouTube/Vimeo instead — provide the embed URL.

| File | What it is |
|------|------------|
| `principal.mp4`         | Principal video (DPT + affordability / Mother & Child Foundation) |
| `principal.vtt`         | Captions/subtitles — REQUIRED (captions on by default) |
| `principal-poster.jpg`  | Poster frame shown before autoplay |

## img/campus/  (Section 10 — Why Choose Us / facilities)
Real photos only, no stock.

| File | What it is |
|------|------------|
| `facility-1.jpg`, `facility-2.jpg`, … | Facility / campus shots |

## img/gallery/  (Section 11 — optional gallery grid)

| File | What it is |
|------|------------|
| `gallery-1.jpg`, `gallery-2.jpg`, … | Remaining real photos |
| `clip-1.mp4`, …                     | Extra short videos (optional) |

## img/  (root)

| File | What it is |
|------|------------|
| `favicon.svg` | Branded browser-tab icon (navy disc + green ring + "MC" monogram). Shipped by default. The public site automatically prefers the CMS-uploaded MC College logo when one is set. |

---

## Contact details wired into the page (source of truth)

- WhatsApp: **+92 331 2004658**  (wa.me link uses `923312004658`)
- Email (primary): **admission@mccollege.edu.pk**
- Email (this domain): **admission@apply-mccollege.pk**
- Phone: **021-36684658**
- Address: Main Campus, C 177/2, Rameez Raja Road, Block A, North Nazimabad,
  off KDA Chowrangi, near Rose Garden, Karachi
- Map: https://maps.google.com/maps?ll=24.934505,67.03239&z=18&t=m&hl=en&gl=US&mapclient=embed&cid=3602515813633013250
