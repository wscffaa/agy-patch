@echo off
rem Manual-use shim; install.py writes an absolute-interpreter variant.
python -I "%~dp0agy_wrapper.py" %*
