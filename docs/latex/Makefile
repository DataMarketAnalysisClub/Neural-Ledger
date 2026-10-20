# Build both documents with latexmk and copy the PDFs to build/ (committed).
#   make            build both PDFs
#   make check      build, then fail on any undefined reference, overfull box or LaTeX warning
#   make clean      remove auxiliary files (keeps build/)
LATEXMK ?= latexmk
DOCS = technical/technical-documentation security-assessment/security-self-assessment

.PHONY: all check clean
all: $(addprefix build/,$(addsuffix .pdf,$(notdir $(DOCS))))

build/%.pdf: FORCE
	@mkdir -p build .aux
	$(LATEXMK) -pdf -cd- -r latexmkrc $(filter %/$*.tex,$(addsuffix .tex,$(DOCS)))
	cp .aux/$*.pdf $@

check: all
	@! grep -nE "Overfull|undefined|Warning:|Citation .* undefined|Rerun to get" .aux/*.log | grep -v "Package microtype Warning" ; \
	  status=$$?; if [ $$status -ne 0 ]; then echo "LaTeX warnings found (see above)"; exit 1; fi; echo "no warnings"

clean:
	$(LATEXMK) -c -r latexmkrc
	rm -rf .aux

FORCE:
