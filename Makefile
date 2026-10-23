CXX = g++
CXXFLAGS = -O3 -std=c++17 -Wall -Wextra
PYTHON = python3

.PHONY: all scan report test clean

all: exact real

exact: exact.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

real: real.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

scan: exact
	@set -eu; tmp=scan-100000/raw.txt.tmp; trap 'rm -f "$$tmp"' EXIT; \
	./exact --range 1 100000 > "$$tmp"; mv "$$tmp" scan-100000/raw.txt

report:
	$(PYTHON) analyze_scan.py

test: all
	$(PYTHON) verify.py
	$(PYTHON) -m unittest -v test_analyze_scan

clean:
	rm -f exact real
	rm -rf __pycache__
