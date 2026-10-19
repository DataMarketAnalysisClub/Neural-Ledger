# LaTeX documentation

Two documents for the FinTechathon judges, built from the code at the commit named on their title pages:

| Source | PDF |
|---|---|
| `technical/technical-documentation.tex`: architecture, data model, financial core algorithms, design decisions, security design, privacy and Law 21.719 | `build/technical-documentation.pdf` |
| `security-assessment/security-self-assessment.tex`: security tiers, controls and evidence, known-risk register, residual risk after option B | `build/security-self-assessment.pdf` |

`common/` holds the shared style (`neuralledger.sty`), the metadata (`meta.tex`: project, date, versions, authors) and the
TikZ figures both documents use. Figures are greyscale so they print in black and white.

Build (TeX Live with `latexmk`, `algorithm2e`, `tikz`, `booktabs`, `cleveref`):

```sh
cd docs/latex
make          # latexmk -pdf for both documents; PDFs copied to build/
make check    # the same, then fails on any overfull box, undefined reference or LaTeX warning
make clean    # remove the auxiliary files in .aux/
```

`latexmk` alone also works from this directory (`latexmkrc`); its output stays in `.aux/`. Commit the PDFs in `build/`
together with the sources they come from.
