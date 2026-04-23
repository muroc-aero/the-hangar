# Paper figure crops

`fig5.png` and `fig6.png` are cropped from Brelje 2018a (the PDF
`Brelje2018a_OCPpareto.pdf` at the repo root).

Regenerate with:

```bash
uv run python -c "
import pymupdf
from PIL import Image
doc = pymupdf.open('Brelje2018a_OCPpareto.pdf')
for page_idx, fig, crop in [(13, 5, (100, 280, 1170, 1200)),
                             (15, 6, (100, 270, 1170, 1200))]:
    pix = doc[page_idx].get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0))
    pix.save(f'/tmp/brelje_p{page_idx+1}.png')
    Image.open(f'/tmp/brelje_p{page_idx+1}.png').crop(crop).save(
        f'packages/omd/demos/brelje_2018a/figures/paper/fig{fig}.png')
"
```

Crops capture the 2x2 subplot grid for each figure (page 14 for Fig 5,
page 16 for Fig 6).  Dependencies: `pymupdf`, `pillow`.
