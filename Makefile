all:
	@echo Assuming you already have python3, to install
	@echo all necessary dependencies do: make install

FSENV=$(HOME)/fsenv
install:
	python3 -m venv $(FSENV)
	$(FSENV)/bin/pip install wheel
	$(FSENV)/bin/pip install -r ./pip.requirements
