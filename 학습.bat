@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/3] data\docs -^> docs_kb.jsonl
py sync_docs.py || goto :fail
echo [2/3] chunking
py chunk_documents.py || goto :fail
echo [3/3] building index (takes a few minutes)
py build_index.py || goto :fail
echo Done. Restart the app (실행.bat) to use the new data.
pause
exit /b 0
:fail
echo FAILED - see error above.
pause
exit /b 1
