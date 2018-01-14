all:
	@echo Assuming you already have python2.6 and virtualenv, to install
	@echo all necessary dependencies do: make install

FSENV=$(HOME)/fsenv
install:
	virtualenv --no-site-packages --unzip-setuptools $(FSENV)
	$(FSENV)/bin/pip install -r ./pip.requirements
