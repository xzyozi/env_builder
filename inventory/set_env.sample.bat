@echo off
rem =====================================================================
rem  env_builder credentials template (no secrets here).
rem  init_config.py copies this to <project>\build_env\set_env.bat.
rem  Fill in real values after copying. The copy is git-ignored. Never commit.
rem
rem  Usage: call <project>\build_env\set_env.bat
rem  Keep this file ASCII only (cmd reads .bat in the OEM code page).
rem =====================================================================

rem --- SSH (names must match password_env in inventory\servers.json) ---
rem set "ENVB_GATEWAY_PASSWORD=<PASSWORD>"
rem set "ENVB_ANMHOST_PASSWORD=<PASSWORD>"
rem set "ENVB_SRC_PASSWORD=<PASSWORD>"
rem set "ENVB_DST_PASSWORD=<PASSWORD>"
rem set "ENVB_DST_ROOT_PASSWORD=<PASSWORD>"

rem --- Git (GitLab) credentials. Do not embed in URLs or command lines. ---
set "ENVB_GIT_USER=<GIT_USER>"
set "ENVB_GIT_PASSWORD=<GIT_PASSWORD>"