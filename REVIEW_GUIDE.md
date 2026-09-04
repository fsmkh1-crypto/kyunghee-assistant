# Current desktop review target

This branch is the current Windows desktop product target.

- Branch: `ui/dark-kyunghee-redesign`
- Pull request: #3
- Product entrypoint: `desktop_compact.py`
- Base desktop/detail UI: `desktop_app.py`
- Timer/state core: `app.py`
- User settings: `settings.py`
- Character asset mapping: `asset_manager.py`

Do not review the repository default branch (`main`) as the current desktop UI implementation. `main` still contains the older windowed UI and is intentionally behind this branch until the redesign is stabilized.

## Review priorities

For current reviews, inspect the branch above and focus on:

1. Frameless/transparent Windows behaviour
2. Window movement, restore, multi-monitor/off-screen recovery
3. Global emergency hide/restore behaviour
4. User image import and settings durability
5. Timer/away/break state correctness
6. Packaging/startup behaviour
7. DPI and image-edge quality (Phase 2 work)

The packaged executable is built from `desktop_compact.py` by `.github/workflows/desktop-package.yml`.
