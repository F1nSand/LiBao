@echo off
cd /d C:\Users\Admin1\Desktop\Agent\FrontEnd
call npx playwright test --config playwright.real.config.ts 2>&1
